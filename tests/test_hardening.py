"""Security hardening, and keeping the source free of hidden characters.

Everything here is something a hostile or broken file could otherwise do:
a mod archive that writes outside its folder or fills the disk, a link that
launches a program instead of a web page, a download that isn't what GitHub
published, a picture that carries GPS or AI-provenance tags into a shared
package, or source text carrying invisible watermark characters.
"""
import hashlib
import io
import subprocess
import zipfile

from helpers import ROOT, Checker, make_game, sandbox, use_game

SB = sandbox("hardening")
import palget, palinstall, palmedia, palregistry      # noqa: E402

check = Checker()
game = use_game(make_game(SB))


# ==========================================================================
check.section("no invisible characters in the source")
# The code points watermarking and "humanizer" tools hide in text: zero-width
# characters, bidi controls, tag characters, soft hyphens, blank-rendering
# fillers, odd spaces, and noncharacters.
HIDDEN = (set(range(0x200B, 0x2010)) | set(range(0x202A, 0x202F))
          | set(range(0x2060, 0x2070)) | set(range(0xE0000, 0xE0100))
          | set(range(0xFFF0, 0xFFF9)) | set(range(0xFDD0, 0xFDF0))
          | set(range(0x2000, 0x200B))
          | {0x00A0, 0x00AD, 0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180E,
             0x180F, 0x202F, 0x205F, 0x3000, 0x3164, 0xFEFF, 0xFFA0,
             0xFFFE, 0xFFFF})
tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True).stdout.split()
found = []
for rel in tracked:
    if rel.endswith((".png", ".ico", ".jpg", ".pak", ".zip")):
        continue
    try:
        text = (ROOT / rel).read_text("utf8")
    except (OSError, UnicodeDecodeError):
        continue
    for n, line in enumerate(text.splitlines(), 1):
        for c in line:
            if ord(c) in HIDDEN:
                found.append(f"{rel}:{n} U+{ord(c):04X}")
check(f"{len(tracked)} tracked files are clean", not found, found[:10])

# ==========================================================================
check.section("links only ever open web pages")
for url, ok in [("https://www.nexusmods.com/palworld/mods/3915", True),
                ("http://example.com/x", True),
                ("C:\\Windows\\System32\\calc.exe", False),
                ("file:///C:/Windows/System32/calc.exe", False),
                ("javascript:alert(1)", False),
                ("steam://run/1623730", False),
                ("ms-settings:privacy", False),
                ("https://", False),
                ("https://example.com/\nC:\\evil.exe", False),
                ("", False), (None, False)]:
    check(f"{url!r} -> {'opens' if ok else 'refused'}",
          bool(palregistry.web_link(url)) is ok)

# ==========================================================================
check.section("archives can't escape their folder")
check("a sibling folder with a longer name is not 'inside'",
      not palinstall.inside(SB / "Win64evil" / "x.dll", SB / "Win64"))
check("a real child is inside",
      palinstall.inside(SB / "Win64" / "ue4ss" / "x.dll", SB / "Win64"))
# Names aimed at the root of the drive or at C:\Windows are only ever checked
# as paths, never unpacked: with the guard broken, unpacking would write there.
for name in ("/abs/escaped.txt", "C:/Windows/escaped.txt"):
    check(f"{name} is not 'inside' the unpack folder",
          not palinstall.inside(SB / "unpack" / name, SB / "unpack"))

# Unpacked three folders deep in the sandbox, a member that climbs out still
# lands inside it, where the check below can find it. So even a broken guard
# writes nothing outside the temp folder. Never climb more than three levels.
evil = SB / "evil.zip"
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("GoodMod/Scripts/main.lua", "print(1)")
    z.writestr("../../escaped.txt", "gotcha")
into = SB / "unpack" / "a" / "b"
palinstall.unpack(evil, into)
unpacked = sorted(p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file())
check("the real mod was still unpacked",
      unpacked == ["GoodMod/Scripts/main.lua"], unpacked)
escaped = list(SB.rglob("escaped.txt"))
check("nothing climbed out of the unpack folder", not escaped, escaped)

# ==========================================================================
check.section("zip bombs are refused before they fill the disk")
bomb = SB / "bomb.zip"
with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("Bomb/Scripts/main.lua", "print(1)")
    z.writestr("Bomb/zeros.bin", b"\0" * (60 * 1024 * 1024))   # 60 MB of nothing
try:
    palinstall.inspect(bomb)
    check("a file that inflates 1000x is refused", False)
except palinstall.InstallError as exc:
    check("a file that inflates 1000x is refused", "zip bomb" in str(exc), str(exc))

