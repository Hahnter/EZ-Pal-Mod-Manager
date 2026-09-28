"""Nexus Mods, through its public API.

Everything here is opt-in. Until someone pastes their personal API key, no
request is ever made to Nexus. With a key:

  updates    each Nexus mod's current version is compared with the one you
             installed. Only mods Nexus reports as changed in the last month
             are asked about again, so a check costs one request plus one per
             changed mod.
  details    the mod's summary, description and main picture can be filled in
             from its Nexus listing instead of being copied over by hand.
  identify   a download whose file name was changed is matched to its mod by
             checksum.
  downloads  the site's "Mod Manager Download" button (an nxm:// link) opens
             here, and Premium members can update a mod in one click.

This is Nexus's own API, used the way their terms ask: requests name the app,
the key is the user's own, and Nexus's rate limits are respected. The site's
pages are never read.

The key is kept in Windows Credential Manager, never in settings.json. It is
only ever sent to api.nexusmods.com; downloads and pictures come from Nexus's
file servers, which are sent nothing but the link Nexus handed out.
"""

import functools
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import palpaths

GAME = "palworld"
API = "https://api.nexusmods.com/v1"
API_HOST = "api.nexusmods.com"
APP_NAME = "EZ Pal Mod Manager"
APP_VERSION = "1.0.0"            # kept equal to VERSION in the in-game main.lua
KEY_PAGE = "https://next.nexusmods.com/settings/api-keys"
MOD_PAGE = "https://www.nexusmods.com/palworld/mods/{id}"
FILES_PAGE = "https://www.nexusmods.com/palworld/mods/{id}?tab=files"

# Files and pictures are served from Nexus's own hosts. Anything else --
# including a download link that redirects somewhere unexpected -- is refused.
FILE_HOST_SUFFIXES = (".nexusmods.com", ".nexus-cdn.com")
TIMEOUT = 30
CHUNK = 64 * 1024
MAX_DOWNLOAD = 4 * 1024 ** 3           # no Palworld mod comes close
MAX_PICTURE = 15 * 1024 ** 2
ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".pak")

# How long an answer is trusted before asking again. A mod Nexus says has
# changed is always asked about again, whatever its age.
MOD_TTL = 24 * 3600
UPDATED_TTL = 15 * 60

# Nexus file categories. Deleted and archived files are never offered as an
# update; old versions only when there is nothing newer to offer.
CURRENT_CATEGORIES = ("MAIN", "UPDATE", "PATCH", "OPTIONAL", "OPTION",
                      "MISCELLANEOUS")

NXM = re.compile(r"^nxm://(?P<game>[\w-]+)/mods/(?P<mod>\d+)/files/(?P<file>\d+)"
                 r"/?(?:\?(?P<query>.*))?$", re.I)


