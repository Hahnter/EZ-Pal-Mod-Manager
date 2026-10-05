#!/usr/bin/env python3
"""Install a mod from an archive, a folder, or a bare .pak -- and remove it again.

Palworld mods are distributed with no agreed layout. The same archive might
contain a UE4SS Lua mod, a blueprint pak, a content pak, a PalSchema patch, or
several of those at once, nested under anything from nothing at all to the full
``Pal/Binaries/Win64/ue4ss/Mods/`` path. Installing by hand means knowing which
of four folders each piece belongs in, and getting it wrong is the single most
common reason a mod "doesn't work".

So: inspect first, decide where every piece goes, show that plan, and only then
write. Every file written is recorded, which is what makes a clean uninstall
possible instead of a hunt through four folders.
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import palmedia
from paltext import plural
import palmods
import palpaths
import palregistry

ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}

# Kinds, in the order they are reported.
UE4SS_MOD = "UE4SS mod"
PALSCHEMA = "PalSchema"
LOGIC_PAK = "blueprint pak"
CONTENT_PAK = "content pak"

# Junk that some archives carry and nothing should install.
SKIP_NAMES = {"__macosx", ".ds_store", "thumbs.db", "desktop.ini"}


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------
# unpacking
# --------------------------------------------------------------------------
def _seven_zip():
    """7-Zip, if it is installed -- the only way to read .7z and .rar."""
    for guess in (r"C:\Program Files\7-Zip\7z.exe",
                  r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if Path(guess).is_file():
            return guess
    return shutil.which("7z") or shutil.which("7za")


def can_read(path):
    """Whether we can open this file at all. (ok, reason)"""
    p = Path(path)
    if p.is_dir() or p.suffix.lower() == ".pak":
        return True, ""
    suf = p.suffix.lower()
    if suf == ".zip":
        return True, ""
    if suf in (".7z", ".rar"):
        if _seven_zip():
            return True, ""
        return False, (f"{suf} archives need 7-Zip installed. Extract it "
                       f"yourself and install the folder instead.")
    return False, f"Not a mod archive ({suf or 'no extension'})."


# An archive is a stranger's file. Big Palworld mods (model swaps) run to a
# couple of GB unpacked; anything far past that, or a file that inflates
# thousands of times over, is a zip bomb and would fill the disk.
MAX_UNPACKED = 8 * 1024 ** 3
MAX_FILES = 20000
MAX_RATIO = 1000


def inside(path, folder):
    """Whether `path` really is within `folder` once resolved.

    Comparing strings is not enough: C:\\game\\Win64evil starts with
    C:\\game\\Win64 and is not inside it.
    """
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False


def _check_sizes(members):
    """(size, compressed) pairs for every file -> raises if it's a bomb."""
    total = 0
    for n, (size, packed) in enumerate(members, 1):
        if n > MAX_FILES:
            raise InstallError(f"That archive holds more than {MAX_FILES} "
                               f"files. No Palworld mod is that big.")
        total += size
        if total > MAX_UNPACKED:
            raise InstallError("That archive would unpack to more than "
                               f"{MAX_UNPACKED // 1024 ** 3} GB. No Palworld "
                               "mod is that big, so it wasn't opened.")
        if packed and size > 10 * 1024 ** 2 and size / packed > MAX_RATIO:
            raise InstallError("A file in that archive expands to more than "
                               f"{MAX_RATIO} times its packed size, which is "
                               "what a zip bomb does. It wasn't opened.")


