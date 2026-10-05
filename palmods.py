#!/usr/bin/env python3
"""
PalModManager -- status dashboard and toggle tool for Palworld mods.

Scans every place a Palworld mod can live, cross-references what UE4SS actually
loaded, and reports what is working, what failed, and what is in the wrong folder.

    python palmods.py status              full report
    python palmods.py status --html       also write dashboard.html
    python palmods.py enable  <name>      stage a mod on  (applies next launch)
    python palmods.py disable <name>      stage a mod off (applies next launch)

A name that two kinds of mod share, such as the Lua and PalSchema halves of a
hybrid mod, is given with its kind: ue4ss:<name>, pak:<name>, palschema:<name>.

Writes manifest.json on every run; the in-game panel (stage 2) reads that file,
because UE4SS Lua has io.open but no directory listing.
"""

import argparse
import json
import re
import struct
import sys
from datetime import datetime
from pathlib import Path

import palpaths
import palregistry

HERE = palpaths.data_dir()          # writable; never the frozen temp folder


def game_root():
    """The Palworld folder in use.

    Discovered and remembered by palpaths -- it used to be a constant here,
    which meant the tool only ran on the machine it was written on.
    """
    return palpaths.require_game()

ANSI = re.compile(r"\x1b?\[\d{1,2}m")
# UE4SS DLL-mod load failures report a raw Win32 error code.
WIN32_ERRORS = {
    0x7E: "ERROR_MOD_NOT_FOUND - a dependency DLL is missing",
    0x7F: "ERROR_PROC_NOT_FOUND - built against a different UE4SS ABI",
    0xC1: "ERROR_BAD_EXE_FORMAT - wrong architecture (32/64-bit)",
}


# --------------------------------------------------------------------------
# layout discovery
# --------------------------------------------------------------------------
def discover():
    """Locate every place a Palworld mod can live.

    Palworld mods land in more than one folder depending on how they were
    installed -- UE4SS script/native mods, blueprint paks, content paks, and
    whatever the CurseForge app or Steam Workshop drops in. All of them are
    scanned; the active UE4SS root is whichever layout owns the log.
    """
    game = game_root()
    win64 = game / "Pal" / "Binaries" / "Win64"
    paks = game / "Pal" / "Content" / "Paks"
    nested, flat = win64 / "ue4ss", win64

    # The active root is the layout that actually has mods in it; an empty
    # Win64\Mods gets recreated by UE4SS and must not win.
    def populated(p):
        return p.is_dir() and any(c.is_dir() for c in p.iterdir())

    # Where UE4SS.dll actually is decides the layout. Only when both exist (a
    # conflict) or neither does do the mod folders get a say.
    cores = [(d, lbl) for d, lbl in ((nested, "experimental (ue4ss/)"),
                                     (flat, "flat (<=3.0.1)"))
             if (d / "UE4SS.dll").is_file()]
    if len(cores) == 1:
        root, layout = cores[0]
    elif populated(nested / "Mods"):
        root, layout = nested, "experimental (ue4ss/)"
    elif populated(flat / "Mods"):
        root, layout = flat, "flat (<=3.0.1)"
    elif (nested / "Mods").is_dir():
        root, layout = nested, "experimental (ue4ss/)"
    elif (flat / "Mods").is_dir():
        root, layout = flat, "flat (<=3.0.1)"
    else:
        # No UE4SS at all. That used to be a hard exit, which made the whole
        # app unusable on a fresh install -- yet pak mods need no UE4SS, and
        # this is exactly the install that most needs telling what is missing.
        root, layout = nested, "not installed"

    # (label, path) for every UE4SS-style mod folder that exists.
    mod_roots = [(lbl, p) for lbl, p in (
        ("ue4ss/Mods",       nested / "Mods"),
        ("Win64/Mods",       flat / "Mods"),
        ("Workshop UE4SS",   game / "Mods" / "NativeMods" / "UE4SS" / "Mods"),
    ) if p.is_dir()]

    # (label, path, recurse) for every place .pak files can sit.
    pak_roots = [(lbl, p) for lbl, p in (
        ("~mods",      paks / "~mods"),
        ("LogicMods",  paks / "LogicMods"),
        ("Paks",       paks),               # stray paks dropped at the root
        ("game Mods",  game / "Mods"),      # Palworld's own / CurseForge folder
    ) if p.is_dir()]

    return {
        "game": game,
        "kind": palpaths.kind_of(game),
        "win64": win64,
        "paks": paks,
        "layout": layout,
        "ue4ss_root": root,
        "ue4ss_mods": root / "Mods",
        "log": root / "UE4SS.log",
        "mod_roots": mod_roots,
        "pak_roots": pak_roots,
    }


# --------------------------------------------------------------------------
# is UE4SS installed, and is it the right one?
# --------------------------------------------------------------------------
PROXY_DLLS = ("dwmapi.dll", "xinput1_3.dll")


def ue4ss_status(paths, log=None):
    """What UE4SS the game will load, in terms a user can act on.

    UE4SS is two parts: UE4SS.dll, and a proxy DLL (dwmapi.dll) that Windows
    loads into the game on its behalf. Either one alone does nothing. The
    folder UE4SS.dll sits in is the layout: ue4ss\\ for the experimental
    Palworld build, Win64 itself for the official 3.0.1 and older.
    """
    win64 = paths["win64"]
    nested = (win64 / "ue4ss" / "UE4SS.dll").is_file()
    flat = (win64 / "UE4SS.dll").is_file()
    proxy = next((n for n in PROXY_DLLS if (win64 / n).is_file()), None)
    if log is None:
        log = parse_log(paths["log"])
    version = (log.get("ue4ss_version") or "").split(" - Git")[0] or None

    st = {"installed": nested or flat, "state": "ok", "layout": None,
          "version": version, "proxy": proxy,
          "ran": bool(log.get("found") and log.get("when")),
          "problems": [], "summary": ""}

    if not (nested or flat):
        st["state"] = "missing"
        st["summary"] = "UE4SS not installed"
        st["problems"].append(
            "UE4SS isn't installed, so UE4SS mods and LogicMods blueprint mods "
            "won't load. Content paks in ~mods work without it.")
        if proxy:
            st["problems"].append(
                f"{proxy} is still in Win64 without UE4SS.dll -- leftovers "
                f"from a removed or half-finished install.")
        return st

    st["layout"] = "experimental" if nested else "flat"
    if nested and flat:
        st["state"] = "conflict"
        st["problems"].append(
            "Two UE4SS installs: UE4SS.dll is in both Win64 and Win64\\ue4ss. "
            "Only one can load. Repair parks the flat copy.")
    if not proxy:
        st["state"] = "broken"
        st["problems"].append(
            "UE4SS.dll is present but dwmapi.dll is missing, so the game never "
            "loads UE4SS. Reinstall UE4SS.")
    if nested and not (win64 / "ue4ss" / "MemberVariableLayout.ini").is_file():
        st["state"] = "warn" if st["state"] == "ok" else st["state"]
        st["problems"].append(
            "ue4ss\\MemberVariableLayout.ini is missing. The Palworld "
            "experimental build ships with it; mods that read game data can "
            "fail without it.")
    if flat and not nested:
        st["state"] = "warn" if st["state"] == "ok" else st["state"]
        st["problems"].append(
            "This is the flat (official 3.0.1 or older) UE4SS. Most current "
            "Palworld mods need the experimental-palworld build, which "
            "installs into Win64\\ue4ss.")

    bits = [f"UE4SS {version}" if version else "UE4SS",
            f"{st['layout']} layout"]
    if not st["ran"]:
        bits.append("not run yet")
    st["summary"] = " · ".join(bits)
    return st


