"""The test harness itself: a test must never be able to reach a real install."""
import os
import shutil
import time
from pathlib import Path

from helpers import (ROOT, STALE_DAYS, Checker, make_game, prune_sandboxes, sandbox,
                     sandbox_home, use_game)

SB = sandbox("isolation")
import palmods, palpaths                    # noqa: E402

check = Checker()

check("auto-detection is disabled", palpaths.detect() == [])
check("no game until a test sets one", palpaths.game() is None)

# Pretend a real install was saved in settings: resolving it must fail loudly.
outside = Path.home() / "pmm-not-a-test-install"
palpaths._game = outside
try:
    palpaths.game()
    check("a non-temp game folder is refused", False)
except AssertionError as exc:
    check("a non-temp game folder is refused", "real Palworld install" in str(exc))
palpaths._game = None

try:
    use_game(outside)
    check("use_game refuses non-temp folders", False)
except AssertionError:
    check("use_game refuses non-temp folders", True)

game = use_game(make_game(SB))
paths = palmods.discover()
check("sandbox game resolves", Path(paths["game"]) == game)
check("app data is inside the sandbox",
      str(palpaths.data_dir()).startswith(str(SB)), palpaths.data_dir())

check.section("each checkout has its own sandboxes")
# Worktrees run the suite at the same time; sharing one folder, a run in one
# wiped the sandbox a run in another was still using.
home = sandbox_home()
other = sandbox_home(ROOT / "another-checkout")     # stands in for a sibling worktree
check("this test's sandbox is in this checkout's folder", SB.parent == home, SB)
check("another checkout gets a different folder", other != home, other)

stale = time.time() - (STALE_DAYS + 1) * 86400
for d in (home / "probe-old", home / "probe-new", other / "probe-old"):
    (d / "data").mkdir(parents=True, exist_ok=True)
for d in (home / "probe-old", other / "probe-old", other):
    os.utime(d, (stale, stale))
prune_sandboxes()
check("a sandbox untouched for a week is pruned", not (home / "probe-old").exists())
check("a recent one is kept", (home / "probe-new").is_dir() and SB.is_dir())
check("another checkout's sandboxes are never touched", (other / "probe-old").is_dir())
shutil.rmtree(home / "probe-new", ignore_errors=True)
shutil.rmtree(other, ignore_errors=True)

check.finish()
