#!/usr/bin/env python3
"""Build the distributable archive for EZ Pal Mod Manager.

Produces dist/PalModManager-<version>.zip laid out so that extracting it into
the Palworld folder drops the mod in the right place -- the same convention
Pal Insight and PalMiniMap use.

    PalModManager-0.1.0.zip
      README.md
      CHANGELOG.md
      Pal/Binaries/Win64/ue4ss/Mods/PalModManager/
        enabled.txt
        Scripts/main.lua

    python package.py             the zip
    python package.py --release   the zip, which must hold the exe, plus
                                  dist/release-notes.md and dist/version.txt
                                  for the GitHub release
"""

import hashlib
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE / "ingame" / "PalModManager"
GAME_PREFIX = "Pal/Binaries/Win64/ue4ss/Mods/PalModManager"
# Machine-specific or generated; must never ship.
EXCLUDE = {"modlist.txt", "manifest.json"}


def version():
    m = re.search(r'local VERSION\s*=\s*"([^"]+)"',
                  (MOD / "Scripts" / "main.lua").read_text("utf8"))
    if not m:
        sys.exit("could not read VERSION from Scripts/main.lua")
    return m.group(1)


def main():
    if not (MOD / "Scripts" / "main.lua").is_file():
        sys.exit(f"mod source not found at {MOD}")
    ver = version()
    dist = HERE / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"EZPalModManager-{ver}.zip"

    # enabled.txt must be present so the mod is live on a fresh install.
    (MOD / "enabled.txt").touch()

    exe = HERE / "dist" / "app" / "EZPalModManager.exe"
    written = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if exe.is_file():
            z.write(exe, exe.name)
            written.append(exe.name)
        for doc in ("README.md", "CHANGELOG.md"):
            p = MOD / doc
            if p.is_file():
                z.write(p, doc)
                written.append(doc)
        # Licence lives at the project root, not with the in-game mod.
        lic = HERE / "LICENSE"
        if lic.is_file():
            z.write(lic, "LICENSE")
            written.append("LICENSE")
        for p in sorted(MOD.rglob("*")):
            if not p.is_file() or p.name in EXCLUDE:
                continue
            if p.name in ("README.md", "CHANGELOG.md"):
                continue          # already at archive root
            arc = f"{GAME_PREFIX}/{p.relative_to(MOD).as_posix()}"
            z.write(p, arc)
            written.append(arc)

    print(f"built {out}  ({out.stat().st_size:,} bytes)")
    for w in written:
        print("  ", w)
    if "--release" in sys.argv:
        if exe.name not in written:
            sys.exit(f"{exe} isn't built, so the zip has no app in it. "
                     f"Run PyInstaller first.")
        notes = dist / "release-notes.md"
        notes.write_text(release_notes(ver, exe, out), "utf8")
        (dist / "version.txt").write_text(ver, "utf8")
        print(f"wrote {notes}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def changelog(ver):
    """This version's part of the changelog, without its heading."""
    text = (MOD / "CHANGELOG.md").read_text("utf8")
    m = re.search(rf"^## {re.escape(ver)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md has no section for {ver}")
    return m.group(1).strip()


def release_notes(ver, exe, zip_path):
    """The release page: what each download is, what changed, and the hashes
    people check their download against."""
    width = max(len(exe.name), len(zip_path.name)) + 1
    return "\n".join([
        f"**{exe.name}**: the app on its own. Put it anywhere and run it.",
        f"**{zip_path.name}**: the app plus the optional in-game panel (F8). "
        f"Extract into your Palworld folder.",
        "",
        changelog(ver),
        "",
        "**SHA-256**",
        "```",
        f"{exe.name:<{width}}{sha256(exe)}",
        f"{zip_path.name:<{width}}{sha256(zip_path)}",
        "```",
        "",
    ])


if __name__ == "__main__":
    main()
