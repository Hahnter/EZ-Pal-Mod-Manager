#!/usr/bin/env python3
"""Housekeeping: leftovers, BP load order, shareable modlists, the UE4SS log.

  leftovers   files that belong to no installed mod -- orphaned configs,
              parked UE4SS copies, empty mod folders. Removed to the Recycle
              Bin, never deleted outright.
  load order  BPModLoaderMod's load_order.txt, which decides which blueprint
              mods start first.
  modlists    an export of what you run, so friends joining a multiplayer
              world can match it, and a comparison against theirs.
  log         classification for the live UE4SS.log viewer.
"""

import ctypes
import json
import re
from datetime import datetime
from pathlib import Path

import palregistry


# ==========================================================================
# recycle bin
# ==========================================================================
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", ctypes.c_int),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_void_p)]


def recycle(paths):
    """Send files or folders to the Recycle Bin. Returns True on success.

    Uses the shell's own delete with undo allowed, so anything removed here
    can be restored from the Recycle Bin like a normal Explorer delete.
    """
    items = [str(Path(p).resolve()) for p in paths if Path(p).exists()]
    if not items:
        return True
    # pFrom is a list of NUL-terminated paths ending in an extra NUL.
    joined = "\0".join(items) + "\0\0"
    buf = ctypes.create_unicode_buffer(joined, len(joined))
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION = 3, 0x4, 0x10
    FOF_ALLOWUNDO, FOF_NOERRORUI = 0x40, 0x400
    op = _SHFILEOPSTRUCTW(None, FO_DELETE, ctypes.addressof(buf), None,
                          FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
                          | FOF_NOERRORUI, 0, None, None)
    try:
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except (AttributeError, OSError):
        return False
    return rc == 0 and not op.fAnyOperationsAborted


# ==========================================================================
# leftovers
# ==========================================================================
def _size(path):
    p = Path(path)
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def find_leftovers(paths, data):
    """Things on disk that belong to no installed mod.

    `checked` marks what is safe to remove without a second thought. Backups
    that Repair or the installer made are listed but left unticked: they are
    inert, but someone may still want them.
    """
    items = []

    def add(path, kind, why, checked):
        items.append({"path": str(path), "kind": kind, "why": why,
                      "checked": checked, "size": _size(path)})

    game, win64, paks = paths["game"], paths["win64"], paths["paks"]
    pak_names = {p["name"].lower() for p in data["pak_mods"]}

    for folder in (paks / "~mods", paks / "LogicMods"):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            low = f.name.lower()
            stem = f.name.split(".")[0].lower()
            if f.is_dir():
                # BPModLoaderMod reads per-mod config folders from LogicMods.
                if folder.name == "LogicMods" and low not in pak_names:
                    add(f, "orphaned folder",
                        f"config folder for '{f.name}', which isn't installed", True)
                continue
            if low.endswith((".pak", ".pak.disabled")):
                continue
            if low.endswith(".pmm-bak"):
                add(f, "install backup",
                    "copy kept when an install replaced this file", False)
                continue
            # 'My.Mod_P.json' belongs to 'My.Mod_P.pak'; match by prefix, not stem.
            if any(low.startswith(n + '.') for n in pak_names):
                continue
            if low.endswith((".ucas", ".utoc", ".ucas.disabled", ".utoc.disabled")):
                add(f, "orphaned pak half",
                    f"IoStore file for '{stem}', whose .pak is gone", True)
            else:
                add(f, "orphaned config",
                    f"belongs to '{f.name.split('.')[0]}', which isn't installed", True)

    for name in ("UE4SS.dll.bak", "UE4SS-settings.ini.bak", "UE4SS.log.bak"):
        if (win64 / name).is_file():
            add(win64 / name, "old UE4SS file",
                "flat-layout UE4SS file parked by Repair", False)
    if (win64 / "Mods.flat-bak").is_dir():
        add(win64 / "Mods.flat-bak", "old UE4SS folder",
            "flat Win64\\Mods folder parked by Repair", False)
    for d in sorted(game.glob("_UE4SS_backup_*")):
        if d.is_dir():
            add(d, "old UE4SS backup", "backup of an earlier UE4SS install", False)
    # The UE4SS installer keeps whatever it replaced, rather than deleting it.
    for d in sorted(win64.glob("*.pmm-old-*")):
        add(d, "old UE4SS", "the UE4SS this app replaced, kept in case you "
                             "want it back", False)

    for _, root in paths["mod_roots"]:
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name == "shared":
                continue
            if (d / "Scripts" / "main.lua").is_file() or (d / "dlls" / "main.dll").is_file():
                continue
            files = [f for f in d.rglob("*") if f.is_file()]
            if not files:
                add(d, "empty mod folder", "no files at all", True)
            elif all(f.name.lower() in ("enabled.txt", "enabled.txt.disabled")
                     for f in files):
                add(d, "empty mod folder",
                    "only an enabled.txt -- the mod itself is gone", True)
        for f in sorted(root.rglob("*.pmm-bak")):
            add(f, "install backup",
                "copy kept when an install replaced this file", False)
    return items


