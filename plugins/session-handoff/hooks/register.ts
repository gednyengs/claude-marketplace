// session-handoff's lifecycle, as a Claude Code hooks module.
//
// This file decides WHEN something happens; the Python scripts beside it decide
// WHAT. Every path, topic and file-format rule lives in scripts/lib.py, where the
// test suite is. Three things here could not be done from command hooks:
//
//   /clear       The module stays loaded across a /clear and sees the session
//                that ended and the one that began, so the cleared session's
//                topic is handed over by id. (Command hooks were two processes
//                with only the working directory in common.)
//   compaction   One `session.compact` hook wraps the whole compaction and
//                saves the summary on the way out. (Command hooks needed a
//                skeleton file written before and found again after.) A
//                summarize that Claude Code runs without that dispatch is
//                saved from its PostCompact event instead.
//   agents       Only a module can ask Claude Code which agents are running.
//
// A restart, `--resume`, `--fork-session` and "Move to background" each start a
// new process and load this module afresh, with nothing in memory. Continuity
// across those is carried by files, exactly as before: see scripts/lib.py.
//
// Nothing here may break the session. Every call out is wrapped, and on any
// failure the event continues as if this plugin were not installed.
import type { EngineInterface, Register } from 'claude-code'

// What this module does NOT do is steer the compaction summary. That text comes
// from the PreCompact command hook (scripts/precompact.py): Claude Code throws
// away a summary it computed ahead of time when a module rewrites the
// instructions of the compaction that installs it, and a PreCompact hook's text
// does not count as a rewrite. So this hook never touches `instructions`.

const COMMANDS = 'session-handoff:'
const SAVE_COMMAND = `${COMMANDS}save`
const ENDED = ['completed', 'failed', 'killed']

// Module memory. It survives /clear and compaction and nothing else, which is
// exactly the span it is used for.
let clearedFrom: string | undefined // the session a /clear just ended
let compactTrigger: string | undefined // what started the compaction under way
let rawSummary: string | undefined // that compaction's summary, as PostCompact carried it
let wrapped = false // a `session.compact` dispatch for this conversation is in flight and will save
let markedSession: string | undefined // the session session-start.py last ran for

/** Runs one of the plugin's scripts with `payload` as JSON on stdin; its stdout, or '' on any failure. */
async function run($: EngineInterface, script: string, payload: unknown): Promise<string> {
  try {
    const env = await $.process.hookEnv()
    const project = env.CLAUDE_PROJECT_DIR ?? (await $.session.root())
    const argv = ['python3', `${$.plugin.root}/scripts/${script}`, '--project-dir', project]
    if (env.CLAUDE_PLUGIN_DATA) argv.push('--plugin-data', env.CLAUDE_PLUGIN_DATA)
    const ran = await $.process.run(argv, { stdin: JSON.stringify(payload), env, timeoutMs: 60_000 })
    return ran.exitCode === 0 ? ran.stdout.trim() : ''
  } catch {
    return ''
  }
}

/** The agents Claude Code lists as not yet ended, reduced to what a handoff records. */
async function runningAgents($: EngineInterface) {
  try {
    const agents = await $.agent.list()
    return agents
      .filter(agent => !ENDED.includes(agent.status))
      .map(agent => ({ id: agent.id, type: agent.type, description: agent.description, status: agent.status }))
  } catch {
    return []
  }
}

/**
 * The id of the conversation's last row. A session that continues another under
 * a new id starts with that conversation's rows, ids included, so this is how
 * the fork is matched to the transcript it came from before Claude Code has
 * written anything that names the parent.
 */
async function lastRowId($: EngineInterface): Promise<string | undefined> {
  try {
    const rows = await $.session.messages({ last: 1 })
    return Array.isArray(rows) ? rows[0]?.uuid : undefined
  } catch {
    return undefined
  }
}