# --------------------------------------------------------------------------
# .pak inspection
# --------------------------------------------------------------------------
def _fstring(buf, off):
    """Read a UE FString (negative length means UTF-16)."""
    n = struct.unpack_from("<i", buf, off)[0]
    off += 4
    if n == 0:
        return "", off
    if n < 0:
        n = -n
        return buf[off:off + n * 2].decode("utf-16-le", "replace").rstrip("\0"), off + n * 2
    return buf[off:off + n].decode("utf8", "replace").rstrip("\0"), off + n


def _legacy_index(idx, version):
    """Index layout for pak versions < 10: mount, count, then inline FPakEntry records."""
    off = 0
    mount, off = _fstring(idx, off)
    count = struct.unpack_from("<i", idx, off)[0]
    off += 4
    files = []
    for _ in range(count):
        name, off = _fstring(idx, off)
        files.append(name)
        off += 8 + 8 + 8                                  # offset, size, uncompressed
        method = struct.unpack_from("<I", idx, off)[0]
        off += 4
        if version <= 1:
            off += 8                                      # timestamp
        off += 20                                         # sha1
        if version >= 3:
            if method != 0:                               # compression block table
                nblocks = struct.unpack_from("<i", idx, off)[0]
                off += 4 + nblocks * 16
            off += 1 + 4                                  # bEncrypted, block size
    return mount, files


def _modern_index(f, idx):
    """Index layout for pak versions >= 10: path-hash + full directory index."""
    off = 0
    mount, off = _fstring(idx, off)
    off += 4 + 8                                          # entry count + path-hash seed
    if struct.unpack_from("<i", idx, off)[0]:             # has path-hash index
        off += 4 + 8 + 8 + 20
    else:
        off += 4
    if not struct.unpack_from("<i", idx, off)[0]:         # no full directory index
        return mount, []
    off += 4

    fd_off, fd_size = struct.unpack_from("<qq", idx, off)
    f.seek(fd_off)
    fd = f.read(fd_size)

    files, p = [], 0
    ndirs = struct.unpack_from("<i", fd, p)[0]
    p += 4
    for _ in range(ndirs):
        d, p = _fstring(fd, p)
        nfiles = struct.unpack_from("<i", fd, p)[0]
        p += 4
        for _ in range(nfiles):
            fn, p = _fstring(fd, p)
            p += 4
            files.append(d + fn)
    return mount, files


def read_pak(path):
    """Return {version, mount, files[]} for a .pak, or {error} if unreadable."""
    info = {"version": None, "mount": None, "files": []}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read(4096)

            at = tail.rfind(struct.pack("<I", 0x5A6F12E1))
            if at < 0:
                return {"error": "not a valid .pak (magic missing)"}
            version = struct.unpack_from("<I", tail, at + 4)[0]
            info["version"] = version
            idx_off, idx_size = struct.unpack_from("<QQ", tail, at + 8)

            f.seek(idx_off)
            idx = f.read(idx_size)
            if version >= 10:
                info["mount"], info["files"] = _modern_index(f, idx)
            else:
                info["mount"], info["files"] = _legacy_index(idx, version)
    except Exception as exc:                      # noqa: BLE001 - report, never crash
        return {"error": f"{type(exc).__name__}: {exc}", **info}
    return info


def classify_pak(pak):
    """Decide whether a pak is a blueprint mod (LogicMods) or content (~mods).

    The only reliable blueprint signature is a ModActor asset -- that is what
    BPModLoaderMod scans LogicMods for. A path merely containing "Mods/" is NOT
    enough: plenty of content mods namespace their assets under
    /Game/Mods/<author>/..., and treating that as a blueprint told people to
    move working mods out of the folder where they belong.

    Returns (None, ...) when undetermined, so an unreadable pak is never
    reported as misplaced.
    """
    mount = (pak.get("mount") or "").replace("\\", "/")
    files = [f.replace("\\", "/") for f in pak.get("files", [])]

    has_modactor = any(
        re.search(r"(^|/)ModActor[\w-]*\.uasset$", f, re.I) for f in files)
    mounts_as_mod = bool(re.search(r"/Content/Mods/[^/]+/?$", mount))

    if has_modactor or mounts_as_mod:
        return "LogicMods", "blueprint mod (ModActor)"
    if not mount and not files:
        return None, "could not read index"
    return "~mods", "content pak (asset override)"


# --------------------------------------------------------------------------
# UE4SS.log parsing -- last run only
# --------------------------------------------------------------------------
def parse_log(path):
    out = {
        "found": False, "ue4ss_version": None, "engine": None, "when": None,
        "started": {}, "disabled": [], "bp_mods": [], "failures": [],
        "mod_list": None,       # which list UE4SS read: "mods.txt" / "mods.json"
    }
    if not path.is_file():
        return out
    out["found"] = True
    lines = [ANSI.sub("", ln.rstrip("\n"))
             for ln in path.read_text("utf8", "replace").splitlines()]

    # A log can hold several runs; only the newest reflects reality.
    starts = [i for i, ln in enumerate(lines) if "UE4SS - v" in ln]
    if starts:
        lines = lines[starts[-1]:]

    for ln in lines:
        if m := re.search(r"UE4SS - (v\S+.*?Git SHA #\w+)", ln):
            out["ue4ss_version"] = m.group(1)
        if m := re.search(r"Found EngineVersion: (\S+)", ln):
            out["engine"] = m.group(1)
        if m := re.match(r"\[([\d\-: .]+)\]", ln):
            out["when"] = out["when"] or m.group(1).strip()

        if m := re.search(r"Starting mods \(from (mods\.(?:txt|json))", ln):
            out["mod_list"] = m.group(1)
        if m := re.search(r"Starting (?:Lua )?mod '([^']+)'", ln):
            out["started"].setdefault(m.group(1), None)
        if m := re.search(r"Mod '([^']+)' has enabled\.txt, starting mod", ln):
            out["started"].setdefault(m.group(1), None)
        if m := re.search(r"Mod '([^']+)' disabled in mods\.txt", ln):
            out["disabled"].append(m.group(1))
        if m := re.search(r"BPModLoaderMod\]\s+Name == (\S+)", ln):
            out["bp_mods"].append(m.group(1))

        # Version strings the mods print themselves, e.g. "PalMiniMap 2.3.6 loaded"
        if m := re.search(r"\[(\w+)[ /]v?(\d+\.\d+[\w.]*)\]", ln):
            if m.group(1) in out["started"]:
                out["started"][m.group(1)] = m.group(2)
        if m := re.search(r"(\w+) (?:version )?v?(\d+\.\d+[\w.]*) loaded", ln):
            if m.group(1) in out["started"]:
                out["started"][m.group(1)] = m.group(2)

        # ---- failures, translated to plain language -------------------
        if m := re.search(r"Failed to load dll <([^>]+)> for mod (\S+), error code: (0x[0-9a-fA-F]+)", ln):
            code = int(m.group(3), 16)
            out["failures"].append({
                "mod": m.group(2), "kind": "dll",
                "detail": f"DLL rejected ({m.group(3)}): "
                          f"{WIN32_ERRORS.get(code, 'unknown Win32 error')}",
            })
        if m := re.search(r"lua_pcall returned \S+ => .*?[\\/]([\w.]+\.lua):(\d+): (.+)", ln):
            out["failures"].append({
                "mod": "?", "kind": "lua",
                "detail": f"Lua error in {m.group(1)}:{m.group(2)} -- {m.group(3)}",
            })
        if m := re.search(r"\[(\w+)\].*cannot open config file \(([^)]+)\)", ln):
            out["failures"].append({
                "mod": m.group(1), "kind": "config",
                "detail": f"config not found at {m.group(2)}",
            })
        if m := re.search(r"Was unable to install mod '([^']+)'", ln):
            out["failures"].append({
                "mod": m.group(1), "kind": "install", "detail": "mod could not be installed",
            })

    # Attribute anonymous Lua errors to a mod by matching the script path.
    for fail in out["failures"]:
        if fail["mod"] == "?":
            for name in out["started"]:
                if name.lower() in fail["detail"].lower():
                    fail["mod"] = name
                    break
    return out


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------
BUILTIN = {
    "BPModLoaderMod", "BPML_GenericFunctions", "CheatManagerEnablerMod",
    "ConsoleCommandsMod", "ConsoleEnablerMod", "Keybinds", "LineTraceMod",
    "SplitScreenMod", "ActorDumperMod", "jsbLuaProfilerMod", "shared",
}


