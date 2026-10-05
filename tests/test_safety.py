"""Game-update safety and tools: UE4SS detection, dedicated servers, patch
tracking, pak conflicts, hotkeys, PalSchema, save backups, leftovers, load
order, modlists and log classification."""
import json
import os
import time
from pathlib import Path

from helpers import (Checker, fake_pak, lua_mod, make_game, sandbox, scan,
                     steam_library as steamify, write_log)

SB = sandbox("safety")
import palmods, palpaths, palsafety, paltools   # noqa: E402

check = Checker()
use = scan


# ======================================================== UE4SS detection
print("\n== UE4SS detection ==")
g = make_game(SB / "noue4ss", ue4ss=None)
paths, data = use(g)
check("no UE4SS: app still scans (no exit)", data["layout"] == "not installed")
check("no UE4SS: status missing", data["ue4ss"]["state"] == "missing", data["ue4ss"]["summary"])
check("no UE4SS: doctor has nothing to repair", palmods.doctor(False) == ([], []))

g = make_game(SB / "flat", ue4ss="flat")
paths, data = use(g)
check("flat UE4SS: detected as flat + warned", data["ue4ss"]["layout"] == "flat"
      and data["ue4ss"]["state"] == "warn", data["ue4ss"]["problems"][0][:50])

g = make_game(SB / "noproxy", ue4ss="experimental")
(g / "Pal/Binaries/Win64/dwmapi.dll").unlink()
paths, data = use(g)
check("proxy missing: broken", data["ue4ss"]["state"] == "broken")

g = make_game(SB / "both", ue4ss="experimental")
(g / "Pal/Binaries/Win64/UE4SS.dll").write_bytes(b"x")
paths, data = use(g)
check("both layouts: conflict", data["ue4ss"]["state"] == "conflict")

# ======================================================== dedicated server
print("\n== dedicated server ==")
common = steamify(SB / "srvlib", "PalServer", "2394010", "777", 1000)
srv = make_game(common, server=True)
check("server validates", palpaths.validate(srv)[0], palpaths.validate(srv)[1])
check("server kind + label", palpaths.kind_of(srv) == "server"
      and palpaths.label(srv) == "Dedicated server")
check("server build from manifest", palsafety.build_info(srv)["id"] == "777")
paths, data = use(srv)
check("server scans", data["install"]["kind"] == "server")
(srv / "Pal/Saved/SaveGames/0/world").mkdir(parents=True)
check("server save dir is inside install",
      palsafety.save_dir(srv) == srv / "Pal/Saved/SaveGames")

# ======================================================== patch tracking
print("\n== patch tracking ==")
common = steamify(SB / "lib", "Palworld", "1623730", "1000", int(time.time()) - 86400)
game = make_game(common)
mods = game / "Pal/Binaries/Win64/ue4ss/Mods"
lua_mod(mods, "Alpha")
lua_mod(mods, "Beta")
write_log(game / "Pal/Binaries/Win64", ["Alpha", "Beta"])       # ran after patch
paths, data = use(game)
check("run on current build: no banner", not data["patch"]["updated"], json.dumps(data["patch"]))

# Steam patches the game: new buildid, LastUpdated now.
steamify(SB / "lib", "Palworld", "1623730", "2000", int(time.time()) + 5)
paths, data = use(game)
check("after patch: banner", data["patch"]["updated"])
check("after patch: both mods unverified", sorted(data["patch"]["unverified"]) == ["Alpha", "Beta"],
      data["patch"]["unverified"])
check("after patch: names previous build", data["patch"]["last_run_build"] == "build 1000",
      data["patch"]["last_run_build"])

# The user plays on the new build; Beta breaks.
write_log(game / "Pal/Binaries/Win64", ["Alpha"], when_offset=60)
paths, data = use(game)
check("played on new build: banner gone", not data["patch"]["updated"])
check("Beta regressed after the patch", data["patch"]["regressed"] == {"Beta": "build 1000"},
      data["patch"]["regressed"])

