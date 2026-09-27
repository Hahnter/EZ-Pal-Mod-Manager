#!/usr/bin/env python3
"""Keeping a working mod setup working.

Four things break a modded Palworld that was fine yesterday, and each has a
check here:

  patches     Steam updated the game. Mods built against the old build may
              now fail -- and the only way to know is to launch once.
  conflicts   two paks replace the same asset. Only one wins, silently.
  hotkeys     two UE4SS mods listen for the same key.
  saves       a broken mod corrupts a world. Backups make that recoverable.

It also launches the game and notices when it closes, so the result of a play
session shows up without anyone pressing Refresh.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import palpaths

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ==========================================================================
# patches: which build did each mod last load on?
# ==========================================================================
def build_info(game):
    """Identity of the installed game build.

    Steam's appmanifest buildid is authoritative. Without Steam (Xbox, a
    copied install) the executable's size and timestamp stand in for it.
    """
    game = Path(game)
    manifest = palpaths.steam_manifest(game)
    exe = next((game / e for e in (palpaths.GAME_EXE, *palpaths.SERVER_EXES)
                if (game / e).is_file()), None)
    try:
        st = exe.stat() if exe else None
    except OSError:
        st = None

    if manifest and manifest.get("buildid"):
        return {"id": manifest["buildid"],
                "label": f"build {manifest['buildid']}",
                "patched": manifest.get("updated") or (st.st_mtime if st else 0),
                "source": "steam"}
    if st:
        when = datetime.fromtimestamp(st.st_mtime)
        return {"id": f"files-{st.st_size}-{int(st.st_mtime)}",
                "label": f"game files of {when:%Y-%m-%d}",
                "patched": st.st_mtime, "source": "files"}
    return {"id": "unknown", "label": "unknown build", "patched": 0,
            "source": "none"}


def _state_file():
    return palpaths.data_dir() / "state.json"


def _load_state():
    f = _state_file()
    if f.is_file():
        try:
            data = json.loads(f.read_text("utf8"))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


def _save_state(state):
    _state_file().write_text(json.dumps(state, indent=2) + "\n", "utf8")


def _install_key(game):
    return str(Path(game)).lower().rstrip("\\/")


EARLIER = "earlier"      # a run we saw, on a build that was already replaced


def observe(paths, data):
    """Attribute the latest UE4SS run to a build, and report what that means.

    A run is on the current build if UE4SS.log was written after the build
    was installed. Each mod confirmed loaded in that run is remembered as
    working on that build, so after the next patch the app can say which mods
    have not been seen working since -- and, once the game has been run on the
    new build, which ones worked before the patch and don't now.
    """
    game = paths["game"]
    cur = data.get("build") or build_info(game)
    state = _load_state()
    installs = state.setdefault("installs", {})
    st = installs.setdefault(_install_key(game), {})
    verified = st.setdefault("verified", {})
    labels = st.setdefault("labels", {})
    labels[cur["id"]] = cur["label"]

    log_path = paths["log"]
    try:
        log_mtime = log_path.stat().st_mtime if log_path.is_file() else None
    except OSError:
        log_mtime = None

    loaded = ([m["name"] for m in data["ue4ss_mods"] if m["loaded"]]
              + [p["name"] for p in data["pak_mods"] if p["loaded"]])

    if log_mtime and log_mtime != st.get("run_seen"):
        on_current = log_mtime >= (cur["patched"] or 0)
        ran_on = cur["id"] if on_current else (
            st.get("ran_on") if st.get("ran_on") not in (None, cur["id"])
            else EARLIER)
        st["ran_on"] = ran_on
        st["run_seen"] = log_mtime
        for name in loaded:
            verified[name] = ran_on
    _save_state(state)

    # What needs saying.
    loggable_on = ([m["name"] for m in data["ue4ss_mods"]
                    if m["enabled"] and not m["builtin"]]
                   + [p["name"] for p in data["pak_mods"]
                      if not p["disabled"] and p["folder"] == "LogicMods"])
    content_on = [p["name"] for p in data["pak_mods"]
                  if not p["disabled"] and p["folder"] != "LogicMods"]
    loaded_set = set(loaded)

    def label_of(build_id):
        if build_id == EARLIER:
            return "an earlier build"
        return labels.get(build_id, f"build {build_id}")

    ran_on = st.get("ran_on")
    updated = bool(ran_on) and ran_on != cur["id"]
    report = {
        "build": cur["label"],
        "updated": updated and bool(loggable_on or content_on),
        "last_run_build": label_of(ran_on) if ran_on else None,
        "unverified": [n for n in loggable_on if verified.get(n) != cur["id"]]
                      if updated else [],
        "content_unverifiable": len(content_on) if updated else 0,
        # Worked on an older build, did not load on this one.
        "regressed": {n: label_of(verified[n]) for n in loggable_on
                      if not updated and n not in loaded_set
                      and verified.get(n) not in (None, cur["id"])},
    }
    return report


# ==========================================================================
# pak conflicts: two mods replacing the same asset
# ==========================================================================
# An asset is split across several files (.uasset + .uexp + .ubulk); a
# conflict is about the asset, not the halves.
ASSET_PARTS = re.compile(r"\.(uasset|uexp|ubulk|uptnl|umap)$", re.I)
PATCH_PAK = re.compile(r"_p$", re.I)


def _assets(pak):
    base = (pak.get("mount") or "").replace("\\", "/")
    while base.startswith("../"):
        base = base[3:]
    base = base.strip("/")
    out = set()
    for f in pak.get("files", []):
        rel = f.replace("\\", "/").lstrip("/")
        full = f"{base}/{rel}" if base else rel
        out.add(ASSET_PARTS.sub("", full.lower()))
    return out


def pak_priority(name):
    """Sort key: the higher key is the pak Unreal reads a shared asset from.

    Unreal gives patch paks -- file names ending in _P -- a large bump in
    read order, which is why mods are told to use that suffix. Between two
    paks with the same order the mount order decides, and paks mount in
    descending name order, so the name that sorts last is read first. That
    second rule is the engine default; treat the result as a likely winner.
    """
    return (1 if PATCH_PAK.search(name) else 0, name.lower())


# A handful of blueprints are the game's own scaffolding: the player, the
# controller that drives it, the state the server keeps about it. A mod that
# ships its own copy replaces the whole thing, so it carries whatever the game
# had when the mod was built. After a patch that is a common way to crash on
# load, and two mods that both replace one cannot work together at all.
CORE_ASSETS = {
    "bp_palplayercharacter": "the player character",
    "bp_palplayercontroller": "the player controller",
    "bp_palplayerstate": "the player state",
    "bp_palgamemode": "the game mode",
    "bp_palgamestate": "the game state",
    "bp_palgameinstance": "the game instance",
}


def core_overrides(pak_mods):
    """Mods replacing one of the game's core blueprints. {mod: [what]}"""
    out = {}
    for p in pak_mods:
        hit = []
        for f in p.get("files", []):
            stem = Path(f.replace("\\", "/")).name.lower()
            stem = ASSET_PARTS.sub("", stem)
            what = CORE_ASSETS.get(stem)
            if what and what not in hit:
                hit.append(what)
        if hit:
            out[p["name"]] = hit
    return out