def _safe_extract_zip(src, dest):
    """Extract, refusing any member that would land outside dest."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(src) as z:
        files = [m for m in z.infolist() if not m.is_dir()]
        _check_sizes((m.file_size, m.compress_size) for m in files)
        for member in files:
            name = member.filename.replace("\\", "/")
            if Path(name).is_absolute() or ".." in Path(name).parts \
                    or ":" in name:
                continue                      # zip-slip; silently dropped
            target = dest / name
            if not inside(target, dest):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as fsrc, open(target, "wb") as fdst:
                # The header's size can lie; stop at what it promised.
                left = member.file_size
                while True:
                    block = fsrc.read(min(65536, left + 1))
                    if not block:
                        break
                    left -= len(block)
                    if left < 0:
                        raise InstallError(f"{name} unpacks to more than its "
                                           f"archive says. It wasn't opened.")
                    fdst.write(block)


def _check_unpacked(root):
    """After 7-Zip: nothing outside the folder, no links, nothing huge.

    7-Zip is a separate program with its own rules. What it left behind is
    checked here rather than trusted.
    """
    root = Path(root).resolve()
    sizes = []
    for p in root.rglob("*"):
        if p.is_symlink() or (os.name == "nt" and _is_junction(p)):
            raise InstallError(f"{p.name} in that archive is a link to "
                               f"somewhere else on disk. It wasn't installed.")
        if not inside(p, root):
            raise InstallError("That archive tried to write outside its "
                               "folder. It wasn't installed.")
        if p.is_file():
            sizes.append((p.stat().st_size, 0))
    _check_sizes(sizes)


def _is_junction(p):
    try:
        return bool(os.lstat(p).st_file_attributes & 0x400)   # reparse point
    except (OSError, AttributeError):
        return False


def unpack(path, into):
    """Put the contents of an archive / folder / bare pak into `into`."""
    p = Path(path)
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)

    if p.is_dir():
        shutil.copytree(p, into / p.name, dirs_exist_ok=True)
        return into
    if p.suffix.lower() == ".pak":
        shutil.copy2(p, into / p.name)
        return into
    if p.suffix.lower() == ".zip":
        _safe_extract_zip(p, into)
        return into

    exe = _seven_zip()
    if not exe:
        raise InstallError(can_read(p)[1])
    res = subprocess.run([exe, "x", str(p), f"-o{into}", "-y", "-bso0", "-bsp0"],
                         capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if res.returncode != 0:
        raise InstallError(f"7-Zip could not read that archive:\n{res.stderr.strip()[:400]}")
    _check_unpacked(into)
    return into


# --------------------------------------------------------------------------
# working out what is in there
# --------------------------------------------------------------------------
def _iter_files(root):
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        parts = [s.lower() for s in p.relative_to(root).parts]
        if any(s in SKIP_NAMES for s in parts):
            continue
        yield p


def _ue4ss_roots(root):
    """Directories that are themselves a UE4SS mod.

    The signature is the one UE4SS itself looks for: Scripts/main.lua for a Lua
    mod, dlls/main.dll for a C++ one.
    """
    found = {}
    for p in _iter_files(root):
        rel = p.relative_to(root)
        parts = [s.lower() for s in rel.parts]
        if len(parts) >= 2 and parts[-2:] == ["scripts", "main.lua"]:
            found[p.parent.parent] = "Lua"
        elif len(parts) >= 2 and parts[-2:] == ["dlls", "main.dll"]:
            found.setdefault(p.parent.parent, "C++")
    return found


def _palschema_roots(root):
    """Folders shipped as a PalSchema patch: .../PalSchema/mods/<name>/..."""
    found = {}
    for p in _iter_files(root):
        parts = [s.lower() for s in p.relative_to(root).parts]
        if "palschema" in parts:
            i = parts.index("palschema")
            if i + 2 < len(parts) and parts[i + 1] == "mods":
                found.setdefault(p.relative_to(root).parts[i + 2],
                                 Path(root, *p.relative_to(root).parts[:i + 3]))
    return found


def _declared_folder(rel_parts):
    """The folder an archive says a pak belongs in, if it says so at all."""
    lowered = [s.lower() for s in rel_parts]
    for want, label in (("logicmods", "LogicMods"), ("~mods", "~mods")):
        if want in lowered:
            return label
    return None


def inspect(source, game_paths=None):
    """Unpack to a temp folder and work out what would be installed where.

    Returns a plan:
        {tmp, source, components[], files[], warnings[], skipped[]}
    where each component is one installable thing with its own destination.
    The caller is responsible for calling discard(plan) or apply(plan).
    """
    src = Path(source)
    ok, why = can_read(src)
    if not ok:
        raise InstallError(why)

    paths = game_paths or palmods.discover()
    tmp = Path(tempfile.mkdtemp(prefix="pmm-"))
    try:
        unpack(src, tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    game = palmods.game_root()
    dest_ue4ss = paths["ue4ss_mods"]
    dest_logic = game / "Pal" / "Content" / "Paks" / "LogicMods"
    dest_mods = game / "Pal" / "Content" / "Paks" / "~mods"
    _, dest_schema, schema_off = palmods.palschema_dirs(paths)

    components, claimed, warnings = [], set(), []

    # --- UE4SS mods ----------------------------------------------------
    for mod_root, kind in _ue4ss_roots(tmp).items():
        # An archive of the mod's *insides* has no folder to take a name from.
        name = mod_root.name if mod_root != tmp else src.stem
        files = [p for p in _iter_files(mod_root)]
        claimed.update(files)
        components.append({
            "kind": UE4SS_MOD, "name": name, "lang": kind,
            "dest": dest_ue4ss / name, "root": mod_root,
            "files": [(p, dest_ue4ss / name / p.relative_to(mod_root))
                      for p in files],
            "note": f"{kind} mod",
        })

    # --- PalSchema -----------------------------------------------------
    for name, schema_root in _palschema_roots(tmp).items():
        files = [p for p in _iter_files(schema_root) if p not in claimed]
        if not files:
            continue
        claimed.update(files)
        components.append({
            "kind": PALSCHEMA, "name": name, "lang": "json",
            "dest": dest_schema / name, "root": schema_root,
            # Where its folder is moved to while it is switched off.
            "dest_off": schema_off / name,
            "files": [(p, dest_schema / name / p.relative_to(schema_root))
                      for p in files],
            "note": "PalSchema patch - needs the PalSchema mod installed",
        })

    # --- paks ----------------------------------------------------------
    for p in _iter_files(tmp):
        if p in claimed or p.suffix.lower() not in (".pak", ".ucas", ".utoc"):
            continue
        rel = p.relative_to(tmp)
        stem = p.name.split(".pak")[0]

        if p.suffix.lower() in (".ucas", ".utoc"):
            # Side files of an IoStore pak; they follow their .pak.
            continue

        info = palmods.read_pak(p)
        guessed, desc = palmods.classify_pak(info)
        declared = _declared_folder(rel.parts)
        folder = declared or guessed or "~mods"
        if declared and guessed and declared != guessed:
            warnings.append(
                f"{p.name}: the archive puts it in {declared}, but its contents "
                f"look like a {desc}. Using {declared} - the author's choice.")
        elif not declared and not guessed:
            warnings.append(f"{p.name}: could not read its index; defaulting to ~mods.")

        target_dir = dest_logic if folder == "LogicMods" else dest_mods
        files = [(p, target_dir / p.name)]
        # IoStore paks ship as a trio and are useless split up.
        for side in (".ucas", ".utoc"):
            mate = p.with_suffix(side)
            if mate.is_file():
                files.append((mate, target_dir / mate.name))
                claimed.add(mate)
        claimed.add(p)
        components.append({
            "kind": LOGIC_PAK if folder == "LogicMods" else CONTENT_PAK,
            "name": stem, "lang": f"pak v{info.get('version')}",
            "dest": target_dir, "root": p.parent, "files": files,
            "note": desc if not info.get("error") else info["error"],
        })

    needs_ue4ss = [c["name"] for c in components
                   if c["kind"] in (UE4SS_MOD, LOGIC_PAK, PALSCHEMA)]
    if needs_ue4ss and not palmods.ue4ss_status(paths)["installed"]:
        warnings.append(
            "UE4SS isn't installed in this Palworld, so "
            + ", ".join(needs_ue4ss)
            + " won't load until it is. Content paks work without it.")

    skipped = [p.relative_to(tmp).as_posix()
               for p in _iter_files(tmp) if p not in claimed]
    if not components:
        warnings.append(
            "Nothing recognisable as a Palworld mod was found. A UE4SS mod "
            "needs Scripts/main.lua or dlls/main.dll; otherwise the archive "
            "should contain a .pak.")

    return {
        "tmp": tmp, "source": src, "components": components,
        "warnings": warnings, "skipped": skipped,
        "total_files": sum(len(c["files"]) for c in components),
    }


def conflicts(plan):
    """Existing files a plan would overwrite, per component."""
    out = {}
    for c in plan["components"]:
        hits = [dst for _, dst in c["files"] if dst.exists()]
        if c["kind"] == PALSCHEMA and not c["dest"].exists():
            # Switched off, it is in disabled-mods, and those are the files
            # an update replaces.
            off = [c["dest_off"] / dst.relative_to(c["dest"])
                   for _, dst in c["files"]]
            hits = [p for p in off if p.exists()]
        if hits:
            out[c["name"]] = hits
    return out


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def link_fields(link):
    """Registry fields for a mod page link typed or pasted at install time.

    Returns {} for no link. A link replaces whatever the filename suggested:
    a CurseForge page clears a Nexus ID guessed from the filename.
    """
    link = (link or "").strip()
    if not link:
        return {}
    fields = palmedia.parse_link(link)
    fields.setdefault("source", "manual")
    fields.setdefault("id", None)
    return fields


# Files people edit and expect to keep. A mod's code is not on this list:
# updating a mod is meant to replace its code, and only its settings are
# worth arguing about.
CONFIG_SUFFIXES = {".ini", ".cfg", ".conf", ".json", ".jsonc", ".txt",
                   ".toml", ".yaml", ".yml", ".lua"}
CONFIG_NAME = re.compile(
    r"(^|[_. -])(config|configs|settings|options|prefs|keybinds?|hotkeys?)"
    r"([_. -]|$)", re.I)


def looks_like_config(rel):
    """Whether a file inside a mod is the kind users edit and want kept."""
    rel = Path(str(rel).replace("\\", "/"))
    if rel.suffix.lower() not in CONFIG_SUFFIXES:
        return False
    if any(p.lower() in ("config", "configs", "settings")
           for p in rel.parts[:-1]):
        return True
    return bool(CONFIG_NAME.search(rel.stem))


def _digest(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _keep_users_copy(dst, src, shipped):
    """Whether the file on disk is the user's own work rather than the mod's.

    Known history: the copy on disk differs from what the mod shipped there
    last time, so somebody edited it. No history: keep it if it differs from
    what is arriving, which is the cautious reading.
    """
    was = shipped.get(str(dst))
    now = _digest(dst)
    if now is None:
        return False
    if was:
        return now != was
    return now != _digest(src)


def _as_shipped(folder, dest, shipped):
    """Whether every file in `folder` is exactly what the mod shipped to the
    same place in `dest`, which leaves nothing in it that is the user's own."""
    for f in Path(folder).rglob("*"):
        if f.is_file():
            was = shipped.get(str(dest / f.relative_to(folder)))
            if not was or was != _digest(f):
                return False
    return True