# ======================================================== conflicts
print("\n== pak conflicts ==")
paks = game / "Pal/Content/Paks"
fake_pak(paks / "~mods/HairA_P.pak", "../../../", ["Pal/Content/Hair/SK_Hair.uasset", "Pal/Content/Hair/SK_Hair.uexp"])
fake_pak(paks / "~mods/zzHairB_P.pak", "../../../Pal/Content/Hair/", ["SK_Hair.uasset", "SK_Hair.uexp", "Other.uasset"])
fake_pak(paks / "~mods/NoSuffix.pak", "../../../", ["Pal/Content/Hair/SK_Hair.uasset"])
paths, data = use(game)
pairs = {tuple(c["mods"]): c for c in data["conflicts"]["pairs"]}
ab = pairs.get(("HairA_P", "zzHairB_P"))
check("same asset via different mount/file splits detected", ab is not None and ab["assets"] == 1,
      ab and ab["examples"])
check("tie between _P paks: later name likely wins, not certain",
      ab and ab["winner"] == "zzHairB_P" and not ab["sure"])
ns = pairs.get(("HairA_P", "NoSuffix"))
check("_P beats non-_P, certain", ns and ns["winner"] == "HairA_P" and ns["sure"])
check("non-_P content pak flagged", data["conflicts"]["no_patch_suffix"] == ["NoSuffix"])
check("both enabled -> live", ab and ab["live"])

# ======================================================== keybinds
print("\n== keybinds ==")
lua_mod(mods, "LitMod", main="RegisterKeyBind(Key.F6, {ModifierKey.CONTROL}, function() end)\n"
                            "-- RegisterKeyBind(Key.F12, function() end)\n")
lua_mod(mods, "CfgLua", main="local c = require('config')\n",
        extra={"Scripts/config.lua": 'return {\n ToggleKey = "F6", ToggleModifiers = {"Ctrl"},\n OpenKey = "F7",\n PadKey = "Gamepad_FaceButton_Top",\n}'})
lua_mod(mods, "IniMod", extra={"config.ini": "[keys]\nmenu = CTRL+F6 ; open\nzoom = F7, F8\n[other]\nSpeed = 3\n"})
lua_mod(mods, "Opaque", main="local k = cfg() RegisterKeyBind(k, function() end)")
lua_mod(mods, "OffMod", enabled=False, extra={"config.ini": "HotKey = F8\n"})
paths, data = use(game)
kb = data["keybinds"]
check("literal bind with modifier read; commented one ignored", kb["keys"].get("LitMod") == ["Ctrl+F6"], kb["keys"].get("LitMod"))
check("lua config key + paired modifiers; gamepad skipped",
      sorted(kb["keys"].get("CfgLua", [])) == ["Ctrl+F6", "F7"], kb["keys"].get("CfgLua"))
check("ini [keys] section incl. combos and lists",
      sorted(kb["keys"].get("IniMod", [])) == ["Ctrl+F6", "F7", "F8"], kb["keys"].get("IniMod"))
clash = {c["key"]: c for c in kb["clashes"]}
check("Ctrl+F6 claimed by three mods, live", "Ctrl+F6" in clash and len(clash["Ctrl+F6"]["mods"]) == 3
      and clash["Ctrl+F6"]["live"], clash.get("Ctrl+F6"))
check("F8 clash with a disabled mod is not live", "F8" in clash and not clash["F8"]["live"])
check("variable-key mod reported unreadable", "Opaque" in kb["unreadable"], kb["unreadable"])

# ======================================================== PalSchema
print("\n== PalSchema ==")
fw = mods / "PalSchema"
(fw / "dlls").mkdir(parents=True)
(fw / "dlls/main.dll").write_bytes(b"x")
(fw / "enabled.txt").write_text("")
(fw / "mods/BetterRates/raw").mkdir(parents=True)
(fw / "mods/BetterRates/raw/rates.json").write_text("{}")
paths, data = use(game)
ps = {s["name"]: s for s in data["palschema_mods"]}
check("PalSchema mod listed", "BetterRates" in ps and ps["BetterRates"]["enabled"]
      and ps["BetterRates"]["sections"] == ["raw"], ps)
print("   ", palmods.set_enabled("BetterRates", False))
check("disable moves folder out of mods/", (fw / "disabled-mods/BetterRates").is_dir()
      and not (fw / "mods/BetterRates").exists())
paths, data = use(game)
check("rescan shows it off", not {s["name"]: s for s in data["palschema_mods"]}["BetterRates"]["enabled"])
print("   ", palmods.set_enabled("BetterRates", True))
check("enable moves it back", (fw / "mods/BetterRates").is_dir())

