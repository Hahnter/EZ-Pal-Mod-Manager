#!/usr/bin/env python3
"""Where Palworld is, and where our own data goes.

The game folder used to be a constant in palmods.py, which meant the tool only
ever worked on the machine it was written on. It is now discovered, validated
and remembered:

    PALWORLD_PATH  ->  environment override, for a second install or a test
    settings.json  ->  a path the user picked, if it is still valid
    Steam          ->  libraryfolders.vdf across every library, appid 1623730
    Xbox           ->  <drive>\\XboxGames\\Palworld\\Content
    brute force    ->  the handful of paths installers actually use

Our own files (settings, registry, manifest, install receipts, profiles) live
in %LOCALAPPDATA%\\PalModManager. They cannot live next to the program: the
release is a PyInstaller one-file build, so the folder holding the script at
runtime is a temp directory that is deleted on exit.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

STEAM_APPID = "1623730"
SERVER_APPID = "2394010"

# Relative to the game root. Present in both the Steam and Xbox layouts, which
# is what makes one validator enough for both.
GAME_EXE = Path("Pal/Binaries/Win64/Palworld-Win64-Shipping.exe")

# The dedicated server has the same Pal/ layout -- and the same UE4SS, pak and
# LogicMods folders -- but a different executable. Its name has changed across
# releases, so every known spelling is accepted.
SERVER_EXES = tuple(Path("Pal/Binaries/Win64") / n for n in (
    "PalServer-Win64-Shipping-Cmd.exe",
    "PalServer-Win64-Shipping.exe",
    "PalServer-Win64-Test-Cmd.exe",
    "PalServer-Win64-Test.exe",
))


# --------------------------------------------------------------------------
# our own storage
# --------------------------------------------------------------------------
def data_dir():
    """Writable folder for everything this tool generates.

    Never the program folder -- when frozen, that is an unpacked temp dir.
    PMM_DATA_DIR overrides it, which keeps a test run out of the real one.
    """
    override = os.environ.get("PMM_DATA_DIR")
    if override:
        d = Path(override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "PalModManager"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_dir():
    """Folder holding read-only files shipped with the program."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# crash-safe files
# --------------------------------------------------------------------------
def backup_of(path):
    """Where a save keeps the version it replaced: <name>.bak."""
    p = Path(path)
    return p.with_name(p.name + ".bak")


def _replace(src, dst):
    # Windows refuses to rename over a file another program has open -- an
    # antivirus scan, the search indexer -- usually only for a moment.
    for wait in (0.05, 0.1, 0.2, 0.4, None):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if wait is None:
                raise
            time.sleep(wait)


def write_bytes(path, data):
    """Replace a file so that it is never left half-written.

    A plain write cut off by a crash, a power cut or an antivirus lock leaves
    a truncated file, and a store that reads that as empty then saves the
    emptiness back over everything it held. Here the new bytes go to a temp
    file beside the old one and are flushed to disk, the old file is kept as
    <name>.bak, and one rename swaps the new file in. Interrupted anywhere,
    the file is all old or all new.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=path.parent)
    try:
        with open(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.is_file():
            shutil.copyfile(path, backup_of(path))
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text(path, text, newline=None):
    """write_bytes for text. `newline` means what it does to open(): None
    writes the platform's line endings, "" writes the text as given."""
    if newline is None:
        newline = os.linesep
    if newline not in ("", "\n"):
        text = text.replace("\n", newline)
    write_bytes(path, text.encode("utf8"))


def write_json(path, data, indent=2, sort_keys=False):
    write_text(path, json.dumps(data, indent=indent, sort_keys=sort_keys) + "\n")


def read_json(path):
    """A JSON store's contents (a dict), or None if there is no usable copy.

    A file that doesn't parse is never treated as simply empty: the next save
    would write that emptiness over whatever it held. It is moved aside as
    <name>.corrupt-<time>, and the <name>.bak from the save before is put back
    in its place if that one is whole.
    """
    path = Path(path)
    if not path.is_file():
        return None
    for f in (path, backup_of(path)):
        if not f.is_file():
            break
        raw = f.read_bytes()
        try:
            data = json.loads(raw)          # bytes: a BOM or UTF-16 is fine too
        except ValueError:
            data = None
        if isinstance(data, dict):
            if f != path:
                write_bytes(path, raw)      # put the good copy back
            return data
        _set_aside(f)
    return None


