#!/usr/bin/env python3
# Print a project snapshot (git state + detected build/test/run commands) as
# markdown, used as ground truth when writing a handoff.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

def main():
    lib.bootstrap(sys.argv[1:], strict=True)
    print(lib.facts())


if __name__ == "__main__":          # importable for tests; commands run it as a script
    main()
