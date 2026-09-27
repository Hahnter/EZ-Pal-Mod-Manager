"""Linking downloaded zips to their Nexus / CurseForge pages. No network."""
import os
import subprocess
import sys
import zipfile

from helpers import (ROOT, Checker, FakeMessageBox, fake_pak, hidden_tk,
                     make_game, sandbox, silence_dialogs, use_game)

SB = sandbox("links")
import palinstall, palregistry            # noqa: E402

check = Checker()
game = use_game(make_game(SB))
dl = SB / "Downloads"
dl.mkdir()

CF = "https://www.curseforge.com/palworld/patch-pak-mods/instant-craft-and-more"
NX = "https://www.nexusmods.com/palworld/mods/3915"


def lua_zip(name, filename):
    out = dl / filename
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(f"{name}/Scripts/main.lua", "print(1)")
    return out


def install(archive, link=None):
    plan = palinstall.inspect(archive)
    try:
        return palinstall.apply(plan, link=link)
    finally:
        palinstall.discard(plan)


check.section("link fields")
check("no link -> nothing", palinstall.link_fields("  ") == {})
check("curseforge page", palinstall.link_fields(CF + "/files")
      == {"source": "CurseForge", "url": CF, "id": None})
check("nexus page", palinstall.link_fields(NX + "?tab=files")
      == {"source": "Nexus", "id": 3915, "url": NX})
check("other site", palinstall.link_fields("https://github.com/a/b")
      == {"source": "manual", "url": "https://github.com/a/b", "id": None})

check.section("CurseForge zip + pasted link")
pak_zip = dl / "InstantCraft-1.2.zip"
fake_pak(SB / "tmp/InstantCraft_P.pak", "../../../", ["Pal/Content/Pal/DT/DT_Craft.uasset"])
with zipfile.ZipFile(pak_zip, "w") as z:
    z.write(SB / "tmp/InstantCraft_P.pak", "InstantCraft_P.pak")
results = install(pak_zip, link=CF)
meta = palregistry.get("InstantCraft_P")
check("source + url from the link", meta.get("source") == "CurseForge" and meta.get("url") == CF, meta)
check("version still read from the file name", meta.get("version") == "1.2", meta.get("version"))
check("install summary mentions the link", results[-1] == "Linked to its CurseForge page", results[-1])

check.section("updating keeps the link")
pak_zip2 = dl / "InstantCraft-1.3.zip"
with zipfile.ZipFile(pak_zip2, "w") as z:
    z.write(SB / "tmp/InstantCraft_P.pak", "InstantCraft_P.pak")
install(pak_zip2)                                   # no link this time
meta = palregistry.get("InstantCraft_P")
check("source stays CurseForge after a linkless update", meta.get("source") == "CurseForge", meta)
check("url kept", meta.get("url") == CF)
check("version updated", meta.get("version") == "1.3")

check.section("Nexus zip")
install(lua_zip("PalMiniMap", "PalMiniMap-3915-2-3-8-1754251234.zip"))
meta = palregistry.get("PalMiniMap")
check("Nexus file name links itself", meta.get("source") == "Nexus" and meta.get("id") == 3915
      and meta.get("url") == NX, meta)

# A link beats the file name's guess, and clears a stale Nexus id.
install(lua_zip("Mirror", "Mirror-4444-1-0-0-1754251234.zip"), link=CF)
meta = palregistry.get("Mirror")
check("explicit CurseForge link overrides a Nexus-looking name",
      meta.get("source") == "CurseForge" and "id" not in meta and meta.get("url") == CF, meta)

check.section("hybrid archive: one link, every part")
hybrid = dl / "Harvest.zip"
fake_pak(SB / "tmp/HarvestBP_P.pak", "../../../", ["Pal/Content/Mods/Harvest/ModActor.uasset"])
with zipfile.ZipFile(hybrid, "w") as z:
    z.writestr("Harvest/Scripts/main.lua", "print(1)")
    z.write(SB / "tmp/HarvestBP_P.pak", "LogicMods/HarvestBP_P.pak")
install(hybrid, link="https://www.nexusmods.com/palworld/mods/5000")
check("both components linked",
      palregistry.get("Harvest").get("id") == 5000
      and palregistry.get("HarvestBP_P").get("id") == 5000)

check.section("command line")
cli_zip = lua_zip("CliLinked", "CliLinked.zip")
env = dict(os.environ, PALWORLD_PATH=str(game), PYTHONIOENCODING="utf-8")
res = subprocess.run([sys.executable, str(ROOT / "palmods.py"), "install", str(cli_zip),
                      "-y", "--link", CF], capture_output=True, text=True, env=env,
                     encoding="utf-8", timeout=120)
check("install --link succeeds", res.returncode == 0 and "Linked to its CurseForge page" in res.stdout,
      (res.stdout + res.stderr)[-300:])
check("link recorded by the CLI", palregistry.get("CliLinked").get("url") == CF)

check.section("install window")
root, pump, errors = hidden_tk()
import palmods_gui as G                      # noqa: E402
silence_dialogs(G)
clipboard = {"text": ""}
G.InstallWindow.clipboard_get = lambda self: clipboard["text"]   # never the real clipboard

app = G.App(root)
pump(0.4)

win = G.InstallWindow(app, pak_zip2)
pump(0.6)
check("update prefills the link from last time", win.link_var.get() == CF, win.link_var.get())
check("note explains where it came from", "kept from the last install" in win.link_note.cget("text"),
      win.link_note.cget("text"))
win._close(advance=False)

new_zip = lua_zip("FreshMod", "FreshMod.zip")
win = G.InstallWindow(app, new_zip)
pump(0.6)
check("new CurseForge-style zip starts empty", win.link_var.get() == "")
clipboard["text"] = "https://www.curseforge.com/palworld/blueprint-code-mods/fresh-mod"
win._link_changed()
check("clipboard link offered", "CurseForge link on your clipboard" in win.link_note.cget("text"),
      win.link_note.cget("text"))
win._paste_link()
check("Paste link fills it", win.link_var.get().endswith("/fresh-mod"))
win._install()
pump(0.5)
check("installed with the link",
      palregistry.get("FreshMod").get("url")
      == "https://www.curseforge.com/palworld/blueprint-code-mods/fresh-mod")

check.section("several downloads in a row")
FakeMessageBox.calls.clear()
q1, q2 = lua_zip("QueueA", "QueueA.zip"), lua_zip("QueueB", "QueueB.zip")
app.queue_installs([str(q1), str(q2)])
pump(0.6)
wins = [w for w in root.winfo_children() if isinstance(w, G.InstallWindow)]
check("first window open, one queued", len(wins) == 1 and len(app._install_queue) == 1
      and "1 more after this" in wins[0].title(), wins[0].title() if wins else "")
wins[0]._install()
pump(0.6)
wins = [w for w in root.winfo_children() if isinstance(w, G.InstallWindow)]
check("next window opens by itself", len(wins) == 1 and app._install_queue == [])
check("no dialog between queued installs",
      not any(k == "showinfo" for k, _ in FakeMessageBox.calls))
wins[0]._close()
pump(0.3)
check("closing the last one leaves nothing open",
      not any(isinstance(w, G.InstallWindow) for w in root.winfo_children()))
check("both queued mods handled", palregistry.get("QueueA").get("installed") is not None)

root.destroy()
check.finish(errors)
