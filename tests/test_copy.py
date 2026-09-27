"""House style for text the app shows: no '(s)' plurals, no stray emoji.

Scans string literals in the app's modules rather than rendered windows, so
a regression shows up even in a window no other test opens.
"""
import ast
import re

from helpers import ROOT, Checker

check = Checker()

UI_MODULES = ["palmods_gui.py", "palwindows.py", "palinfo.py", "palui.py",
              "palinstall.py"]
PLURAL_HACK = re.compile(r"\w\(s\)")
# The old glyph icons; the app now draws its own (palicons).
GLYPHS = ["🔍", "▶", "＋", "●", "✕", "↗"]


def literals(path):
    tree = ast.parse((ROOT / path).read_text("utf8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            yield node.lineno, node.value


for mod in UI_MODULES:
    hacks = [(ln, v) for ln, v in literals(mod) if PLURAL_HACK.search(v)]
    check(f"{mod}: no '(s)' plurals", not hacks, hacks[:3])
    glyphs = [(ln, v) for ln, v in literals(mod) if any(g in v for g in GLYPHS)]
    check(f"{mod}: no glyph icons in text", not glyphs, glyphs[:3])

import sys                    # noqa: E402
sys.path.insert(0, str(ROOT))  # no sandbox needed: this reads source files only
from paltext import plural   # noqa: E402
check("plural()", plural(1, "mod") == "1 mod" and plural(3, "mod") == "3 mods"
      and plural(2, "change") == "2 changes")

check.finish()
