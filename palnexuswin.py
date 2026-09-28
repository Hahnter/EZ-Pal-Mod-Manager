#!/usr/bin/env python3
"""The Nexus Mods windows: connecting, downloading a file, and updates.

Every request runs on a background thread and reports through a queue; only
the Tk thread touches widgets. Nothing is asked of Nexus until the user has
added their own API key.
"""

import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import palnexus
import palpaths
import palsafety
from paltext import plural
from palui import (open_link, SURFACE, RAISED, TEXT, DIM, FAINT, GOOD,
                   WARN, BAD, button, checkbox, human_size, Window)

TITLE = "EZ Pal Mod Manager"


class _Worker:
    """Run a function off the Tk thread and hand its result back to it."""

    def __init__(self, window):
        self.window = window
        self.q = queue.Queue()
        window.after(80, self._pump)

    def run(self, fn, done, failed, progress=None):
        def work():
            try:
                kw = {"progress": lambda *a: self.q.put((progress, a))} \
                    if progress else {}
                self.q.put((done, (fn(**kw),)))
            except palnexus.NexusError as exc:
                self.q.put((failed, (exc,)))
            except OSError as exc:
                self.q.put((failed, (palnexus.NexusError(
                    f"Couldn't write the file: {exc}"),)))
        threading.Thread(target=work, daemon=True).start()

    def _pump(self):
        try:
            while True:
                cb, args = self.q.get_nowait()
                if cb:
                    cb(*args)
        except queue.Empty:
            pass
        try:
            if self.window.winfo_exists():
                self.window.after(80, self._pump)
        except tk.TclError:
            pass


