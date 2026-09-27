"""Mod descriptions and pictures: links, image store, clipboard, suggestions,
archive capture, packaging and uninstall. Uses no network."""
import os
import shutil
import zipfile
from pathlib import Path

from helpers import Checker, make_game, sandbox, use_game

SB = sandbox("media")
from PIL import Image                                         # noqa: E402
import palinstall, palmedia, palmods, palpaths, palregistry  # noqa: E402

check = Checker()


game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"


def picture(path, size=(2400, 1200), mode="RGB", fmt=None, colour=(40, 120, 200, 255)):
    img = Image.new(mode, size, colour[:len(mode)] if mode != "P" else 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, fmt)
    return path


# ======================================================== links (offline)
print("\n== link parsing ==")
L = palmedia.parse_link
check("nexus link -> source + id + canonical url",
      L("https://www.nexusmods.com/palworld/mods/3915?tab=files") ==
      {"source": "Nexus", "id": 3915, "url": "https://www.nexusmods.com/palworld/mods/3915"})
check("nexus link without scheme", L("nexusmods.com/palworld/mods/304").get("id") == 304)
check("curseforge mod page", L("https://www.curseforge.com/palworld/patch-pak-mods/instant-craft-and-more/files")
      == {"source": "CurseForge", "url": "https://www.curseforge.com/palworld/patch-pak-mods/instant-craft-and-more"})
check("curseforge search is not a mod page", L("https://www.curseforge.com/palworld/search?search=x")["url"].endswith("x"))
check("other link kept as manual", L("https://github.com/me/mod") == {"source": "manual", "url": "https://github.com/me/mod"})
check("local path kept", L(r"D:\Projects\MyMod") == {"url": r"D:\Projects\MyMod"})

# ======================================================== description + images
print("\n== store ==")
palmedia.set_description("Alpha", "  Line one\r\nLine two  ")
check("description saved + normalised", palmedia.info("Alpha")["description"] == "Line one\nLine two")
big = picture(SB / "in/big.webp", (2400, 1200), fmt="WEBP")
stored = palmedia.add_image_file("Alpha", big)
with Image.open(stored) as im:
    check("webp stored as jpg, capped at 1920", stored.suffix == ".jpg" and max(im.size) == 1920, im.size)
check("first image becomes cover", palmedia.info("Alpha")["cover"] == stored)
again = palmedia.add_image_file("Alpha", big)
check("same picture twice is stored once", again == stored and len(palmedia.info("Alpha")["images"]) == 1)
alpha = picture(SB / "in/icon.png", (300, 300), mode="RGBA", colour=(255, 0, 0, 128))
stored2 = palmedia.add_image_file("Alpha", alpha)
check("transparent image stays png", stored2.suffix == ".png")
palmedia.set_cover("Alpha", stored2.name)
check("set cover", palmedia.info("Alpha")["cover"] == stored2)
t1 = palmedia.thumbnail(stored2, 64, 36)
with Image.open(t1) as im:
    check("row thumbnail is exactly 64x36", im.size == (64, 36))
t2 = palmedia.thumbnail(stored, 760, 380, fit="contain")
with Image.open(t2) as im:
    check("contain-fit keeps aspect inside box", im.size == (760, 380) or (im.size[0] <= 760 and im.size[1] <= 380), im.size)
check("thumbnail cached", palmedia.thumbnail(stored2, 64, 36) == t1)
palmedia.remove_image("Alpha", stored2.name)
info = palmedia.info("Alpha")
check("removing cover falls back to remaining image", info["cover"] == stored and not stored2.exists())
bad = SB / "in/notimage.png"
bad.write_text("nope")
try:
    palmedia.add_image_file("Alpha", bad)
    check("non-image rejected", False)
except palmedia.MediaError:
    check("non-image rejected", True)

# ======================================================== clipboard (mocked; never touches yours)
print("\n== clipboard ==")
clip = {"value": Image.new("RGB", (640, 360), (10, 200, 90))}
palmedia.ImageGrab.grabclipboard = lambda: clip["value"]
kind, _ = palmedia.clipboard_image()
check("clipboard picture detected", kind == "image")
pasted = palmedia.paste_images("Beta")
check("pasted picture stored", len(pasted) == 1 and pasted[0].is_file())
clip["value"] = [str(big), str(SB / "in/readme.txt")]
kind, files = palmedia.clipboard_image()
check("files copied in Explorer: only images taken", kind == "files" and files == [str(big)])
clip["value"] = None
try:
    palmedia.paste_images("Beta")
    check("empty clipboard explains how to copy an image", False)
except palmedia.MediaError as exc:
    check("empty clipboard explains how to copy an image", "Copy image" in str(exc))
def boom():
    raise OSError("clipboard busy")
palmedia.ImageGrab.grabclipboard = boom
check("busy clipboard doesn't crash", palmedia.clipboard_image() == (None, None))