def apply(plan, components=None, enable=True, backup=True, link=None):
    """Install the chosen components. Returns a list of human-readable results.

    Anything overwritten is kept as <file>.pmm-bak, and every file written is
    recorded so uninstall does not have to guess. `link` is the page the mod
    was downloaded from; it applies to every component, since the parts of a
    hybrid mod share one page.
    """
    chosen = components if components is not None else plan["components"]
    page = link_fields(link)
    results, installed = [], []
    for c in chosen:
        written, replaced, kept = [], 0, []
        shipped_before = palregistry.shipped_hashes(c["name"])
        before = [Path(f) for f in
                  (palregistry.receipt(c["name"]) or {}).get("files", [])]
        if c["kind"] == PALSCHEMA and c["dest_off"].is_dir():
            # A switched-off PalSchema mod is in disabled-mods. Installing
            # beside it left two copies that could be switched neither on nor
            # off. It moves back to be updated like any other mod, which keeps
            # your settings in it, and `enable` then decides where it ends up.
            on, off = c["dest"], c["dest_off"]
            if on.exists():
                # Two copies already, left by an earlier version. A copy that
                # is still exactly as the mod shipped holds nothing of yours.
                if _as_shipped(on, on, shipped_before):
                    shutil.rmtree(on)
                elif _as_shipped(off, on, shipped_before):
                    shutil.rmtree(off)
                else:
                    results.append(
                        f"Skipped {c['name']}: it is in both PalSchema\\mods and "
                        f"PalSchema\\{palmods.PALSCHEMA_OFF}. Delete the copy "
                        f"you don't want, then install it again.")
                    continue
            if off.is_dir():
                on.parent.mkdir(parents=True, exist_ok=True)
                off.rename(on)
        shipped = {}
        for src, dst in c["files"]:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shipped[str(dst)] = _digest(src)
            if dst.exists():
                # Your settings survive an update; the new version lands
                # beside them so you can see what changed.
                try:
                    rel = dst.relative_to(c["dest"])
                except ValueError:
                    rel = Path(dst.name)
                if looks_like_config(rel) \
                        and _keep_users_copy(dst, src, shipped_before):
                    fresh = dst.with_name(dst.name + ".new")
                    shutil.copy2(src, fresh)
                    # Both are the mod's files as far as removal is concerned.
                    written.extend([dst, fresh])
                    kept.append(dst.name)
                    continue
                if backup:
                    shutil.copy2(dst, dst.with_suffix(dst.suffix + ".pmm-bak"))
                replaced += 1
            shutil.copy2(src, dst)
            written.append(dst)

        if c["kind"] == UE4SS_MOD:
            # UE4SS reads enabled.txt; without it a fresh mod is inert.
            flag = c["dest"] / "enabled.txt"
            off = c["dest"] / "enabled.txt.disabled"
            if enable:
                if off.is_file():
                    off.unlink()
                if not flag.is_file():
                    flag.write_text("")
                    written.append(flag)
            elif flag.is_file():
                flag.replace(off)

        # An update usually ships fewer files than the last version wrote --
        # and never rewrites enabled.txt. Carry the old receipt's survivors
        # forward, or uninstall leaves them behind and the folder stays.
        for old in before:
            if old.exists() and old not in written:
                written.append(old)
        # Switched off, a PalSchema mod's folder goes to disabled-mods. That
        # comes last, once the survivors are found where the receipt says.
        # The receipt names mods\ either way, as after switching it off later.
        where = c["dest"]
        if c["kind"] == PALSCHEMA and not enable:
            where = c["dest_off"]
            where.parent.mkdir(parents=True, exist_ok=True)
            c["dest"].rename(where)
        palregistry.save_receipt(c["name"], written, roots=[c["dest"]],
                                 shipped=shipped)
        palregistry.record_install(
            c["name"], archive=plan["source"],
            extra={"kind": c["kind"], "installed_from": str(plan["source"])})
        if page:
            palregistry.set_entry(c["name"], **page)
        # A README shipped inside a UE4SS mod's own folder describes it.
        if c["kind"] == UE4SS_MOD and not palmedia.info(c["name"])["description"]:
            readme = palmedia.readme_in(c["dest"])
            if readme:
                try:
                    palmedia.set_description(c["name"], palmedia._read_text(readme))
                except OSError:
                    pass
        results.append(
            f"{c['name']}: {plural(len(written), 'file')} -> {where}"
            + (f"  ({replaced} replaced, backups kept)" if replaced else ""))
        if kept:
            results.append(
                f"Kept your settings in {', '.join(kept)}. The new version of "
                f"{'each' if len(kept) > 1 else 'it'} is beside it as .new")
        installed.append(c)

    # README and pictures that shipped loose in the download are not mod
    # files, but they are exactly the description and screenshots people want.
    if installed and plan.get("skipped"):
        got = palmedia.capture_from_archive([c["name"] for c in installed],
                                            plan["tmp"], plan["skipped"])
        if got["description"] or got["images"]:
            bits = ((["description"] if got["description"] else [])
                    + ([plural(got['images'], 'picture')] if got["images"] else []))
            results.append("Kept from the download: " + " and ".join(bits))
    if page and installed:
        results.append("Linked to " + describe_link(page))
    return results


