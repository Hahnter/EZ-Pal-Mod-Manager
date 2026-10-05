"""Telling mods apart: by install, and by kind when two mods share a name.

Receipts used to be keyed by name alone, across every install, so an uninstall
in the game also deleted the dedicated server's copy. And a hybrid mod's Lua
and PalSchema halves, which often share a folder name, were toggled, tracked
and listed as one.
"""
import contextlib
import io
import json
import sys
import zipfile

from helpers import (Checker, FakeMessageBox, hidden_tk, lua_mod, make_game,
                     picture, sandbox, silence_dialogs, use_game)

SB = sandbox("identity")
import palinstall, palmedia, palmods, palpaths, palregistry      # noqa: E402

check = Checker()
SPEED = "Pal/Binaries/Win64/ue4ss/Mods/SpeedMod"
MODS = "Pal/Binaries/Win64/ue4ss/Mods"


def install(archive, link=None, only=None):
    plan = palinstall.inspect(archive)
    try:
        chosen = [c for c in plan["components"]
                  if only is None or palinstall.component_id(c) in only]
        return palinstall.apply(plan, chosen, link=link)
    finally:
        palinstall.discard(plan)


def zip_of(out, files):
    with zipfile.ZipFile(out, "w") as z:
        for arc, text in files.items():
            z.writestr(arc, text)
    return out


def stored():
    return json.loads((palpaths.data_dir() / "receipts.json").read_text("utf8"))


def key(game):
    return palpaths.install_key(game)


# ==========================================================================
check.section("mod ids")
check("kind and name", palregistry.split_id("palschema:Hybrid") == ("palschema", "Hybrid"))
check("a plain name has no kind", palregistry.split_id("Hybrid") == (None, "Hybrid"))
check("a colon alone is not a kind", palregistry.split_id("C:\\x") == (None, "C:\\x"))
check("round trip", palregistry.split_id(palregistry.mod_id("pak", "Sky_P"))
      == ("pak", "Sky_P"))

# ==========================================================================
# Runs first: it needs a receipts.json that nothing else has written yet.
check.section("receipts written before they were kept per install")
mc, ms = make_game(SB / "mig/c"), make_game(SB / "mig/s", server=True)
for g in (mc, ms):
    lua_mod(g / MODS, "SpeedMod")
lua_mod(mc / MODS, "Hybrid")
(mc / MODS / "PalSchema/mods/Hybrid/raw").mkdir(parents=True)
(mc / MODS / "PalSchema/mods/Hybrid/raw/items.json").write_text("{}")
(mc / "Pal/Content/Paks/~mods/NiceSky_P.pak").write_bytes(b"x")


def p(game, rel):
    return str(game / rel)


c_speed = [p(mc, f"{SPEED}/Scripts/main.lua"), p(mc, f"{SPEED}/enabled.txt")]
s_speed = [p(ms, f"{SPEED}/Scripts/main.lua"), p(ms, f"{SPEED}/enabled.txt")]
lua_half = [p(mc, f"{MODS}/Hybrid/Scripts/main.lua"), p(mc, f"{MODS}/Hybrid/enabled.txt")]
schema_half = p(mc, f"{MODS}/PalSchema/mods/Hybrid/raw/items.json")
v1 = {
    # Installed in the game, then the server: the update loop carried the
    # game's paths into the server's receipt.
    "SpeedMod": {"when": "2026-09-30T10:00:00", "files": s_speed + c_speed,
                 "roots": [p(ms, SPEED)], "shipped": {s_speed[0]: "aa"}},
    # Both halves of a hybrid mod in one receipt, under the last half's root.
    "Hybrid": {"when": "2026-09-30T11:00:00", "files": [schema_half] + lua_half,
               "roots": [p(mc, f"{MODS}/PalSchema/mods/Hybrid")],
               "shipped": {schema_half: "bb"}},
    "NiceSky_P": {"when": "2026-09-30T12:00:00",
                  "files": [p(mc, "Pal/Content/Paks/~mods/NiceSky_P.pak")],
                  "roots": [p(mc, "Pal/Content/Paks/~mods")], "shipped": {}},
    "Nowhere": {"when": "2026-09-30T13:00:00", "files": ["notes/readme.txt"],
                "roots": [], "shipped": {}},
}
old_text = json.dumps(v1, indent=2) + "\n"
(palpaths.data_dir() / "receipts.json").write_text(old_text, "utf8")

use_game(mc)
palregistry.receipt("ue4ss", "SpeedMod")            # the first read migrates
data = stored()
game_r, server_r = data["installs"][key(mc)], data["installs"][key(ms)]
check("rewritten as version 2", data["version"] == 2, data.get("version"))
check("the original is kept beside it",
      (palpaths.data_dir() / "receipts-v1.json").read_text("utf8") == old_text)