old = palinstall.MAX_UNPACKED
palinstall.MAX_UNPACKED = 1024
big = SB / "big.zip"
with zipfile.ZipFile(big, "w", zipfile.ZIP_STORED) as z:
    z.writestr("Big/Scripts/main.lua", "x" * 2000)
try:
    palinstall.inspect(big)
    check("an archive over the size cap is refused", False)
except palinstall.InstallError as exc:
    check("an archive over the size cap is refused", "GB" in str(exc), str(exc))
palinstall.MAX_UNPACKED = old

# ==========================================================================
check.section("downloads only come from GitHub, and match its checksum")
for url, ok in [("https://api.github.com/repos/Okaetsu/RE-UE4SS/releases", True),
                ("https://github.com/Okaetsu/RE-UE4SS/releases/download/x/a.zip", True),
                ("https://objects.githubusercontent.com/abc", True),
                ("http://github.com/x.zip", False),
                ("https://github.com.evil.example/x.zip", False),
                ("https://evil.example/github.com/x.zip", False),
                ("file:///C:/x.zip", False)]:
    try:
        palget.check_url(url)
        got = True
    except palget.GetError:
        got = False
    check(f"{url} -> {'allowed' if ok else 'refused'}", got is ok)

payload = io.BytesIO()
with zipfile.ZipFile(payload, "w") as z:
    z.writestr("ue4ss/UE4SS.dll", "x")
data = payload.getvalue()


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


palget._open = lambda url: Resp(data)


def rel_with(digest, name="UE4SS-Palworld.zip", size=None):
    return {"asset": {"name": name, "size": len(data) if size is None else size,
                      "url": "https://github.com/x/a.zip", "digest": digest}}


good = "sha256:" + hashlib.sha256(data).hexdigest()
check("a download matching GitHub's checksum is kept",
      palget.download(rel_with(good), SB / "dl").is_file())
try:
    palget.download(rel_with("sha256:" + "0" * 64), SB / "dl2")
    check("a download with the wrong checksum is refused", False)
except palget.GetError as exc:
    check("a download with the wrong checksum is refused",
          "checksum" in str(exc) and not list((SB / "dl2").glob("*.zip")), str(exc))
try:
    palget.download(rel_with("", size=10), SB / "dl3")
    check("a download bigger than promised is stopped", False)
except palget.GetError as exc:
    check("a download bigger than promised is stopped", "bigger" in str(exc), str(exc))
try:
    palget.download(rel_with("", name="..\\..\\climbed.zip"), SB / "dl4")
    check("a file name can't climb out of the downloads folder",
          not (SB / "climbed.zip").exists()
          and (SB / "dl4" / "climbed.zip").is_file())
except palget.GetError as exc:
    check("a file name can't climb out of the downloads folder", False, str(exc))

# ==========================================================================
check.section("pictures lose their metadata")
from PIL import Image, PngImagePlugin              # noqa: E402

exif = Image.Exif()
exif[0x010F] = "SpyCam"
exif[0x0131] = "AI Generator 3000"
exif[0x8825] = {1: "N", 2: (35.0, 41.0, 22.0)}
src = SB / "tagged.jpg"
Image.new("RGB", (400, 300), (200, 50, 50)).save(
    src, "JPEG", exif=exif, comment=b"generated by AI",
    xmp=b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><c2pa>manifest</c2pa></x:xmpmeta>')
out = palmedia.add_image_file("Probe", src)
raw = out.read_bytes()
check("no EXIF (camera, GPS) in the stored copy", not dict(Image.open(out).getexif()))
check("no XMP or C2PA provenance",
      b"xmpmeta" not in raw and b"c2pa" not in raw)
check("no JPEG comment", b"generated by AI" not in raw)

meta = PngImagePlugin.PngInfo()
meta.add_text("parameters", "prompt: a cat, Steps: 30, Sampler: Euler")
meta.add_text("Software", "AI Generator 3000")
png = SB / "tagged.png"
Image.new("RGBA", (300, 300), (0, 0, 0, 128)).save(png, pnginfo=meta)
out = palmedia.add_image_file("Probe", png)
raw = out.read_bytes()
check("no generator prompt in PNG text", b"prompt" not in raw and b"Generator" not in raw)

bomb_png = SB / "huge.png"
Image.new("1", (12000, 12000)).save(bomb_png)        # 144 MP, tiny on disk
try:
    palmedia.add_image_file("Probe", bomb_png)
    check("a picture far bigger than any real one is refused", False)
except palmedia.MediaError as exc:
    check("a picture far bigger than any real one is refused",
          "bigger than any real" in str(exc), str(exc))

check.finish()