def describe_link(fields):
    """'Nexus mod 3915', 'its CurseForge page', 'github.com/...'"""
    if fields.get("source") == "Nexus" and fields.get("id"):
        return f"Nexus mod {fields['id']}"
    if fields.get("source") in ("Nexus", "CurseForge"):
        return f"its {fields['source']} page"
    return fields.get("url", "")


def discard(plan):
    shutil.rmtree(plan.get("tmp", ""), ignore_errors=True)


# --------------------------------------------------------------------------
# removal
# --------------------------------------------------------------------------
def uninstall(name, mod_path=None, pak_path=None):
    """Delete a mod. A receipt makes this exact; without one we fall back.

    The fallback only ever removes the mod's own folder or its own .pak, never
    a shared folder -- guessing wrongly here deletes someone else's mod.
    """
    removed, notes = [], []
    rec = palregistry.receipt(name)

    if rec:
        for f in rec.get("files", []):
            p = Path(f)
            # A receipted file may have been renamed since: disabling a mod
            # moves enabled.txt aside, and saving a config leaves a backup.
            # Missing those left the folder non-empty and so undeletable.
            for cand in (p, p.with_suffix(p.suffix + ".disabled"),
                         p.with_suffix(p.suffix + ".pmm-bak"),
                         p.with_suffix(p.suffix + ".bak")):
                try:
                    if cand.is_file():
                        cand.unlink()
                        removed.append(cand)
                except OSError as exc:
                    notes.append(f"could not delete {cand.name}: {exc}")
        # Take the folders too, but only if no files of anyone else's remain.
        # Empty directories left behind by the deletion do not count -- a mod
        # with Scripts/ would otherwise never be fully removed.
        for r in rec.get("roots", []):
            root = Path(r)
            if root.is_dir() and not any(f.is_file() for f in root.rglob("*")):
                shutil.rmtree(root, ignore_errors=True)
            elif root.is_dir():
                notes.append(f"kept {root.name}: files remain that we did not install")
        palregistry.drop_receipt(name)
    else:
        notes.append("no install record - removing what is on disk")
        if mod_path and Path(mod_path).is_dir():
            folder = Path(mod_path)
            removed += [p for p in folder.rglob("*") if p.is_file()]
            shutil.rmtree(folder, ignore_errors=True)
        if pak_path and Path(pak_path).exists():
            p = Path(pak_path)
            for side in (p, p.with_suffix(".ucas"), p.with_suffix(".utoc")):
                if side.is_file():
                    side.unlink()
                    removed.append(side)

    palmedia.forget(name)
    palregistry.forget(name)
    return removed, notes


