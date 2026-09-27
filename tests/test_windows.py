"""Secondary windows, warning banners and the play-session watcher."""
import time

from helpers import (Checker, fake_pak, hidden_tk, lua_mod, make_game, sandbox,
                     silence_dialogs, steam_library, use_game, write_log)

SB = sandbox("windows")
import palmods, palsafety, paltools          # noqa: E402

check = Checker()
now = int(time.time())
common = steam_library(SB / "lib", "Palworld", "1623730", "1000", now - 86400)
game = use_game(make_game(common))
win64 = game / "Pal/Binaries/Win64"
mods = win64 / "ue4ss/Mods"
paks = game / "Pal/Content/Paks"

lua_mod(mods, "BaseDoorControl",
        extra={"Scripts/config.lua": 'return { ToggleKey = "F6", OpenKey = "F7" }'})
lua_mod(mods, "PalInsightSettings",
        extra={"config.lua": 'return { settingsKey = "F6", potentialVisionKey = "F7" }'})
lua_mod(mods, "FastTravel")
hair = ["Pal/Content/Pal/Model/Hair/SK_Hair001.uasset",
        "Pal/Content/Pal/Model/Hair/SK_Hair001.uexp"]
fake_pak(paks / "~mods/Misty_P.pak", "../../../", hair)
fake_pak(paks / "~mods/zzOutfit_P.pak", "../../../", hair)
fake_pak(paks / "LogicMods/SimpleDPS.pak", "../../../Pal/Content/Mods/SimpleDPS/",
         ["ModActor.uasset"])
(paks / "LogicMods/Ghost.modconfig.json").write_text("{}")
(SB / "localappdata/Pal/Saved/SaveGames/1/WORLD").mkdir(parents=True)
(SB / "localappdata/Pal/Saved/SaveGames/1/WORLD/Level.sav").write_bytes(b"x" * 1000)

# Mods ran on build 1000; then Steam patches to 2000.
write_log(win64, ["BaseDoorControl", "PalInsightSettings", "FastTravel"], when_offset=-3600)
palmods.build(palmods.discover())
steam_library(SB / "lib", "Palworld", "1623730", "2000", now - 60)

root, pump, errors = hidden_tk()
import palmods_gui as G                        # noqa: E402
import palwindows as W                         # noqa: E402
silence_dialogs(G, W)

app = G.App(root)
pump(0.6)

check.section("banners")
banners = [w.winfo_children()[-1].cget("text") for w in app.warnbox.winfo_children()]
check("game update banner", any("Palworld updated to build 2000" in b for b in banners), banners)
check("conflict + hotkey banner",
      any("replace the same game files" in b and "F6" in b for b in banners), banners)
states = {e["name"]: e["state"] for e in app._entries_cache}
check("mods show 'worked before update'", states["FastTravel"] == "worked before update", states)
notes = {e["name"]: e["note"] for e in app._entries_cache}
check("hotkey note on both mods", "F6, F7 also bound by PalInsightSettings" in notes["BaseDoorControl"],
      notes["BaseDoorControl"])
check("conflict loser noted", "zzOutfit_P overrides" in notes["Misty_P"], notes["Misty_P"])

check.section("windows")
cw = W.ConflictsWindow(app); pump(0.3)
check("conflicts window", cw.winfo_exists()); cw.destroy()

lo = W.LoadOrderWindow(app); pump(0.2)
check("load order lists LogicMods paks", lo.installed == ["SimpleDPS"], lo.installed)
check("no BPModLoaderMod -> save disabled", not lo.can_save)
lo.destroy()

bw = W.BackupsWindow(app); pump(0.2)
bw._backup(); pump(0.2)
check("backup from window", len(palsafety.list_backups(game)) == 1)
bw.destroy()

cl = W.CleanupWindow(app); pump(0.3)
check("cleanup finds the orphaned config",
      [i["kind"] for i in cl.items] == ["orphaned config"], [i["kind"] for i in cl.items])
cl._clean(); pump(0.3)
check("cleanup removes it", not (paks / "LogicMods/Ghost.modconfig.json").exists())
cl.destroy()

lw = W.LogWindow(app); pump(0.3)
check("log window reads the log", "lines" in lw.status.cget("text"), lw.status.cget("text"))
lw._mode("Problems"); pump(0.1)
lw.destroy()

doc = paltools.export_modlist(app._data)
doc["mods"].append({"name": "FriendMod", "kind": "UE4SS mod", "enabled": True})
cmp = W.CompareWindow(app, doc, "friend.json"); pump(0.2)
check("compare window lists the missing mod",
      [m["name"] for m in cmp.result["missing"]] == ["FriendMod"])
cmp.destroy()

check.section("play session")
app._launched_by_us = True
app._events.put(("started", time.time() - 600))
pump(1.0)
check("button shows running", "Running" in app.play_btn.cget("text"))
# The session ran on the new build and FastTravel didn't start.
write_log(win64, ["BaseDoorControl", "PalInsightSettings"])
app._events.put(("stopped", time.time()))
pump(2.5)
sessions = [w for w in root.winfo_children() if isinstance(w, W.SessionWindow)]
check("session summary opened", len(sessions) == 1)
# FastTravel didn't start, and SimpleDPS (on, in LogicMods) never announced itself.
check("summary counts both mods that didn't load",
      sessions and "2 mods didn't load" in sessions[0].subtitle.cget("text"),
      sessions[0].subtitle.cget("text") if sessions else "")
check("play button restored", "Play" in app.play_btn.cget("text")
      and str(app.play_btn.cget("state")) == "normal")
check("regression reported after playing",
      "FastTravel" in app._data["patch"]["regressed"], app._data["patch"])

root.destroy()
check.finish(errors)