check("the game gets back its own receipt",
      game_r["ue4ss:SpeedMod"]["files"] == c_speed, game_r["ue4ss:SpeedMod"])
check("with its mod folder as the root",
      game_r["ue4ss:SpeedMod"]["roots"] == [p(mc, SPEED)])
check("the server keeps only its own files",
      server_r["ue4ss:SpeedMod"]["files"] == s_speed, server_r["ue4ss:SpeedMod"])
check("and its own root and hashes",
      server_r["ue4ss:SpeedMod"]["roots"] == [p(ms, SPEED)]
      and server_r["ue4ss:SpeedMod"]["shipped"] == {s_speed[0]: "aa"})
check("a hybrid receipt is split into its two halves",
      game_r["ue4ss:Hybrid"]["files"] == lua_half
      and game_r["palschema:Hybrid"]["files"] == [schema_half], sorted(game_r))
check("each half has its own root",
      game_r["ue4ss:Hybrid"]["roots"] == [p(mc, f"{MODS}/Hybrid")]
      and game_r["palschema:Hybrid"]["roots"] == [p(mc, f"{MODS}/PalSchema/mods/Hybrid")])
check("a pak keeps its receipt", "pak:NiceSky_P" in game_r)
check("a path in no install is dropped",
      not any("Nowhere" in mid for r in data["installs"].values() for mid in r))
palregistry.receipt("ue4ss", "SpeedMod")
check("it only happens once", stored() == data)

palinstall.uninstall("SpeedMod")
check("uninstalling in the game leaves the server's copy",
      (ms / SPEED / "Scripts/main.lua").is_file() and (ms / SPEED / "enabled.txt").is_file())
check("the game's copy is gone", not (mc / SPEED).exists())
use_game(ms)
palinstall.uninstall("SpeedMod")
check("then the server's goes cleanly, folder and all", not (ms / SPEED).exists())
use_game(mc)
try:
    palinstall.uninstall("Hybrid")
    check("an uninstall that could mean either half is refused", False)
except palinstall.InstallError as exc:
    check("an uninstall that could mean either half is refused",
          "both a UE4SS mod and a PalSchema mod" in str(exc), str(exc))
palinstall.uninstall("Hybrid", kind="palschema")
check("the PalSchema half goes on its own",
      not (mc / MODS / "PalSchema/mods/Hybrid").exists()
      and (mc / MODS / "Hybrid/Scripts/main.lua").is_file())

# ==========================================================================
check.section("one mod in the game and in a dedicated server")
client, server = make_game(SB / "c"), make_game(SB / "s", server=True)
speed = zip_of(SB / "SpeedMod.zip", {"SpeedMod/Scripts/main.lua": "x"})
LINK = "https://www.nexusmods.com/palworld/mods/4242"
for g in (client, server):
    use_game(g)
    install(speed, link=LINK)
use_game(client)
install(speed, link=LINK)                  # an update, after the server install
data = stored()["installs"]
c_files = data[key(client)]["ue4ss:SpeedMod"]["files"]
s_files = data[key(server)]["ue4ss:SpeedMod"]["files"]
check("each install has its own receipt",
      all(palinstall.in_install(f, client) for f in c_files)
      and all(palinstall.in_install(f, server) for f in s_files), (c_files, s_files))
check("an update carries no other install's files forward", len(c_files) == 2, c_files)

removed, notes = palinstall.uninstall("SpeedMod")
check("uninstalling from the game removes the game's copy",
      not (client / SPEED).exists(), removed)
check("the server's copy is still there",
      (server / SPEED / "Scripts/main.lua").is_file()
      and (server / SPEED / "enabled.txt").is_file())
check("and so is its receipt", palregistry.receipt("ue4ss", "SpeedMod", server) is not None)
check("the shared page link stays while the server has the mod",
      palregistry.get("SpeedMod").get("url") == LINK, palregistry.get("SpeedMod"))
use_game(server)
removed, notes = palinstall.uninstall("SpeedMod")
check("the server's uninstall removes all of it", not (server / SPEED).exists()
      and len(removed) == 2 and notes == [], (removed, notes))
check("the link goes with the last copy", palregistry.get("SpeedMod") == {})

# ==========================================================================
check.section("nothing outside the install is touched")
use_game(client)
install(speed)
outside = server / SPEED / "Scripts/main.lua"
lua_mod(server / MODS, "SpeedMod")
# A receipt that names another install's file, whatever wrote it.
rec = palregistry.receipt("ue4ss", "SpeedMod", client)
palregistry.save_receipt("ue4ss", "SpeedMod", rec["files"] + [str(outside)],
                         roots=rec["roots"] + [str(server / SPEED)], game=client)