def pak_conflicts(pak_mods):
    """Every pair of paks that replace at least one of the same assets."""
    assets = {p["name"]: _assets(p) for p in pak_mods if p.get("files")}
    enabled = {p["name"]: not p["disabled"] for p in pak_mods}
    names = sorted(assets)

    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = assets[a] & assets[b]
            if not shared:
                continue
            winner = max((a, b), key=pak_priority)
            loser = b if winner == a else a
            # Certain only when exactly one of the two is a patch pak.
            sure = bool(PATCH_PAK.search(a)) != bool(PATCH_PAK.search(b))
            pairs.append({
                "mods": [a, b], "winner": winner, "loser": loser,
                "sure": sure, "assets": len(shared),
                "examples": sorted(shared)[:3],
                "live": enabled.get(a, False) and enabled.get(b, False),
            })

    by_mod = {}
    for idx, c in enumerate(pairs):
        for n in c["mods"]:
            by_mod.setdefault(n, []).append(idx)

    # A content pak without the _P suffix sits below the game's own paks in
    # read order, so it can add new assets but not replace existing ones.
    weak = [p["name"] for p in pak_mods
            if p["folder"] == "~mods" and not PATCH_PAK.search(p["name"])
            and p.get("expected_folder") == "~mods"]
    return {"pairs": pairs, "by_mod": by_mod, "no_patch_suffix": weak}


# ==========================================================================
# hotkeys
# ==========================================================================
LITERAL_BIND = re.compile(
    r"(?:RegisterKeyBind(?:Async)?|\b[bB]ind\w*)\s*\(\s*Key\.([A-Z0-9_]+)"
    r"\s*(?:,\s*\{([^}]*)\})?")
