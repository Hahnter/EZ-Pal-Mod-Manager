"""Palworld's own mod loader, and the Steam Workshop mods it loads.

Since the v0.7 update Palworld has an official mod loader fed by the Steam
Workshop. Its rules are Pocketpair's, published with their Palworld Mod
Uploader (github.com/pocketpairjp/PalworldModUploader, docs/en/04-Tech.md):

  Mods\\PalModSettings.ini    which Workshop mods are on. The game's own
                              Options > Mod Management menu edits it:
                                [PalModSettings]
                                bGlobalEnableMod=True
                                WorkshopRootDir=...\\workshop\\content\\1623730
                                ActiveModList=<PackageName>   (one per mod)
  <WorkshopRootDir>\\<item id>\\Info.json
                              one per subscribed item: ModName, PackageName,
                              Version, Author, Thumbnail, Dependencies, and the
                              InstallRules that say where its files go.

When the game starts it copies each switched-on package into the game folder:

  UE4SS      Mods\\NativeMods\\UE4SS          a UE4SS of the game's own
  Lua        Mods\\NativeMods\\UE4SS\\Mods\\<PackageName>
  PalSchema  Mods\\NativeMods\\UE4SS\\Mods\\PalSchema\\mods
  LogicMods  Pal\\Content\\Paks\\LogicMods
  Paks       Pal\\Content\\Paks\\~WorkshopMods

Those copies are the loader's. This module reads packages and settings, and
switches mods the way Mod Management does, by their ActiveModList line. It
never moves, renames or deletes anything the loader put in the game folder.
"""

import json
import re
from pathlib import Path

import palpaths

SETTINGS = Path("Mods") / "PalModSettings.ini"
SECTION = "PalModSettings"
NATIVE_UE4SS = Path("Mods") / "NativeMods" / "UE4SS"
WORKSHOP_PAKS = Path("Pal") / "Content" / "Paks" / "~WorkshopMods"
CLIENT_APPID = "1623730"
ITEM_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={id}"

# What each install type is called in the app.
TYPE_LABELS = {"UE4SS": "UE4SS", "Lua": "script mod", "PalSchema": "PalSchema mod",
               "LogicMods": "blueprint pak", "Paks": "pak"}
# Pocketpair's uploader accepts a type in any case; the loader's names are these.
_TYPES = {t.lower(): t for t in TYPE_LABELS}
# Install types whose start UE4SS writes to its log.
LOGGED = {"Lua", "LogicMods"}
# Pocketpair's uploader allows letters and digits only. Anything else is left
# to the game's own menu rather than written into its settings by the app.
SAFE_PACKAGE = re.compile(r"^[A-Za-z0-9]+$")

_KEY = re.compile(r"^\s*[+.]?\s*([A-Za-z_][\w]*)\s*=\s*(.*?)\s*$")
_SECTION = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*$")


# --------------------------------------------------------------------------
# PalModSettings.ini
# --------------------------------------------------------------------------
def settings_file(game):
    return Path(game) / SETTINGS


def _decode(raw):
    """(text, encoding) for an ini Unreal wrote: ANSI, UTF-8 or UTF-16 with a BOM."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _encode(text, encoding):
    return text.encode(encoding)


def _lines(game):
    f = settings_file(game)
    raw = f.read_bytes() if f.is_file() else b""
    text, encoding = _decode(raw)
    return text.splitlines(keepends=True), encoding


def _ours(section):
    """[PalModSettings], as Pocketpair documents it, or the same section named
    the way Unreal names a config class's: [/Script/Pal.PalModSettings]."""
    name = section.strip().lower()
    return name == SECTION.lower() or name.endswith("." + SECTION.lower())


def _in_section(lines):
    """Which lines are in [PalModSettings]. A file with no section header at
    all is read as if everything were in it."""
    has_header = any(_SECTION.match(ln) for ln in lines)
    inside, out = not has_header, []
    for ln in lines:
        m = _SECTION.match(ln)
        if m:
            inside = _ours(m.group(1))
            out.append(False)
            continue
        out.append(inside and not ln.lstrip().startswith((";", "#")))
    return out


