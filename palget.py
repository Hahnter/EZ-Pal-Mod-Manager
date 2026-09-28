"""Fetching UE4SS and PalSchema from their own GitHub releases.

Neither one ships with this app. They are other people's work under their own
licences, a bundled copy goes stale the week after it is bundled, and the
Palworld build of UE4SS moves faster than this app does. So the app asks
GitHub what the current release is and downloads it -- only ever after the
user presses a button, and only from the two repositories named here.

This and palnexus (Nexus Mods, only once the user has connected an account)
are the only modules that touch the network.
"""
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import palinstall
import palpaths

# Palworld needs Okaetsu's fork. The official RE-UE4SS 3.0.1 installs flat
# into Win64 and current Palworld mods do not load under it.
UE4SS_REPO = "Okaetsu/RE-UE4SS"
PALSCHEMA_REPO = "Okaetsu/PalSchema"

AGENT = "PalModManager-local"
# Where a request may go. Release files are served from GitHub's own
# download hosts; anything else -- including a URL that came from a
# tampered cache file -- is refused before it is fetched.
ALLOWED_HOSTS = {"api.github.com", "github.com",
                 "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
TIMEOUT = 20
CACHE_MINUTES = 60
CHUNK = 64 * 1024

# The "dev edition" of either project is a much larger build aimed at mod
# authors. Ordinary users want the plain one.
DEV_ASSET = re.compile(r"(_|-)(z?dev)\.zip$", re.I)
UE4SS_ASSET = re.compile(r"^UE4SS.*\.zip$", re.I)
PALSCHEMA_ASSET = re.compile(r"^PalSchema.*\.zip$", re.I)


class GetError(Exception):
    """Anything that stopped a download, in words worth showing."""


# --------------------------------------------------------------------------
# asking GitHub
# --------------------------------------------------------------------------
def _cache_file():
    return palpaths.data_dir() / "github.json"


def _cached(repo, max_age_minutes):
    try:
        data = json.loads(_cache_file().read_text("utf8"))
    except (OSError, ValueError):
        return None
    got = data.get(repo)
    if not got:
        return None
    if time.time() - got.get("when", 0) > max_age_minutes * 60:
        return None
    return got.get("releases")


def _remember(repo, releases):
    try:
        data = json.loads(_cache_file().read_text("utf8"))
    except (OSError, ValueError):
        data = {}
    data[repo] = {"when": time.time(), "releases": releases}
    try:
        _cache_file().write_text(json.dumps(data, indent=2) + "\n", "utf8")
    except OSError:
        pass                                   # a cache miss is not an error


def _open(url):
    """One request, with our name on it. Separated so tests can replace it."""
    if os.environ.get("PMM_NO_NETWORK") == "1":
        raise GetError("This copy is set not to use the network "
                       "(PMM_NO_NETWORK=1).")
    check_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": AGENT,
        "Accept": "application/vnd.github+json",
    })
    return _OPENER.open(req, timeout=TIMEOUT)


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Release downloads redirect from github.com to GitHub's file hosts.

    urllib follows redirects on its own, which would carry a request past the
    host check to wherever the redirect says. Each hop is checked instead.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirects)


def check_url(url):
    """Refuse anything that isn't HTTPS to GitHub."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise GetError("That download address isn't valid.") from exc
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise GetError(f"Refused to download from {parts.hostname or url}: "
                       "only GitHub is allowed.")
    return url


def releases(repo, refresh=False):
    """Recent releases of a repo, newest first. Cached for an hour."""
    if not refresh:
        got = _cached(repo, CACHE_MINUTES)
        if got is not None:
            return got
    url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
    try:
        with _open(url) as r:
            raw = json.loads(r.read().decode("utf8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            stale = _cached(repo, 60 * 24 * 30)
            if stale:
                return stale
            raise GetError("GitHub is rate-limiting this connection. "
                           "Try again in an hour, or download it yourself "
                           f"from github.com/{repo}/releases.") from exc
        raise GetError(f"GitHub returned {exc.code} for {repo}.") from exc
    except urllib.error.URLError as exc:
        stale = _cached(repo, 60 * 24 * 30)
        if stale:
            return stale
        raise GetError(f"Could not reach GitHub: {exc.reason}") from exc
    except (ValueError, OSError) as exc:
        raise GetError(f"Could not read GitHub's answer: {exc}") from exc

    keep = [{
        "tag": r.get("tag_name") or "",
        "name": r.get("name") or r.get("tag_name") or "",
        "published": r.get("published_at") or "",
        "prerelease": bool(r.get("prerelease")),
        "page": r.get("html_url") or "",
        "assets": [{"name": a.get("name") or "",
                    "size": a.get("size") or 0,
                    "url": a.get("browser_download_url") or "",
                    # GitHub publishes a sha256 for each release file.
                    "digest": a.get("digest") or ""}
                   for a in (r.get("assets") or [])],
    } for r in raw if not r.get("draft")]
    keep.sort(key=lambda r: r["published"], reverse=True)
    _remember(repo, keep)
    return keep


def _pick_asset(rel, pattern, dev=False):
    for a in rel["assets"]:
        if not pattern.match(a["name"]) or not a["url"]:
            continue
        if bool(DEV_ASSET.search(a["name"])) == bool(dev):
            return a
    return None


def latest(kind, dev=False, refresh=False):
    """The newest release of UE4SS or PalSchema that has a usable download.

    Returns {kind, repo, tag, name, published, page, asset{name,size,url}}.
    """
    repo, pattern = ((UE4SS_REPO, UE4SS_ASSET) if kind == "ue4ss"
                     else (PALSCHEMA_REPO, PALSCHEMA_ASSET))
    for rel in releases(repo, refresh=refresh):
        asset = _pick_asset(rel, pattern, dev=dev)
        if asset:
            out = {k: rel[k] for k in ("tag", "name", "published", "page",
                                       "prerelease")}
            out.update(kind=kind, repo=repo, asset=asset)
            return out
    raise GetError(f"No download found in the releases of {repo}.")


def when(rel):
    """'3 Sep 2026' from a release's timestamp."""
    try:
        t = datetime.fromisoformat(rel["published"].replace("Z", "+00:00"))
    except (ValueError, KeyError, AttributeError):
        return ""
    return t.astimezone().strftime("%d %b %Y").lstrip("0")