# --------------------------------------------------------------------------
# scaffolding a mod of your own
# --------------------------------------------------------------------------
TEMPLATE_MAIN = '''\
--[[
  {name} -- a Palworld UE4SS mod.

  Created by EZ Pal Mod Manager. UE4SS loads this once, at startup.
]]

local MOD_NAME = "{name}"
local VERSION  = "0.1.0"

local function log(msg)
    print("[" .. MOD_NAME .. "] " .. tostring(msg) .. "\\n")
end

log(MOD_NAME .. " " .. VERSION .. " loaded")

-- Press F7 to try it. RegisterKeyBind is UE4SS's own API.
RegisterKeyBind(Key.F7, function()
    log("F7 pressed")
end)
'''

TEMPLATE_README = """\
# {name}

A Palworld UE4SS Lua mod.

- `Scripts/main.lua` runs once when the game starts.
- `enabled.txt` must exist for UE4SS to load the mod at all.
- Reload by restarting Palworld; UE4SS has no hot reload.

Logs appear in `Pal/Binaries/Win64/ue4ss/UE4SS.log`, prefixed `[{name}]`.
"""


def scaffold(name, game_paths=None):
    """Create an empty, working UE4SS Lua mod and register it as yours."""
    clean = "".join(ch for ch in name if ch.isalnum() or ch in "_- ").strip()
    if not clean:
        raise InstallError("Give the mod a name.")
    paths = game_paths or palmods.discover()
    dest = paths["ue4ss_mods"] / clean
    if dest.exists():
        raise InstallError(f"A mod folder named {clean} already exists.")

    (dest / "Scripts").mkdir(parents=True)
    (dest / "Scripts" / "main.lua").write_text(
        TEMPLATE_MAIN.format(name=clean), "utf8")
    (dest / "README.md").write_text(TEMPLATE_README.format(name=clean), "utf8")
    (dest / "enabled.txt").write_text("")

    written = [dest / "Scripts" / "main.lua", dest / "README.md",
               dest / "enabled.txt"]
    palregistry.save_receipt(clean, written, roots=[dest])
    palregistry.set_entry(clean, source="local", name=clean, version="0.1.0",
                          released=None, kind=UE4SS_MOD,
                          url=str(dest), note="Created with EZ Pal Mod Manager.")
    return dest


