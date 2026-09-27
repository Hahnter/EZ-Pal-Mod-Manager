"""The install window end to end: plan, install, config editor, uninstall."""
import zipfile
from pathlib import Path

from helpers import (Checker, FakeMessageBox, hidden_tk, make_game, sandbox,
                     silence_dialogs, use_game)

SB = sandbox("install_gui")
import palinstall, palregistry               # noqa: E402

check = Checker()
game = use_game(make_game(SB))

src = SB / "src"
(src / "Scripts").mkdir(parents=True)
(src / "Scripts/main.lua").write_text("print('x')")
(src / "config.ini").write_text("[Main]\nSpeed = 2\nDebug = false\n")
arc = SB / "SpeedTweak-5120-1-4-0-1770000000.zip"
with zipfile.ZipFile(arc, "w") as z:
    for p in sorted(src.rglob("*")):
        if p.is_file():
            z.write(p, f"SpeedTweak/{p.relative_to(src).as_posix()}")

root, pump, errors = hidden_tk()
import palmods_gui as G                       # noqa: E402
silence_dialogs(G)

app = G.App(root)
pump(0.4)
check("empty install shows no mods", app._entries_cache == [])

win = G.InstallWindow(app, arc)
pump(0.6)
check("plan shows one UE4SS mod",
      [(c["name"], c["kind"]) for c in win.plan["components"]]
      == [("SpeedTweak", palinstall.UE4SS_MOD)])
check("subtitle mentions the Nexus mod", "Nexus mod 5120" in win.sub.cget("text"),
      win.sub.cget("text"))

win._install()
pump(0.5)
check("success dialog shown", FakeMessageBox.calls and FakeMessageBox.calls[-1][0] == "showinfo")
names = [e["name"] for e in app._entries_cache]
check("list refreshed with the new mod", names == ["SpeedTweak"], names)
meta = palregistry.get("SpeedTweak")
check("source recorded", meta.get("source") == "Nexus" and meta.get("id") == 5120)
e = app._entries_cache[0]
check("config file found", [Path(c).name for c in e["configs"]] == ["config.ini"])
check("enabled on install",
      (game / "Pal/Binaries/Win64/ue4ss/Mods/SpeedTweak/enabled.txt").is_file())

cw = G.ConfigWindow(app, "SpeedTweak", e["configs"])
pump(0.2)
check("config editor opens", cw.winfo_exists())
cw.destroy()

removed, _ = palinstall.uninstall("SpeedTweak", mod_path=e["path"])
app.reload(full=True)
pump(0.2)
check("uninstall removes the folder",
      not (game / "Pal/Binaries/Win64/ue4ss/Mods/SpeedTweak").exists())
check("list is empty again", app._entries_cache == [])

root.destroy()
check.finish(errors)
