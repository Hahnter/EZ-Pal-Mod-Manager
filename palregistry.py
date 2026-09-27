#!/usr/bin/env python3
"""Where each mod came from, and which sets of mods you run together.

Three things live here:

  registry   per-mod metadata -- source site, mod id, version, notes. Used to
             build a link back to the mod page and to warn about mods old
             enough to predate the current game build.
  receipts   what a managed install actually wrote, so it can be removed again
             without guessing.
  profiles   named sets of enabled mods, for switching between (say) a heavily
             modded solo save and a near-vanilla one for multiplayer.

All three are stored under %LOCALAPPDATA%\\PalModManager so they survive an
upgrade of the program and are never lost to a one-file build's temp folder.
An existing registry.json sitting next to the source is imported once.
"""

import json
import re
from datetime import datetime, date
from pathlib import Path

import palpaths

SOURCES = ("Nexus", "CurseForge", "local", "manual", "unknown")

NEXUS_URL = "https://www.nexusmods.com/palworld/mods/{id}"
CURSEFORGE_SEARCH = "https://www.curseforge.com/palworld/search?search={name}"

# Nexus names its downloads  <Name>-<modid>-<version with dots as dashes>-<epoch>.<ext>
# e.g. PalMiniMap-3915-2-3-8-1754251234.zip -> id 3915, version 2.3.8
NEXUS_ARCHIVE = re.compile(
    r"^(?P<name>.+?)-(?P<id>\d{2,7})-(?P<ver>\d+(?:-[0-9A-Za-z]+)*)-(?P<ts>\d{9,13})$"
)
# Plainer archives: Name-1.2.3.zip / Name_v1.2.3.zip
PLAIN_VERSION = re.compile(r"^(?P<name>.+?)[-_ ]v?(?P<ver>\d+(?:\.\d+){1,3}[A-Za-z]?)$")


def _file(name):
    return palpaths.data_dir() / name


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
def _legacy_registry():
    """The hand-maintained registry.json that shipped beside the source."""
    old = palpaths.bundled_dir() / "registry.json"
    if not old.is_file():
        old = Path(__file__).resolve().parent / "registry.json"
    if old.is_file():
        try:
            data = json.loads(old.read_text("utf8"))
            return {k: v for k, v in data.items()
                    if not k.startswith("_") and isinstance(v, dict)}
        except (ValueError, OSError):
            pass
    return {}


