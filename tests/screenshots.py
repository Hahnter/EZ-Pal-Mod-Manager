#!/usr/bin/env python3
"""Take the README screenshots against a made-up install.

    python tests/screenshots.py            writes docs/screenshots/*.png

Not a test (run_all.py only runs test_*.py). It uses the same sandbox as the
tests -- a throwaway Palworld install in the temp folder, network blocked --
so the pictures never show anyone's real mods or saves, and taking them
never touches a real install.

Windows draws the windows it captures, so it has to be run on a desktop where
the app's windows can appear (or under Xvfb on Linux).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import (fake_pak, lua_mod, make_game, sandbox, use_game,   # noqa: E402
                     write_log)

SB = sandbox("screenshots")
import palinfo, palmedia, palregistry, palsafety   # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# a believable install
# --------------------------------------------------------------------------
game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"
mods = win64 / "ue4ss/Mods"
paks = game / "Pal/Content/Paks"

LUA = {
    "BetterStorage": dict(version="1.4.2", id=6121, released="2026-07-02",
                          config={"config.json": json.dumps({"StackSize": 9999})}),
    "PalStatsOverlay": dict(version="2.1.0", id=5874, released="2026-05-14"),
    "FastTravelAnywhere": dict(version="3.0.1", id=4410, released="2026-08-20"),
    "NoDurabilityLoss": dict(version="1.1.0", id=3977, released="2026-06-11",
                             enabled=False),
    "BaseCampTweaks": dict(version="0.9.3", id=6340, released="2026-08-30"),
    "MyFirstMod": dict(local=True),
}
for name, m in LUA.items():
    main = ('RegisterKeyBind(Key.F6, function() end)' if name == "PalStatsOverlay"
            else "print('loaded')")
    lua_mod(mods, name, main=main, enabled=m.get("enabled", True),
            extra=m.get("config"))
    if m.get("local"):
        palregistry.set_entry(name, source="local")
    else:
        palregistry.set_entry(name, source="Nexus", id=m["id"],
                              version=m["version"], released=m["released"])

fake_pak(paks / "~mods/HDPalTextures_P.pak", "../../../Pal/Content/",
         ["Pal/Content/Pal/Texture/Pal/T_Lamball_D.uasset"])
fake_pak(paks / "~mods/BrighterNights_P.pak", "../../../Pal/Content/",
         ["Pal/Content/Pal/Environment/Sky/DA_SkySettings.uasset"])
fake_pak(paks / "LogicMods/AutoSortChests_P.pak", "../../../Pal/Content/",
         ["Pal/Content/Mods/AutoSortChests/ModActor.uasset"])
palregistry.set_entry("HDPalTextures_P", source="Nexus", id=2987, version="2.0",
                      released="2026-04-02")
palregistry.set_entry("AutoSortChests_P", source="CurseForge",
                      url="https://www.curseforge.com/palworld/mods/auto-sort-chests")

# BaseCampTweaks didn't start last session: the row says so.
write_log(win64, ["BetterStorage", "PalStatsOverlay", "FastTravelAnywhere",
                  "MyFirstMod", "BPModLoaderMod"])
(paks / "LogicMods").mkdir(exist_ok=True)


def cover(name, a, b, shape):
    """Placeholder artwork: a gradient with a simple mark, clearly not a real mod's."""
    from PIL import Image, ImageDraw
    w, h = 960, 540
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w * 0.6 + y / h * 0.4)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2
    light = (255, 255, 255)
    if shape == "circle":
        d.ellipse((cx - 150, cy - 150, cx + 150, cy + 150), outline=light, width=18)
    elif shape == "grid":
        for i in range(3):
            for j in range(3):
                d.rectangle((cx - 165 + i * 115, cy - 165 + j * 115,
                             cx - 75 + i * 115, cy - 75 + j * 115), outline=light, width=10)
    elif shape == "bolt":
        d.polygon([(cx + 40, cy - 190), (cx - 90, cy + 20), (cx - 5, cy + 20),
                   (cx - 45, cy + 190), (cx + 95, cy - 30), (cx + 5, cy - 30)],
                  fill=light)
    else:
        d.polygon([(cx, cy - 170), (cx + 180, cy + 140), (cx - 180, cy + 140)],
                  outline=light, width=18)
    path = SB / f"{name}.png"
    img.save(path)
    palmedia.add_image_file(name, path)


cover("BetterStorage", (46, 84, 140), (22, 34, 60), "grid")
cover("PalStatsOverlay", (120, 60, 150), (40, 24, 70), "circle")
cover("FastTravelAnywhere", (200, 120, 40), (80, 36, 20), "bolt")
cover("HDPalTextures_P", (40, 130, 110), (16, 50, 50), "triangle")
palmedia.set_description(
    "BetterStorage",
    "Raises the stack limit in every chest and the Palbox, and adds a sort "
    "button to storage screens.\n\nSettings are in config.json:\n"
    "• StackSize: the most of one item a slot holds (default 9999)\n"
    "• SortOnOpen: sort a chest every time it's opened\n\n"
    "Works with the current game build. Needs UE4SS.")

# --------------------------------------------------------------------------
# the app
# --------------------------------------------------------------------------
import tkinter as tk                                           # noqa: E402
from PIL import ImageGrab                                      # noqa: E402

palsafety.game_running = lambda g: False
import palmods                                                 # noqa: E402
# A developer's reference/dwmapi.dll beside the source would flag the
# sandbox's fake UE4SS as the wrong build.
palmods.doctor = lambda fix=False: ([], [])
import palmods_gui as G                                        # noqa: E402

# Tk reports positions in real pixels only once the process is DPI aware,
# which is what ImageGrab captures in. Pin the scale to 100% so the
# pictures come out the same size on any display.
G._dpi_aware()
root = tk.Tk()
root.tk.call("tk", "scaling", 96 / 72)
# X11 draws a focus ring around text fields that Windows doesn't.
root.option_add("*Entry.highlightThickness", 0)
root.option_add("*Text.highlightThickness", 0)
app = G.App(root)


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def shot(widget, name):
    # ImageGrab copies the screen, so anything covering the window would be
    # captured instead of it.
    widget.attributes("-topmost", True)
    widget.lift()
    widget.update_idletasks()
    # Park the pointer in the footer, so no row is drawn hovered.
    widget.event_generate("<Motion>", warp=True, x=widget.winfo_width() - 4,
                          y=widget.winfo_height() - 4)
    pump(0.4)
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h),
                         **({} if sys.platform == "win32" else {"xdisplay": None}))
    img.save(OUT / f"{name}.png", optimize=True)
    print("wrote", OUT / f"{name}.png", img.size)


pump(2.5)
shot(root, "main")

info = palinfo.ModInfoWindow(app, app.rows["BetterStorage"]["entry"])
info.geometry("840x860+0+0")
shot(info, "mod-info")
info.destroy()

src = SB / "src"
lua_mod(src, "PalHarvest")
fake_pak(src / "PalHarvestIcons_P.pak", "../../../Pal/Content/",
         ["Pal/Content/Pal/Texture/UI/T_Icon_Harvest.uasset"])
import zipfile                                                 # noqa: E402
archive = SB / "PalHarvest-5233-2-1-0-1754251234.zip"
with zipfile.ZipFile(archive, "w") as z:
    for p in src.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(src).as_posix())
app.queue_installs([str(archive)])
pump(1.2)
inst = next(w for w in root.winfo_children() if isinstance(w, G.InstallWindow))
inst.geometry("760x600+0+0")
shot(inst, "install")
inst._close(advance=False)

root.destroy()
