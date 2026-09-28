"""Passing work to a copy of the app that is already open.

Windows starts a new process for every Mod Manager Download click and every
file dropped on the exe. Opening a second window each time would mean two
copies of the app writing the same settings, so a new copy that finds one
already running leaves what it was given in an inbox folder and exits; the
running one picks it up within a few seconds.

"Running" is a heartbeat file the open app rewrites while it polls. A copy
that crashed stops beating, and after a few seconds it no longer counts.
"""

import itertools
import json
import os
import time

import palpaths

BEAT_FILE = "running.json"
INBOX = "inbox"
STALE_AFTER = 8          # seconds; the app beats every 2.5
_seq = itertools.count()


def _beat_file():
    return palpaths.data_dir() / BEAT_FILE


def _inbox():
    d = palpaths.data_dir() / INBOX
    d.mkdir(parents=True, exist_ok=True)
    return d


def heartbeat():
    try:
        _beat_file().write_text(json.dumps({"pid": os.getpid(),
                                            "beat": time.time()}), "utf8")
    except OSError:
        pass


def stop():
    """The app is closing: stop counting as running (if it was us)."""
    try:
        data = json.loads(_beat_file().read_text("utf8"))
        if data.get("pid") == os.getpid():
            _beat_file().unlink()
    except (OSError, ValueError):
        pass


def other_running():
    try:
        data = json.loads(_beat_file().read_text("utf8"))
    except (OSError, ValueError):
        return False
    return (data.get("pid") != os.getpid()
            and time.time() - float(data.get("beat") or 0) < STALE_AFTER)


def send(items):
    """Leave files and links for the running copy. Returns the file written."""
    items = [str(i) for i in items if str(i).strip()]
    if not items:
        return None
    d = _inbox()
    # Sorted by name when read: the time orders copies, the counter orders
    # two sends from one copy inside the same tick of the clock.
    name = f"{time.time_ns():020d}-{os.getpid():08d}-{next(_seq):06d}.json"
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps({"items": items}), "utf8")
    os.replace(tmp, d / name)          # never read half-written
    return d / name


def receive():
    """Everything waiting in the inbox, oldest first. The inbox is emptied."""
    try:
        files = sorted(p for p in _inbox().glob("*.json"))
    except OSError:
        return []
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text("utf8"))
            out += [str(i) for i in data.get("items") or []][:50]
        except (OSError, ValueError):
            pass
        try:
            f.unlink()
        except OSError:
            pass
    return out
