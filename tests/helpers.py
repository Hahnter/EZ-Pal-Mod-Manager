"""Shared scaffolding for the test scripts.

Every test runs against a throwaway Palworld install in the temp folder. Call
`sandbox()` before importing any app module: it redirects the app's data
folder and %LOCALAPPDATA%, turns off install auto-detection (so a test can
never find and modify your real game), blocks network access, and swaps the
Recycle Bin for a plain delete so test runs don't fill it.

Each checkout of the repo keeps its sandboxes in a folder of its own, so
several worktrees can run the tests at the same time.
"""

import hashlib
import os
import shutil
import socket
import struct
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STALE_DAYS = 7


# --------------------------------------------------------------------------
# isolation
# --------------------------------------------------------------------------
def sandbox_home(checkout=ROOT):
    """Where one checkout's sandboxes live: pmm-tests/<hash of its path>.

    With one folder shared by every checkout, a run in one worktree wiped
    pmm-tests/windows while a run in another was still using it.
    """
    key = os.path.normcase(str(Path(checkout).resolve())).encode()
    return Path(tempfile.gettempdir()) / "pmm-tests" / hashlib.sha256(key).hexdigest()[:10]


def prune_sandboxes():
    """Delete this checkout's sandboxes that no test has rebuilt in a week.

    Never looks outside this checkout's own folder: another checkout's
    sandboxes can belong to a run going on right now.
    """
    cutoff = time.time() - STALE_DAYS * 86400
    try:
        old = [d for d in sandbox_home().iterdir()
               if d.is_dir() and d.stat().st_mtime < cutoff]
    except OSError:
        return
    for d in old:
        shutil.rmtree(d, ignore_errors=True)


def sandbox(tag):
    home = sandbox_home()
    sb = home / tag
    if sb.exists():
        shutil.rmtree(sb)
    sb.mkdir(parents=True)
    (home / "checkout.txt").write_text(str(ROOT), "utf8")   # whose folder this is
    prune_sandboxes()
    os.environ["PMM_DATA_DIR"] = str(sb / "data")
    os.environ["LOCALAPPDATA"] = str(sb / "localappdata")
    os.environ.pop("PALWORLD_PATH", None)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    def no_network(*_a, **_k):
        raise AssertionError("a test tried to use the network")
    socket.socket.connect = no_network
    socket.create_connection = no_network

    import palpaths
    palpaths.detect = lambda extra=None: []          # never find the real game
    palpaths._game = None

    # Hard stop: the app may only ever resolve a game folder inside the temp
    # directory. Any code path that reaches a real install fails the test
    # instead of touching it.
    temp_root = str(Path(tempfile.gettempdir()).resolve()).lower()
    real_game = palpaths.game

    def guarded_game(auto=True):
        g = real_game(auto=False)
        if g is not None and not str(Path(g).resolve()).lower().startswith(temp_root):
            raise AssertionError(f"test reached a real Palworld install: {g}")
        return g
    palpaths.game = guarded_game

    # A developer's old hand-made registry.json beside the source would be
    # adopted on first load and leak real mods into every test.
    import palregistry
    palregistry._legacy_registry = lambda: {}

    if os.environ.get("PMM_TEST_REAL_RECYCLE") != "1":
        import paltools

        def fake_recycle(paths):
            for p in paths:
                p = Path(p)
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.exists():
                    p.unlink()
            return True
        paltools.recycle = fake_recycle
    return sb


def use_game(game):
    """Point the app at a sandbox install (never remembered)."""
    import palpaths
    assert str(Path(game).resolve()).lower().startswith(
        str(Path(tempfile.gettempdir()).resolve()).lower()), "not a sandbox install"
    palpaths._game = None
    ok, msg = palpaths.set_game(game, remember=False)
    assert ok, msg
    return game


def scan(game):
    import palmods
    use_game(game)
    paths = palmods.discover()
    return paths, palmods.build(paths)


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------
class Checker:
    def __init__(self):
        self.failed = []

    def __call__(self, label, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + label
              + (f"   [{detail}]" if detail != "" else ""))
        if not cond:
            self.failed.append(label)
        return cond

    def section(self, title):
        print(f"\n== {title} ==")

    def finish(self, errors=()):
        if errors:
            print("\nCALLBACK ERRORS:\n" + "\n".join(errors))
        ok = not self.failed and not errors
        print("\n" + ("ALL PASS" if ok else f"{len(self.failed)} FAILED: {self.failed}"))
        sys.exit(0 if ok else 1)