LUA_STRING_FIELD = re.compile(r"""\b(\w+)\s*=\s*["']([^"']*)["']""")
LUA_TABLE_FIELD = re.compile(r"\b(\w+)\s*=\s*\{([^}]*)\}")
INI_LINE = re.compile(r"^\s*([A-Za-z_][\w .-]*?)\s*[=:]\s*(.*?)\s*$")
INI_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")

KEYISH_NAME = re.compile(r"(?i)(key|bind|hotkey|shortcut)")
MODIFIER_NAME = re.compile(r"(?i)(modifier|mods$)")
KEYISH_SECTION = re.compile(r"(?i)(key|bind|hotkey|shortcut|input|control)")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{0,30}$")
NOT_A_KEY = {"NONE", "NULL", "NIL", "FALSE", "TRUE", "DEFAULT", "DISABLED",
             "OFF", "ON", "UNBOUND", "EMPTY"}

MODIFIERS = {
    "CTRL": "Ctrl", "CONTROL": "Ctrl", "LEFTCONTROL": "Ctrl", "LCTRL": "Ctrl",
    "RIGHTCONTROL": "Ctrl", "ALT": "Alt", "LEFTALT": "Alt", "LALT": "Alt",
    "RIGHTALT": "Alt", "SHIFT": "Shift", "LEFTSHIFT": "Shift",
    "LSHIFT": "Shift", "RIGHTSHIFT": "Shift",
}


def _norm(token):
    return re.sub(r"[\s_]", "", token).upper()


def _combo(key, mods):
    """(id, label) for a key plus modifiers, order-independent."""
    mods = sorted({MODIFIERS.get(_norm(m), m.title()) for m in mods if m})
    k = _norm(key)
    return "+".join(mods + [k]), "+".join(mods + [key.upper()])


def _parse_value(raw):
    """A config value -> [(key, modifiers)]. Handles 'CTRL+F5' and lists."""
    raw = re.split(r"\s[;#]|\s--", raw, maxsplit=1)[0].strip().strip("\"'")
    out = []
    for part in re.split(r"[,|]", raw):
        tokens = [t.strip() for t in part.split("+") if t.strip()]
        if not tokens or not all(TOKEN.match(t) for t in tokens):
            continue
        key, mods = tokens[-1], tokens[:-1]
        if _norm(key) in NOT_A_KEY or _norm(key).startswith("GAMEPAD"):
            continue
        out.append((key, mods))
    return out


# Parsed results per file, reused until the file changes. Rescans happen on
# every apply and whenever a mod folder changes; re-reading a 2,000-line
# main.lua each time made hotkeys the slowest part of a scan.
_KEY_CACHE = {}
KEY_FILE_SUFFIXES = (".lua", ".ini", ".txt", ".cfg")
SKIP_KEY_FILES = ("enabled.txt", "modlist.txt", "readme.txt", "license.txt")


def _mod_keys(mod_path):
    """[(combo_id, label, file)] for one UE4SS mod."""
    root = Path(mod_path)
    found = []
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            low = name.lower()
            if not low.endswith(KEY_FILE_SUFFIXES) or low in SKIP_KEY_FILES:
                continue
            f = Path(dirpath) / name
            try:
                st = f.stat()
            except OSError:
                continue
            stamp = (st.st_mtime_ns, st.st_size)
            hit = _KEY_CACHE.get(str(f))
            if hit and hit[0] == stamp:
                found.extend(hit[1])
                continue
            keys = _file_keys(f, root)
            _KEY_CACHE[str(f)] = (stamp, keys)
            found.extend(keys)
    return found