def _when(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%d %b %Y").lstrip("0")
    except (TypeError, ValueError, OSError):
        return ""


def _details(win, rows):
    card = win.card()
    for label, value in rows:
        row = tk.Frame(card, bg=RAISED)
        row.pack(fill="x", padx=12, pady=3)
        tk.Label(row, text=label, bg=RAISED, fg=FAINT, font=win.app.f_small,
                 width=10, anchor="w").pack(side="left")
        tk.Label(row, text=value, bg=RAISED, fg=TEXT, font=win.app.f_small,
                 anchor="w", justify="left", wraplength=460).pack(
                     side="left", fill="x", expand=True)
    tk.Frame(card, bg=RAISED, height=6).pack()
    return card


# ==========================================================================
# connecting
# ==========================================================================
class NexusWindow(Window):
    """Add or remove the API key, and choose what the connection is used for."""

    def __init__(self, app):
        super().__init__(app, "Nexus Mods",
                         "Connect with your own Nexus account to check your mods "
                         "for updates, fill in their details, and open the "
                         "site's Mod Manager Download button here.",
                         size="720x660")
        self.worker = _Worker(self)
        self.primary = button(self.foot, "Close", self.destroy, "quiet",
                              app.f_small, (14, 7))
        self.primary.pack(side="right")
        self.render()

    def render(self):
        self.clear()
        if palnexus.connected():
            self._connected()
        else:
            self._disconnected()

    # -- not connected ---------------------------------------------------
    def _disconnected(self):
        app = self.app
        self.section("Connect")
        self.note("1.  Open your API keys page on Nexus and copy the Personal "
                  "API Key at the bottom.", TEXT, pady=(0, 2))
        row = tk.Frame(self.body, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=(2, 8))
        button(row, "Open API keys page", lambda: open_link(palnexus.KEY_PAGE),
               "quiet", app.f_small, (12, 5), icon_name="external").pack(side="left")
        self.note("2.  Paste it here and press Connect.", TEXT, pady=(4, 2))

        row = tk.Frame(self.body, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=(2, 4))
        self.key_var = tk.StringVar()
        self.key_entry = tk.Entry(row, textvariable=self.key_var, show="•",
                                  bg=RAISED, fg=TEXT, insertbackground=TEXT,
                                  relief="flat", font=app.f_small)
        self.key_entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)
        button(row, "Paste", self._paste, "quiet", app.f_small,
               (10, 5)).pack(side="left", padx=(6, 0))
        self.connect_btn = button(row, "Connect", self._connect, "primary",
                                  app.f_small, (14, 5))
        self.connect_btn.pack(side="left", padx=(6, 0))
        self.key_entry.bind("<Return>", lambda _e: self._connect())
        self.msg = self.note("", DIM, pady=(4, 2))

        self.section("What connecting does")
        for line in (
                "Your key is kept in Windows Credential Manager, not in the "
                "app's files, and is only ever sent to api.nexusmods.com.",
                "Requests carry the ID numbers of the Nexus mods you have "
                "installed and nothing else about your PC.",
                "Update checks ask Nexus once for everything that changed "
                "this month, then only about the mods of yours that did.",
                "Nothing is downloaded until you press a button that says so.",
                "Disconnect here at any time; that deletes the key."):
            self.note(line, DIM, pady=(0, 4), icon_name="dot")

    def _paste(self):
        try:
            self.key_var.set(self.clipboard_get().strip())
        except tk.TclError:
            self.msg.config(text="There's nothing on the clipboard.", fg=WARN)

    def _connect(self):
        key = self.key_var.get().strip()
        if not palnexus.looks_like_key(key):
            self.msg.config(text="That doesn't look like an API key. Copy the "
                                 "whole Personal API Key from the Nexus page.",
                            fg=WARN)
            return
        self.connect_btn.config(state="disabled")
        self.msg.config(text="Checking the key with Nexus…", fg=DIM)
        self.worker.run(lambda: palnexus.validate(key),
                        lambda acct: self._connected_ok(key, acct),
                        self._connect_failed)

    def _connected_ok(self, key, acct):
        try:
            palnexus.set_key(key)
        except palnexus.NexusError as exc:
            self._connect_failed(exc)
            return
        self.app.nexus_changed()
        self.render()
        self.app.flash(f"Connected to Nexus Mods as {acct['name']}")
        if palpaths.load_settings().get("nexus_check_updates", True):
            self.app.check_nexus_updates()

    def _connect_failed(self, exc):
        if not self.winfo_exists():
            return
        self.connect_btn.config(state="normal")
        self.msg.config(text=str(exc), fg=BAD)

    # -- connected -------------------------------------------------------
    def _connected(self):
        app = self.app
        acct = palnexus.account()
        self.section("Account")
        if acct:
            kind = ("Premium" if acct["premium"] else
                    "Supporter" if acct["supporter"] else "Free account")
            self.acct = self.note(f"Connected as {acct['name']}   ·   {kind}",
                                  TEXT, icon_name="check")
        else:
            self.acct = self.note("Connected. Checking the account…", DIM)
            self.worker.run(palnexus.validate, lambda _a: self.render(),
                            lambda exc: self.acct.config(text=str(exc), fg=BAD))
        if acct and not acct["premium"]:
            self.note("Free accounts download from the website: press Mod "
                      "Manager Download on a mod's Files tab. Premium members "
                      "can also update straight from this app.", FAINT)

        self.section("Use it to")
        s = palpaths.load_settings()
        self.v_updates = tk.BooleanVar(value=s.get("nexus_check_updates", True))
        self.v_fill = tk.BooleanVar(value=s.get("nexus_autofill", True))
        for var, key, text in (
                (self.v_updates, "nexus_check_updates",
                 "Check for mod updates when the app opens"),
                (self.v_fill, "nexus_autofill",
                 "Fill in the description and picture when installing a Nexus mod")):
            row = tk.Frame(self.body, bg=SURFACE)
            row.pack(fill="x", padx=22, pady=3)
            checkbox(row, var, SURFACE, app.f_small, text,
                     command=lambda v=var, k=key: palpaths.save_settings(
                         {k: bool(v.get())})).pack(side="left")

        st = palnexus.handler_status()
        if st["supported"]:
            self.v_nxm = tk.BooleanVar(value=st["ours"])
            row = tk.Frame(self.body, bg=SURFACE)
            row.pack(fill="x", padx=22, pady=3)
            checkbox(row, self.v_nxm, SURFACE, app.f_small,
                     "Open the website's Mod Manager Download button here",
                     command=self._toggle_handler).pack(side="left")
            if st["ours"]:
                note = "Mod Manager Download opens here."
            elif st["owner"]:
                note = (f"Right now {st['owner']} opens them. Turning this on "
                        f"switches them here; turning it off gives them back.")
            else:
                note = "Nothing on this PC opens them yet."
            self.note(note, FAINT, pady=(0, 4))

        self.section("Updates")
        when = palnexus.last_checked()
        self.note(f"Last checked {datetime.fromtimestamp(when):%d %b, %H:%M}."
                  if when else "Not checked yet.", DIM)
        row = tk.Frame(self.body, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=(4, 4))
        button(row, "Check now", self._check, "quiet", app.f_small,
               (12, 5)).pack(side="left")
        q = palnexus.quota
        if q["hourly"] is not None:
            self.note(f"Nexus allows this key {q['hourly']} more requests this "
                      f"hour and {q['daily']} today.", FAINT, pady=(6, 2))

        self.section("Disconnect")
        self.note("Deletes the key from this PC. Links to mod pages stay.", DIM)
        row = tk.Frame(self.body, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=(4, 12))
        button(row, "Disconnect", self._disconnect, "danger", app.f_small,
               (12, 5)).pack(side="left")

    def _toggle_handler(self):
        try:
            if self.v_nxm.get():
                st = palnexus.handler_status()
                if st["owner"] and not st["ours"] and not messagebox.askyesno(
                        TITLE, f"{st['owner']} opens Nexus download links now.\n\n"
                               f"Switch them to EZ Pal Mod Manager? Turning this "
                               f"off later gives them back to {st['owner']}.",
                        parent=self):
                    self.v_nxm.set(False)
                    return
                palnexus.register_handler()
                self.app.flash("Mod Manager Download now opens here")
            else:
                back = palnexus.unregister_handler()
                self.app.flash(f"Download links handed back to {back}" if back
                               else "Download links no longer open here")
        except (palnexus.NexusError, OSError) as exc:
            messagebox.showerror(TITLE, f"Couldn't change that:\n\n{exc}",
                                 parent=self)
        self.render()

    def _check(self):
        self.app.check_nexus_updates(force=True, report=True)
        self.status.config(text="Checking…", fg=DIM)

    def _disconnect(self):
        if not messagebox.askyesno(TITLE, "Disconnect from Nexus Mods? The key "
                                          "is deleted from this PC.", parent=self):
            return
        try:
            palnexus.clear_key()
        except palnexus.NexusError as exc:
            messagebox.showerror(TITLE, str(exc), parent=self)
            return
        self.app.nexus_changed()
        self.render()
        self.app.flash("Disconnected from Nexus Mods")