MODS_TXT_LINE = re.compile(r"^(\s*)([\w.-]+)(\s*:\s*)([01])(.*)$")

# A real mod folder always carries one of these.
UE4SS_SIGNS = ("enabled.txt", "enabled.txt.disabled", "Scripts/main.lua",
               "dlls/main.dll")


def read_mod_lists(mods_dir):
    """{'mods.txt': {name: on}, 'mods.json': {name: on}} -- either may be empty.

    UE4SS keeps a list of mods to start in one of these files, and some builds
    ship both. They can disagree, and only one is actually read: Palworld's
    experimental 3.0.1 reads mods.txt, which is why the log says "Starting
    mods (from mods.txt ...)".
    """
    lists = {"mods.txt": {}, "mods.json": {}}
    txt = Path(mods_dir) / "mods.txt"
    if txt.is_file():
        for ln in txt.read_text("utf8", "replace").splitlines():
            if (m := MODS_TXT_LINE.match(ln)) and not ln.lstrip().startswith(";"):
                lists["mods.txt"][m.group(2)] = m.group(4) == "1"
    js = Path(mods_dir) / "mods.json"
    if js.is_file():
        try:
            for e in json.loads(js.read_text("utf8", "replace")):
                lists["mods.json"][e["mod_name"]] = bool(e.get("mod_enabled"))
        except (ValueError, KeyError, TypeError):
            pass
    return lists


def list_in_use(mods_dir, log=None):
    """Which mod list UE4SS reads: what the log says, else mods.txt if present."""
    if log and log.get("mod_list"):
        return log["mod_list"]
    if (Path(mods_dir) / "mods.txt").is_file():
        return "mods.txt"
    return "mods.json" if (Path(mods_dir) / "mods.json").is_file() else None


def load_toggles(mods_dir, log=None):
    """Enabled/disabled state from the mod list UE4SS actually reads.

    The other list only fills in mods the one in use doesn't mention. Letting
    mods.json win (as this used to) showed mods as off that UE4SS was still
    starting from mods.txt every launch.
    """
    lists = read_mod_lists(mods_dir)
    used = list_in_use(mods_dir, log)
    other = "mods.json" if used == "mods.txt" else "mods.txt"
    toggles = dict(lists[other])
    if used:
        toggles.update(lists[used])
    return toggles


def scan_ue4ss(paths, log):
    """Scan every UE4SS mod folder, not just the active one.

    A mod present in more than one root is reported once, from the active root,
    since that is the copy UE4SS will actually load.
    """
    mods, seen = [], {}
    active = paths["ue4ss_mods"]
    ordered = sorted(paths["mod_roots"], key=lambda lp: lp[1] != active)
    for label, rootdir in ordered:
        # The log describes the active root only.
        root_log = log if rootdir == active else None
        toggles = load_toggles(rootdir, root_log)
        lists = read_mod_lists(rootdir)
        used = list_in_use(rootdir, root_log)
        for d in sorted(rootdir.iterdir()):
            if not d.is_dir() or d.name == "shared":
                continue
            if not any((d / s).exists() for s in UE4SS_SIGNS):
                continue
            if d.name in seen:
                seen[d.name]["also_in"].append(label)
                continue
            kind = ("Lua" if (d / "Scripts" / "main.lua").is_file()
                    else "C++" if (d / "dlls" / "main.dll").is_file() else "unknown")
            has_flag = (d / "enabled.txt").is_file()
            rec = {
                "name": d.name, "kind": kind, "builtin": d.name in BUILTIN,
                "enabled": has_flag or toggles.get(d.name, False),
                "via": "enabled.txt" if has_flag else
                       ((used or "mod list") if d.name in toggles else "not listed"),
                # Both lists name the mod and say different things.
                "list_conflict": (d.name in lists["mods.txt"] and d.name in lists["mods.json"]
                                  and lists["mods.txt"][d.name] != lists["mods.json"][d.name]),
                "list_used": used,
                "loaded": d.name in log["started"],
                "version": log["started"].get(d.name),
                "failures": [f["detail"] for f in log["failures"] if f["mod"] == d.name],
                "path": str(d), "location": label, "also_in": [],
                "inactive_root": rootdir != active,
                # Found once here rather than per repaint: this walks the mod's
                # whole folder, and the UI used to redo it on every keystroke.
                "configs": [str(c) for c in find_configs(d)],
            }
            seen[d.name] = rec
            mods.append(rec)
    return mods


def scan_paks(paths, log):
    out = []
    for label, folder in paths["pak_roots"]:
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() not in (".pak", ".disabled"):
                continue
            # The base game archive is not a mod.
            if p.name.lower().startswith("pal-windows"):
                continue
            disabled = p.suffix.lower() == ".disabled"
            info = read_pak(p)
            expected, desc = classify_pak(info)
            stem = p.name.split(".pak")[0]
            out.append({
                "name": stem, "file": p.name, "folder": label, "disabled": disabled,
                "expected_folder": expected, "type": desc,
                "pak_version": info.get("version"), "mount": info.get("mount"),
                "file_count": len(info.get("files", [])), "error": info.get("error"),
                # Kept only long enough to find conflicts; build() drops it.
                "files": info.get("files", []),
                "misplaced": (not disabled) and expected is not None and expected != label,
                # Only LogicMods blueprint mods announce themselves in the log.
                "loaded": stem in log["bp_mods"] or any(
                    stem.lower() in b.lower() for b in log["bp_mods"]),
                "path": str(p),
            })
    return out


# --------------------------------------------------------------------------
# PalSchema mods
# --------------------------------------------------------------------------
# PalSchema is a UE4SS mod that applies JSON patches from its own mods folder.
# Its mods are neither UE4SS mods nor paks, so they got no row at all. There is
# no enable flag for them; a mod is switched off by moving its folder out of
# mods\ into a sibling folder PalSchema never reads.
PALSCHEMA_OFF = "disabled-mods"


def palschema_dirs(paths):
    base = paths["ue4ss_mods"] / "PalSchema"
    return base, base / "mods", base / PALSCHEMA_OFF


def scan_palschema(paths, log, ue4ss_mods):
    base, on_dir, off_dir = palschema_dirs(paths)
    framework = next((m for m in ue4ss_mods if m["name"] == "PalSchema"), None)
    lines = []
    if log.get("found") and paths["log"].is_file():
        try:
            text = ANSI.sub("", paths["log"].read_text("utf8", "replace"))
            starts = [m.start() for m in re.finditer(r"UE4SS - v", text)]
            text = text[starts[-1]:] if starts else text
            lines = [ln for ln in text.splitlines() if "palschema" in ln.lower()]
        except OSError:
            pass

    out = []
    for folder, enabled in ((on_dir, True), (off_dir, False)):
        if not folder.is_dir():
            continue
        for d in sorted(folder.iterdir()):
            if not d.is_dir():
                continue
            files = [f for f in d.rglob("*") if f.is_file()]
            parts = sorted({f.relative_to(d).parts[0] for f in files
                            if len(f.relative_to(d).parts) > 1})
            mentioned = any(d.name.lower() in ln.lower() for ln in lines)
            out.append({
                "name": d.name, "enabled": enabled, "path": str(d),
                "file_count": len(files), "sections": parts,
                "loaded": enabled and mentioned,
                "framework": bool(framework),
                "framework_on": bool(framework and framework["enabled"]),
            })
    return out