def _file_keys(f, root):
    """Hotkeys declared in a single file."""
    found = []
    name = f.name.lower()
    try:
        text = f.read_text("utf8", "replace")
    except OSError:
        return found
    rel = f.relative_to(root).as_posix()

    if f.suffix.lower() == ".lua":
        code = "\n".join(ln for ln in text.splitlines()
                         if not ln.lstrip().startswith("--"))
        for m in LITERAL_BIND.finditer(code):
            mods = re.findall(r"ModifierKey\.(\w+)", m.group(2) or "")
            found.append((*_combo(m.group(1), mods), rel))

        # Config tables: ToggleKey = "F6", ToggleModifiers = {"Ctrl"}
        if any(w in name for w in ("config", "setting", "option")):
            tables = {k: v for k, v in LUA_TABLE_FIELD.findall(code)}
            for field, value in LUA_STRING_FIELD.findall(code):
                if not KEYISH_NAME.search(field) or MODIFIER_NAME.search(field):
                    continue
                prefix = re.sub(r"(?i)(keys?|bind|hotkey|shortcut)$", "", field)
                mod_src = next((v for k, v in tables.items()
                                if k.lower().startswith(prefix.lower())
                                and MODIFIER_NAME.search(k)), "") if prefix else ""
                extra = re.findall(r"""["'](\w+)["']""", mod_src)
                for key, mods in _parse_value(value):
                    found.append((*_combo(key, mods + extra), rel))
        return found

    # ini / txt / cfg
    section = ""
    for line in text.splitlines():
        if line.lstrip().startswith((";", "#", "//")):
            continue
        sm = INI_SECTION.match(line)
        if sm:
            section = sm.group(1)
            continue
        m = INI_LINE.match(line)
        if not m:
            continue
        field, value = m.group(1).strip(), m.group(2)
        if MODIFIER_NAME.search(field):
            continue
        if KEYISH_NAME.search(field) or KEYISH_SECTION.search(section):
            for key, mods in _parse_value(value):
                found.append((*_combo(key, mods), rel))
    return found




def keybind_report(ue4ss_mods):
    """Hotkeys each mod registers, and every key claimed by two mods.

    Reads literal Key.X bindings in Lua, key fields in Lua config tables, and
    ini/txt entries named like a key or under a [keys]-style section. A mod
    that builds its keys some other way is listed as unreadable rather than
    assumed to be clash-free.
    """
    per_mod, unreadable = {}, []
    enabled = {m["name"]: m["enabled"] for m in ue4ss_mods}
    for m in ue4ss_mods:
        keys = _mod_keys(m["path"])
        if keys:
            per_mod[m["name"]] = sorted({(cid, lbl) for cid, lbl, _ in keys})
        elif not m["builtin"]:
            try:
                calls = any("RegisterKeyBind" in f.read_text("utf8", "replace")
                            for f in Path(m["path"]).rglob("*.lua"))
            except OSError:
                calls = False
            if calls:
                unreadable.append(m["name"])

    owners = {}
    for name, keys in per_mod.items():
        for cid, lbl in keys:
            owners.setdefault(cid, {"label": lbl, "mods": set()})["mods"].add(name)

    clashes = []
    for cid, o in sorted(owners.items()):
        if len(o["mods"]) < 2:
            continue
        mods = sorted(o["mods"])
        on = [n for n in mods if enabled.get(n)]
        clashes.append({"key": o["label"], "mods": mods, "enabled": on,
                        "live": len(on) >= 2})

    by_mod = {}
    for c in clashes:
        for n in c["mods"]:
            others = [o for o in c["mods"] if o != n]
            by_mod.setdefault(n, []).append({"key": c["key"], "with": others,
                                             "live": c["live"]})
    return {"keys": {n: [lbl for _, lbl in k] for n, k in per_mod.items()},
            "clashes": clashes, "by_mod": by_mod, "unreadable": unreadable}


# ==========================================================================
# save backups
# ==========================================================================
def save_dir(game):
    """Where this install keeps its worlds, or None if we can't find it."""
    game = Path(game)
    if palpaths.kind_of(game) == "server":
        d = game / "Pal" / "Saved" / "SaveGames"
        return d if d.is_dir() else None

    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    if "xboxgames" in str(game).lower():
        for d in sorted((local / "Packages").glob("PocketpairInc.Palworld_*")):
            wgs = d / "SystemAppData" / "wgs"
            if wgs.is_dir():
                return wgs
    d = local / "Pal" / "Saved" / "SaveGames"
    return d if d.is_dir() else None


def _backup_root(game):
    tag = hashlib.sha1(_install_key(game).encode()).hexdigest()[:10]
    d = palpaths.data_dir() / "backups" / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tree_size(path):
    total = count = 0
    for f in Path(path).rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
                count += 1
            except OSError:
                pass
    return total, count


def setup_fingerprint(data):
    """Identifies a mod setup: which mods are on, on which game build."""
    on = sorted([m["name"] for m in data["ue4ss_mods"]
                 if m["enabled"] and not m["builtin"]]
                + [p["name"] for p in data["pak_mods"] if not p["disabled"]]
                + [f"schema:{s['name']}" for s in data.get("palschema_mods", [])
                   if s["enabled"]])
    raw = json.dumps([on, (data.get("build") or {}).get("id")])
    return hashlib.sha1(raw.encode()).hexdigest()[:12], on


