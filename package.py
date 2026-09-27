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

    python package.py
"""

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


if __name__ == "__main__":
    main()