# --------------------------------------------------------------------------
# registry (version / update tracking)
# --------------------------------------------------------------------------
def load_registry():
    """Per-mod source/version metadata. Lives in palregistry now."""
    return palregistry.load_registry()


def age_note(entry):
    return palregistry.age_note(entry)


# --------------------------------------------------------------------------
# toggling
# --------------------------------------------------------------------------
KIND_LABELS = {"ue4ss": "UE4SS mod", "pak": "pak", "palschema": "PalSchema mod"}


def _ue4ss_folder(paths, name):
    """(Mods folder, mod folder) for the UE4SS mod called `name`, or None."""
    for _, rootdir in paths["mod_roots"]:
        d = rootdir / name
        if d.is_dir() and any((d / s).exists() for s in UE4SS_SIGNS):
            return rootdir, d
    return None


def _pak_files(paths, name):
    """The pak called `name`, on or off, in every folder paks are read from."""
    return [p for _, folder in paths["pak_roots"]
            for p in (folder / f"{name}.pak", folder / f"{name}.pak.disabled")
            if p.is_file()]


def _plain_name(name):
    """A mod's name is one folder or file name. A path or an empty name would
    reach past the mod folders: '' is the PalSchema mods folder itself."""
    return bool(name) and name not in (".", "..") and not any(c in name for c in "\\/:")


def kinds_of(name, paths=None):
    """Every kind of mod called `name` in this install, in KINDS order."""
    if not _plain_name(name):
        return []
    paths = paths or discover()
    _, on_dir, off_dir = palschema_dirs(paths)
    found = {"ue4ss": _ue4ss_folder(paths, name) is not None,
             "pak": bool(_pak_files(paths, name)),
             "palschema": (on_dir / name).is_dir() or (off_dir / name).is_dir()}
    return [k for k in palregistry.KINDS if found[k]]


def _either(words):
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " or " + words[-1]


def describe_kinds(kinds):
    """'both a UE4SS mod and a PalSchema mod', for the kinds sharing a name."""
    bits = [f"a {KIND_LABELS[k]}" for k in kinds]
    if len(bits) == 2:
        return f"both {bits[0]} and {bits[1]}"
    return bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " and " + bits[-1]


def _toggle_ue4ss(paths, name, on):
    found = _ue4ss_folder(paths, name)
    if found is None:
        return None
    rootdir, d = found
    live, off = d / "enabled.txt", d / "enabled.txt.disabled"
    if on:
        if off.is_file() and not live.is_file():
            off.rename(live)
        elif not live.is_file():
            live.write_text("")
    elif live.is_file():
        live.replace(off)

    # Update both mod lists, whichever this UE4SS build reads, so they
    # can't drift apart and turn a switched-off mod back on.
    js = rootdir / "mods.json"
    if js.is_file():
        try:
            data = json.loads(js.read_text("utf8"))
            for e in data:
                if e.get("mod_name") == name:
                    e["mod_enabled"] = on
                    js.write_text(json.dumps(data, indent=4) + "\n", "utf8")
                    break
        except ValueError:
            pass
    txt = rootdir / "mods.txt"
    if txt.is_file():
        # Read bytes: read_text would turn the file's CRLF endings into LF.
        lines = txt.read_bytes().decode("utf8", "replace").splitlines(keepends=True)
        for i, ln in enumerate(lines):
            body = ln.rstrip("\r\n")
            m = MODS_TXT_LINE.match(body)
            if m and m.group(2) == name and not body.lstrip().startswith(";"):
                lines[i] = (f"{m.group(1)}{name}{m.group(3)}{int(on)}{m.group(5)}"
                            + ln[len(body):])
                txt.write_text("".join(lines), "utf8", newline="")
                break
    return f"UE4SS mod '{name}' -> {'enabled' if on else 'disabled'} (applies next launch)"


def _toggle_pak(paths, name, on):
    for _, folder in paths["pak_roots"]:
        live, off = folder / f"{name}.pak", folder / f"{name}.pak.disabled"
        if on and off.is_file() and not live.exists():
            off.rename(live)
            return f"pak '{name}' -> enabled (applies next launch)"
        if not on and live.is_file():
            live.rename(off)
            return f"pak '{name}' -> disabled (applies next launch)"
        if live.is_file() or off.is_file():
            return f"pak '{name}' already {'enabled' if on else 'disabled'}"
    return None


def _toggle_palschema(paths, name, on):
    _, on_dir, off_dir = palschema_dirs(paths)
    src, dst = ((off_dir / name, on_dir / name) if on
                else (on_dir / name, off_dir / name))
    if src.is_dir():
        if dst.exists():
            return f"PalSchema mod '{name}' exists in both folders; resolve by hand."
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return (f"PalSchema mod '{name}' -> {'enabled' if on else 'disabled'} "
                f"(applies next launch)")
    if dst.is_dir():
        return f"PalSchema mod '{name}' already {'enabled' if on else 'disabled'}"
    return None


TOGGLES = {"ue4ss": _toggle_ue4ss, "pak": _toggle_pak, "palschema": _toggle_palschema}


def set_enabled(name, on, kind=None):
    """Toggle a mod wherever it lives: any UE4SS root, pak folder or PalSchema.

    One name can belong to two kinds of mod: a hybrid mod often ships a Lua mod
    and a PalSchema mod in folders of the same name. `kind` ("ue4ss", "pak" or
    "palschema") says which one is meant. Without it, a shared name is refused
    instead of guessed at, because a guess switches off the wrong half.
    """
    if kind is not None and kind not in TOGGLES:
        raise ValueError(f"unknown kind of mod: {kind!r}")
    if not _plain_name(name):
        return f"No mod named '{name}' found."
    paths = discover()
    if kind is None:
        found = kinds_of(name, paths)
        if not found:
            return f"No mod named '{name}' found."
        if len(found) > 1:
            return (f"Nothing was changed: '{name}' is {describe_kinds(found)}. "
                    f"Say which: "
                    + _either([palregistry.mod_id(k, name) for k in found]) + ".")
        kind = found[0]
    return (TOGGLES[kind](paths, name, on)
            or f"No {KIND_LABELS[kind]} named '{name}' found.")


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def build(paths):
    import palsafety          # imports this module; kept local to avoid a cycle

    log = parse_log(paths["log"])
    ue4ss = scan_ue4ss(paths, log)
    paks = scan_paks(paths, log)
    data = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "layout": paths["layout"], "log": log,
        "install": {"path": str(paths["game"]), "kind": paths["kind"],
                    "label": palpaths.label(paths["game"])},
        "ue4ss": ue4ss_status(paths, log),
        "ue4ss_mods": ue4ss,
        "pak_mods": paks,
        "palschema_mods": scan_palschema(paths, log, ue4ss),
        "registry": load_registry(),
    }
    data["conflicts"] = palsafety.pak_conflicts(paks)
    data["core_overrides"] = palsafety.core_overrides(paks)
    for p in paks:
        p.pop("files", None)      # thousands of paths; not worth keeping
    data["keybinds"] = palsafety.keybind_report(ue4ss)
    data["build"] = palsafety.build_info(paths["game"])
    data["patch"] = palsafety.observe(paths, data)
    return data