def load_registry():
    f = _file("registry.json")
    if f.is_file():
        try:
            data = json.loads(f.read_text("utf8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if not k.startswith("_")}
        except ValueError:
            pass
    # First run after the move: adopt whatever was maintained by hand.
    seeded = _legacy_registry()
    if seeded:
        save_registry(seeded)
    return seeded


def save_registry(reg):
    _file("registry.json").write_text(json.dumps(reg, indent=2, sort_keys=True)
                                      + "\n", "utf8")


def get(name):
    return load_registry().get(name, {})


def set_entry(mod, **fields):
    """Update one mod's metadata. None values clear a field.

    The mod is named positionally as `mod`, not `name`, so that callers can
    pass a display `name=` field through **fields without colliding with it.
    """
    reg = load_registry()
    entry = dict(reg.get(mod, {}))
    for k, v in fields.items():
        if v is None:
            entry.pop(k, None)
        else:
            entry[k] = v
    # A Nexus id is enough to rebuild the link, so keep them in step.
    if entry.get("source") == "Nexus" and entry.get("id") and not entry.get("url"):
        entry["url"] = NEXUS_URL.format(id=entry["id"])
    reg[mod] = entry
    save_registry(reg)
    return entry


def forget(name):
    reg = load_registry()
    if reg.pop(name, None) is not None:
        save_registry(reg)


def web_link(url):
    """The link if it is a web page, else None.

    Links reach this app from people: pasted into a field, or read from a
    shared modlist or an imported registry. Handing Windows anything else to
    "open" is how a link becomes a program launch -- a local .exe path, a
    file:// URL, or a custom protocol handler all open without a browser.
    """
    from urllib.parse import urlsplit
    text = str(url or "").strip()
    if any(c.isspace() or ord(c) < 32 for c in text):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return text


def url_for(name, entry=None):
    """A link to the mod's page, if we can work one out."""
    e = entry if entry is not None else get(name)
    if e.get("url"):
        return e["url"]
    if e.get("source") == "Nexus" and e.get("id"):
        return NEXUS_URL.format(id=e["id"])
    if e.get("source") == "CurseForge":
        return CURSEFORGE_SEARCH.format(name=e.get("name") or name)
    return None


def describe_source(name, entry=None):
    """Short label for the UI: 'Nexus 3915', 'CurseForge', 'you', ..."""
    e = entry if entry is not None else get(name)
    src = e.get("source")
    if src == "Nexus":
        return f"Nexus {e['id']}" if e.get("id") else "Nexus"
    if src == "local":
        return "your mod"
    if src in ("CurseForge", "manual"):
        return src
    return "source unknown"


def age_note(entry):
    """Human note about how old a release is, or None.

    Palworld's builds move fast enough that a mod more than a year old is a
    genuine suspect when something stops working.
    """
    released = entry.get("released")
    if not released:
        return None
    try:
        when = datetime.fromisoformat(str(released))
    except ValueError:
        return None
    days = (datetime.now() - when).days
    if days < 0:
        return None
    if days > 365:
        return f"{days // 365}y {(days % 365) // 30}m old - may predate the current build"
    if days > 180:
        return f"{days // 30} months old"
    return f"{days} days old"


# --------------------------------------------------------------------------
# guessing metadata from a downloaded file
# --------------------------------------------------------------------------
def from_filename(path):
    """Read what a download's own name reveals about where it came from.

    Nexus encodes the mod id and version in every archive it serves, which is
    the difference between a registry someone has to maintain by hand and one
    that fills itself in.
    """
    p = Path(path)
    stem = p.stem
    out = {}

    if m := NEXUS_ARCHIVE.match(stem):
        out = {
            "source": "Nexus",
            "id": int(m.group("id")),
            "name": m.group("name").replace("_", " ").strip(),
            "version": m.group("ver").replace("-", "."),
            "url": NEXUS_URL.format(id=m.group("id")),
        }
        try:
            ts = int(m.group("ts"))
            ts = ts / 1000 if ts > 10 ** 11 else ts
            out["released"] = datetime.fromtimestamp(ts).date().isoformat()
        except (ValueError, OSError, OverflowError):
            pass
        return out

    # A CurseForge download keeps its folder, not its id.
    lowered = str(p).lower()
    if "curseforge" in lowered or "curse" in lowered:
        out["source"] = "CurseForge"

    if m := PLAIN_VERSION.match(stem):
        out.setdefault("name", m.group("name").replace("_", " ").strip())
        out["version"] = m.group("ver")
    else:
        out.setdefault("name", stem.replace("_", " ").strip())
    out.setdefault("source", "manual")
    return out


def record_install(mod, archive=None, extra=None):
    """Register a mod at install time, keeping anything already known.

    A Nexus filename names its mod page, so it is trusted outright. Any other
    filename only says "not from Nexus" -- it must not overwrite a source and
    link added earlier, or updating a CurseForge mod from a newer zip would
    quietly turn it into an unlinked "manual" one.
    """
    fields = {"installed": date.today().isoformat()}
    if archive:
        guessed = from_filename(archive)
        guessed.pop("name", None)          # folder name wins over file name
        known = get(mod).get("source") not in (None, "unknown")
        if guessed.get("source") != "Nexus" and known:
            guessed.pop("source", None)
        fields.update(guessed)
    if extra:
        fields.update({k: v for k, v in extra.items() if v not in (None, "")})
    return set_entry(mod, **fields)


# --------------------------------------------------------------------------
# install receipts
# --------------------------------------------------------------------------
def _receipts():
    f = _file("receipts.json")
    if f.is_file():
        try:
            data = json.loads(f.read_text("utf8"))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


def save_receipt(name, files, roots=(), shipped=None):
    """Remember every path an install created, so removal is exact.

    `shipped` maps a path to a hash of the file the mod shipped there. That is
    what tells a later update whether the copy on disk is still the mod's own
    or something the user has edited since.
    """
    data = _receipts()
    data[name] = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "files": [str(f) for f in files],
        "roots": [str(r) for r in roots],
        "shipped": {str(k): v for k, v in (shipped or {}).items()},
    }
    _file("receipts.json").write_text(json.dumps(data, indent=2) + "\n", "utf8")


def receipt(name):
    return _receipts().get(name)


def shipped_hashes(name):
    """What the last install of this mod wrote, by path. {} if unknown."""
    return (receipt(name) or {}).get("shipped") or {}


def drop_receipt(name):
    data = _receipts()
    if data.pop(name, None) is not None:
        _file("receipts.json").write_text(json.dumps(data, indent=2) + "\n", "utf8")


# --------------------------------------------------------------------------
# profiles
# --------------------------------------------------------------------------
def _profiles():
    f = _file("profiles.json")
    if f.is_file():
        try:
            data = json.loads(f.read_text("utf8"))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


def profile_names():
    return sorted(_profiles())


def save_profile(name, enabled_names, all_names):
    """Store a named on/off set.

    Both lists are kept: without the full roster, restoring a profile could not
    tell "this mod was off" from "this mod did not exist yet".
    """
    data = _profiles()
    data[name] = {
        "saved": datetime.now().isoformat(timespec="seconds"),
        "enabled": sorted(enabled_names),
        "known": sorted(all_names),
    }
    _file("profiles.json").write_text(json.dumps(data, indent=2) + "\n", "utf8")


def load_profile(name):
    return _profiles().get(name)


def delete_profile(name):
    data = _profiles()
    if data.pop(name, None) is not None:
        _file("profiles.json").write_text(json.dumps(data, indent=2) + "\n", "utf8")