def read_settings(game):
    """{exists, global_on, root, active[]} from Mods\\PalModSettings.ini."""
    out = {"exists": settings_file(game).is_file(), "global_on": False,
           "root": None, "active": []}
    if not out["exists"]:
        return out
    try:
        lines, _ = _lines(game)
    except OSError:
        return out
    for ln, inside in zip(lines, _in_section(lines)):
        m = _KEY.match(ln) if inside else None
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip().strip('"')
        if key == "bglobalenablemod":
            out["global_on"] = value.lower() in ("true", "1", "yes")
        elif key == "workshoprootdir":
            out["root"] = value or None
        elif key == "activemodlist" and value:
            out["active"].append(value)
    return out


def _write(game, lines, encoding):
    f = settings_file(game)
    f.parent.mkdir(parents=True, exist_ok=True)
    palpaths.write_bytes(f, _encode("".join(lines), encoding))


def _eol(lines):
    return "\r\n" if not lines or any(ln.endswith("\r\n") for ln in lines) else "\n"


def _set_lines(game, key, values):
    """Make [PalModSettings] hold exactly `values` for `key`, in place.

    Existing lines for the key keep their place; new ones go after the last
    of them, or at the end of the section. Everything else in the file is
    written back exactly as it was read.
    """
    lines, encoding = _lines(game)
    eol = _eol(lines)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += eol
    want, keep, last = list(values), [], None
    for ln, inside in zip(lines, _in_section(lines)):
        m = _KEY.match(ln) if inside else None
        if m and m.group(1).lower() == key.lower():
            value = m.group(2).strip().strip('"')
            match = next((w for w in want if w.lower() == value.lower()), None)
            if match is None:                 # a value no longer wanted
                last = len(keep) - 1
                continue
            want.remove(match)
        keep.append(ln)
        if m and m.group(1).lower() == key.lower():
            last = len(keep) - 1
    if want:
        if last is None:
            # After the section's last line, or a new section at the end.
            ends = [i for i, (ln, inside) in enumerate(zip(keep, _in_section(keep)))
                    if inside or (_SECTION.match(ln) and _ours(_SECTION.match(ln).group(1)))]
            if ends:
                last = ends[-1]
            else:
                keep.append(f"[{SECTION}]{eol}")
                last = len(keep) - 1
        keep[last + 1:last + 1] = [f"{key}={v}{eol}" for v in want]
    _write(game, keep, encoding)


def set_active(game, package, on):
    """Switch one Workshop mod on or off, as Mod Management does."""
    settings = read_settings(game)
    if on and not settings["exists"]:
        # Switching a mod on means wanting mods on. A file made here would
        # otherwise say nothing about it.
        set_global(game, True)
    others, seen = [], {package.lower()}
    for a in settings["active"]:                 # once each, in their order
        if a.lower() not in seen:
            seen.add(a.lower())
            others.append(a)
    _set_lines(game, "ActiveModList", others + ([package] if on else []))


def set_global(game, on):
    _set_lines(game, "bGlobalEnableMod", ["True" if on else "False"])


def set_root(game, folder):
    _set_lines(game, "WorkshopRootDir", [str(Path(folder))])


# --------------------------------------------------------------------------
# packages
# --------------------------------------------------------------------------
def workshop_root(game, settings=None, server=False):
    """The folder subscribed Workshop items are in, or None.

    PalModSettings.ini names it once the game has run with a subscription.
    Until then a Steam install's own library folder is where Steam puts them.
    A dedicated server only ever uses the folder its settings name.
    """
    settings = settings or read_settings(game)
    if settings["root"]:
        p = Path(settings["root"])
        return p if p.is_dir() else None
    g = Path(game)
    if not server and g.parent.name.lower() == "common" \
            and g.parent.parent.name.lower() == "steamapps":
        p = g.parent.parent / "workshop" / "content" / CLIENT_APPID
        if p.is_dir():
            return p
    return None


def inside(path, folder):
    """Whether `path` is inside `folder` once resolved. A package is a
    stranger's folder; a target of ../../ must not reach outside it."""
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False