# --------------------------------------------------------------------------
# mod configuration files
# --------------------------------------------------------------------------
# Every mod invents its own config format, so there is nothing universal to
# parse. What is safe is line-preserving edits to `key = value` files (ini/txt)
# and structured edits to json. Lua configs are code and are opened externally
# rather than rewritten -- a bad write there breaks a working mod.

CONFIG_NAMES = ("config", "settings", "setting", "options", "keybinds")
CONFIG_SUFFIXES = (".ini", ".json", ".txt", ".cfg", ".lua")
KV_LINE = re.compile(r"^(\s*)([A-Za-z_][\w.\- ]*?)(\s*[:=]\s*)(.*?)(\s*(?:[;#].*)?)$")
SECTION_LINE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def config_kind(path):
    suf = path.suffix.lower()
    if suf == ".json":
        return "json"
    if suf == ".lua":
        return "lua"
    if suf in (".ini", ".txt", ".cfg"):
        return "kv"
    return "other"


def find_configs(mod_path):
    """Config files belonging to a mod, nearest the root first."""
    root = Path(mod_path)
    if not root.is_dir():
        return []
    found = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in CONFIG_SUFFIXES:
            continue
        stem = p.stem.lower()
        if not any(n in stem for n in CONFIG_NAMES):
            continue
        if p.name.lower() in ("mods.json", "modlist.txt", "enabled.txt"):
            continue
        found.append(p)
    return sorted(found, key=lambda p: (len(p.relative_to(root).parts), p.name))


def _coerce(raw):
    """Classify a raw config value so the UI can pick a sensible control."""
    v = raw.strip().strip('"')
    low = v.lower()
    if low in ("true", "false", "yes", "no", "on", "off"):
        return "bool", low in ("true", "yes", "on")
    try:
        return "number", (float(v) if "." in v else int(v))
    except ValueError:
        return "text", v


def load_config(path):
    """Return {kind, fields[]}. Fields carry the info needed to write back."""
    path = Path(path)
    kind = config_kind(path)
    if kind == "json":
        try:
            data = json.loads(path.read_text("utf8", "replace"))
        except ValueError as exc:
            return {"kind": "error", "error": f"invalid JSON: {exc}", "fields": []}
        if not isinstance(data, dict):
            return {"kind": "error", "error": "JSON root is not an object", "fields": []}
        fields = []
        for k, v in data.items():
            if isinstance(v, bool):
                t, val = "bool", v
            elif isinstance(v, (int, float)):
                t, val = "number", v
            elif isinstance(v, str):
                t, val = "text", v
            else:
                continue                      # nested structures stay untouched
            fields.append({"id": k, "label": k, "section": "", "type": t, "value": val})
        return {"kind": "json", "fields": fields}

    if kind == "kv":
        fields, section = [], ""
        for i, line in enumerate(path.read_text("utf8", "replace").splitlines()):
            m = SECTION_LINE.match(line)
            if m:
                section = m.group(1)
                continue
            if line.strip().startswith((";", "#")) or not line.strip():
                continue
            m = KV_LINE.match(line)
            if not m:
                continue
            t, val = _coerce(m.group(4))
            fields.append({"id": i, "label": m.group(2).strip(), "section": section,
                           "type": t, "value": val})
        return {"kind": "kv", "fields": fields}

    return {"kind": kind, "fields": []}       # lua / other -> open externally


def save_config(path, updates):
    """Write changed values back, preserving comments and layout.

    `updates` maps field id -> new value. A .bak copy is made first.
    """
    path = Path(path)
    if not updates:
        return "No changes."
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_bytes(path.read_bytes())
    kind = config_kind(path)

    if kind == "json":
        data = json.loads(path.read_text("utf8", "replace"))
        data.update(updates)
        path.write_text(json.dumps(data, indent=2) + "\n", "utf8")
        return f"Saved {len(updates)} setting(s); backup at {backup.name}"

    lines = path.read_text("utf8", "replace").splitlines(keepends=True)
    for idx, new in updates.items():
        i = int(idx)
        if not (0 <= i < len(lines)):
            continue
        m = KV_LINE.match(lines[i].rstrip("\r\n"))
        if not m:
            continue
        if isinstance(new, bool):
            new = "true" if new else "false"
        eol = "\n" if lines[i].endswith("\n") else ""
        lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}{new}{m.group(5)}{eol}"
    path.write_text("".join(lines), "utf8")
    return f"Saved {len(updates)} setting(s); backup at {backup.name}"


def snapshot(paths):
    """Cheap fingerprint of every watched folder, for change detection.

    Names plus mtimes across all mod roots -- enough to notice a mod being
    added, removed, enabled or disabled without a full rescan.
    """
    bits = []
    _, ps_on, ps_off = palschema_dirs(paths)
    extra = [("PalSchema", d) for d in (ps_on, ps_off) if d.is_dir()]
    for _, d in paths["mod_roots"] + paths["pak_roots"] + extra:
        try:
            for c in sorted(d.iterdir()):
                bits.append(f"{c.name}:{int(c.stat().st_mtime)}")
        except OSError:
            continue
    return hash(tuple(bits))


def write_modlist(paths, data):
    """Emit modlist.txt for the in-game panel: name|kind|enabled|path

    UE4SS Lua can open a file but cannot enumerate a directory, so the in-game
    panel relies on this being regenerated whenever mods change.
    """
    target = paths["ue4ss_mods"] / "PalModManager"
    if not target.is_dir():
        return None
    lines = ["# name|kind|enabled|path  -- regenerated by palmods.py"]
    for m in data["ue4ss_mods"]:
        if m["builtin"] or m["name"].startswith("PalModManager"):
            continue
        kind = "c++" if m["kind"] == "C++" else "lua"
        lines.append(f"{m['name']}|{kind}|{int(m['enabled'])}|"
                     f"{m['path'].replace(chr(92), '/')}")
    for p in data["pak_mods"]:
        lines.append(f"{p['name']}|pak|{int(not p['disabled'])}|"
                     f"{p['path'].replace(chr(92), '/')}")
    out = target / "modlist.txt"
    out.write_text("\n".join(lines) + "\n", "utf8")
    return out