# ==========================================================================
# BPModLoaderMod load order
# ==========================================================================
DEFAULT_ORDER_HEADER = [
    "; You only have to include BP mods where load order matters, mods not "
    "included here will be loaded in any random order after loading the "
    "prioritized mods.",
    "; Add your BP mods below by their name without .pak at the end, they "
    "will be loaded in top to bottom order.",
]


def load_order_file(paths):
    return paths["ue4ss_mods"] / "BPModLoaderMod" / "load_order.txt"


def read_load_order(paths):
    """(header comment lines, ordered mod names). Mirrors BPModLoaderMod,
    which skips lines starting with ';' and dedupes the rest."""
    f = load_order_file(paths)
    if not f.is_file():
        return list(DEFAULT_ORDER_HEADER), []
    header, entries = [], []
    for line in f.read_text("utf8", "replace").splitlines():
        if line.startswith(";"):
            header.append(line)
        elif line.strip() and line.strip() not in entries:
            entries.append(line.strip())
    return header or list(DEFAULT_ORDER_HEADER), entries


def write_load_order(paths, entries):
    f = load_order_file(paths)
    if not f.parent.is_dir():
        raise FileNotFoundError("BPModLoaderMod isn't installed, so there is "
                                "no load order to write.")
    header, _ = read_load_order(paths)
    clean = []
    for e in entries:
        e = e.strip()
        if e.lower().endswith(".pak"):
            e = e[:-4]
        if e and e not in clean:
            clean.append(e)
    if f.is_file():
        f.with_suffix(".txt.bak").write_bytes(f.read_bytes())
    # The shipped file uses CRLF; Lua's io.lines strips it either way.
    f.write_bytes(("\r\n".join(header + clean) + "\r\n").encode("utf8"))
    return clean


# ==========================================================================
# shareable modlists
# ==========================================================================
FORMAT = "pal-mod-manager-modlist"


def _version(name, reg, fallback=None):
    return (reg.get(name) or {}).get("version") or fallback


def export_modlist(data, only_enabled=True):
    reg = data.get("registry") or palregistry.load_registry()
    mods = []

    def add(name, kind, enabled, version=None):
        if only_enabled and not enabled:
            return
        entry = reg.get(name) or {}
        mods.append({
            "name": name, "kind": kind, "enabled": enabled,
            "version": _version(name, reg, version),
            "source": entry.get("source"),
            "url": palregistry.url_for(name, entry),
        })

    for m in data["ue4ss_mods"]:
        if not m["builtin"]:
            add(m["name"], "UE4SS mod", m["enabled"], m.get("version"))
    for p in data["pak_mods"]:
        add(p["name"], "blueprint pak" if p["folder"] == "LogicMods"
            else "content pak", not p["disabled"])
    for s in data.get("palschema_mods", []):
        add(s["name"], "PalSchema mod", s["enabled"])

    return {
        "format": FORMAT, "version": 1,
        "exported": datetime.now().isoformat(timespec="seconds"),
        "only_enabled": only_enabled,
        "game": (data.get("build") or {}).get("label"),
        "ue4ss": (data.get("ue4ss") or {}).get("summary"),
        "mods": mods,
    }