# --------------------------------------------------------------------------
# building fake installs
# --------------------------------------------------------------------------
def fake_pak(path, mount, files, version=3):
    """A minimal pre-v10 .pak: inline index entries, footer with the magic."""
    def fstring(s):
        b = s.encode() + b"\0"
        return struct.pack("<i", len(b)) + b
    idx = fstring(mount) + struct.pack("<i", len(files))
    for f in files:
        idx += fstring(f) + struct.pack("<qqq", 0, 0, 0) + struct.pack("<I", 0)
        idx += b"\0" * 20 + b"\0" + struct.pack("<i", 0)
    body = b"\0" * 64
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body + idx + b"\0" * 16 + struct.pack("<I", 0x5A6F12E1)
                     + struct.pack("<I", version)
                     + struct.pack("<QQ", len(body), len(idx)) + b"\0" * 24)
    return path


def make_game(root, server=False, ue4ss="experimental"):
    game = Path(root) / ("PalServer" if server else "Palworld")
    win64 = game / "Pal/Binaries/Win64"
    win64.mkdir(parents=True)
    exe = "PalServer-Win64-Shipping-Cmd.exe" if server else "Palworld-Win64-Shipping.exe"
    (win64 / exe).write_bytes(b"stub")
    (game / "Pal/Content/Paks/~mods").mkdir(parents=True)
    (game / "Pal/Content/Paks/LogicMods").mkdir(parents=True)
    if ue4ss == "experimental":
        (win64 / "ue4ss/Mods").mkdir(parents=True)
        (win64 / "ue4ss/UE4SS.dll").write_bytes(b"x")
        (win64 / "ue4ss/MemberVariableLayout.ini").write_text("")
        (win64 / "dwmapi.dll").write_bytes(b"x")
    elif ue4ss == "flat":
        (win64 / "Mods").mkdir(parents=True)
        (win64 / "UE4SS.dll").write_bytes(b"x")
        (win64 / "dwmapi.dll").write_bytes(b"x")
    return game


def steam_library(root, name, appid, build, updated):
    """A fake steamapps/common with an appmanifest. Returns the common dir."""
    apps = Path(root) / "steamapps"
    (apps / "common").mkdir(parents=True, exist_ok=True)
    (apps / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"installdir"\t\t"{name}"\n'
        f'\t"LastUpdated"\t\t"{updated}"\n\t"buildid"\t\t"{build}"\n}}\n')
    return apps / "common"


def lua_mod(mods_dir, name, main="print('x')", enabled=True, extra=None):
    d = Path(mods_dir) / name
    (d / "Scripts").mkdir(parents=True)
    (d / "Scripts/main.lua").write_text(main)
    if enabled:
        (d / "enabled.txt").write_text("")
    for rel, text in (extra or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


def write_log(win64, started, when_offset=0):
    log = Path(win64) / "ue4ss/UE4SS.log"
    lines = ["[2026-09-12 10:00:00.0] UE4SS - v3.0.1 Beta #0 - Git SHA #abc"]
    lines += [f"[2026-09-12 10:00:01.0] Starting Lua mod '{n}'" for n in started]
    log.write_text("\n".join(lines) + "\n")
    t = time.time() + when_offset
    os.utime(log, (t, t))
    return log


def picture(path, size=(800, 450), mode="RGB", fmt=None, colour=(40, 120, 200, 255)):
    from PIL import Image
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, colour[:len(mode)]).save(path, fmt)
    return path


# --------------------------------------------------------------------------
# Tk without windows popping up
# --------------------------------------------------------------------------
class FakeMessageBox:
    """Records dialog calls; answers from `answers` (default: yes)."""
    answers = {}
    calls = []

    @classmethod
    def _call(cls, kind, *args):
        cls.calls.append((kind, args))
        return cls.answers.get(kind, True)


for _kind in ("showinfo", "showerror", "showwarning", "askyesno", "askyesnocancel"):
    setattr(FakeMessageBox, _kind,
            classmethod(lambda cls, *a, _k=_kind, **_kw: cls._call(_k, *a)))


def hidden_tk():
    """A Tk root whose windows never appear. Returns (root, pump, errors)."""
    import tkinter as tk
    original = tk.Toplevel.__init__

    def hidden(self, *a, **k):
        original(self, *a, **k)
        self.withdraw()
    tk.Toplevel.__init__ = hidden
    tk.Toplevel.deiconify = lambda self: None

    root = tk.Tk()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *a: errors.append(
        "".join(traceback.format_exception(*a)))

    def pump(seconds=0.3):
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.01)
    return root, pump, errors


def silence_dialogs(*modules):
    for m in modules:
        m.messagebox = FakeMessageBox