# ==========================================================================
# downloading one file
# ==========================================================================
class DownloadWindow(Window):
    """Download a file from Nexus and hand it to the install window.

    Opened by a Mod Manager Download link (which carries a one-time key that
    lets free accounts download) or by Update for a Premium member. Shows
    what will be fetched first; nothing is downloaded until Download.
    """

    def __init__(self, app, mod_id, file_id=None, link=None):
        super().__init__(app, "Download from Nexus", "", size="680x500")
        self.mod_id, self.file_id, self.link = int(mod_id), file_id, link
        self.info = self.file = None
        self.worker = _Worker(self)
        self.go = button(self.foot, "Download and install", self._start,
                         "primary", app.f_name, (18, 8))
        self.go.pack(side="right")
        self.go.config(state="disabled")
        self.page_btn = button(self.foot, "Open on Nexus", self._open_page,
                               "quiet", app.f_small, (12, 6))
        self.page_btn.pack(side="right", padx=(0, 8))
        self._look()

    def _look(self):
        self.clear()
        if not palnexus.connected():
            self._need_key()
            return
        self.note("Asking Nexus about this file…", DIM, pady=(18, 4))
        self.go.config(state="disabled")

        def look():
            info = palnexus.mod_info(self.mod_id, refresh=True)
            if info.get("missing") or not info.get("available", True):
                raise palnexus.NexusError("That mod isn't available on Nexus "
                                          "any more.", code=404)
            if self.file_id is None:
                f = palnexus.newest_file(
                    palnexus.mod_files(self.mod_id, refresh=True)["files"])
                if not f:
                    raise palnexus.NexusError("That mod has no files to download.")
            else:
                f = palnexus.find_file(self.mod_id, self.file_id)
            return info, f
        self.worker.run(look, self._ready, self._failed)

    def _need_key(self):
        self.section("Connect to Nexus first")
        self.note("Downloads go through Nexus's API, which needs your own API "
                  "key. It takes a minute and only has to be done once.", DIM)
        row = tk.Frame(self.body, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=8)
        button(row, "Connect…", lambda: NexusWindow(self.app), "quiet",
               self.app.f_small, (12, 5)).pack(side="left")
        button(row, "Try again", self._look, "ghost", self.app.f_small,
               (10, 5)).pack(side="left", padx=6)

    def _ready(self, got):
        if not self.winfo_exists():
            return
        self.info, self.file = got
        self.file_id = self.file["id"]
        self.clear()
        f, info = self.file, self.info
        self.subtitle.config(text=info.get("name") or f"Nexus mod {self.mod_id}")
        self.section("What will be downloaded")
        _details(self, [
            ("Mod", f"{info.get('name') or self.mod_id}"
                    + (f"   ·   by {info['author']}" if info.get("author") else "")),
            ("File", f["name"] + (f"   ·   v{f['version']}" if f["version"] else "")),
            ("Uploaded", _when(f["uploaded"])),
            ("Size", human_size(f["size"]) if f["size"] else "?"),
            ("From", "nexusmods.com"),
        ])
        installed = [n for n, e in self.app._data["registry"].items()
                     if str(e.get("id")) == str(self.mod_id)
                     and e.get("source") == "Nexus"] if self.app._data else []
        if installed:
            e = self.app._data["registry"][installed[0]]
            self.note(f"You have {e.get('version') and 'v' + e['version'] or 'a copy'} "
                      f"installed as {', '.join(installed)}. Your settings "
                      f"files are kept through the update.", DIM, pady=(10, 2),
                      icon_name="undo")
        self.note("You'll see what's in it and where each part goes before "
                  "anything is installed.", FAINT, pady=(6, 2))
        if self.link and palnexus.link_expired(self.link):
            self.note("This link has expired. Press Mod Manager Download on the "
                      "Nexus page again.", WARN, pady=(6, 2), icon_name="alert")
            return
        self.go.config(state="normal")

    def _failed(self, exc):
        if not self.winfo_exists():
            return
        self.clear()
        self.section("That didn't work")
        self.note(str(exc), BAD, pady=(2, 6), icon_name="error")
        if getattr(exc, "code", None) == 403:
            self.note("On the Nexus page, open the Files tab and press Mod "
                      "Manager Download. That opens here with a link that "
                      "lets any account download.", DIM, pady=(4, 2))
        else:
            self.note("You can still download it from the Nexus page and "
                      "install the file here.", DIM, pady=(4, 2))
        self.status.config(text="", fg=DIM)
        self.go.config(text="Try again", state="normal", command=self._retry)

    def _retry(self):
        self.go.config(text="Download and install", command=self._start)
        self._look()

    def _start(self):
        if self.app._paths and palsafety.game_running(self.app._paths["game"]):
            messagebox.showwarning(TITLE, "Close Palworld first. Its files are "
                                   "in use while it runs.", parent=self)
            return
        self.go.config(state="disabled")
        self.status.config(text="Downloading…", fg=DIM)
        self.worker.run(
            lambda progress: palnexus.download(
                self.mod_id, self.file_id, palnexus.downloads_dir(),
                link=self.link, progress=progress),
            self._done, self._failed, progress=self._progress)

    def _progress(self, done, total):
        if self.winfo_exists():
            self.status.config(
                text=f"Downloading   {human_size(done)} of {human_size(total)}"
                if total else f"Downloading   {human_size(done)}")

    def _done(self, got):
        path, f = got
        self.destroy()
        self.app.install_downloaded(path, self.mod_id, f)

    def _open_page(self):
        open_link(palnexus.FILES_PAGE.format(id=self.mod_id))