install(speed)
check("an update doesn't adopt it",
      str(outside) not in palregistry.receipt("ue4ss", "SpeedMod", client)["files"])
palregistry.save_receipt("ue4ss", "SpeedMod", rec["files"] + [str(outside)],
                         roots=rec["roots"] + [str(server / SPEED)], game=client)
removed, notes = palinstall.uninstall("SpeedMod")
check("uninstall doesn't delete it", outside.is_file() and outside not in removed)
check("nor its folder", (server / SPEED / "enabled.txt").is_file())
check("and says it skipped it",
      "skipped 1 file recorded outside this install" in notes, notes)
check("this install's copy still went", not (client / SPEED).exists())
check("a folder outside the install counts as outside",
      not palinstall.in_install(server / SPEED, client)
      and not palinstall.in_install(client, client)
      and palinstall.in_install(client / SPEED, client))

# ==========================================================================
check.section("one name, two kinds of mod")
game = use_game(make_game(SB / "h"))
mods = game / MODS
lua_mod(mods, "PalSchema")
lua_mod(mods, "Hybrid")
(mods / "PalSchema/mods/Hybrid").mkdir(parents=True)
lua_mod(mods, "Solo")
check("both kinds found", palmods.kinds_of("Hybrid") == ["ue4ss", "palschema"],
      palmods.kinds_of("Hybrid"))
msg = palmods.set_enabled("Hybrid", False)
check("a name two mods share is refused without a kind",
      msg.startswith("Nothing was changed") and "ue4ss:Hybrid" in msg
      and "palschema:Hybrid" in msg, msg)
check("and nothing moved", (mods / "Hybrid/enabled.txt").is_file()
      and (mods / "PalSchema/mods/Hybrid").is_dir())
palmods.set_enabled("Hybrid", False, kind="palschema")
check("the PalSchema half switches off",
      (mods / "PalSchema/disabled-mods/Hybrid").is_dir()
      and not (mods / "PalSchema/mods/Hybrid").exists())
check("the Lua half stays on", (mods / "Hybrid/enabled.txt").is_file())
palmods.set_enabled("Hybrid", False, kind="ue4ss")
check("the Lua half switches off on its own",
      (mods / "Hybrid/enabled.txt.disabled").is_file()
      and (mods / "PalSchema/disabled-mods/Hybrid").is_dir())
palmods.set_enabled("Hybrid", True, kind="ue4ss")
palmods.set_enabled("Hybrid", True, kind="palschema")
check("a name only one mod has needs no kind",
      "disabled" in palmods.set_enabled("Solo", False)
      and (mods / "Solo/enabled.txt.disabled").is_file())
palmods.set_enabled("Solo", True)
check("a kind that has no such mod says so",
      palmods.set_enabled("Solo", False, kind="pak") == "No pak named 'Solo' found.")
try:
    palmods.set_enabled("Solo", False, kind="lua")
    check("an unknown kind is an error", False)
except ValueError:
    check("an unknown kind is an error", True)
check("an empty name or a path is no mod at all",
      palmods.kinds_of("") == [] and palmods.kinds_of("..\\Hybrid") == []
      and palmods.set_enabled("", False) == "No mod named '' found."
      and (mods / "PalSchema/mods/Hybrid").is_dir())

# ==========================================================================
check.section("the command line asks for a kind only when it must")


def cli(*argv):
    out, saved = io.StringIO(), sys.argv
    sys.argv = ["palmods.py", *argv]
    try:
        with contextlib.redirect_stdout(out):
            palmods.main()
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = saved
    return code, out.getvalue()


code, out = cli("disable", "Hybrid")
check("a shared name is refused", code == 1, (code, out))
check("with the commands that pick one",
      "palmods.py disable ue4ss:Hybrid" in out
      and "palmods.py disable palschema:Hybrid" in out, out)
check("and nothing changed", (mods / "Hybrid/enabled.txt").is_file()
      and (mods / "PalSchema/mods/Hybrid").is_dir())
code, out = cli("disable", "palschema:Hybrid")
check("kind:name picks one", code == 0
      and (mods / "PalSchema/disabled-mods/Hybrid").is_dir()
      and (mods / "Hybrid/enabled.txt").is_file(), (code, out))
code, out = cli("enable", "palschema:Hybrid")
check("and turns it back on", code == 0 and (mods / "PalSchema/mods/Hybrid").is_dir())
code, out = cli("disable", "Solo")
check("a name only one mod has works as before",
      code == 0 and (mods / "Solo/enabled.txt.disabled").is_file(), (code, out))
cli("enable", "Solo")
code, out = cli("uninstall", "Hybrid", "-y")
check("uninstall asks for a kind too",
      code == 1 and "palmods.py uninstall palschema:Hybrid" in out
      and (mods / "Hybrid").is_dir(), (code, out))