# ======================================================== backups
print("\n== save backups ==")
saves = Path(os.environ["LOCALAPPDATA"]) / "Pal/Saved/SaveGames/7656/WORLD1"
saves.mkdir(parents=True)
(saves / "Level.sav").write_text("original world")
paths, data = use(game)
check("save dir found", palsafety.save_dir(game) == saves.parent.parent)
check("new setup needs a backup", palsafety.needs_auto_backup(game, data))
meta = palsafety.backup_saves(game, reason="auto", data=data)
check("backup copied", Path(meta["path"] if "path" in meta else "").exists() or
      (palpaths.data_dir() / "backups").exists(), meta["id"])
check("same setup no longer needs a backup", not palsafety.needs_auto_backup(game, data))
(saves / "Level.sav").write_text("CORRUPTED by a bad mod")
before = palsafety.restore_backup(game, meta["id"])
check("restore put the original back", (saves / "Level.sav").read_text() == "original world")
check("restore backed up the corrupted state first",
      any(b["reason"] == "before restore" for b in palsafety.list_backups(game)), before["id"])
check("no leftover .pmm-restoring folder",
      not any(p.name.endswith(".pmm-restoring") for p in saves.parent.parent.parent.iterdir()))
for _ in range(12):
    palsafety.backup_saves(game, reason="auto", data=data)
autos = [b for b in palsafety.list_backups(game) if b["reason"] == "auto"]
check("auto backups pruned to 10", len(autos) == 10, len(autos))

# ======================================================== leftovers + recycle
print("\n== leftovers ==")
(paks / "LogicMods/Ghost.modconfig.json").write_text("{}")
(paks / "LogicMods/GhostDir").mkdir()
(paks / "~mods/HairA_P.pak.json").write_text("{}")          # belongs to HairA_P
(paks / "~mods/Gone_P.ucas").write_bytes(b"x")
(mods / "Husk").mkdir()
(mods / "Husk/enabled.txt").write_text("")
(game / "Pal/Binaries/Win64/UE4SS.log.bak").write_text("old")
# UE4SS folders the installer parked. Installing with 1.0.0 parked ue4ss\Mods
# along with the rest, so one can hold the only copy of someone's mods.
win64 = game / "Pal/Binaries/Win64"
old = win64 / "ue4ss.pmm-old-20261001-1200"
for name in ("Alpha", "beta", "Zed", "BPModLoaderMod", "shared"):
    lua_mod(old / "Mods", name)              # Alpha and Beta are installed;
                                             # case doesn't matter on Windows
(old / "Mods/Gone/dlls").mkdir(parents=True)
(old / "Mods/Gone/dlls/main.dll").write_bytes(b"x")
(old / "Mods/OffLost").mkdir()
(old / "Mods/OffLost/enabled.txt.disabled").write_text("")
(old / "Mods/Notes").mkdir()
(old / "Mods/Notes/readme.txt").write_text("not a mod")
(old / "Mods/mods.txt").write_text("Zed : 1\n")
(old / "Mods/PalSchema/dlls").mkdir(parents=True)
(old / "Mods/PalSchema/dlls/main.dll").write_bytes(b"x")
for sub in ("mods/BetterRates", "mods/OldRates", "disabled-mods/OffRates"):
    (old / "Mods/PalSchema" / sub).mkdir(parents=True)
lua_mod(win64 / "ue4ss.pmm-old-20261002-0900/Mods", "Alpha")
lua_mod(win64 / "ue4ss.pmm-old-20261003-0900/Mods", "Solo")
(win64 / "UE4SS.dll.pmm-old-20261001-1200").write_bytes(b"x")
paths, data = use(game)
left = {Path(i["path"]).name: i for i in paltools.find_leftovers(paths, data)}
check("orphaned config found + ticked", left.get("Ghost.modconfig.json", {}).get("checked"))
check("orphaned LogicMods folder found", "GhostDir" in left)
check("companion of an installed pak NOT flagged", "HairA_P.pak.json" not in left)
check("orphaned .ucas found", "Gone_P.ucas" in left)
check("husk mod folder found", "Husk" in left)
check("parked UE4SS file listed but unticked", "UE4SS.log.bak" in left and not left["UE4SS.log.bak"]["checked"])
victims = [left["Ghost.modconfig.json"]["path"], left["Husk"]["path"]]
ok = paltools.recycle(victims)
check("recycle bin removal succeeded", ok and not any(Path(v).exists() for v in victims))