export const register: Register = on => {
  // The module's own start: once per process, and again when the plugin is
  // installed or reloaded into a session already under way. Only the second
  // case needs anything: no SessionStart will come to mark this session.
  on('session.start', async ($, e, next) => {
    try {
      const id = await $.session.id()
      if (markedSession !== id) {
        markedSession = id
        await run($, 'session-start.py', { session_id: id, source: 'module' })
      }
    } catch {
      // not worth failing a start over
    }
    return next(e)
  })

  on('session.end', ($, e, next) => {
    clearedFrom = e.reason === 'clear' ? e.sessionId : undefined
    return next(e)
  })

  // startup, resume, fork, clear and compact. What session-start.py prints is
  // handed to the model with the event.
  on('classic.SessionStart', async ($, e, next) => {
    // A subagent's own start (after it compacts, say) is not this conversation's.
    if (e.agent_id !== undefined) return next(e)
    const payload = {
      session_id: e.session_id,
      transcript_path: e.transcript_path,
      source: e.source,
      cleared_from: e.source === 'clear' ? clearedFrom : undefined,
      compact_trigger: e.source === 'compact' ? compactTrigger : undefined,
      last_uuid: e.source === 'fork' ? await lastRowId($) : undefined,
      seconds_since_last_response: e.source === 'fork' ? e.seconds_since_last_response : undefined,
    }
    if (e.source === 'clear') clearedFrom = undefined
    markedSession = e.session_id
    const said = await run($, 'session-start.py', payload)
    const beneath = await next(e)
    if (said === '') return beneath
    return { ...beneath, additionalContext: [...(beneath.additionalContext ?? []), said] }
  })

  // Not every compaction goes through `session.compact`: "Summarize from here"
  // and "up to here", and one of Claude Code's automatic paths, run PreCompact,
  // the start, and PostCompact with nothing wrapped around them. For those, the
  // trigger is taken here so the start that follows knows what began it, and
  // the summary is saved from PostCompact below.
  on('classic.PreCompact', ($, e, next) => {
    if (e.agent_id === undefined && !wrapped) compactTrigger = e.trigger
    return next(e)
  })

  // The summary alone, before Claude Code wraps it in its continuation text.
  on('classic.PostCompact', async ($, e, next) => {
    if (e.agent_id !== undefined) return next(e)
    if (wrapped) {
      rawSummary = e.compact_summary // saved by the `session.compact` hook on its way out
      return next(e)
    }
    compactTrigger = undefined
    const answer = await next(e)
    // An empty summary here is another plugin's replacement compaction reporting
    // in after its dispatch; there is nothing to save and nothing to say.
    if (!e.compact_summary) return answer
    try {
      const said = await run($, 'compact.py', {
        session_id: e.session_id,
        trigger: e.trigger,
        compact_summary: e.compact_summary,
        agents: await runningAgents($),
      })
      if (said !== '') $.ui.log(said)
    } catch {
      // the summarize itself stands
    }
    return answer
  })

  on('session.compact', async ($, e, next) => {
    // A subagent compacting its own transcript is not this conversation. A
    // precompute installs nothing: the compaction it prepares for comes later,
    // through this same hook, and is saved then.
    // It touches no state here either: a precompute can settle while a real
    // compaction or a bare summarize is under way, and must not disturb it.
    if (e.agentId !== undefined || e.trigger === 'precompute') return next(e)

    // Taken now: this is the session being compacted, whatever follows.
    let id: string | undefined
    try {
      id = await $.session.id()
    } catch {
      // without it the compaction still runs; it is just not saved
    }
    wrapped = true
    compactTrigger = e.trigger
    rawSummary = undefined
    let summary: string | undefined
    let done
    try {
      done = await next(e) // unchanged: see the note on steering above
    } finally {
      summary = rawSummary
      rawSummary = undefined
      compactTrigger = undefined
      wrapped = false
    }
    if (done.messages === undefined || id === undefined) return done
    try {
      const said = await run($, 'compact.py', {
        session_id: id,
        trigger: e.trigger,
        compact_summary: summary ?? '',
        agents: await runningAgents($),
      })
      if (said !== '') $.ui.log(said)
    } catch {
      // the compaction itself stands
    }
    return done
  })

  // The plugin's own slash commands. Before /session-handoff:save, note which
  // agents are running; the command's script prints the note into the prompt.
  // Before any of them, refresh this session's mark, so a long-lived session
  // whose mark was swept is not told the module is missing.
  on('command.run', async ($, e, next) => {
    if (!e.command.startsWith(COMMANDS)) return next(e)
    try {
      const id = await $.session.id()
      if (e.command === SAVE_COMMAND) {
        await run($, 'agents.py', { session_id: id, agents: await runningAgents($) })
      } else {
        await run($, 'session-start.py', { session_id: id, source: 'module' })
      }
    } catch {
      // the command goes ahead regardless
    }
    return next(e)
  })
}
