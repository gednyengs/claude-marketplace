// Tests for the hooks module, run by `claude plugin test <plugin folder>`.
//
// The Python scripts are stubbed: each test's `process.run` hook stands for the
// engine and records what the module asked for. What the scripts do with it is
// covered by tests/test_session_handoff.py, as is the PreCompact command hook that
// steers the summary (the module never touches a compaction's instructions).
import { expect, test } from 'claude-code/testing'
import type { AgentInfo, CommandRunInput, On, SessionMessage } from 'claude-code'


type Ran = { script: string; payload: Record<string, unknown>; argv: readonly string[] }

const ranOk = (stdout: string, exitCode = 0) => ({
  exitCode,
  stdout,
  stderr: '',
  isStdoutTruncated: false,
  isStderrTruncated: false,
})

/** An agent as `$.agent.list()` reports one, down to the fields the module reads. */
const agent = (id: string, type: string, description: string, status: AgentInfo['status']) =>
  ({ id, type, description, status }) as AgentInfo

/** A slash command as the person typed it. */
const typed = (command: string, args = '') => ({ command, args, origin: { kind: 'composer' } }) as CommandRunInput

/** Stands in for the engine beneath the module; returns what the module ran. */
function beneath(
  on: On,
  options: { stdout?: Record<string, string>; exitCode?: number; sessionId?: () => string; order?: string[] } = {},
) {
  const ran: Ran[] = []
  on('process.hookEnv', () => ({ value: { CLAUDE_PROJECT_DIR: '/proj', CLAUDE_PLUGIN_DATA: '/data' } }))
  on('process.run', (_, e) => {
    const script = String(e.argv[1]).split('/').pop() ?? ''
    ran.push({ script, payload: JSON.parse(e.init?.stdin ?? '{}'), argv: e.argv })
    options.order?.push(script)
    return { value: ranOk(options.stdout?.[script] ?? '', options.exitCode ?? 0) }
  })
  on('session.id', () => ({ value: options.sessionId?.() ?? 'session-under-test' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  return ran
}

const only = (ran: Ran[], script: string) => ran.filter(one => one.script === script)

/** The nth thing the module ran; fails the test when it ran fewer. */
function nth(ran: Ran[], index: number): Ran {
  const one = ran[index]
  if (one === undefined) throw new Error(`the module ran ${ran.length} script(s), none at index ${index}`)
  return one
}

// The kit holds a compaction to the engine's own rule: it starts from, and
// leaves, at least one message.
const BEFORE: SessionMessage[] = [{ role: 'user', text: 'the conversation so far', toolUses: [] }]
const after = (text: string): { messages: SessionMessage[] } => ({ messages: [{ role: 'user', text, toolUses: [] }] })

test('session start runs the script and hands its output to the model', async ($, on) => {
  const ran = beneath(on, { stdout: { 'session-start.py': '=== recent topics ===\n' } })
  on('classic.SessionStart', () => ({ additionalContext: ['from another hook'] }))

  const answer = await $.classic.SessionStart({ source: 'startup', session_id: 'abc', transcript_path: '/t/abc.jsonl' })

  expect(ran).toHaveLength(1)
  expect(nth(ran, 0).script).toBe('session-start.py')
  expect(nth(ran, 0).argv.slice(2)).toEqual(['--project-dir', '/proj', '--plugin-data', '/data'])
  expect(nth(ran, 0).payload).toEqual({ session_id: 'abc', transcript_path: '/t/abc.jsonl', source: 'startup' })
  expect(answer.additionalContext).toEqual(['from another hook', '=== recent topics ==='])
})

test('a script that prints nothing adds no context', async ($, on) => {
  beneath(on)
  on('classic.SessionStart', () => ({}))

  const answer = await $.classic.SessionStart({ source: 'resume', session_id: 'abc' })

  expect(answer.additionalContext).toBeUndefined()
})

test('a fork is matched to its conversation by its last row', async ($, on) => {
  const ran = beneath(on)
  let asked: unknown
  on('classic.SessionStart', () => ({}))
  on('session.messages', (_, e) => {
    asked = e
    return { value: [{ role: 'assistant', text: 'the last thing said', toolUses: [], uuid: 'row-uuid-1' }] }
  })

  await $.classic.SessionStart({ source: 'fork', session_id: 'forked', seconds_since_last_response: 14 })
  // a resumed session may have forks of its own holding its rows: it is not matched to them
  await $.classic.SessionStart({ source: 'resume', session_id: 'resumed', seconds_since_last_response: 14 })
  await $.classic.SessionStart({ source: 'startup', session_id: 'fresh' })
  await $.classic.SessionStart({ source: 'clear', session_id: 'cleared' })

  expect(JSON.stringify(asked)).toContain('"last":1')
  expect(ran.map(one => [one.payload.last_uuid, one.payload.seconds_since_last_response])).toEqual([
    ['row-uuid-1', 14],
    [undefined, undefined],
    [undefined, undefined],
    [undefined, undefined],
  ])
})

test('a fork with no readable history still starts', async ($, on) => {
  const ran = beneath(on)
  on('classic.SessionStart', () => ({}))
  on('session.messages', () => {
    throw new Error('not loaded yet')
  })

  await $.classic.SessionStart({ source: 'fork', session_id: 'forked' })

  expect(nth(ran, 0).payload).toEqual({ session_id: 'forked', transcript_path: '', source: 'fork' })
})

test('after /clear the new session is told which session ended', async ($, on) => {
  const ran = beneath(on)
  on('classic.SessionStart', () => ({}))

  await $.session.end({ reason: 'clear', sessionId: 'old-session', resume: { id: 'old-session' } })
  await $.classic.SessionStart({ source: 'clear', session_id: 'new-session' })

  expect(nth(ran, 0).payload).toEqual({ session_id: 'new-session', transcript_path: '', source: 'clear', cleared_from: 'old-session' })

  // The handover is used once: a later clear this module saw no end for names nobody.
  await $.classic.SessionStart({ source: 'clear', session_id: 'third-session' })
  expect(nth(ran, 1).payload.cleared_from).toBeUndefined()
})

test('only a /clear hands a session over', async ($, on) => {
  const ran = beneath(on)
  on('classic.SessionStart', () => ({}))

  await $.session.end({ reason: 'clear', sessionId: 'cleared', resume: { id: 'cleared' } })
  await $.session.end({ reason: 'other', sessionId: 'exited', resume: { id: 'exited' } })
  await $.classic.SessionStart({ source: 'clear', session_id: 'next' })
  expect(nth(ran, 0).payload.cleared_from).toBeUndefined()

  // and a start that is not a clear never carries one
  await $.session.end({ reason: 'clear', sessionId: 'cleared', resume: { id: 'cleared' } })
  await $.classic.SessionStart({ source: 'startup', session_id: 'next' })
  expect(nth(ran, 1).payload.cleared_from).toBeUndefined()
})

test('a compaction is saved on the way out, its instructions untouched', async ($, on) => {
  const ran = beneath(on, { stdout: { 'compact.py': 'Compaction summary saved to x.md.' } })
  const logged: string[] = []
  let instructions: string | undefined
  on('ui.log', (_, e) => {
    logged.push(String(e.text))
    return { value: undefined }
  })
  on('agent.list', () => ({
    value: [
      agent('a1', 'Explore', 'map the parser', 'running'),
      agent('a2', 'general-purpose', 'done long ago', 'completed'),
      agent('a3', 'general-purpose', 'holds a shell', 'waiting'),
    ],
  }))
  on('classic.SessionStart', () => ({}))
  on('classic.PostCompact', () => ({}))
  // The engine: summarize, restart the conversation, announce the summary.
  on('session.compact', async (_, e) => {
    instructions = e.instructions
    await $.classic.SessionStart({ source: 'compact' })
    await $.classic.PostCompact({ trigger: 'auto', compact_summary: '<summary>THE SUMMARY</summary>' })
    return after('continued... THE SUMMARY')
  })

  const done = await $.session.compact({ trigger: 'auto', instructions: 'keep the codeword', messages: BEFORE })

  expect(instructions).toBe('keep the codeword')
  expect(done.messages).toHaveLength(1)
  // SessionStart(compact) learned what started the compaction
  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBe('auto')
  // and the snapshot got the summary alone and the agents still running
  const saved = only(ran, 'compact.py')
  expect(saved).toHaveLength(1)
  expect(nth(saved, 0).payload).toEqual({
    session_id: 'session-under-test',
    trigger: 'auto',
    compact_summary: '<summary>THE SUMMARY</summary>',
    agents: [
      { id: 'a1', type: 'Explore', description: 'map the parser', status: 'running' },
      { id: 'a3', type: 'general-purpose', description: 'holds a shell', status: 'waiting' },
    ],
  })
  expect(logged).toEqual(['Compaction summary saved to x.md.'])
})

test("the module never rewrites a compaction's instructions", async ($, on) => {
  // Claude Code discards a summary it computed ahead of time when a module
  // rewrites the instructions of the compaction that installs it. Steering comes
  // from the PreCompact command hook instead.
  beneath(on)
  const seen: (string | undefined)[] = []
  on('agent.list', () => ({ value: [] }))
  on('session.compact', (_, e) => {
    seen.push(e.instructions)
    return after('summary')
  })

  await $.session.compact({ trigger: 'precompute', messages: BEFORE })
  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  await $.session.compact({ trigger: 'manual', messages: BEFORE })
  await $.session.compact({ trigger: 'manual', instructions: 'keep X', messages: BEFORE })
  await $.session.compact({ trigger: 'plugin', instructions: 'keep Y', messages: BEFORE })
  await $.session.compact({ trigger: 'auto', agentId: 'agent-7', messages: BEFORE })

  expect(seen).toEqual([undefined, undefined, undefined, 'keep X', 'keep Y', undefined])
})

test('the snapshot records what started the compaction, and the scripts get the hook environment', async ($, on) => {
  const inits: unknown[] = []
  const ran: Ran[] = []
  on('process.hookEnv', () => ({ value: { CLAUDE_PROJECT_DIR: '/proj', CLAUDE_PLUGIN_DATA: '/data', CLAUDE_PID: '4242' } }))
  on('process.run', (_, e) => {
    inits.push(e.init)
    ran.push({ script: String(e.argv[1]).split('/').pop() ?? '', payload: JSON.parse(e.init?.stdin ?? '{}'), argv: e.argv })
    return { value: ranOk('') }
  })
  on('session.id', () => ({ value: 's' }))
  on('agent.list', () => ({ value: [] }))
  on('session.compact', () => after('summary'))

  await $.session.compact({ trigger: 'manual', messages: BEFORE })
  await $.session.compact({ trigger: 'plugin', messages: BEFORE })

  expect(only(ran, 'compact.py').map(one => one.payload.trigger)).toEqual(['manual', 'plugin'])
  // CLAUDE_PID is how the scripts tell this process's mark from an earlier one's
  expect(JSON.stringify(inits[0])).toContain('"CLAUDE_PID":"4242"')
})

test('a compaction whose session cannot be named still runs, unsaved', async ($, on) => {
  const scripts: string[] = []
  on('process.hookEnv', () => ({ value: { CLAUDE_PROJECT_DIR: '/proj' } }))
  on('process.run', (_, e) => {
    scripts.push(String(e.argv[1]).split('/').pop() ?? '')
    return { value: ranOk('') }
  })
  on('session.id', () => {
    throw new Error('no session')
  })
  on('agent.list', () => ({ value: [] }))
  on('session.compact', () => after('summary'))

  const done = await $.session.compact({ trigger: 'auto', messages: BEFORE })

  expect(done.messages).toHaveLength(1)
  expect(scripts).toEqual([])
})

test('a compaction that fails leaves nothing behind for the next start', async ($, on) => {
  const ran = beneath(on)
  on('classic.SessionStart', () => ({}))
  on('session.compact', () => {
    throw new Error('the summarizer fell over')
  })

  await $.session.compact({ trigger: 'auto', messages: BEFORE }).catch(() => undefined)
  await $.classic.SessionStart({ source: 'compact' })

  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBeUndefined()
  expect(only(ran, 'compact.py')).toHaveLength(0)
})

test('the snapshot is filed under the session that was compacted', async ($, on) => {
  let id = 'compacted-session'
  const ran = beneath(on, { sessionId: () => id })
  on('agent.list', () => ({ value: [] }))
  on('session.compact', () => {
    id = 'some-later-session' // the id moves while the summarizer runs
    return after('summary')
  })

  await $.session.compact({ trigger: 'auto', messages: BEFORE })

  expect(nth(only(ran, 'compact.py'), 0).payload.session_id).toBe('compacted-session')
})

test("a subagent's own start is left alone", async ($, on) => {
  const ran = beneath(on)
  on('classic.SessionStart', () => ({ additionalContext: ['for the subagent'] }))

  const answer = await $.classic.SessionStart({ source: 'compact', agent_id: 'agent-7' })

  expect(ran).toHaveLength(0)
  expect(answer.additionalContext).toEqual(['for the subagent'])
})

test('a compaction that was skipped saves nothing', async ($, on) => {
  const ran = beneath(on)
  on('session.compact', () => ({ skip: 'blocked by a hook' }))

  const done = await $.session.compact({ trigger: 'auto', messages: BEFORE })

  expect(done.skip).toBe('blocked by a hook')
  expect(only(ran, 'compact.py')).toHaveLength(0)
})

test('a precompute is not saved and disturbs nothing under way', async ($, on) => {
  const ran = beneath(on)
  on('classic.PreCompact', () => ({}))
  on('classic.SessionStart', () => ({}))
  on('classic.PostCompact', () => ({}))
  on('agent.list', () => ({ value: [] }))
  on('session.compact', async (_, e) => {
    if (e.trigger === 'precompute') return after('computed ahead')
    // a precompute settles while this compaction is still running
    await $.session.compact({ trigger: 'precompute', messages: BEFORE })
    await $.classic.SessionStart({ source: 'compact' })
    await $.classic.PostCompact({ trigger: 'auto', compact_summary: 'THE SUMMARY' })
    return after('summary')
  })

  await $.session.compact({ trigger: 'precompute', messages: BEFORE })
  expect(only(ran, 'compact.py')).toHaveLength(0)

  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  // saved once, by the wrapping hook, with its summary and its trigger intact
  expect(only(ran, 'compact.py').map(one => [one.payload.trigger, one.payload.compact_summary])).toEqual([
    ['auto', 'THE SUMMARY'],
  ])
  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBe('auto')

  // and a bare summarize that overlaps a precompute keeps its trigger and its summary
  await $.classic.PreCompact({ trigger: 'manual', custom_instructions: null })
  await $.session.compact({ trigger: 'precompute', messages: BEFORE })
  await $.classic.SessionStart({ source: 'compact' })
  await $.classic.PostCompact({ trigger: 'manual', compact_summary: 'BARE' })
  expect(nth(only(ran, 'session-start.py'), 1).payload.compact_trigger).toBe('manual')
  expect(only(ran, 'compact.py').map(one => one.payload.compact_summary)).toEqual(['THE SUMMARY', 'BARE'])
})

test("a subagent's own compaction is left alone", async ($, on) => {
  const ran = beneath(on)
  let instructions: string | undefined = 'unset'
  on('session.compact', (_, e) => {
    instructions = e.instructions
    return after('summary')
  })

  await $.session.compact({ trigger: 'auto', agentId: 'agent-7', messages: BEFORE })

  expect(instructions).toBeUndefined()
  expect(ran).toHaveLength(0)
})

test('a summary is never carried from one compaction into the next', async ($, on) => {
  const ran = beneath(on)
  on('agent.list', () => ({ value: [] }))
  on('classic.PostCompact', () => ({}))
  let round = 0
  on('session.compact', async () => {
    round += 1
    // the first compaction announces its summary; the second announces none,
    // and a subagent's PostCompact in between must not be taken for it
    if (round === 1) await $.classic.PostCompact({ trigger: 'auto', compact_summary: 'FIRST' })
    else await $.classic.PostCompact({ trigger: 'auto', compact_summary: 'SUBAGENT', agent_id: 'agent-7' })
    return after(`text ${round}`)
  })

  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  await $.session.compact({ trigger: 'auto', messages: BEFORE })

  const saved = only(ran, 'compact.py')
  expect(saved.map(one => one.payload.compact_summary)).toEqual(['FIRST', ''])
  // the text the conversation now holds is Claude Code's wrapper, never sent as a stand-in
  expect(saved.map(one => Object.keys(one.payload).sort())).toEqual([
    ['agents', 'compact_summary', 'session_id', 'trigger'],
    ['agents', 'compact_summary', 'session_id', 'trigger'],
  ])
})

test('only the start that follows a compaction is told its trigger', async ($, on) => {
  const ran = beneath(on)
  on('agent.list', () => ({ value: [] }))
  on('classic.SessionStart', () => ({}))
  on('session.compact', async () => {
    // some other start arrives while the compaction is still under way
    await $.classic.SessionStart({ source: 'startup', session_id: 'bystander' })
    await $.classic.SessionStart({ source: 'compact' })
    return after('summary')
  })

  await $.session.compact({ trigger: 'auto', messages: BEFORE })

  const starts = only(ran, 'session-start.py')
  expect(starts.map(one => [one.payload.source, one.payload.compact_trigger])).toEqual([
    ['startup', undefined],
    ['compact', 'auto'],
  ])
})

test('a summarize that runs without the compaction dispatch is saved from its PostCompact', async ($, on) => {
  // "Summarize from here" and "up to here": PreCompact, the start, PostCompact; no session.compact.
  const ran = beneath(on, { stdout: { 'compact.py': 'Compaction summary saved to y.md.' } })
  const logged: string[] = []
  on('ui.log', (_, e) => {
    logged.push(String(e.text))
    return { value: undefined }
  })
  on('agent.list', () => ({ value: [agent('a1', 'Explore', 'map', 'running')] }))
  on('classic.PreCompact', () => ({}))
  on('classic.SessionStart', () => ({}))
  on('classic.PostCompact', () => ({}))
  on('session.compact', () => after('a later, ordinary compaction'))

  await $.classic.PreCompact({ trigger: 'manual', custom_instructions: null })
  await $.classic.SessionStart({ source: 'compact', session_id: 'partial' })
  await $.classic.PostCompact({ trigger: 'manual', compact_summary: 'PARTIAL SUMMARY', session_id: 'partial' })

  // the start knew the user asked for it, so no nudge to carry on unprompted
  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBe('manual')
  expect(only(ran, 'compact.py').map(one => one.payload)).toEqual([
    {
      session_id: 'partial',
      trigger: 'manual',
      compact_summary: 'PARTIAL SUMMARY',
      agents: [{ id: 'a1', type: 'Explore', description: 'map', status: 'running' }],
    },
  ])
  expect(logged).toEqual(['Compaction summary saved to y.md.'])

  // and it is not saved a second time with the compaction that comes next
  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  expect(only(ran, 'compact.py').map(one => one.payload.compact_summary)).toEqual(['PARTIAL SUMMARY', ''])
  await $.classic.SessionStart({ source: 'compact', session_id: 'partial' })
  expect(nth(only(ran, 'session-start.py'), 1).payload.compact_trigger).toBeUndefined()
})

test('events inside a wrapped compaction are not mistaken for a bare summarize', async ($, on) => {
  const ran = beneath(on)
  on('agent.list', () => ({ value: [] }))
  on('classic.PreCompact', () => ({}))
  on('classic.SessionStart', () => ({}))
  on('classic.PostCompact', () => ({}))
  on('session.compact', async (_, e) => {
    // the engine reports its own trigger on PreCompact; the wrapping hook's must stand
    await $.classic.PreCompact({ trigger: 'manual', custom_instructions: null })
    await $.classic.SessionStart({ source: 'compact' })
    await $.classic.PostCompact({ trigger: 'manual', compact_summary: `SUMMARY OF ${e.trigger}` })
    return after('summary')
  })

  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBe('auto')
  expect(only(ran, 'compact.py').map(one => [one.payload.trigger, one.payload.compact_summary])).toEqual([
    ['auto', 'SUMMARY OF auto'],
  ]) // once, by the wrapping hook

  // a subagent's summarize is not this conversation's
  await $.classic.PreCompact({ trigger: 'manual', custom_instructions: null, agent_id: 'agent-7' })
  await $.classic.PostCompact({ trigger: 'manual', compact_summary: 'SUBAGENT', agent_id: 'agent-7' })
  expect(only(ran, 'compact.py')).toHaveLength(1)
  await $.classic.SessionStart({ source: 'compact' })
  expect(nth(only(ran, 'session-start.py'), 1).payload.compact_trigger).toBeUndefined()
})

test('a bare summarize leaves nothing behind, and neither does a wrapped compaction', async ($, on) => {
  const ran = beneath(on)
  on('agent.list', () => ({ value: [] }))
  on('classic.PreCompact', () => ({}))
  on('classic.SessionStart', () => ({}))
  on('classic.PostCompact', () => ({}))
  on('session.compact', () => after('summary'))

  // bare summarize, then a start that reports a compaction with no trigger of its own
  await $.classic.PreCompact({ trigger: 'manual', custom_instructions: null })
  await $.classic.PostCompact({ trigger: 'manual', compact_summary: 'FIRST' })
  await $.classic.SessionStart({ source: 'compact' })
  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBeUndefined()

  // wrapped compaction, then a bare summarize: the second is saved on its own
  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  await $.classic.PostCompact({ trigger: 'manual', compact_summary: 'THIRD' })
  expect(only(ran, 'compact.py').map(one => one.payload.compact_summary)).toEqual(['FIRST', '', 'THIRD'])
})

test("an automatic compaction that skips the dispatch is saved as automatic", async ($, on) => {
  // One of Claude Code's automatic paths runs the three classic events and no session.compact.
  const ran = beneath(on)
  on('agent.list', () => ({ value: [] }))
  on('classic.PreCompact', () => ({}))
  on('classic.SessionStart', () => ({}))
  on('classic.PostCompact', () => ({}))

  await $.classic.PreCompact({ trigger: 'auto', custom_instructions: null })
  await $.classic.SessionStart({ source: 'compact' })
  await $.classic.PostCompact({ trigger: 'auto', compact_summary: 'AUTO SUMMARY', session_id: 'auto-session' })

  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBe('auto') // so the model is told to carry on
  expect(only(ran, 'compact.py').map(one => one.payload)).toEqual([
    { session_id: 'auto-session', trigger: 'auto', compact_summary: 'AUTO SUMMARY', agents: [] },
  ])
})

test('a PostCompact with no summary outside a compaction saves and says nothing', async ($, on) => {
  // What another plugin's replacement compaction reports after its dispatch has returned.
  const ran = beneath(on)
  const logged: string[] = []
  on('ui.log', (_, e) => {
    logged.push(String(e.text))
    return { value: undefined }
  })
  on('agent.list', () => ({ value: [] }))
  on('classic.PostCompact', () => ({}))

  await $.classic.PostCompact({ trigger: 'manual', compact_summary: '' })

  expect(ran).toHaveLength(0)
  expect(logged).toEqual([])
})

test('a bare summarize that fails to save does not fail the event', async ($, on) => {
  on('process.hookEnv', () => ({ value: { CLAUDE_PROJECT_DIR: '/proj' } }))
  on('process.run', () => {
    throw new Error('python3 is not installed')
  })
  on('agent.list', () => ({ value: [] }))
  on('classic.PostCompact', () => ({ stopReason: 'kept' }))

  const answer = await $.classic.PostCompact({ trigger: 'manual', compact_summary: 'S' })

  expect(answer.stopReason).toBe('kept')
})

test('the trigger of a finished compaction does not leak into a later start', async ($, on) => {
  const ran = beneath(on)
  on('agent.list', () => ({ value: [] }))
  on('classic.SessionStart', () => ({}))
  on('session.compact', () => after('summary'))

  await $.session.compact({ trigger: 'auto', messages: BEFORE })
  await $.classic.SessionStart({ source: 'compact' })

  expect(nth(only(ran, 'session-start.py'), 0).payload.compact_trigger).toBeUndefined()
})

test("before the plugin's own commands: agents for a save, a fresh mark for the rest", async ($, on) => {
  const order: string[] = []
  const ran = beneath(on, { order })
  on('agent.list', () => ({ value: [agent('a1', 'Explore', 'map', 'running')] }))
  on('command.run', (_, e) => {
    order.push(`command:${e.command}`)
    return {}
  })

  await $.command.run(typed('session-handoff:save', 'a note'))
  await $.command.run(typed('session-handoff:resume'))
  await $.command.run(typed('exit'))
  await $.command.run(typed('another-plugin:save'))

  expect(order).toEqual([
    'agents.py',
    'command:session-handoff:save',
    'session-start.py',
    'command:session-handoff:resume',
    'command:exit',
    'command:another-plugin:save',
  ])
  expect(nth(only(ran, 'agents.py'), 0).payload).toEqual({
    session_id: 'session-under-test',
    agents: [agent('a1', 'Explore', 'map', 'running')].map(({ id, type, description, status }) => ({ id, type, description, status })),
  })
  expect(nth(only(ran, 'session-start.py'), 0).payload).toEqual({ session_id: 'session-under-test', source: 'module' })
})

test('a failing script never fails the event', async ($, on) => {
  on('process.hookEnv', () => ({ value: { CLAUDE_PROJECT_DIR: '/proj' } }))
  on('process.run', () => {
    throw new Error('python3 is not installed')
  })
  on('session.id', () => ({ value: 's' }))
  on('agent.list', () => {
    throw new Error('no agents today')
  })
  on('classic.SessionStart', () => ({ additionalContext: ['kept'] }))
  on('session.compact', () => after('summary'))
  on('command.run', () => ({ text: 'ran' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  expect((await $.classic.SessionStart({ source: 'startup' })).additionalContext).toEqual(['kept'])
  expect((await $.session.compact({ trigger: 'auto', messages: BEFORE })).messages).toHaveLength(1)
  expect((await $.command.run(typed('session-handoff:save'))).text).toBe('ran')
  expect((await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })).cwd).toBe('/')
})

test('a script that exits non-zero contributes nothing', async ($, on) => {
  beneath(on, { exitCode: 1, stdout: { 'session-start.py': 'half an answer' } })
  on('classic.SessionStart', () => ({}))

  expect((await $.classic.SessionStart({ source: 'startup' })).additionalContext).toBeUndefined()
})

test('without a plugin data folder the scripts fall back to their own', async ($, on) => {
  const argvs: (readonly string[])[] = []
  on('process.hookEnv', () => ({ value: { CLAUDE_PROJECT_DIR: '/proj' } }))
  on('process.run', (_, e) => {
    argvs.push(e.argv)
    return { value: ranOk('') }
  })
  on('classic.SessionStart', () => ({}))

  await $.classic.SessionStart({ source: 'startup' })

  expect(argvs[0]?.slice(2)).toEqual(['--project-dir', '/proj'])
})

test('a module loaded into a running session marks it once', async ($, on) => {
  let id = 'loaded-mid-session'
  const ran = beneath(on, { sessionId: () => id })
  on('classic.SessionStart', () => ({}))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(ran.map(one => one.payload)).toEqual([{ session_id: 'loaded-mid-session', source: 'module' }])

  // a session SessionStart already ran for needs no second visit
  id = 'fresh-process'
  await $.classic.SessionStart({ source: 'startup', session_id: 'fresh-process' })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(ran).toHaveLength(2)
})