def backup_saves(game, reason="manual", data=None, keep_auto=10):
    src = save_dir(game)
    if src is None:
        raise FileNotFoundError("Couldn't find this install's SaveGames folder.")
    root = _backup_root(game)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest, n = root / stamp, 1
    while dest.exists():
        n += 1
        dest = root / f"{stamp}-{n}"
    shutil.copytree(src, dest / "SaveGames")

    size, count = _tree_size(dest / "SaveGames")
    fingerprint, mods = setup_fingerprint(data) if data else (None, [])
    meta = {"id": dest.name, "when": datetime.now().isoformat(timespec="seconds"),
            "reason": reason, "setup": fingerprint, "mods": mods,
            "build": (data or {}).get("build", {}).get("label"),
            "source": str(src), "size": size, "files": count}
    (dest / "backup.json").write_text(json.dumps(meta, indent=2) + "\n", "utf8")
    if reason == "auto":
        _prune(game, keep_auto)
    return meta


def list_backups(game):
    out = []
    for d in _backup_root(game).iterdir():
        f = d / "backup.json"
        if d.is_dir() and f.is_file():
            try:
                meta = json.loads(f.read_text("utf8"))
                meta["path"] = str(d)
                out.append(meta)
            except ValueError:
                continue
    return sorted(out, key=lambda m: m.get("when", ""), reverse=True)


def _prune(game, keep):
    autos = [b for b in list_backups(game) if b.get("reason") == "auto"]
    for b in autos[keep:]:
        shutil.rmtree(b["path"], ignore_errors=True)


def needs_auto_backup(game, data):
    """True when this mod setup has never been backed up before a launch."""
    fingerprint, _ = setup_fingerprint(data)
    return not any(b.get("setup") == fingerprint for b in list_backups(game)
                   if b.get("reason") in ("auto", "manual"))


def restore_backup(game, backup_id):
    """Put a backup back. What is there now is backed up first.

    The live folder is renamed aside rather than deleted, and only removed
    once the copy has fully succeeded -- a failed restore leaves you where
    you started.
    """
    if game_running(game):
        raise RuntimeError("Close Palworld before restoring saves.")
    src = _backup_root(game) / backup_id / "SaveGames"
    if not src.is_dir():
        raise FileNotFoundError(f"Backup {backup_id} is missing its files.")
    target = save_dir(game)
    if target is None:
        raise FileNotFoundError("Couldn't find this install's SaveGames folder.")

    safety = backup_saves(game, reason="before restore")
    aside = target.with_name(target.name + ".pmm-restoring")
    if aside.exists():
        shutil.rmtree(aside)
    target.rename(aside)
    try:
        shutil.copytree(src, target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        aside.rename(target)
        raise
    shutil.rmtree(aside, ignore_errors=True)
    return safety


# ==========================================================================
# launching and watching the game
# ==========================================================================
CLIENT_PROCESSES = ("palworld-win64-shipping.exe",)
SERVER_PROCESSES = ("palserver-win64-shipping-cmd.exe",
                    "palserver-win64-shipping.exe",
                    "palserver-win64-test-cmd.exe", "palserver-win64-test.exe")


def _process_names():
    try:
        res = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return set()
    names = set()
    for line in res.stdout.splitlines():
        if line.startswith('"'):
            names.add(line[1:line.find('"', 1)].lower())
    return names


def game_running(game):
    wanted = (SERVER_PROCESSES if palpaths.kind_of(game) == "server"
              else CLIENT_PROCESSES)
    return bool(_process_names() & set(wanted))


def launch(game):
    """Start the game (or server). Returns how it was started."""
    game = Path(game)
    manifest = palpaths.steam_manifest(game)
    if manifest:
        os.startfile(f"steam://rungameid/{manifest['appid']}")
        return "Steam"
    server = palpaths.kind_of(game) == "server"
    for exe in (("PalServer.exe",) if server else ("Palworld.exe",)):
        if (game / exe).is_file():
            subprocess.Popen([str(game / exe)], cwd=str(game))
            return exe
    raise FileNotFoundError(
        "Couldn't start this install directly. Launch it the usual way -- "
        "the app will still notice when it closes.")