def report(data):
    log, reg = data["log"], data["registry"]
    L = []
    L.append("=" * 68)
    L.append("  PALWORLD MOD STATUS")
    L.append("=" * 68)
    L.append(f"  Install : {data['install']['label']} ({data['build']['label']})")
    L.append(f"  UE4SS   : {data['ue4ss']['summary']}")
    L.append(f"  Layout  : {data['layout']}")
    L.append(f"  Engine  : {log['engine'] or '?'}      Last run: {log['when'] or 'never'}")

    user = [m for m in data["ue4ss_mods"] if not m["builtin"]]
    built = [m for m in data["ue4ss_mods"] if m["builtin"]]

    L.append("\n  UE4SS MODS")
    for m in user:
        if m["loaded"] and not m["failures"]:
            state = "LOADED"
        elif m["failures"]:
            state = "FAILED"
        elif m["enabled"]:
            state = "not loaded"
        else:
            state = "off"
        ver = f" {m['version']}" if m["version"] else ""
        L.append(f"    {m['name']:<22}{ver:<9}{m['kind']:<9}{state}")
        for f in m["failures"]:
            L.append(f"        ! {f}")
        if (note := age_note(reg.get(m["name"], {}))):
            L.append(f"        - {note}")
    L.append(f"    ({len(built)} UE4SS built-ins: "
             f"{sum(1 for m in built if m['enabled'])} on)")

    L.append("\n  PAK MODS")
    for p in data["pak_mods"]:
        bits = []
        if p["disabled"]:
            bits.append("DISABLED")
        elif p["misplaced"]:
            bits.append(f"MISPLACED -> move to {p['expected_folder']}")
        elif p["folder"] == "LogicMods":
            bits.append("LOADED" if p["loaded"] else "not seen in log")
        else:
            bits.append("silent (content paks do not log)")
        if p["error"]:
            bits.append(p["error"])
        L.append(f"    {p['name']:<24}{p['folder']:<11}pak v{p['pak_version']}  "
                 f"{p['file_count']:>4} files  {' | '.join(bits)}")
        if (note := age_note(reg.get(p["name"], {}))):
            L.append(f"        - {note}")

    warn = [f"{p['name']}: in {p['folder']}, belongs in {p['expected_folder']} ({p['type']})"
            for p in data["pak_mods"] if p["misplaced"]]
    warn += [f"{m['name']}: {f}" for m in user for f in m["failures"]]
    # An old pak format only matters if the mod is not demonstrably working.
    warn += [f"{p['name']}: pak v{p['pak_version']} predates the game's v11 "
             f"and it is not confirmed loaded"
             for p in data["pak_mods"]
             if p["pak_version"] and p["pak_version"] < 11
             and not p["disabled"] and not p["loaded"]]
    warn += [f"{p['name']}: {p['error']}" for p in data["pak_mods"] if p.get("error")]
    warn += [f"UE4SS: {msg}" for msg in data["ue4ss"]["problems"]]
    patch = data["patch"]
    if patch["updated"]:
        warn.append(f"Palworld updated to {patch['build']} since mods last ran "
                    f"(on {patch['last_run_build']}); {len(patch['unverified'])} "
                    f"mod(s) not yet seen loading on this build")
    warn += [f"{n}: loaded on {b}, not since the update"
             for n, b in patch["regressed"].items()]
    warn += [f"{c['loser']} loses {c['assets']} file(s) to {c['winner']}"
             + ("" if c["sure"] else " (likely)")
             for c in data["conflicts"]["pairs"] if c["live"]]
    warn += [f"hotkey {c['key']} bound by {', '.join(c['mods'])}"
             for c in data["keybinds"]["clashes"] if c["live"]]

    L.append("\n  WARNINGS")
    L.extend([f"    ! {w}" for w in warn] or ["    none"])
    L.append("=" * 68)
    return "\n".join(L)


def html(data):
    log = data["log"]
    rows = []
    for m in (x for x in data["ue4ss_mods"] if not x["builtin"]):
        cls = "fail" if m["failures"] else ("ok" if m["loaded"] else
                                            ("warn" if m["enabled"] else "off"))
        state = ("FAILED" if m["failures"] else "LOADED" if m["loaded"]
                 else "not loaded" if m["enabled"] else "off")
        detail = "<br>".join(m["failures"]) or "&mdash;"
        rows.append(f"<tr class='{cls}'><td>{m['name']}</td><td>{m['version'] or ''}</td>"
                    f"<td>{m['kind']}</td><td>UE4SS</td><td>{state}</td><td>{detail}</td></tr>")
    for p in data["pak_mods"]:
        if p["disabled"]:
            cls, state = "off", "DISABLED"
        elif p["misplaced"]:
            cls, state = "fail", f"MISPLACED &rarr; {p['expected_folder']}"
        elif p["folder"] == "LogicMods":
            cls, state = ("ok", "LOADED") if p["loaded"] else ("warn", "not seen in log")
        else:
            cls, state = "warn", "silent"
        rows.append(f"<tr class='{cls}'><td>{p['name']}</td><td>pak v{p['pak_version']}</td>"
                    f"<td>{p['type']}</td><td>{p['folder']}</td><td>{state}</td>"
                    f"<td>{p['mount'] or p.get('error') or ''}</td></tr>")

    return f"""<title>Palworld Mod Status</title>
<style>
:root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --line:#d8d8d8; --mut:#666; --hd:#f4f4f5; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#15161a; --fg:#e8e8ea; --line:#2c2e36; --mut:#9a9aa4; --hd:#1d1e24; }} }}
body {{ background:var(--bg); color:var(--fg); font:14px/1.5 ui-sans-serif,system-ui,sans-serif;
        margin:0; padding:2rem 1rem; }}
main {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:1.3rem; margin:0 0 .25rem; }}
p.meta {{ color:var(--mut); margin:0 0 1.5rem; font-size:.85rem; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; min-width:720px; }}
th,td {{ text-align:left; padding:.5rem .7rem; border-bottom:1px solid var(--line);
         vertical-align:top; }}
th {{ background:var(--hd); font-weight:600; font-size:.78rem; text-transform:uppercase;
      letter-spacing:.04em; color:var(--mut); }}
td:first-child {{ font-weight:600; }}
tr.ok td:nth-child(5) {{ color:#1a7f37; font-weight:600; }}
tr.fail td:nth-child(5) {{ color:#c9372c; font-weight:600; }}
tr.warn td:nth-child(5) {{ color:#9a6700; }}
tr.off td {{ color:var(--mut); }}
code {{ font:12px ui-monospace,monospace; }}
</style>
<main>
<h1>Palworld Mod Status</h1>
<p class="meta"><code>{log['ue4ss_version'] or 'UE4SS unknown'}</code> &middot;
{data['layout']} &middot; engine {log['engine'] or '?'} &middot;
generated {data['generated']}</p>
<div class="scroll"><table>
<tr><th>Mod</th><th>Version</th><th>Type</th><th>Location</th><th>Status</th><th>Detail</th></tr>
{chr(10).join(rows)}
</table></div>
</main>"""


_doctor_cache = {}


def doctor_cached(ttl=5.0):
    """doctor() without the cost. It hashes a 3 MB DLL, so the UI must not
    call it on every repaint."""
    import time
    now = time.time()
    hit = _doctor_cache.get("v")
    if hit and now - hit[0] < ttl:
        return hit[1]
    res = doctor(False)
    _doctor_cache["v"] = (now, res)
    return res


def doctor(fix=False):
    """Detect (and optionally repair) a second UE4SS hijacking the dwmapi proxy.

    The CurseForge app reinstalls the flat-layout UE4SS 3.0.1 over the top of the
    experimental build, which silently reverts every Nexus mod that needs the
    newer one. Symptom: mods stop loading and UE4SS.log reappears in Win64\\.
    """
    import hashlib
    import shutil

    win64 = game_root() / "Pal" / "Binaries" / "Win64"
    # A known-good copy of the experimental build's proxy DLL, used only as a
    # checksum reference. Not shipped with the app -- it is UE4SS's binary, not
    # ours -- so it is looked for beside the source and in the data folder,
    # where a user can drop their own copy. Absent, this check is skipped.
    ref = next((c for c in (
        palpaths.bundled_dir() / "reference" / "dwmapi.dll",
        Path(__file__).resolve().parent / "reference" / "dwmapi.dll",
        palpaths.data_dir() / "reference" / "dwmapi.dll",
    ) if c.is_file()), palpaths.data_dir() / "reference" / "dwmapi.dll")
    issues, actions = [], []

    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

    # Only a conflict *with* the experimental build is repairable here. No
    # UE4SS, or only the flat one, is reported by ue4ss_status() instead --
    # a Repair button that cannot repair anything is worse than none.
    if not (win64 / "ue4ss" / "UE4SS.dll").is_file():
        return [], []

    if ref.is_file() and sha(win64 / "dwmapi.dll") != sha(ref):
        issues.append("dwmapi.dll does not match the experimental build "
                      "-- the wrong UE4SS is loading")
        if fix:
            shutil.copy2(ref, win64 / "dwmapi.dll")
            actions.append("restored dwmapi.dll from reference/")

    flat_mods = win64 / "Mods"
    # UE4SS recreates an empty Win64\Mods on startup; only a populated one is a
    # real conflict worth reporting.
    if flat_mods.is_dir() and any(d.is_dir() for d in flat_mods.iterdir()):
        nested_mods = win64 / "ue4ss" / "Mods"
        ours = ({d.name for d in nested_mods.iterdir() if d.is_dir()}
                if nested_mods.is_dir() else set())
        strays = [d for d in flat_mods.iterdir() if d.is_dir() and d.name not in ours]
        issues.append(f"flat Win64\\Mods has {len(list(flat_mods.iterdir()))} entries"
                      + (f"; {len(strays)} not in ue4ss\\Mods" if strays else ""))
        if fix:
            for d in strays:
                shutil.copytree(d, win64 / "ue4ss" / "Mods" / d.name, dirs_exist_ok=True)
                actions.append(f"rescued {d.name} -> ue4ss\\Mods")
            flat_mods.rename(win64 / "Mods.flat-bak")
            actions.append("parked Win64\\Mods as Mods.flat-bak")

    if fix:
        _doctor_cache.clear()

    for name in ("UE4SS.dll", "UE4SS-settings.ini", "UE4SS.log"):
        p = win64 / name
        if p.is_file():
            issues.append(f"stray flat-layout {name}")
            if fix:
                p.replace(win64 / (name + ".bak"))
                actions.append(f"parked {name} as {name}.bak")
    return issues, actions