def modlist_text(doc):
    """Readable version for pasting into Discord or a Steam chat."""
    lines = [f"Palworld mods ({len(doc['mods'])})"]
    if doc.get("game") or doc.get("ue4ss"):
        lines.append(" · ".join(x for x in (doc.get("game"), doc.get("ue4ss")) if x))
    for kind in ("UE4SS mod", "blueprint pak", "content pak", "PalSchema mod"):
        group = [m for m in doc["mods"] if m["kind"] == kind]
        if not group:
            continue
        lines.append("")
        lines.append(f"{kind}s:")
        for m in group:
            bits = [f"- {m['name']}"]
            if m.get("version"):
                bits.append(f"v{m['version']}")
            if m.get("url") and m["url"].startswith("http"):
                bits.append(m["url"])
            lines.append("  ".join(bits))
    return "\n".join(lines)


def load_modlist(path):
    try:
        doc = json.loads(Path(path).read_text("utf8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Couldn't read that file: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("That isn't a EZ Pal Mod Manager modlist.")
    return doc


def compare_modlist(doc, data):
    """How your install differs from a shared list."""
    reg = data.get("registry") or {}
    mine = {}
    for m in data["ue4ss_mods"]:
        if not m["builtin"]:
            mine[m["name"]] = (m["enabled"], _version(m["name"], reg, m.get("version")))
    for p in data["pak_mods"]:
        mine[p["name"]] = (not p["disabled"], _version(p["name"], reg))
    for s in data.get("palschema_mods", []):
        mine[s["name"]] = (s["enabled"], None)

    theirs_on = {m["name"]: m for m in doc["mods"] if m.get("enabled", True)}
    missing = [m for n, m in theirs_on.items() if n not in mine]
    turn_on = [n for n in theirs_on if n in mine and not mine[n][0]]
    turn_off = ([n for n, (on, _) in mine.items() if on and n not in theirs_on]
                if doc.get("only_enabled", True) else [])
    versions = [(n, m.get("version"), mine[n][1]) for n, m in theirs_on.items()
                if n in mine and m.get("version") and mine[n][1]
                and str(m["version"]) != str(mine[n][1])]
    matched = [n for n in theirs_on if n in mine and mine[n][0]]
    return {"missing": missing, "turn_on": turn_on, "turn_off": turn_off,
            "versions": versions, "matched": matched,
            "want_on": list(theirs_on)}


# ==========================================================================
# UE4SS.log lines
# ==========================================================================
# UE4SS dumps hundreds of engine offsets at startup ("ArIsError = 0x29"). They
# contain words like Error but are not errors, and would drown a filter.
OFFSET_DUMP = re.compile(r"(::\w+|\w+)\s*=\s*0x[0-9A-Fa-f]+\s*$")
PROBLEM = re.compile(r"(?i)\b(errors?|failed|failure|fail|exception|cannot|"
                     r"can't|unable|not found|invalid|crash(ed)?|missing)\b")
MOD_START = re.compile(r"Starting (?:Lua |C\+\+ )?mod|has enabled\.txt|"
                       r"Name == |loaded\b")
MOD_TAG = re.compile(r"^\[[\d\-: .]+\]\s*\[(?!Lua\])[A-Za-z][\w .-]{1,40}\]|\[Lua\]")


def classify_log_line(line):
    """'problem', 'start', 'mod' or 'other'."""
    if OFFSET_DUMP.search(line):
        return "other"
    if PROBLEM.search(line):
        return "problem"
    if MOD_START.search(line):
        return "start"
    if MOD_TAG.search(line):
        return "mod"
    return "other"