code, out = cli("uninstall", "palschema:Hybrid", "-y")
check("and removes just the one named",
      code == 0 and not (mods / "PalSchema/mods/Hybrid").exists()
      and (mods / "Hybrid/Scripts/main.lua").is_file(), (code, out))
(mods / "PalSchema/mods/Hybrid").mkdir(parents=True)

# ==========================================================================
check.section("a hybrid archive installs as two mods")
twin = zip_of(SB / "Twin.zip", {
    f"{MODS}/Twin/Scripts/main.lua": "print(1)",
    f"{MODS}/PalSchema/mods/Twin/raw/items.json": "{}",
})
TWIN_LINK = "https://www.nexusmods.com/palworld/mods/777"
install(twin, link=TWIN_LINK)
code, out = cli("install", str(twin), "-y", "--link", TWIN_LINK)     # an update
check("the command line says which half overwrites what",
      code == 0 and "Twin (UE4SS mod) overwrites" in out
      and "Twin (PalSchema) overwrites" in out, out)
lua_rec = palregistry.receipt("ue4ss", "Twin")
schema_rec = palregistry.receipt("palschema", "Twin")
check("each half has its own receipt", lua_rec is not None and schema_rec is not None)
check("holding only its own files",
      all("PalSchema" not in f for f in lua_rec["files"])
      and all("PalSchema" in f for f in schema_rec["files"]),
      (lua_rec["files"], schema_rec["files"]))
palinstall.uninstall("Twin", kind="palschema")
check("removing the PalSchema half leaves the Lua half",
      not (mods / "PalSchema/mods/Twin").exists()
      and (mods / "Twin/Scripts/main.lua").is_file())
check("both halves share one page link, which stays",
      palregistry.get("Twin").get("url") == TWIN_LINK)
palinstall.uninstall("Twin")
check("the other half then goes too", not (mods / "Twin").exists())
check("and the link with it", palregistry.get("Twin") == {})

# ==========================================================================
check.section("the main window keeps the halves apart")
root, pump, errors = hidden_tk()
import palmods_gui as G                    # noqa: E402
silence_dialogs(G)
app = G.App(root)
pump(0.5)
check("one row each", {"ue4ss:Hybrid", "palschema:Hybrid"} <= set(app.rows),
      sorted(app.rows))
app.rows["palschema:Hybrid"]["toggle"]._click(None)
pump(0.1)
check("switching off the PalSchema row stages just that one",
      app._pending() == [("palschema:Hybrid", False)], app._pending())
app.render()
pump(0.1)
check("and survives a rebuild", app._pending() == [("palschema:Hybrid", False)])
app.apply()
pump(0.3)
check("applying moves only the PalSchema half",
      (mods / "PalSchema/disabled-mods/Hybrid").is_dir()
      and (mods / "Hybrid/enabled.txt").is_file())
check("both rows show what happened",
      app.rows["ue4ss:Hybrid"]["entry"]["on"]
      and not app.rows["palschema:Hybrid"]["entry"]["on"])

palregistry.save_profile("both on", ["ue4ss:Hybrid", "palschema:Hybrid"],
                         ["ue4ss:Hybrid", "palschema:Hybrid"])
app.load_profile("both on")
check("a profile stages each half on its own",
      app._pending() == [("palschema:Hybrid", True)], app._pending())
app.revert()

palmedia.add_image_file("Hybrid", picture(SB / "hybrid.png"))
app.reload()
pump(0.2)
FakeMessageBox.answers["askyesno"] = False          # look, don't uninstall
app.uninstall(app.rows["palschema:Hybrid"]["entry"])
asked, args = FakeMessageBox.calls[-1]
del FakeMessageBox.answers["askyesno"]
check("the uninstall question says which half",
      asked == "askyesno" and "Remove Hybrid (PalSchema mod)?" in args[1], args)
check("and doesn't promise to bin pictures the other half still shows",
      "Recycle Bin" not in args[1], args[1])

win = G.InstallWindow(app, twin)
pump(0.5)
check("the install window has a checkbox for each half",
      sorted(win.vars) == ["palschema:Twin", "ue4ss:Twin"], sorted(win.vars))
win.vars["ue4ss:Twin"][0].set(False)
win._install()
pump(0.5)
check("leaving one out installs only the other",
      (mods / "PalSchema/mods/Twin/raw/items.json").is_file()
      and not (mods / "Twin").exists())
check("and only that one gets a receipt",
      palregistry.receipt("palschema", "Twin") is not None
      and palregistry.receipt("ue4ss", "Twin") is None)
root.destroy()

check.finish(errors)