def _targets(folder, rule):
    out = []
    for t in rule["Targets"]:
        rel = t.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        rel = rel.strip("/")
        p = folder / rel if rel not in ("", ".") else folder
        if inside(p, folder):
            out.append(p)
    return out


def _paks(paths):
    out = []
    for p in paths:
        if p.is_file() and p.suffix.lower() == ".pak":
            out.append(p)
        elif p.is_dir():
            out += sorted(f for f in p.rglob("*.pak") if f.is_file())
    return out


def _string_end(text, i):
    """Where the JSON string that starts at text[i] ends, just past its quote."""
    j, n = i + 1, len(text)
    while j < n and text[j] != '"':
        j += 2 if text[j] == "\\" else 1
    return min(j + 1, n)


def _without_comments(text):
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            j = _string_end(text, i)
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _without_trailing_commas(text):
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            j = _string_end(text, i)
            out.append(text[i:j])
            i = j
            continue
        if text[i] == ",":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _loose_json(raw):
    """Parse JSON the way Pocketpair's tools do: comments and trailing commas
    are allowed. Anything else wrong with it is still an error."""
    text, _ = _decode(raw)
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(_without_trailing_commas(_without_comments(text)))


def _text(value, most):
    """A field shown in the app: text or a number, on one line, cut to size.
    Info.json is written by strangers and nothing else checks it."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = " ".join(str(value).split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def _fields(obj):
    """A JSON object's keys in lower case: the uploader reads them in any case."""
    return {str(k).lower(): v for k, v in obj.items()} if isinstance(obj, dict) else {}


def _strings(value):
    """A list of non-empty strings from a JSON value that should be one."""
    if isinstance(value, str):
        value = [value]
    return [str(x).strip() for x in value or [] if str(x).strip()] \
        if isinstance(value, (list, tuple, str)) else []


def packages(game, settings=None, server=False):
    """Every subscribed Workshop item, read from its Info.json.

    Install rules are filtered to the ones for this kind of install: the game
    uses the rules without IsServer, a dedicated server the ones with it.
    """
    settings = settings or read_settings(game)
    root = workshop_root(game, settings, server)
    if root is None:
        return []
    active = {a.lower() for a in settings["active"]}
    out = []
    try:
        folders = sorted(d for d in root.iterdir() if d.is_dir())
    except OSError:
        return []
    for d in folders:
        info_file = d / "Info.json"
        if not info_file.is_file():
            continue
        item = {"id": d.name, "path": d, "package": "", "title": d.name,
                "version": "", "author": "", "deps": [], "types": [],
                "rules": [], "thumbnail": None, "error": None,
                "listed": False, "for_other": False, "switchable": False,
                "url": ITEM_URL.format(id=d.name) if d.name.isdigit() else None}
        try:
            info = _fields(_loose_json(info_file.read_bytes()))
        except (OSError, ValueError):
            info = {}
        package = info.get("packagename")
        if not isinstance(package, str) or not package.strip():
            item["error"] = "its Info.json can't be read"
            out.append(item)
            continue
        item["package"] = package.strip()
        item["switchable"] = bool(SAFE_PACKAGE.match(item["package"]))
        item["title"] = _text(info.get("modname"), 100) or item["package"]
        item["version"] = _text(info.get("version"), 40)
        item["author"] = _text(info.get("author"), 60)
        item["deps"] = _strings(info.get("dependencies"))
        rules = []
        for r in info.get("installrule") or []:
            r = _fields(r)
            kind = str(r.get("type") or "").strip()
            if kind:
                rules.append({"Type": _TYPES.get(kind.lower(), kind),
                              "IsServer": r.get("isserver") is True,
                              "Targets": _strings(r.get("targets"))})
        mine = [r for r in rules if r["IsServer"] == server]
        item["rules"] = mine
        item["types"] = sorted({r["Type"] for r in mine})
        item["for_other"] = bool(rules) and not mine
        thumb = info.get("thumbnail")
        thumb = thumb.strip() if isinstance(thumb, str) else ""
        if thumb and inside(d / thumb, d) and (d / thumb).is_file():
            item["thumbnail"] = d / thumb
        item["listed"] = item["package"].lower() in active
        out.append(item)
    return out


