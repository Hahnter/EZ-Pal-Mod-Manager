"""The test harness itself: a test must never be able to reach a real install."""
from pathlib import Path

from helpers import Checker, make_game, sandbox, use_game

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

check.finish()
