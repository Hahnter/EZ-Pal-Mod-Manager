#!/usr/bin/env python3
"""Run every test script and summarise.

    python tests/run_all.py            all tests
    python tests/run_all.py safety     only files whose name contains 'safety'
    python tests/run_all.py -v         show each test's full output

Each script runs in its own process against a throwaway install in the temp
folder; none touch your game, your saves or the app's real data. No test
windows appear on screen.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    # A failure message can contain any character; a cp1252 console mustn't
    # turn that into a crash of the runner itself.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv
    scripts = sorted(p for p in HERE.glob("test_*.py")
                     if not args or any(a in p.name for a in args))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    failed = []
    started = time.time()
    for script in scripts:
        t = time.time()
        try:
            res = subprocess.run([sys.executable, str(script)], capture_output=True,
                                 text=True, encoding="utf-8", env=env, timeout=600,
                                 cwd=str(HERE.parent))
            out, code = res.stdout + res.stderr, res.returncode
        except subprocess.TimeoutExpired:
            out, code = "timed out after 600 s", 1
        checks = sum(1 for ln in out.splitlines() if ln.startswith(("PASS ", "FAIL ")))
        status = "ok  " if code == 0 else "FAIL"
        print(f"{status}  {script.name:<24} {checks:>3} checks  {time.time() - t:5.1f}s")
        if code != 0:
            failed.append(script.name)
            lines = out.splitlines()
            shown = [ln for ln in lines if ln.startswith("FAIL ")] or lines[-25:]
            for ln in shown:
                print("        " + ln)
        elif verbose:
            print("\n".join("        " + ln for ln in out.splitlines()))
    print(f"\n{len(scripts) - len(failed)}/{len(scripts)} test files passed "
          f"in {time.time() - started:.0f}s")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