class NexusError(Exception):
    """Anything that stopped a Nexus request, in words worth showing."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# the API key
# --------------------------------------------------------------------------
# Windows Credential Manager holds it where other programs' passwords live:
# encrypted to the Windows account and never written to a file we manage.
# Elsewhere (the tests, a dev machine) it falls back to a file in the data
# folder that only the owner can read.
CRED_TARGET = "EZPalModManager/NexusMods"
KEY_FILE = "nexus-key"


@functools.lru_cache(maxsize=1)
def _credman():
    """ctypes bindings for the three Credential Manager calls, or None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR),
                    ("LastWritten", FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    try:
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
    except OSError:
        return None
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredReadW.restype = wintypes.BOOL
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredWriteW.restype = wintypes.BOOL
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredDeleteW.restype = wintypes.BOOL
    adv.CredFree.argtypes = [ctypes.c_void_p]
    adv.CredFree.restype = None
    return ctypes, CREDENTIAL, adv


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


def _key_file():
    return palpaths.data_dir() / KEY_FILE


def get_key():
    """The stored API key, or None."""
    # For scripting the command line on a machine without a stored key.
    if os.environ.get("PMM_NEXUS_KEY"):
        return os.environ["PMM_NEXUS_KEY"].strip() or None
    cm = _credman()
    if cm:
        ctypes, CREDENTIAL, adv = cm
        p = ctypes.POINTER(CREDENTIAL)()
        if not adv.CredReadW(CRED_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
            return raw.decode("utf-16-le").strip() or None
        finally:
            adv.CredFree(ctypes.cast(p, ctypes.c_void_p))
    try:
        return _key_file().read_text("utf8").strip() or None
    except OSError:
        return None


def set_key(key):
    key = (key or "").strip()
    if not key:
        return clear_key()
    cm = _credman()
    if cm:
        ctypes, CREDENTIAL, adv = cm
        blob = key.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = CRED_TARGET
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "Nexus Mods API key"
        if not adv.CredWriteW(ctypes.byref(cred), 0):
            raise NexusError("Windows wouldn't store the key "
                             f"(error {ctypes.get_last_error()}).")
        return
    f = _key_file()
    f.write_text(key + "\n", "utf8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def clear_key():
    cm = _credman()
    if cm:
        ctypes, _CREDENTIAL, adv = cm
        if not adv.CredDeleteW(CRED_TARGET, CRED_TYPE_GENERIC, 0) \
                and ctypes.get_last_error() != ERROR_NOT_FOUND:
            raise NexusError("Windows wouldn't remove the key.")
    try:
        _key_file().unlink()
    except FileNotFoundError:
        pass
    _cache_set("account", None)


def connected():
    return bool(get_key())


def looks_like_key(text):
    """A personal API key is one long run of base64-ish characters."""
    text = (text or "").strip()
    return 20 <= len(text) <= 400 and re.fullmatch(r"[A-Za-z0-9+/=_\-.]+", text) is not None


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------
def check_url(url, api=False):
    """Refuse anything that isn't HTTPS to Nexus. The API key goes to one host."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise NexusError("That address isn't valid.") from exc
    host = (parts.hostname or "").lower()
    ok = host == API_HOST if api else (
        host == "nexusmods.com" or host.endswith(FILE_HOST_SUFFIXES))
    if parts.scheme != "https" or not ok:
        raise NexusError(f"Refused to connect to {host or url}: only Nexus Mods "
                         "is allowed here.")
    return url


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Each redirect hop is checked like the first request.

    urllib carries every header across a redirect, so a redirect away from the
    API host would hand the key to whoever the redirect names. The API opener
    therefore refuses to leave api.nexusmods.com at all.
    """

    def __init__(self, api):
        self.api = api

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, api=self.api)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_API_OPENER = urllib.request.build_opener(_CheckedRedirects(api=True))
_FILE_OPENER = urllib.request.build_opener(_CheckedRedirects(api=False))


def _headers():
    return {"User-Agent": f"{APP_NAME.replace(' ', '')}/{APP_VERSION}",
            "Application-Name": APP_NAME, "Application-Version": APP_VERSION,
            "Accept": "application/json"}


def _open(url, headers, api):
    """One request. Separated so tests can replace it."""
    if os.environ.get("PMM_NO_NETWORK") == "1":
        raise NexusError("This copy is set not to use the network "
                         "(PMM_NO_NETWORK=1).")
    check_url(url, api=api)
    req = urllib.request.Request(url, headers=headers)
    return (_API_OPENER if api else _FILE_OPENER).open(req, timeout=TIMEOUT)


# The last rate-limit headers seen: shown in the settings window, and what
# stops a big update check from spending a user's whole hourly allowance.
quota = {"hourly": None, "daily": None}


def _api(path, key=None, params=None):
    key = key or get_key()
    if not key:
        raise NexusError("Connect to Nexus Mods first: paste your API key in "
                         "… → Nexus Mods.", code="no-key")
    url = API + path + (("?" + urlencode(params)) if params else "")
    headers = dict(_headers(), apikey=key)
    try:
        with _open(url, headers, api=True) as r:
            for name, slot in (("x-rl-hourly-remaining", "hourly"),
                               ("x-rl-daily-remaining", "daily")):
                try:
                    quota[slot] = int(r.headers.get(name))
                except (TypeError, ValueError):
                    pass
            return json.loads(r.read().decode("utf8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, path) from exc
    except urllib.error.URLError as exc:
        raise NexusError(f"Could not reach Nexus Mods: {exc.reason}",
                         code="offline") from exc
    except (ValueError, OSError) as exc:
        raise NexusError(f"Could not read Nexus's answer: {exc}") from exc


def _http_error(exc, path):
    code = exc.code
    if code == 401:
        return NexusError("Nexus refused the API key. Copy it again from your "
                          "Nexus account page and reconnect.", code=401)
    if code == 403 and "download_link" in path:
        return NexusError("Nexus only gives direct downloads to Premium members. "
                          "Use the Mod Manager Download button on the mod's "
                          "Files tab instead.", code=403)
    if code == 403:
        return NexusError("Nexus won't show that (it may be hidden or under "
                          "moderation).", code=403)
    if code == 404:
        return NexusError("Nexus doesn't have that for Palworld. It may have "
                          "been removed or hidden.", code=404)
    if code == 410:
        return NexusError("That download link has expired. Press Mod Manager "
                          "Download on the Nexus page again.", code=410)
    if code == 429:
        return NexusError("Nexus's request limit for this hour is used up. "
                          "Try again later.", code=429)
    if code >= 500:
        return NexusError(f"Nexus Mods isn't answering right now ({code}). "
                          "Try again later.", code=code)
    return NexusError(f"Nexus returned {code}.", code=code)


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def _cache_file():
    return palpaths.data_dir() / "nexus.json"


def _load_cache():
    try:
        data = json.loads(_cache_file().read_text("utf8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# The update check and a details fetch can run on two threads at once; each
# reads the cache, changes one part and writes it back.
_cache_lock = threading.RLock()


def _save_cache(data):
    """Written whole and then swapped in, so a reader never sees half a file.

    The update check runs on a background thread while the window reads the
    results; a torn file would read as "nothing known" at best.
    """
    f = _cache_file()
    tmp = f.with_name(f.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", "utf8")
        os.replace(tmp, f)
    except OSError:
        pass


def _cache_put(section, key, value):
    with _cache_lock:
        data = _load_cache()
        data.setdefault(section, {})[str(key)] = value
        _save_cache(data)


def _cache_set(key, value):
    with _cache_lock:
        data = _load_cache()
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        _save_cache(data)


def account():
    """{name, premium, supporter, user_id} from the last check, or None."""
    return _load_cache().get("account")


# --------------------------------------------------------------------------
# what Nexus knows
# --------------------------------------------------------------------------
def validate(key=None):
    """Check a key and remember whose it is. Raises NexusError if refused."""
    raw = _api("/users/validate", key=key)
    acct = {"name": raw.get("name") or "", "user_id": raw.get("user_id"),
            "premium": bool(raw.get("is_premium")),
            "supporter": bool(raw.get("is_supporter"))}
    _cache_set("account", acct)
    return acct


def _trim_mod(raw):
    return {"id": raw.get("mod_id"), "name": raw.get("name") or "",
            "summary": raw.get("summary") or "",
            "description": raw.get("description") or "",
            "picture": raw.get("picture_url") or "",
            "version": str(raw.get("version") or ""),
            "author": raw.get("author") or raw.get("uploaded_by") or "",
            "updated": raw.get("updated_timestamp") or 0,
            "available": raw.get("available", True) is not False,
            "status": raw.get("status") or "",
            "adult": bool(raw.get("contains_adult_content"))}


def _trim_file(raw):
    size = raw.get("size_in_bytes")
    if not size:
        size = (raw.get("size_kb") or raw.get("size") or 0) * 1024
        exact = False
    else:
        exact = True
    return {"id": raw.get("file_id"), "name": raw.get("name") or "",
            "version": str(raw.get("version") or raw.get("mod_version") or ""),
            "category": (raw.get("category_name") or "").upper(),
            "primary": bool(raw.get("is_primary")),
            "size": int(size or 0), "size_exact": exact,
            "file_name": raw.get("file_name") or "",
            "uploaded": raw.get("uploaded_timestamp") or 0,
            "description": raw.get("description") or ""}


def mod_info(mod_id, refresh=False):
    mod_id = int(mod_id)
    got = _load_cache().get("mods", {}).get(str(mod_id))
    if got and not refresh and time.time() - got.get("when", 0) < MOD_TTL:
        return got["info"]
    try:
        info = _trim_mod(_api(f"/games/{GAME}/mods/{mod_id}"))
    except NexusError as exc:
        if exc.code == 404 or exc.code == 403:
            info = {"id": mod_id, "available": False, "missing": True,
                    "name": "", "version": "", "updated": 0}
        else:
            raise
    _cache_put("mods", mod_id, {"when": time.time(), "info": info})
    return info


def mod_files(mod_id, refresh=False):
    """{files: [...], updates: [(old id, new id)]}, newest file first."""
    mod_id = int(mod_id)
    got = _load_cache().get("files", {}).get(str(mod_id))
    if got and not refresh and time.time() - got.get("when", 0) < MOD_TTL:
        return got["files"]
    raw = _api(f"/games/{GAME}/mods/{mod_id}/files")
    files = sorted((_trim_file(f) for f in raw.get("files") or []),
                   key=lambda f: f["uploaded"], reverse=True)
    out = {"files": files,
           "updates": [[u.get("old_file_id"), u.get("new_file_id")]
                       for u in raw.get("file_updates") or []]}
    _cache_put("files", mod_id, {"when": time.time(), "files": out})
    return out


def recently_updated(period="1m"):
    """{mod id: latest activity} for mods Nexus reports as changed."""
    data = _load_cache()
    got = data.get("updated", {}).get(period)
    if got and time.time() - got.get("when", 0) < UPDATED_TTL:
        return {int(k): v for k, v in got["mods"].items()}
    raw = _api(f"/games/{GAME}/mods/updated", params={"period": period})
    mods = {int(e["mod_id"]): max(e.get("latest_file_update") or 0,
                                  e.get("latest_mod_activity") or 0)
            for e in raw or [] if e.get("mod_id")}
    _cache_put("updated", period, {"when": time.time(),
                                   "mods": {str(k): v for k, v in mods.items()}})
    return mods


def md5_search(digest):
    """Every Nexus file with this MD5, as [(mod info, file info)]."""
    try:
        raw = _api(f"/games/{GAME}/mods/md5_search/{quote(digest)}")
    except NexusError as exc:
        if exc.code in (404, 422):
            return []
        raise
    return [(_trim_mod(r.get("mod") or {}), _trim_file(r.get("file_details") or {}))
            for r in raw or []]


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def identify(path):
    """Registry fields for a download Nexus recognises by checksum, else None.

    For an archive whose name was changed after downloading, so the mod id
    can't be read from it.
    """
    p = Path(path)
    if not p.is_file():
        return None
    hits = md5_search(file_md5(p))
    hits = [(m, f) for m, f in hits if m.get("id")]
    if not hits:
        return None
    mod, f = hits[0]
    fields = {"source": "Nexus", "id": int(mod["id"]),
              "url": MOD_PAGE.format(id=mod["id"]), "nexus_file_id": f.get("id"),
              "nexus_name": mod.get("name") or ""}
    if f.get("version") or mod.get("version"):
        fields["version"] = f.get("version") or mod.get("version")
    return fields


# --------------------------------------------------------------------------
# versions and updates
# --------------------------------------------------------------------------
def _numbers(v):
    return [int(n) for n in re.findall(r"\d+", str(v or ""))]


def _norm(v):
    return re.sub(r"^v(?=\d)", "", str(v or "").strip().lower())


def newer(latest, installed):
    """True / False when the versions can be compared, None when they can't.

    Mod authors number things however they like ("1.2", "v1.2.0", "1.2b",
    "Beta 3"). Numbers are compared when both have them; anything else is
    left to the upload dates.
    """
    a, b = _norm(latest), _norm(installed)
    if not a or not b:
        return None
    if a == b:
        return False
    na, nb = _numbers(a), _numbers(b)
    if na and nb:
        width = max(len(na), len(nb))
        na, nb = na + [0] * (width - len(na)), nb + [0] * (width - len(nb))
        if na != nb:
            return na > nb
        # "2.1" and "2.1.0" are the same release; "1.2a" and "1.2b" aren't,
        # and which of those is newer is anyone's guess.
        if re.sub(r"[\d.\s]", "", a) == re.sub(r"[\d.\s]", "", b):
            return False
    return None


def _installed_time(entry):
    """When the installed file was uploaded to Nexus, as a timestamp, or None."""
    if entry.get("nexus_uploaded"):
        return entry["nexus_uploaded"]
    rel = entry.get("released")
    if rel:
        from datetime import datetime
        try:
            return datetime.fromisoformat(str(rel)).timestamp()
        except ValueError:
            return None
    return None


def newest_file(files):
    """The file a person updating would want: the newest current main file."""
    pool = [f for f in files if f["category"] == "MAIN"] or \
           [f for f in files if f["category"] in CURRENT_CATEGORIES] or \
           [f for f in files if f["category"] not in ("DELETED", "ARCHIVED")]
    primary = [f for f in pool if f["primary"]]
    pool = primary or pool
    return max(pool, key=lambda f: f["uploaded"]) if pool else None


def decide(entry, info, files):
    """Whether a registry entry is behind what Nexus has.

    Returns None when it's current (or unknown), else
    {version, file, removed, mod_id, url, name}.
    """
    mod_id = int(entry["id"])
    base = {"mod_id": mod_id, "url": FILES_PAGE.format(id=mod_id),
            "name": (info or {}).get("name") or ""}
    if (info or {}).get("missing") or (info or {}).get("available") is False:
        return dict(base, removed=True, version="", file=None)
    newest = newest_file((files or {}).get("files") or [])
    latest = (info or {}).get("version") or (newest or {}).get("version") or ""
    installed = entry.get("version") or ""
    # Nexus links an old file to its replacement when the author says so.
    mine = entry.get("nexus_file_id")
    if mine and newest and newest["id"] == mine:
        return None
    replaced = False
    for old, new in (files or {}).get("updates") or []:
        if old == mine and new:
            replaced = True
            if newest and new == newest["id"]:
                return dict(base, removed=False,
                            version=newest["version"] or latest, file=newest)
    # An optional file (a variant, an add-on) that is still current isn't
    # out of date just because the main file moved on.
    listed = next((f for f in (files or {}).get("files") or []
                   if mine and f["id"] == mine), None)
    if listed and not replaced and listed["category"] != "MAIN" \
            and listed["category"] in CURRENT_CATEGORIES:
        return None
    verdict = newer(latest, installed)
    if verdict is None and newest:
        when = _installed_time(entry)
        # A day's slack: a filename's timestamp is the upload time, the
        # released date only the day.
        if when:
            verdict = newest["uploaded"] > when + 86400
    if not verdict:
        return None
    return dict(base, removed=False, version=latest, file=newest)


def nexus_mods(registry):
    """{mod id: [registry names]} for every mod linked to Nexus."""
    out = {}
    for name, e in (registry or {}).items():
        if e.get("source") == "Nexus" and str(e.get("id") or "").isdigit():
            out.setdefault(int(e["id"]), []).append(name)
    return out


def check_updates(registry, progress=None, force=False):
    """Ask Nexus about every linked mod and remember the answers.

    Only mods Nexus says changed since they were last asked about are fetched
    again. Returns {name: update} for the ones with something newer.
    """
    ids = nexus_mods(registry)
    if not ids:
        return {}
    data = _load_cache()
    changed = recently_updated("1m")
    for n, (mod_id, names) in enumerate(sorted(ids.items()), start=1):
        if progress:
            progress(n, len(ids))
        seen = data.get("mods", {}).get(str(mod_id), {}).get("when", 0)
        stale = force or not seen or changed.get(mod_id, 0) > seen \
            or time.time() - seen > 7 * MOD_TTL
        if quota["hourly"] is not None and quota["hourly"] < 20:
            break                          # leave the user something for later
        try:
            mod_info(mod_id, refresh=stale)
            mod_files(mod_id, refresh=stale)
        except NexusError as exc:
            if exc.code in (401, 429, "offline", "no-key"):
                raise
    _cache_set("checked", time.time())
    return updates(registry)


def updates(registry, cache=None):
    """{name: update} from the last check, without asking Nexus anything."""
    data = cache if cache is not None else _load_cache()
    mods, files = data.get("mods", {}), data.get("files", {})
    out = {}
    for mod_id, names in nexus_mods(registry).items():
        info = (mods.get(str(mod_id)) or {}).get("info")
        if not info:
            continue
        for name in names:
            got = decide(registry[name], info,
                         (files.get(str(mod_id)) or {}).get("files"))
            if got:
                out[name] = got
    return out


def last_checked():
    return _load_cache().get("checked")


def cache_snapshot():
    """The whole cache, read once -- for building a list of rows."""
    return _load_cache()


# --------------------------------------------------------------------------
# nxm:// links
# --------------------------------------------------------------------------
def parse_nxm(url):
    """{mod_id, file_id, key, expires, user_id} from a Mod Manager Download link."""
    m = NXM.match(str(url or "").strip())
    if not m:
        raise NexusError("That isn't a Nexus Mods download link.")
    if m.group("game").lower() != GAME:
        raise NexusError(f"That download is for {m.group('game')}, not Palworld.")
    q = parse_qs(m.group("query") or "")
    out = {"mod_id": int(m.group("mod")), "file_id": int(m.group("file")),
           "key": (q.get("key") or [None])[0],
           "expires": None, "user_id": None}
    for field in ("expires", "user_id"):
        try:
            out[field] = int((q.get(field) or [None])[0])
        except (TypeError, ValueError):
            pass
    if out["key"] and not re.fullmatch(r"[\w\-]+", out["key"]):
        raise NexusError("That download link is damaged.")
    return out


def link_expired(link):
    return bool(link.get("expires")) and time.time() > link["expires"]


# --------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------
def find_file(mod_id, file_id):
    files = mod_files(mod_id)
    f = next((f for f in files["files"] if f["id"] == file_id), None)
    if f is None:
        files = mod_files(mod_id, refresh=True)
        f = next((f for f in files["files"] if f["id"] == file_id), None)
    if f is None:
        raise NexusError("Nexus doesn't list that file for this mod any more.")
    return f


def safe_name(name):
    """A file name from Nexus, made safe to write: no folders, no oddities."""
    name = re.split(r"[\\/]", str(name or ""))[-1]
    name = re.sub(r"[^\w.\-()+ ]+", "_", name).strip(" .")
    return name[:180] or "download.zip"


def download_links(mod_id, file_id, link=None):
    params = None
    if link and link.get("key") and link.get("expires"):
        params = {"key": link["key"], "expires": link["expires"]}
    raw = _api(f"/games/{GAME}/mods/{int(mod_id)}/files/{int(file_id)}/download_link",
               params=params)
    urls = [r.get("URI") for r in (raw or []) if r.get("URI")]
    if not urls:
        raise NexusError("Nexus didn't offer a download server for that file.")
    return urls


def download(mod_id, file_id, into, link=None, progress=None):
    """Fetch one file of a mod. Returns (path, file info).

    `link` is a parsed nxm:// link; without one only Premium members get a
    download. The result is checked against the size Nexus lists and the
    file's MD5 is looked up on Nexus: it must be this very file.
    """
    if link and link_expired(link):
        raise NexusError("That download link has expired. Press Mod Manager "
                         "Download on the Nexus page again.", code=410)
    f = find_file(mod_id, file_id)
    name = safe_name(f["file_name"] or f["name"])
    if not name.lower().endswith(ARCHIVE_SUFFIXES):
        raise NexusError(f"{name} isn't a kind of file this app installs.")
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    dest = into / name
    part = dest.with_name(dest.name + ".part")
    want = f["size"]
    ceiling = min(MAX_DOWNLOAD, want + (0 if f["size_exact"] else 1024)) \
        if want else MAX_DOWNLOAD
    md5 = hashlib.md5()
    done = 0
    last = None
    for url in download_links(mod_id, file_id, link):
        try:
            done = 0
            md5 = hashlib.md5()
            with _open(url, {"User-Agent": _headers()["User-Agent"]},
                       api=False) as r, open(part, "wb") as out:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > ceiling:
                        raise NexusError("The download is bigger than Nexus said "
                                         "it would be, so it was stopped.")
                    md5.update(chunk)
                    out.write(chunk)
                    if progress:
                        progress(done, want)
            last = None
            break
        except NexusError:
            part.unlink(missing_ok=True)
            raise
        except (urllib.error.URLError, OSError) as exc:
            part.unlink(missing_ok=True)
            last = exc                      # try the next server
    if last is not None:
        raise NexusError(f"The download failed: {last}")
    if want and (done < want - (0 if f["size_exact"] else 1024)):
        part.unlink(missing_ok=True)
        raise NexusError("The download ended early. Try again.")
    matches = md5_search(md5.hexdigest())
    if not any(m.get("id") == int(mod_id) and fi.get("id") == int(file_id)
               for m, fi in matches):
        part.unlink(missing_ok=True)
        raise NexusError("The download doesn't match the checksum Nexus has for "
                         "this file, so it wasn't used.")
    os.replace(part, dest)
    _prune(into)
    return dest, f


def _prune(folder, keep=10):
    """Keep the last few downloads, so a mod can be reinstalled offline."""
    files = sorted((p for p in Path(folder).iterdir()
                    if p.is_file() and p.suffix.lower() in ARCHIVE_SUFFIXES),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def downloads_dir():
    return palpaths.data_dir() / "downloads" / "nexus"


# --------------------------------------------------------------------------
# descriptions and pictures
# --------------------------------------------------------------------------
_BB_DROP = re.compile(r"\[img[^\]]*\].*?\[/img\]", re.I | re.S)
_BB_URL = re.compile(r"\[url=([^\]]+)\](.*?)\[/url\]", re.I | re.S)
_BB_BARE_URL = re.compile(r"\[url\](.*?)\[/url\]", re.I | re.S)
_BB_YOUTUBE = re.compile(r"\[youtube\]\s*([\w-]+)\s*\[/youtube\]", re.I)
_BB_TAG = re.compile(r"\[/?(?:b|i|u|s|size|color|colour|font|center|left|right|"
                     r"quote|spoiler|code|list|heading|style|sup|sub|indent|"
                     r"justify|ol|ul|li|table|tr|td|th)(?:=[^\]]*)?\]", re.I)


def bbcode_to_text(text):
    """Nexus descriptions are BBCode with HTML line breaks. Make them readable."""
    s = str(text or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?(p|div)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _BB_DROP.sub("", s)
    s = _BB_YOUTUBE.sub(lambda m: f"https://youtu.be/{m.group(1)}", s)

    def link(m):
        url, label = m.group(1).strip("\"' "), m.group(2).strip()
        return url if not label or label == url else f"{label} ({url})"
    s = _BB_URL.sub(link, s)
    s = _BB_BARE_URL.sub(lambda m: m.group(1).strip(), s)
    s = re.sub(r"\[\*\]\s*", "\n• ", s)
    s = re.sub(r"\[(line|hr)\]", "\n———\n", s, flags=re.I)
    s = _BB_TAG.sub("", s)
    s = html.unescape(s).replace("\r\n", "\n").replace("\xa0", " ")
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fetch_picture(url):
    """The bytes of a mod's picture from Nexus's image host, size-capped."""
    check_url(url)
    try:
        with _open(url, {"User-Agent": _headers()["User-Agent"]}, api=False) as r:
            raw = r.read(MAX_PICTURE + 1)
    except urllib.error.HTTPError as exc:
        raise NexusError(f"Nexus returned {exc.code} for the picture.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise NexusError(f"Couldn't fetch the picture: {exc}") from exc
    if len(raw) > MAX_PICTURE:
        raise NexusError("The picture is too large to keep.")
    return raw


def fetch_details(mod_id, picture=True):
    """What Nexus says about a mod: {name, author, description, picture}.

    Network only; nothing is written. `picture` is the image's bytes or None.
    Runs on a background thread, and apply_details() stores the result on
    the main one.
    """
    info = mod_info(mod_id, refresh=True)
    if info.get("missing") or not info.get("available", True):
        raise NexusError("That mod isn't available on Nexus any more.", code=404)
    parts = [p for p in (info.get("summary", "").strip(),
                         bbcode_to_text(info.get("description"))) if p]
    if len(parts) == 2 and parts[1].startswith(parts[0]):
        parts = parts[1:]
    pic = None
    if picture and info.get("picture"):
        try:
            pic = fetch_picture(info["picture"])
        except NexusError:
            pic = None                          # the text is still worth having
    return {"id": info["id"], "name": info.get("name") or "",
            "author": info.get("author") or "",
            "version": info.get("version") or "",
            "description": "\n\n".join(parts), "picture": pic}


def apply_details(name, details, overwrite=False):
    """Store fetched details for a mod. Returns what was filled in, as words."""
    import palmedia
    import palregistry
    got = []
    have = palmedia.info(name)
    if details.get("description") and (overwrite or not have["description"]):
        palmedia.set_description(name, details["description"])
        got.append("description")
    if details.get("picture") and (overwrite or not have["images"]):
        try:
            palmedia.add_image_bytes(name, details["picture"], "Nexus picture")
            got.append("picture")
        except palmedia.MediaError:
            pass
    fields = {}
    if details.get("author"):
        fields["author"] = details["author"]
    if details.get("name"):
        fields["nexus_name"] = details["name"]
    if fields:
        palregistry.set_entry(name, **fields)
    return got


# --------------------------------------------------------------------------
# being the nxm:// handler
# --------------------------------------------------------------------------
# Opting in points HKEY_CURRENT_USER\Software\Classes\nxm at this app, so the
# website's Mod Manager Download button opens here. Whatever handled it before
# (Vortex, Mod Organizer) is remembered and put back when this is turned off.
NXM_KEY = r"Software\Classes\nxm"
COMMAND_KEY = NXM_KEY + r"\shell\open\command"
try:
    import winreg as _winreg
except ImportError:
    _winreg = None


def launch_command():
    """How Windows should start this app with a link."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    exe = Path(sys.executable)
    windowed = exe.with_name("pythonw.exe")
    exe = windowed if windowed.is_file() else exe
    script = Path(__file__).resolve().parent / "palmods_gui.py"
    return f'"{exe}" "{script}" "%1"'


def _read_command(root, key):
    try:
        with _winreg.OpenKey(root, key) as k:
            value, _ = _winreg.QueryValueEx(k, "")
            return value or None
    except OSError:
        return None


def handler_owner(command):
    """Who a registered nxm command belongs to, in words."""
    c = (command or "").lower()
    if not c:
        return None
    if "ezpalmodmanager" in c or "palmods_gui" in c:
        return "EZ Pal Mod Manager"
    if "vortex" in c:
        return "Vortex"
    if "nxmhandler" in c or "modorganizer" in c:
        return "Mod Organizer 2"
    if "nexusmods.app" in c or "nexusmods" in c:
        return "the Nexus Mods app"
    return "another program"


def handler_status():
    """{command, owner, ours, stale} for whatever handles nxm:// links now."""
    if _winreg is None:
        return {"command": None, "owner": None, "ours": False, "stale": False,
                "supported": False}
    cmd = (_read_command(_winreg.HKEY_CURRENT_USER, COMMAND_KEY)
           or _read_command(_winreg.HKEY_CLASSES_ROOT, r"nxm\shell\open\command"))
    owner = handler_owner(cmd)
    ours = owner == "EZ Pal Mod Manager"
    return {"command": cmd, "owner": owner, "ours": ours,
            "stale": ours and cmd != launch_command(), "supported": True}


def register_handler():
    """Make this app open nxm:// links. Remembers what it replaces."""
    if _winreg is None:
        raise NexusError("Download links can only be handled on Windows.")
    before = handler_status()
    settings = palpaths.load_settings()
    if before["command"] and not before["ours"]:
        settings["nxm_previous"] = before["command"]
    exe_path = launch_command().split('"')[1]
    w = _winreg
    with w.CreateKey(w.HKEY_CURRENT_USER, NXM_KEY) as k:
        w.SetValueEx(k, "", 0, w.REG_SZ, "URL:NXM Protocol")
        w.SetValueEx(k, "URL Protocol", 0, w.REG_SZ, "")
    with w.CreateKey(w.HKEY_CURRENT_USER, NXM_KEY + r"\DefaultIcon") as k:
        w.SetValueEx(k, "", 0, w.REG_SZ, f'"{exe_path}",0')
    with w.CreateKey(w.HKEY_CURRENT_USER, COMMAND_KEY) as k:
        w.SetValueEx(k, "", 0, w.REG_SZ, launch_command())
    palpaths.save_settings({"nxm_handler": True,
                            "nxm_previous": settings.get("nxm_previous")})
    return before.get("owner") if not before["ours"] else None


def unregister_handler():
    """Hand nxm:// links back to whatever had them, or to nobody."""
    if _winreg is None:
        return None
    settings = palpaths.load_settings()
    previous = settings.get("nxm_previous")
    w = _winreg
    now = handler_status()
    if now["ours"] or not now["command"]:
        if previous:
            with w.CreateKey(w.HKEY_CURRENT_USER, COMMAND_KEY) as k:
                w.SetValueEx(k, "", 0, w.REG_SZ, previous)
            icon = previous.split('"')[1] if previous.startswith('"') else None
            if icon:
                with w.CreateKey(w.HKEY_CURRENT_USER, NXM_KEY + r"\DefaultIcon") as k:
                    w.SetValueEx(k, "", 0, w.REG_SZ, f'"{icon}",0')
        else:
            for sub in (COMMAND_KEY, NXM_KEY + r"\shell\open", NXM_KEY + r"\shell",
                        NXM_KEY + r"\DefaultIcon", NXM_KEY):
                try:
                    w.DeleteKey(w.HKEY_CURRENT_USER, sub)
                except OSError:
                    pass
    palpaths.save_settings({"nxm_handler": False, "nxm_previous": None})
    return handler_owner(previous)


def refresh_handler():
    """The exe is portable: if it moved, point our registration at the new place.

    Only a registration that is still ours is touched. If another manager has
    taken the links since, that was someone's choice and it stays.
    """
    if _winreg is None or not palpaths.load_settings().get("nxm_handler"):
        return False
    st = handler_status()
    if st["ours"] and st["stale"]:
        try:
            register_handler()
            return True
        except OSError:
            return False
    return False