def package(mod_path, out_dir=None):
    """Zip one of your mods for sharing, laid out to extract into the game.

    The result matches how Nexus mods are shipped, so anyone can drop it in.
    """
    src = Path(mod_path)
    if not src.is_dir():
        raise InstallError("That mod is not a folder on disk.")
    out_dir = Path(out_dir or (palpaths.data_dir() / "packaged"))
    out_dir.mkdir(parents=True, exist_ok=True)

    version = (palregistry.get(src.name).get("version") or "0.1.0")
    out = out_dir / f"{src.name}-{version}.zip"
    prefix = f"Pal/Binaries/Win64/ue4ss/Mods/{src.name}"
    media = palmedia.info(src.name)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        names = set()
        for p in sorted(src.rglob("*")):
            if not p.is_file() or p.suffix in (".pmm-bak", ".bak"):
                continue
            arc = f"{prefix}/{p.relative_to(src).as_posix()}"
            names.add(arc.lower())
            z.write(p, arc)
        # The description and pictures written in the app travel with the
        # mod: a README for players, and the images to upload with it.
        if media["description"]:
            readme = f"{prefix}/README.md"
            if readme.lower() in names:
                readme = f"{prefix}/DESCRIPTION.md"
            z.writestr(readme, f"# {src.name}\n\n{media['description']}\n")
        # Pictures added from the mod's own folder are already in the zip.
        # The store names files by a hash of the bytes they came from, so a
        # match means the same picture.
        in_folder = {hashlib.sha1(p.read_bytes()).hexdigest()[:12]
                     for p in src.rglob("*")
                     if p.is_file() and p.suffix.lower() in palmedia.IMAGE_SUFFIXES}
        for i, img in enumerate(media["images"]):
            if img.stem.removeprefix("img-") in in_folder:
                continue
            label = "preview" if img == media["cover"] else f"screenshot-{i + 1}"
            arc = f"{prefix}/images/{label}{img.suffix}"
            if arc.lower() not in names:
                z.write(img, arc)
    return out