def cmd_check(args):
    """Everything that can go wrong before you launch, in one go."""
    import palsafety
    import paltools
    paths = discover()
    data = build(paths)
    ue, patch = data["ue4ss"], data["patch"]
    print(f"{data['install']['label']}  ·  {data['build']['label']}")
    print(f"UE4SS   {ue['summary']}  [{ue['state']}]")
    for msg in ue["problems"]:
        print(f"  ! {msg}")

    print("\nGame updates")
    if patch["updated"]:
        print(f"  ! updated since your mods last ran (on {patch['last_run_build']})")
        for n in patch["unverified"]:
            print(f"    - {n}: not seen loading on this build yet")
    elif patch["regressed"]:
        for n, b in patch["regressed"].items():
            print(f"  ! {n}: loaded on {b}, not since the update")
    else:
        print("  ok")

    print("\nFile conflicts")
    pairs = data["conflicts"]["pairs"]
    for c in pairs:
        state = "both on" if c["live"] else "one off"
        print(f"  {'!' if c['live'] else '-'} {c['mods'][0]} x {c['mods'][1]}: "
              f"{c['assets']} asset(s), {c['winner']} wins"
              f"{'' if c['sure'] else ' (likely)'}  [{state}]")
    for n in data["conflicts"]["no_patch_suffix"]:
        print(f"  ! {n}: no _P suffix, probably can't replace game files")
    if not pairs and not data["conflicts"]["no_patch_suffix"]:
        print("  none")

    print("\nHotkeys")
    clashes = data["keybinds"]["clashes"]
    for c in clashes:
        print(f"  {'!' if c['live'] else '-'} {c['key']}: {', '.join(c['mods'])}"
              f"  [{'all on' if c['live'] else str(len(c['enabled'])) + ' on'}]")
    if not clashes:
        print("  no clashes")
    if data["keybinds"]["unreadable"]:
        print("  unreadable: " + ", ".join(data["keybinds"]["unreadable"]))

    left = paltools.find_leftovers(paths, data)
    print(f"\nLeftovers  {len(left)}")
    for it in left:
        print(f"  {'x' if it['checked'] else ' '} {it['kind']:<18} {it['path']}")

    saves = palsafety.save_dir(paths["game"])
    backups = palsafety.list_backups(paths["game"])
    print(f"\nSaves    {saves or 'not found'}  ·  {len(backups)} backup(s)")
    return 0