def _set_aside(path):
    """Keep an unreadable file as <name>.corrupt-<time>, out of harm's way."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest, n = path.with_name(f"{path.name}.corrupt-{stamp}"), 1
    while dest.exists():
        n += 1
        dest = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
    _replace(path, dest)
    return dest


SETTINGS_FILE = "settings.json"

DEFAULTS = {
    "game_path": None,
    "confirm_apply": True,      # ask before writing toggles
    "watch_folder": True,       # re-scan when the mod folders change on disk
    "last_install_dir": None,
    "installs": [],             # every install the user has pointed us at
    "auto_backup": True,        # back up saves before a new mod setup launches
}


def load_settings():
    out = dict(DEFAULTS)
    data = read_json(data_dir() / SETTINGS_FILE) or {}
    out.update({k: v for k, v in data.items() if k in DEFAULTS})
    return out


def save_settings(settings):
    merged = load_settings()
    merged.update(settings)
    write_json(data_dir() / SETTINGS_FILE, merged)
    return merged


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def kind_of(path):
    """"client" for the game, "server" for a dedicated server, else None."""
    if not path:
        return None
    p = Path(path)
    try:
        if (p / GAME_EXE).is_file():
            return "client"
        if any((p / e).is_file() for e in SERVER_EXES):
            return "server"
    except OSError:
        pass
    return None


def validate(path):
    """Return (ok, message) for a candidate game or dedicated-server folder."""
    if not path:
        return False, "No folder given."
    p = Path(path)
    if not p.is_dir():
        return False, "That folder does not exist."
    kind = kind_of(p)
    if kind == "client":
        return True, "Palworld found."
    if kind == "server":
        return True, "Palworld dedicated server found."
    return False, ("No Palworld-Win64-Shipping.exe or PalServer executable "
                   "under Pal\\Binaries\\Win64.")


def normalise(path):
    """Snap a nearby folder onto the real game root, or return None.

    Users drop us in Win64, in Paks, in steamapps, or in the Steam library
    root. All of those are one unambiguous hop from the answer.
    """
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    if p.is_file():
        p = p.parent

    # The folder itself, or any parent of it that looks like the game root.
    for cand in (p, *p.parents):
        if kind_of(cand):
            return cand

    # Or a child: steamapps\common, a library root, XboxGames.
    for child in ("Palworld", "steamapps/common/Palworld", "Palworld/Content",
                  "XboxGames/Palworld/Content", "common/Palworld",
                  "PalServer", "steamapps/common/PalServer", "common/PalServer"):
        cand = p / child
        if kind_of(cand):
            return cand
    return None


# --------------------------------------------------------------------------
# Steam
# --------------------------------------------------------------------------
def _steam_roots():
    """Every Steam install root we can find, most authoritative first."""
    roots = []

    try:
        import winreg
        for hive, key, name in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam",
             "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, name)[0]))
            except OSError:
                continue
    except ImportError:
        pass

    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        roots.append(Path(guess))

    seen, out = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def _library_paths(steam_root):
    """Paths of every Steam library, read from libraryfolders.vdf.

    The file moved between Steam versions, so both locations are read. The
    format is loose enough that a targeted regex beats a real VDF parser here.
    """
    libs = [steam_root]
    for rel in ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf"):
        f = steam_root / rel
        if not f.is_file():
            continue
        try:
            text = f.read_text("utf8", "replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def _steam_candidates():
    found = []
    for steam in _steam_roots():
        for lib in _library_paths(steam):
            apps = lib / "steamapps"
            for appid, default, source in (
                (STEAM_APPID, "Palworld", "Steam"),
                (SERVER_APPID, "PalServer", "Steam dedicated server"),
            ):
                manifest = apps / f"appmanifest_{appid}.acf"
                folder = default
                if manifest.is_file():
                    # Honour installdir; it is not always the default name.
                    try:
                        m = re.search(r'"installdir"\s*"([^"]+)"',
                                      manifest.read_text("utf8", "replace"))
                        if m:
                            folder = m.group(1)
                    except OSError:
                        pass
                found.append((apps / "common" / folder, source))
    return found


# --------------------------------------------------------------------------
# Xbox / Game Pass
# --------------------------------------------------------------------------
def _drives():
    out = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        p = Path(f"{letter}:\\")
        try:
            if p.is_dir():
                out.append(p)
        except OSError:
            continue
    return out


def _xbox_candidates():
    # The WindowsApps copy is locked down and cannot be modded; the writable
    # install that people actually mod is the XboxGames one.
    return [(d / "XboxGames" / "Palworld" / "Content", "Xbox")
            for d in _drives()]


def _loose_candidates():
    out = []
    for d in _drives():
        for rel in ("SteamLibrary/steamapps/common/Palworld",
                    "Games/Palworld", "Palworld", "PalServer",
                    "SteamLibrary/steamapps/common/PalServer",
                    "Program Files (x86)/Steam/steamapps/common/Palworld",
                    "Program Files (x86)/Steam/steamapps/common/PalServer"):
            out.append((d / rel, "folder scan"))
    return out


def detect(extra=None):
    """Every valid Palworld install we can find, best guess first.

    Returns [{path, source}]. Cheap: a handful of stat calls, no tree walk.
    """
    cands = []
    if extra:
        cands.append((Path(extra), "your choice"))
    cands += _steam_candidates() + _xbox_candidates() + _loose_candidates()

    seen, out = set(), []
    for path, source in cands:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        if validate(path)[0]:
            out.append({"path": path, "source": source})
    return out


# --------------------------------------------------------------------------
# the resolved game folder
# --------------------------------------------------------------------------
_game = None


def game(auto=True):
    """The game folder in use, or None if we have not found one.

    Resolution order: an explicit set_game() this session, the saved setting,
    then auto-detection. A saved path that no longer validates is ignored
    rather than used -- the game may have been moved or uninstalled.
    """
    global _game
    if _game is not None:
        return _game

    # An override that does not touch the saved setting -- for a second
    # install, a test run, or a portable copy.
    env = os.environ.get("PALWORLD_PATH")
    if env and validate(env)[0]:
        _game = Path(env)
        return _game

    saved = load_settings().get("game_path")
    if saved and validate(saved)[0]:
        _game = Path(saved)
        return _game

    if auto:
        hits = detect()
        if hits:
            _game = hits[0]["path"]
            save_settings({"game_path": str(_game)})
            return _game
    return None


def set_game(path, remember=True):
    """Point the tool at a game folder. Returns (ok, message)."""
    global _game
    fixed = normalise(path) or Path(path) if path else None
    ok, msg = validate(fixed)
    if not ok:
        return False, msg
    _game = Path(fixed)
    if remember:
        known = [i for i in load_settings().get("installs") or []
                 if str(i).lower() != str(_game).lower()]
        save_settings({"game_path": str(_game),
                       "installs": [str(_game)] + known[:9]})
    return True, f"Using {_game}"


def label(path):
    """Short human name for an install: 'Palworld (Steam)', 'Dedicated server'."""
    p = Path(path)
    kind = kind_of(p)
    if kind == "server":
        return "Dedicated server"
    if "xboxgames" in str(p).lower():
        return "Palworld (Xbox)"
    if steam_manifest(p):
        return "Palworld (Steam)"
    return "Palworld"


def known_installs():
    """Everything we can switch to: detected installs plus remembered ones."""
    out, seen = [], set()
    remembered = [Path(i) for i in load_settings().get("installs") or []]
    for path, source in ([(p, "remembered") for p in remembered]
                         + [(h["path"], h["source"]) for h in detect()]):
        key = str(path).lower().rstrip("\\/")
        if key in seen or not validate(path)[0]:
            continue
        seen.add(key)
        out.append({"path": Path(path), "source": source,
                    "kind": kind_of(path), "label": label(path)})
    return out


# --------------------------------------------------------------------------
# Steam build information
# --------------------------------------------------------------------------
def steam_manifest(path):
    """{appid, buildid, updated} from the install's Steam appmanifest, or None.

    Steam rewrites buildid on every patch, which is the most reliable signal
    there is that the game changed under a set of mods. The manifest lives in
    the library's steamapps folder, two levels above the install.
    """
    p = Path(path)
    apps = p.parent.parent
    for appid in (STEAM_APPID, SERVER_APPID):
        f = apps / f"appmanifest_{appid}.acf"
        if not f.is_file():
            continue
        try:
            text = f.read_text("utf8", "replace")
        except OSError:
            continue
        inst = re.search(r'"installdir"\s*"([^"]+)"', text)
        if inst and inst.group(1).lower() != p.name.lower():
            continue
        build = re.search(r'"buildid"\s*"(\d+)"', text)
        updated = re.search(r'"LastUpdated"\s*"(\d+)"', text)
        return {"appid": appid,
                "buildid": build.group(1) if build else None,
                "updated": int(updated.group(1)) if updated else None}
    return None


def require_game():
    g = game()
    if g is None:
        raise FileNotFoundError(
            "Palworld was not found automatically. Point the tool at your "
            "install folder (the one containing Pal\\Binaries\\Win64)."
        )
    return g