def files_of(item, kind):
    """The package's own files for one install type: its pak files for Paks
    and LogicMods, its target folders otherwise."""
    targets = [p for r in item["rules"] if r["Type"] == kind
               for p in _targets(item["path"], r)]
    return _paks(targets) if kind in ("Paks", "LogicMods") else targets


def managed(items):
    """Names of what the loader puts in the game folder, by place, for the
    other scans to leave alone: script mod folders in its UE4SS's Mods,
    PalSchema mod folders, and blueprint and content pak file stems."""
    out = {"lua": set(), "palschema": set(), "logic": set(), "paks": set()}
    for it in items:
        if it["error"]:
            continue
        name = it["package"].casefold()
        if "Lua" in it["types"]:
            out["lua"].add(name)
        if "UE4SS" in it["types"]:
            # UE4SS's own mods (BPModLoaderMod and the rest) come with it.
            for target in files_of(it, "UE4SS"):
                mods = target / "Mods" if (target / "Mods").is_dir() else target
                if mods.is_dir():
                    out["lua"].update(c.name.casefold() for c in mods.iterdir()
                                      if c.is_dir())
        if "PalSchema" in it["types"]:
            out["palschema"].add(name)
            for target in files_of(it, "PalSchema"):
                if target.is_dir():
                    out["palschema"].update(c.name.casefold() for c in target.iterdir()
                                            if c.is_dir())
        for kind, key in (("LogicMods", "logic"), ("Paks", "paks")):
            if kind in it["types"]:
                out[key].update(p.name.split(".pak")[0].casefold()
                                for p in files_of(it, kind))
    return out


# --------------------------------------------------------------------------
# the loader's own UE4SS
# --------------------------------------------------------------------------
def runtime(game):
    """The UE4SS the official loader deploys: where it is and its log.

    `dll` is False when UE4SS.dll isn't there, which is also how players who
    run their own UE4SS switch the Workshop copy off: by renaming that file.
    """
    d = Path(game) / NATIVE_UE4SS
    return {"dir": d, "mods": d / "Mods", "log": d / "UE4SS.log",
            "dll": (d / "UE4SS.dll").is_file()}


def menu(server=False, short=False):
    """Where Workshop mods are switched on and off: the game's own menu, or
    on a dedicated server, which has none, its settings file."""
    if server:
        return "this server's Mods\\PalModSettings.ini"
    return "Mod Management" if short else "Palworld's Options > Mod Management"


# What the Workshop's UE4SS does when the game next starts.
RUNS = "runs"                  # it loads
PENDING = "pending"            # switched on, and the game installs it first
MODS_OFF = "mods off"          # Mod Management has every mod off
SWITCHED_OFF = "switched off"  # Mod Management has it off
NO_DLL = "no dll"              # on, installed, and its UE4SS.dll is gone
NONE = "none"                  # there is no Workshop UE4SS here


def scan(game, server=False):
    """The official loader's whole picture of this install, read once.

    `ue4ss` says what its UE4SS does next start, and `runs` whether it loads.
    `own` names what it puts in folders of its own; `shared` what it puts in
    folders mods from elsewhere use too, which only counts while switched on.
    """
    settings = read_settings(game)
    items = packages(game, settings, server)
    rt = runtime(game)
    ue = [it for it in items if not it["error"] and "UE4SS" in it["types"]]
    if not rt["dll"] and not ue:
        state = NONE
    elif not settings["global_on"]:
        state = MODS_OFF
    elif ue and not any(it["listed"] for it in ue):
        state = SWITCHED_OFF
    elif rt["dll"]:
        state = RUNS
    elif not rt["dir"].is_dir():
        state = PENDING
    else:
        state = NO_DLL
    return {"settings": settings, "items": items, "runtime": rt,
            "root": workshop_root(game, settings, server), "server": server,
            "ue4ss": state, "runs": state in (RUNS, PENDING),
            "own": managed(items),
            "shared": managed([it for it in items if it["listed"]])}