parked = left.get(old.name, {})
check("old UE4SS holding mods that aren't installed has its own kind",
      parked.get("kind") == "old UE4SS with mods", parked.get("kind"))
check("names mods and PalSchema mods; skips installed, built-in and non-mods",
      parked.get("missing") == ["Gone", "OffLost", "Zed", "OffRates", "OldRates"],
      parked.get("missing"))
check("why names the first three and counts the rest",
      parked.get("why") == "It holds Gone, OffLost, Zed and 2 other mods "
                           "that aren't installed now.", parked.get("why"))
check("old UE4SS holding mods stays unticked", parked and not parked["checked"])
solo = left.get("ue4ss.pmm-old-20261003-0900", {})
check("one mod: named in a sentence",
      solo.get("why") == "It holds Solo, which isn't installed now.", solo.get("why"))
plain = left.get("ue4ss.pmm-old-20261002-0900", {})
check("old UE4SS whose mods are all installed: plain entry",
      plain.get("kind") == "old UE4SS" and "missing" not in plain, plain)
check("parked UE4SS.dll: plain entry",
      left.get("UE4SS.dll.pmm-old-20261001-1200", {}).get("kind") == "old UE4SS")
lua_mod(mods, "Zed")                         # put back by hand
paths, data = use(game)
again = {Path(i["path"]).name: i for i in paltools.find_leftovers(paths, data)}
check("a mod put back is no longer named; four are all named",
      again[old.name]["why"] == "It holds Gone, OffLost, OffRates and OldRates, "
                                "which aren't installed now.", again[old.name]["why"])

# ======================================================== load order
print("\n== load order ==")
bpml = mods / "BPModLoaderMod"
(bpml / "Scripts").mkdir(parents=True)
(bpml / "Scripts/main.lua").write_text("x")
(bpml / "load_order.txt").write_bytes(b"; header one\r\n; header two\r\n")
header, entries = paltools.read_load_order(paths)
check("header read, no entries", header == ["; header one", "; header two"] and entries == [])
paltools.write_load_order(paths, ["ModB.pak", "ModA", "ModB", ""])
raw = (bpml / "load_order.txt").read_bytes()
check("written with header, deduped, .pak stripped, CRLF",
      raw == b"; header one\r\n; header two\r\nModB\r\nModA\r\n", raw)
check("previous file backed up", (bpml / "load_order.txt.bak").is_file())

# ======================================================== modlists
print("\n== modlists ==")
paths, data = use(game)
doc = paltools.export_modlist(data)
out = SB / "list.json"
out.write_text(json.dumps(doc))
theirs = paltools.load_modlist(out)
theirs["mods"] = [m for m in theirs["mods"] if m["name"] != "Alpha"]      # they don't run Alpha
theirs["mods"].append({"name": "FriendOnly", "kind": "UE4SS mod", "enabled": True,
                       "url": "https://www.nexusmods.com/palworld/mods/1"})
theirs["mods"].append({"name": "OffMod", "kind": "UE4SS mod", "enabled": True})
cmp = paltools.compare_modlist(theirs, data)
check("missing mod reported with link", [m["name"] for m in cmp["missing"]] == ["FriendOnly"])
check("mod you have but is off", cmp["turn_on"] == ["OffMod"], cmp["turn_on"])
check("mod you run that they don't", "Alpha" in cmp["turn_off"], cmp["turn_off"])
try:
    bad = SB / "bad.json"
    bad.write_text('{"hello": 1}')
    paltools.load_modlist(bad)
    check("rejects non-modlist json", False)
except ValueError:
    check("rejects non-modlist json", True)
print(paltools.modlist_text(doc)[:200])

# ======================================================== log classification
print("\n== log lines ==")
C = paltools.classify_log_line
check("offset dump with 'Error' is noise", C("[t] FArchiveState::ArIsError = 0x29") == "other")
check("real failure is a problem", C("[t] [PS] Failed to find ConsoleManagerSingleton") == "problem")
check("mod start", C("[t] Starting Lua mod 'PalMiniMap'") == "start")
check("mod tagged line", C("[2026-09-10 22:02:03.1] [Lua] [BPModLoaderMod] Mods/x") == "mod")

check.finish()