# --------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------
def download(rel, into, progress=None):
    """Fetch a release's zip. `progress(done, total)` is called as it goes."""
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    name = Path(rel["asset"]["name"]).name       # never a path from outside
    if not name.lower().endswith(".zip"):
        raise GetError("That release file isn't a zip.")
    dest = into / name
    total = rel["asset"]["size"]
    done = 0
    sha = hashlib.sha256()
    try:
        with _open(rel["asset"]["url"]) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                done += len(chunk)
                if total and done > total:
                    raise GetError("The download is bigger than GitHub said "
                                   "it would be, so it was stopped.")
                sha.update(chunk)
                f.write(chunk)
                if progress:
                    progress(done, total)
    except GetError:
        dest.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise GetError(f"The download failed: {exc}") from exc

    if total and done != total:
        dest.unlink(missing_ok=True)
        raise GetError("The download ended early. Try again.")
    want = (rel["asset"].get("digest") or "").lower()
    if want.startswith("sha256:") and want[7:] != sha.hexdigest():
        dest.unlink(missing_ok=True)
        raise GetError("The download doesn't match the checksum GitHub "
                       "publishes for it, so it wasn't used.")
    if not zipfile.is_zipfile(dest):
        dest.unlink(missing_ok=True)
        raise GetError("What arrived is not a zip file.")
    _prune(into)
    return dest


def _prune(folder, keep=3):
    """Downloads pile up otherwise; the newest few are enough to reinstall."""
    zips = sorted((p for p in Path(folder).glob("*.zip") if p.is_file()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in zips[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# installing UE4SS
# --------------------------------------------------------------------------
PROXY_NAMES = {"dwmapi.dll", "xinput1_3.dll", "d3d11.dll"}


def _ue4ss_root(zf):
    """Where inside the zip the UE4SS files start.

    The Palworld zips hold ue4ss\\UE4SS.dll and dwmapi.dll at the top, but a
    zip built with one folder around everything is just as common.
    """
    names = [n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")]
    for n in names:
        parts = n.split("/")
        if len(parts) >= 2 and parts[-2].lower() == "ue4ss" \
                and parts[-1].lower() == "ue4ss.dll":
            return "/".join(parts[:-2])
    raise GetError("That zip has no ue4ss\\UE4SS.dll in it, so it is not the "
                   "Palworld build of UE4SS.")


def park(path):
    """Move something aside instead of deleting it. Returns the new path."""
    path = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    spare = path.with_name(f"{path.name}.pmm-old-{stamp}")
    n = 2
    while spare.exists():
        spare = path.with_name(f"{path.name}.pmm-old-{stamp}-{n}")
        n += 1
    path.rename(spare)
    return spare


def install_ue4ss(zip_path, paths):
    """Put a downloaded UE4SS into Win64, keeping whatever was there.

    Returns (results, parked) -- lines to show, and the paths moved aside.
    """
    win64 = Path(paths["win64"])
    results, parked = [], []
    with zipfile.ZipFile(zip_path) as zf:
        root = _ue4ss_root(zf)
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if root:
            members = [n for n in members
                       if n.replace("\\", "/").startswith(root + "/")]

        existing = win64 / "ue4ss"
        if existing.exists():
            parked.append(park(existing))
            results.append(f"Kept your old UE4SS as {parked[-1].name}")
        # A flat-layout UE4SS.dll beside it would load instead of the new one.
        flat = win64 / "UE4SS.dll"
        if flat.is_file():
            parked.append(park(flat))
            results.append(f"Moved the old flat UE4SS.dll aside as "
                           f"{parked[-1].name}")

        written = 0
        for name in members:
            rel = name.replace("\\", "/")
            if root:
                rel = rel[len(root) + 1:]
            if not rel or ".." in Path(rel).parts or Path(rel).is_absolute():
                continue
            target = win64 / rel
            if not palinstall.inside(target, win64):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
        results.append(f"Installed UE4SS into {win64}")

    if not any((win64 / n).is_file() for n in PROXY_NAMES):
        results.append("Warning: the zip carried no proxy DLL (dwmapi.dll), "
                       "so the game may not load UE4SS.")
    if not (win64 / "ue4ss" / "MemberVariableLayout.ini").is_file():
        results.append("Warning: MemberVariableLayout.ini is missing from "
                       "this build. Mods that read game data may fail.")
    return results, parked
