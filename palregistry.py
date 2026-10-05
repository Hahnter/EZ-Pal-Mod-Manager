#!/usr/bin/env python3
"""Where each mod came from, and which sets of mods you run together.

Three things live here:

  registry   per-mod metadata -- source site, mod id, version, notes. Used to
             build a link back to the mod page and to warn about mods old
             enough to predate the current game build.
  receipts   what a managed install actually wrote, so it can be removed again
             without guessing. Kept per install.
  profiles   named sets of enabled mods, for switching between (say) a heavily
             modded solo save and a near-vanilla one for multiplayer.

The registry is keyed by a mod's name. Receipts and profiles are keyed by its
kind as well (see mod_id), because one name can belong to two mods.

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
# telling mods apart
# --------------------------------------------------------------------------
# A name alone does not pick out one mod. A hybrid mod often ships a Lua mod
# and a PalSchema mod in folders of the same name, and the same mod can be
# installed in the game and in a dedicated server. Registry entries stay keyed
# by name, so both halves and both installs share one page link and one
# description. Whatever acts on files goes by kind and name.
KINDS = ("ue4ss", "pak", "palschema")


def mod_id(kind, name):
    """How one mod of one kind is addressed: 'ue4ss:Hybrid'."""
    return f"{kind}:{name}"


def split_id(text):
    """('palschema', 'Hybrid') for 'palschema:Hybrid'; (None, text) for a name.

    Windows allows no colon in a file or folder name, so a mod's own name is
    never mistaken for one of these.
    """
    kind, sep, name = str(text).partition(":")
    if sep and kind in KINDS and name:
        return kind, name
    return None, str(text)


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
    data = palpaths.read_json(_file("registry.json"))
    if data is not None:
        return {k: v for k, v in data.items() if not k.startswith("_")}
    # First run after the move: adopt whatever was maintained by hand.
    seeded = _legacy_registry()
    if seeded:
        save_registry(seeded)
    return seeded


def save_registry(reg):
    palpaths.write_json(_file("registry.json"), reg, sort_keys=True)


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
# receipts.json is {"version": 2, "installs": {<install key>: {<mod id>: ...}}}.
#
# Version 1 was {<name>: ...}, one list for every install. An update carries
# the files of the previous receipt forward, so installing a mod in a server
# after the game copied the game's paths into the server's receipt, and an
# uninstall from either then deleted both copies. Both halves of a hybrid mod
# shared one receipt in the same way.
RECEIPTS_VERSION = 2


def _write_receipts(data):
    palpaths.write_json(_file("receipts.json"), data)


def _receipts():
    f = _file("receipts.json")
    # A torn or unreadable file is set aside and its .bak used instead, so a
    # crash mid-save can't turn every receipt into an empty list.
    data = palpaths.read_json(f)
    if data is None:
        return {"version": RECEIPTS_VERSION, "installs": {}}
    if isinstance(data.get("version"), int) and isinstance(data.get("installs"), dict):
        return data
    # Version 1, read once and rewritten. The original stays beside it.
    if data:
        palpaths.write_bytes(_file("receipts-v1.json"), f.read_bytes())
    data = _migrate_receipts(data)
    _write_receipts(data)
    return data


def _place(path, name):
    """(install key, kind, root) for a path that a receipt for `name` names.

    Every path an install writes is inside a game folder, at a spot that says
    which kind of mod put it there. `root` is that mod's own folder, or for a
    pak the folder it sits in, as an install records it. None if the path is
    none of those.
    """
    parts = Path(path).parts
    low = [p.lower() for p in parts]
    # The game folder is whatever holds Pal\Binaries or Pal\Content.
    start = next((i for i in range(len(low) - 1)
                  if low[i] == "pal" and low[i + 1] in ("binaries", "content")), None)
    if not start:
        return None
    game = palpaths.install_key(Path(*parts[:start]))
    if low[start:start + 3] == ["pal", "content", "paks"] and len(low) > start + 3:
        return game, "pak", str(Path(*parts[:start + 4]))
    want = str(name).lower()
    # ...\PalSchema\mods\<name> before ...\Mods\<name>, which it also matches.
    for i in range(start, len(low) - 2):
        if (low[i] == "palschema" and low[i + 1] in ("mods", "disabled-mods")
                and low[i + 2] == want):
            return game, "palschema", str(Path(*parts[:i + 3]))
    for i in range(start, len(low) - 1):
        if low[i] == "mods" and low[i + 1] == want:
            return game, "ue4ss", str(Path(*parts[:i + 2]))
    return None


def _migrate_receipts(flat):
    """Version 1 receipts, filed by install and by kind of mod.

    A version 1 receipt can hold files from two installs, or from both halves
    of a hybrid mod. Each path in it is still complete, so where it belongs
    is read from the path, and the receipt is split along those lines.
    """
    installs = {}
    for name, rec in flat.items():
        if not isinstance(rec, dict):
            continue
        groups = {}
        for f in rec.get("files") or []:
            where = _place(f, name)
            if where is None:
                continue
            g = groups.setdefault(where[:2], {"files": [], "roots": [],
                                              "shipped": {}, "own": []})
            g["files"].append(f)
            if where[2] not in g["own"]:
                g["own"].append(where[2])
        for r in rec.get("roots") or []:
            where = _place(r, name)
            if where and where[:2] in groups:
                groups[where[:2]]["roots"].append(r)
        for p, digest in (rec.get("shipped") or {}).items():
            where = _place(p, name)
            if where and where[:2] in groups:
                groups[where[:2]]["shipped"][p] = digest
        for (key, kind), g in groups.items():
            installs.setdefault(key, {})[mod_id(kind, name)] = {
                "when": rec.get("when"), "files": g["files"],
                # A part split away from the receipt's own install has no
                # recorded root; the folder its files are in is that root.
                "roots": g["roots"] or g["own"], "shipped": g["shipped"]}
    return {"version": RECEIPTS_VERSION, "installs": installs}


def _key(game):
    return palpaths.install_key(game if game is not None else palpaths.require_game())


def save_receipt(kind, name, files, roots=(), shipped=None, game=None):
    """Remember every path an install created, so removal is exact.

    One receipt per install and kind of mod: the game and a dedicated server
    keep their own, as do the two halves of a hybrid mod. `game` is the
    install, by default the one in use. `shipped` maps a path to a hash of the
    file the mod shipped there. That is what tells a later update whether the
    copy on disk is still the mod's own or something the user has edited since.
    """
    data = _receipts()
    data["installs"].setdefault(_key(game), {})[mod_id(kind, name)] = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "files": [str(f) for f in files],
        "roots": [str(r) for r in roots],
        "shipped": {str(k): v for k, v in (shipped or {}).items()},
    }
    _write_receipts(data)


def receipt(kind, name, game=None):
    return _receipts()["installs"].get(_key(game), {}).get(mod_id(kind, name))


def shipped_hashes(kind, name, game=None):
    """What the last install of this mod wrote, by path. {} if unknown."""
    return (receipt(kind, name, game) or {}).get("shipped") or {}


def drop_receipt(kind, name, game=None):
    data = _receipts()
    key = _key(game)
    here = data["installs"].get(key, {})
    if here.pop(mod_id(kind, name), None) is not None:
        if not here:
            del data["installs"][key]
        _write_receipts(data)


def receipt_kinds(name, game=None):
    """Each kind of mod called `name` that this install has a receipt for."""
    here = _receipts()["installs"].get(_key(game), {})
    return [k for k in KINDS if mod_id(k, name) in here]


def receipts_for(name):
    """(install key, kind) for every receipt, in any install, of a mod called `name`."""
    return [(key, k) for key, here in _receipts()["installs"].items()
            for k in KINDS if mod_id(k, name) in here]


# --------------------------------------------------------------------------
# profiles
# --------------------------------------------------------------------------
def _profiles():
    return palpaths.read_json(_file("profiles.json")) or {}


def profile_names():
    return sorted(_profiles())


def save_profile(name, enabled_ids, all_ids):
    """Store a named on/off set of mods, each given by mod_id().

    Both lists are kept: without the full roster, restoring a profile could not
    tell "this mod was off" from "this mod did not exist yet".
    """
    data = _profiles()
    data[name] = {
        "saved": datetime.now().isoformat(timespec="seconds"),
        "enabled": sorted(enabled_ids),
        "known": sorted(all_ids),
    }
    palpaths.write_json(_file("profiles.json"), data)


def load_profile(name):
    return _profiles().get(name)


def profile_wants(profile, kind, name):
    """Whether a profile has this mod on: True, False, or None if it never saw it.

    Profiles saved before mods were told apart by kind list plain names. A
    plain name stands for every kind of mod that goes by it.
    """
    known, on = profile.get("known") or [], profile.get("enabled") or []
    for key in (mod_id(kind, name), name):
        if key in known:
            return key in on
    return None


def delete_profile(name):
    data = _profiles()
    if data.pop(name, None) is not None:
        palpaths.write_json(_file("profiles.json"), data)