# ======================================================== own-mod suggestions
print("\n== suggestions from a mod folder ==")
mod = win64 / "ue4ss/Mods/MyMod"
(mod / "Scripts").mkdir(parents=True)
(mod / "Scripts/main.lua").write_text("print(1)")
(mod / "Scripts/readme.txt").write_text("should be ignored: inside Scripts")
(mod / "README.md").write_text("# MyMod\n\nOpens every door.")
picture(mod / "preview.png", (800, 450))
picture(mod / "icons/T_Icon_001.png", (64, 64))
sug = palmedia.suggestions("MyMod", mod)
check("README.md suggested", sug["readme"] and "Opens every door" in sug["readme"])
check("preview image suggested, UI icons not", [p.name for p in sug["images"]] == ["preview.png"], sug["images"])
palmedia.set_description("MyMod", "Opens every door in your base. Press F6.")
check("no README suggestion once a description exists", palmedia.suggestions("MyMod", mod)["readme"] is None)

# ======================================================== install from a download
print("\n== install keeps README + pictures ==")
src = SB / "dl"
(src / "CoolMod/Scripts").mkdir(parents=True)
(src / "CoolMod/Scripts/main.lua").write_text("print(1)")
(src / "README.txt").write_bytes("Cool Mod\r\nMakes pals faster.\r\n".encode("utf-16"))
picture(src / "screenshots/shot1.jpg", (1280, 720), fmt="JPEG")
picture(src / "screenshots/shot2.png", (1280, 720))
arc = SB / "CoolMod-5555-1-0-0-1780000000.zip"
with zipfile.ZipFile(arc, "w") as z:
    for p in src.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(src).as_posix())
plan = palinstall.inspect(arc)
extras = palmedia.archive_extras(plan["skipped"])
check("plan reports README and 2 pictures as extras",
      extras["readmes"] == ["README.txt"] and len(extras["images"]) == 2, extras)
results = palinstall.apply(plan)
palinstall.discard(plan)
print("   ", results[-1])
ci = palmedia.info("CoolMod")
check("UTF-16 README became the description", ci["description"].startswith("Cool Mod\nMakes pals faster"), repr(ci["description"][:40]))
check("both screenshots stored, first is cover", len(ci["images"]) == 2 and ci["cover"] == ci["images"][0])
check("source still recorded from the Nexus filename", palregistry.get("CoolMod").get("id") == 5555)

# Installing again doesn't overwrite a description you edited.
palmedia.set_description("CoolMod", "My own words.")
plan = palinstall.inspect(arc); palinstall.apply(plan); palinstall.discard(plan)
check("reinstall keeps your edited description", palmedia.info("CoolMod")["description"] == "My own words.")

# ======================================================== packaging your own mod
print("\n== package includes description + pictures ==")
palmedia.add_image_file("MyMod", mod / "preview.png")
palmedia.add_image_file("MyMod", picture(SB / "in/shot.png", (1000, 600), colour=(200, 50, 50, 255)))
palregistry.set_entry("MyMod", source="local", version="1.2.0")
out = palinstall.package(mod, out_dir=SB / "out")
with zipfile.ZipFile(out) as z:
    names = z.namelist()
    desc_name = next(n for n in names if n.endswith("DESCRIPTION.md"))
    desc = z.read(desc_name).decode()
check("existing README kept, description added as DESCRIPTION.md",
      any(n.endswith("MyMod/README.md") for n in names) and "Press F6" in desc)
imgs = sorted(n.split("/")[-1] for n in names if "/images/" in n)
check("folder's own preview.png packed once; added screenshot packed",
      imgs == ["screenshot-2.jpg"] and any(n.endswith("MyMod/preview.png") for n in names), imgs)

# A cover that did NOT come from the folder is packed as images/preview.
palregistry.set_entry("MyMod", cover=palmedia.info("MyMod")["images"][1].name)
out2 = palinstall.package(mod, out_dir=SB / "out2")
with zipfile.ZipFile(out2) as z:
    imgs2 = sorted(n.split("/")[-1] for n in z.namelist() if "/images/" in n)
check("pasted cover packed as images/preview", imgs2 == ["preview.jpg"], imgs2)

# ...and those pictures round-trip into another install as mod info.
palmedia.forget("MyMod"); palregistry.forget("MyMod")
shutil.rmtree(mod)
plan = palinstall.inspect(out)
palinstall.apply(plan); palinstall.discard(plan)
sug = palmedia.suggestions("MyMod", win64 / "ue4ss/Mods/MyMod")
check("installed package offers its preview pictures", len(sug["images"]) == 2, [p.name for p in sug["images"]])
check("installed package uses the description you wrote, not the stock README",
      "Press F6" in palmedia.info("MyMod")["description"], palmedia.info("MyMod")["description"][:40])

# ======================================================== uninstall
print("\n== uninstall ==")
d = palmedia.media_dir("CoolMod")
check("media folder exists before uninstall", d.is_dir())
palinstall.uninstall("CoolMod")
check("uninstall removes the mod's pictures", not d.exists())
check("and its registry entry", palregistry.get("CoolMod") == {})

check.finish()