def cmd_backup(args):
    import palsafety
    paths = discover()
    if args.action == "list":
        for b in palsafety.list_backups(paths["game"]):
            print(f"  {b['id']:<18} {b.get('reason', ''):<15} "
                  f"{len(b.get('mods') or []):>3} mods  {b.get('size', 0) // 1024:>7} KB")
        return 0
    if args.action == "create":
        meta = palsafety.backup_saves(paths["game"], "manual", build(paths))
        print(f"Backed up {meta['files']} file(s) as {meta['id']}")
        return 0
    if args.action == "restore":
        if not args.id:
            print("restore needs a backup id (see: backup list)")
            return 1
        if not args.yes and input(f"Replace current saves with {args.id}? "
                                  f"[y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
        safety = palsafety.restore_backup(paths["game"], args.id)
        print(f"Restored {args.id}. Previous saves kept as {safety['id']}.")
        return 0
    return 1


def cmd_export(args):
    import paltools
    doc = paltools.export_modlist(build(discover()), only_enabled=not args.all)
    if args.text:
        print(paltools.modlist_text(doc))
    else:
        print(json.dumps(doc, indent=2))
    return 0


def cmd_path(args):
    """Show, set or re-detect the Palworld folder."""
    if args.set:
        ok, msg = palpaths.set_game(args.set)
        print(msg if ok else f"Not a Palworld folder: {msg}")
        return 0 if ok else 1
    if args.detect:
        hits = palpaths.detect()
        if not hits:
            print("No Palworld install found. Use --set <folder>.")
            return 1
        for h in hits:
            print(f"  {h['source']:<12} {h['path']}")
        return 0
    g = palpaths.game()
    print(g or "Not set. Use --set <folder>, or --detect to search.")
    print(f"data folder: {palpaths.data_dir()}")
    return 0 if g else 1


def cmd_install(args):
    import palinstall
    plan = palinstall.inspect(args.archive)
    try:
        if not plan["components"]:
            for w in plan["warnings"]:
                print(f"  ! {w}")
            return 1
        print(f"{plan['source'].name} contains:")
        for c in plan["components"]:
            print(f"  {c['name']:<26} {c['kind']:<14} {len(c['files']):>3} file(s) "
                  f"-> {c['dest']}")
        for w in plan["warnings"]:
            print(f"  ! {w}")
        clashes = palinstall.conflicts(plan)
        names = [c["name"] for c in plan["components"]]
        for c in plan["components"]:
            files = clashes.get(palinstall.component_id(c))
            if files:
                # Say which half of a hybrid mod, when both share the name.
                label = (c["name"] if names.count(c["name"]) == 1
                         else f"{c['name']} ({c['kind']})")
                print(f"  ! {label} overwrites {len(files)} existing file(s) "
                      f"(backups kept as .pmm-bak)")
        if not args.yes:
            if input("\nInstall? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Cancelled.")
                return 1
        for line in palinstall.apply(plan, link=args.link):
            print(f"  {line}")
        print("\nRestart Palworld for this to take effect.")
        return 0
    finally:
        palinstall.discard(plan)


def _say_which(verb, name, kinds):
    """Explain a name that two kinds of mod share, with the commands to pick one."""
    print(f"'{name}' is {describe_kinds(kinds)}. Say which:")
    for k in kinds:
        print(f"  palmods.py {verb} {palregistry.mod_id(k, name)}")


def cmd_toggle(args):
    """enable / disable <name>, or <kind>:<name> for a name two mods share."""
    kind, name = palregistry.split_id(args.name)
    if kind is None and len(found := kinds_of(name)) > 1:
        _say_which(args.cmd, name, found)
        return 1
    print(set_enabled(name, args.cmd == "enable", kind))
    return 0


def cmd_uninstall(args):
    import palinstall
    kind, name = palregistry.split_id(args.name)
    data = build(discover())
    # Where each kind of mod by this name is, for one that has no receipt.
    where = {"ue4ss": [m["path"] for m in data["ue4ss_mods"] if m["name"] == name],
             "pak": [p["path"] for p in data["pak_mods"] if p["name"] == name],
             "palschema": [s["path"] for s in data["palschema_mods"]
                           if s["name"] == name]}
    have = [k for k in palregistry.KINDS
            if where[k] or palregistry.receipt(k, name)]
    if kind is None and len(have) > 1:
        _say_which("uninstall", name, have)
        return 1
    kind = kind or (have[0] if have else None)
    if kind not in have:
        print(f"No mod named '{args.name}'.")
        return 1
    if not args.yes:
        ans = input(f"Delete '{args.name}' from disk? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Cancelled.")
            return 1
    path = where[kind][0] if where[kind] else None
    removed, notes = palinstall.uninstall(
        name, kind=kind, mod_path=path if kind != "pak" else None,
        pak_path=path if kind == "pak" else None)
    for n in notes:
        print(f"  ! {n}")
    print(f"Removed {len(removed)} file(s).")
    return 0


def cmd_new(args):
    import palinstall
    dest = palinstall.scaffold(args.name)
    print(f"Created {dest}")
    print("  Scripts/main.lua   edit this")
    print("  enabled.txt        present, so UE4SS will load it")
    print("\nRestart Palworld and press F7.")
    return 0


def cmd_source(args):
    """Read or set where a mod came from."""
    if not (args.set_source or args.url or args.id or args.version):
        entry = palregistry.get(args.name)
        if not entry:
            print(f"Nothing recorded for '{args.name}'.")
            return 1
        for k, v in sorted(entry.items()):
            print(f"  {k:<14} {v}")
        if (u := palregistry.url_for(args.name, entry)):
            print(f"  {'page':<14} {u}")
        return 0
    entry = palregistry.set_entry(
        args.name, source=args.set_source, url=args.url,
        id=int(args.id) if args.id else None, version=args.version)
    print(f"{args.name}: {palregistry.describe_source(args.name, entry)}")
    return 0


def cmd_profile(args):
    data = build(discover())
    mods = ([("ue4ss", m["name"], m["enabled"]) for m in data["ue4ss_mods"]
             if not m["builtin"]]
            + [("pak", p["name"], not p["disabled"]) for p in data["pak_mods"]]
            + [("palschema", s["name"], s["enabled"]) for s in data["palschema_mods"]])
    ids = [palregistry.mod_id(k, n) for k, n, _ in mods]
    on = [palregistry.mod_id(k, n) for k, n, enabled in mods if enabled]

    if args.action == "list":
        saved = palregistry.profile_names()
        for n in saved:
            pr = palregistry.load_profile(n)
            print(f"  {n:<24} {len(pr['enabled'])} on   saved {pr['saved'][:10]}")
        if not saved:
            print("  no profiles yet")
        return 0

    if not args.name:
        print(f"profile {args.action} needs a name.")
        return 1

    if args.action == "save":
        palregistry.save_profile(args.name, on, ids)
        print(f"Saved profile '{args.name}' ({len(on)} mods on).")
        return 0
    if args.action == "load":
        pr = palregistry.load_profile(args.name)
        if not pr:
            print(f"No profile named '{args.name}'.")
            return 1
        changed = 0
        for kind, n, enabled in mods:
            want = palregistry.profile_wants(pr, kind, n)
            if want is not None and want != enabled:
                set_enabled(n, want, kind)
                changed += 1
        print(f"Applied '{args.name}': {changed} change(s). "
              f"Restart Palworld to take effect.")
        return 0
    if args.action == "delete":
        palregistry.delete_profile(args.name)
        print(f"Deleted profile '{args.name}'.")
        return 0
    return 1


def main():
    # The report uses a few glyphs the GUI renders fine but a legacy console
    # cannot encode, which turns them into mojibake. Ask for UTF-8 where the
    # terminal supports it, and settle for replacement characters where it
    # does not, rather than letting a separator crash the report.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Palworld mod manager")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("status", help="print the report")
    s.add_argument("--html", action="store_true", help="also write dashboard.html")
    d = sub.add_parser("doctor", help="detect a conflicting second UE4SS install")
    d.add_argument("--fix", action="store_true", help="repair what it finds")
    name_help = ("the mod's name, or kind:name when two kinds of mod share it "
                 "(ue4ss:, pak: or palschema:)")
    for verb in ("enable", "disable"):
        sub.add_parser(verb, help=f"{verb} a mod").add_argument("name", help=name_help)

    pa = sub.add_parser("path", help="show or set the Palworld folder")
    pa.add_argument("--set", metavar="FOLDER", help="use this install")
    pa.add_argument("--detect", action="store_true", help="list every install found")

    ins = sub.add_parser("install", help="install a mod from a zip/7z/rar/folder/pak")
    ins.add_argument("archive")
    ins.add_argument("-y", "--yes", action="store_true", help="do not ask")
    ins.add_argument("--link", metavar="URL",
                     help="the Nexus/CurseForge page it was downloaded from")

    un = sub.add_parser("uninstall", help="delete a mod from disk")
    un.add_argument("name", help=name_help)
    un.add_argument("-y", "--yes", action="store_true", help="do not ask")

    nw = sub.add_parser("new", help="scaffold a mod of your own")
    nw.add_argument("name")

    so = sub.add_parser("source", help="show or set where a mod came from")
    so.add_argument("name")
    so.add_argument("--set-source", choices=palregistry.SOURCES, dest="set_source")
    so.add_argument("--url")
    so.add_argument("--id")
    so.add_argument("--version")

    sub.add_parser("check", help="UE4SS, game updates, conflicts, hotkeys, leftovers")

    bk = sub.add_parser("backup", help="back up or restore save games")
    bk.add_argument("action", choices=("list", "create", "restore"))
    bk.add_argument("id", nargs="?")
    bk.add_argument("-y", "--yes", action="store_true", help="do not ask")

    ex = sub.add_parser("export", help="print a shareable modlist")
    ex.add_argument("--text", action="store_true", help="readable text, not JSON")
    ex.add_argument("--all", action="store_true", help="include disabled mods")

    pr = sub.add_parser("profile", help="save and restore sets of enabled mods")
    pr.add_argument("action", choices=("list", "save", "load", "delete"))
    pr.add_argument("name", nargs="?")

    args = ap.parse_args()

    handlers = {"path": cmd_path, "install": cmd_install,
                "uninstall": cmd_uninstall, "new": cmd_new,
                "source": cmd_source, "profile": cmd_profile,
                "check": cmd_check, "backup": cmd_backup, "export": cmd_export,
                "enable": cmd_toggle, "disable": cmd_toggle}
    if args.cmd in handlers:
        try:
            sys.exit(handlers[args.cmd](args))
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            sys.exit(str(exc))

    if args.cmd == "doctor":
        issues, actions = doctor(args.fix)
        if not issues:
            print("No UE4SS conflict detected -- the experimental build owns dwmapi.dll.")
        else:
            print("Issues found:")
            for i in issues:
                print(f"  ! {i}")
            if actions:
                print("\nRepairs applied:")
                for a in actions:
                    print(f"  - {a}")
                print("\nRelaunch Palworld for these to take effect.")
            else:
                print("\nRun with --fix to repair.")
        return

    try:
        paths = discover()
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    data = build(paths)
    (HERE / "manifest.json").write_text(json.dumps(data, indent=2), "utf8")
    print(report(data))
    print(f"\nmanifest.json written -> {HERE / 'manifest.json'}")
    if (ml := write_modlist(paths, data)):
        print(f"modlist.txt written  -> {ml}   (in-game panel reads this)")
    if getattr(args, "html", False):
        out = HERE / "dashboard.html"
        out.write_text(html(data), "utf8")
        print(f"dashboard.html written -> {out}")


if __name__ == "__main__":
    main()
