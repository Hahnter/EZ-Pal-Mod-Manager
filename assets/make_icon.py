#!/usr/bin/env python3
"""Generate the EZ Pal Mod Manager icon (.ico and .png).

The mark is an amber tile holding a switch, drawn by palicons.logo so the
window icon and the mark in the app's header are the same drawing. It replaced
an earlier capture-sphere design that looked too much like a Poké Ball.

    python assets/make_icon.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import palicons   # noqa: E402

OUT = HERE / "palmodmanager.ico"


def main():
    sizes = [256, 128, 64, 48, 32, 24, 16]
    imgs = [palicons.logo(n) for n in sizes]
    imgs[0].save(OUT, format="ICO", sizes=[(n, n) for n in sizes],
                 append_images=imgs[1:])
    imgs[0].save(HERE / "palmodmanager.png")
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
    print(f"wrote {HERE / 'palmodmanager.png'}")


if __name__ == "__main__":
    main()
