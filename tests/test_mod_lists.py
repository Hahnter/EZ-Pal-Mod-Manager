"""UE4SS's two mod lists (mods.txt / mods.json) when they disagree.

Found on a real install: mods.txt said NoMoreHoldButton : 1, mods.json said
false. UE4SS read mods.txt and started the mod; the app believed mods.json and
showed it as off, and switching it off only edited mods.json.
"""
import json

from helpers import Checker, lua_mod, make_game, sandbox, scan, use_game

SB = sandbox("mod_lists")
import palmods                              # noqa: E402

check = Checker()
game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"
mods = win64 / "ue4ss/Mods"

MODS_TXT = ("NoMoreHoldButton : 1\r\n"
            "SplitScreenMod : 0\r\n"
            "; NoMoreHoldButton : 0   <- a comment, never edited\r\n"
            "BPModLoaderMod : 1\r\n"
            "; Built-in keybinds, do not move up!\r\n"
            "Keybinds : 1\r\n")


def reset():
    (mods / "mods.txt").write_bytes(MODS_TXT.encode())
    (mods / "mods.json").write_text(json.dumps([
        {"mod_name": "NoMoreHoldButton", "mod_enabled": False},
        {"mod_name": "SplitScreenMod", "mod_enabled": False},
        {"mod_name": "OnlyInJson", "mod_enabled": True},
    ], indent=4))


for name in ("NoMoreHoldButton", "SplitScreenMod", "OnlyInJson", "Unlisted"):
    lua_mod(mods, name, enabled=False)
reset()


def log_says(which):
    (win64 / "ue4ss/UE4SS.log").write_text(
        "[2026-09-14 00:05:38.2] UE4SS - v3.0.1 Beta #0 - Git SHA #c838a8ac\n"
        f"[2026-09-14 00:05:39.3] Starting mods (from {which} (X) load order)...\n"
        "[2026-09-14 00:06:06.9] Starting Lua mod 'NoMoreHoldButton'\n")


def state():
    _, data = scan(game)
    return {m["name"]: m for m in data["ue4ss_mods"]}, data


check.section("reading")
log_says("mods.txt")
m, data = state()
check("log tells which list UE4SS read", data["log"]["mod_list"] == "mods.txt")
check("mods.txt wins when UE4SS read it", m["NoMoreHoldButton"]["enabled"] is True)
check("disagreement is flagged", m["NoMoreHoldButton"]["list_conflict"] is True)
check("agreeing mod not flagged", m["SplitScreenMod"]["list_conflict"] is False)
check("mod only in mods.json still counts", m["OnlyInJson"]["enabled"] is True)
check("unlisted mod without enabled.txt is off", m["Unlisted"]["enabled"] is False)

log_says("mods.json")
m, _ = state()
check("mods.json wins when UE4SS read that", m["NoMoreHoldButton"]["enabled"] is False)

(win64 / "ue4ss/UE4SS.log").unlink()
m, _ = state()
check("no log yet: mods.txt is assumed", m["NoMoreHoldButton"]["enabled"] is True)

check.section("writing")
log_says("mods.txt")
palmods.set_enabled("NoMoreHoldButton", False)
raw = (mods / "mods.txt").read_bytes().decode()
check("switching off edits mods.txt", "NoMoreHoldButton : 0\r\n" in raw, raw.splitlines()[0])
check("the commented line is untouched", "; NoMoreHoldButton : 0   <- a comment" in raw)
check("everything else byte-identical",
      raw == MODS_TXT.replace("NoMoreHoldButton : 1\r\n", "NoMoreHoldButton : 0\r\n", 1))
js = {e["mod_name"]: e["mod_enabled"] for e in json.loads((mods / "mods.json").read_text())}
check("and mods.json", js["NoMoreHoldButton"] is False)
m, _ = state()
check("now shown as off", m["NoMoreHoldButton"]["enabled"] is False
      and m["NoMoreHoldButton"]["list_conflict"] is False)

palmods.set_enabled("SplitScreenMod", True)
raw = (mods / "mods.txt").read_text()
js = {e["mod_name"]: e["mod_enabled"] for e in json.loads((mods / "mods.json").read_text())}
check("switching on sets both lists", "SplitScreenMod : 1" in raw and js["SplitScreenMod"] is True)
check("and creates enabled.txt", (mods / "SplitScreenMod/enabled.txt").is_file())

before = (mods / "mods.txt").read_bytes()
palmods.set_enabled("Unlisted", True)
check("a mod not in mods.txt isn't added to it", (mods / "mods.txt").read_bytes() == before)
check("it's switched on by enabled.txt instead", (mods / "Unlisted/enabled.txt").is_file())

check.finish()