# ==========================================================================
# updates
# ==========================================================================
class UpdatesWindow(Window):
    """Every Nexus mod with a newer version, and one button each."""

    def __init__(self, app):
        super().__init__(app, "Updates on Nexus", "", size="720x560")
        button(self.foot, "Close", self.destroy, "quiet", app.f_small,
               (14, 7)).pack(side="right")
        button(self.foot, "Check again", self._check, "ghost", app.f_small,
               (10, 7)).pack(side="right", padx=8)
        self.render()

    def render(self):
        self.clear()
        ups = self.app._nexus_updates
        live = {n: u for n, u in ups.items() if not u["removed"]}
        gone = {n: u for n, u in ups.items() if u["removed"]}
        when = palnexus.last_checked()
        self.subtitle.config(
            text=(f"{plural(len(live), 'mod')} with a newer version"
                  if live else "Everything from Nexus is up to date")
            + (f"   ·   checked {datetime.fromtimestamp(when):%d %b, %H:%M}"
               if when else ""))
        acct = palnexus.account() or {}
        premium = acct.get("premium")
        if live and not premium:
            handler = palnexus.handler_status()
            self.note("Update opens the mod's Files tab on Nexus. Press Mod "
                      "Manager Download there"
                      + (" and it opens here." if handler["ours"] else
                         ", or download it and install the file here."),
                      DIM, pady=(14, 2))
        if live:
            self.section("Updates", len(live))
            for name, u in sorted(live.items()):
                self._row(name, u, premium)
        if gone:
            self.section("No longer on Nexus", len(gone))
            self.note("Their pages were removed or hidden. The mods still work "
                      "as installed, but won't get updates.", FAINT)
            for name, u in sorted(gone.items()):
                self._row(name, u, premium, removed=True)

    def _row(self, name, u, premium, removed=False):
        card = self.card()
        top = tk.Frame(card, bg=RAISED)
        top.pack(fill="x", padx=12, pady=(8, 8))
        entry = (self.app._data or {}).get("registry", {}).get(name, {})
        tk.Label(top, text=name, bg=RAISED, fg=TEXT,
                 font=self.app.f_name).pack(side="left")
        if not removed:
            have = entry.get("version")
            tk.Label(top, text=(f"   v{have}  →  v{u['version']}" if have
                                else f"   v{u['version']} available"),
                     bg=RAISED, fg=GOOD, font=self.app.f_small).pack(side="left")
            button(top, "Update", lambda n=name: self.app.update_mod(n),
                   "quiet", self.app.f_small, (12, 4),
                   icon_name="download").pack(side="right")
        button(top, "Page", lambda: open_link(palnexus.MOD_PAGE.format(
            id=u["mod_id"])), "ghost", self.app.f_small, (8, 4),
            icon_name="external").pack(side="right", padx=4)

    def _check(self):
        self.status.config(text="Checking…", fg=DIM)
        self.app.check_nexus_updates(force=True, report=True)
