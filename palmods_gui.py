#!/usr/bin/env python3
"""EZ Pal Mod Manager -- desktop app.

Install mods, turn them on and off, see what actually loaded last session, and
get told when something is in the wrong folder. Toggles take effect the next
time the game starts, which is why this lives outside it.

Tkinter only, so it runs on a stock Python and freezes to a single .exe.

    python palmods_gui.py                 open the app
    python palmods_gui.py <mod.zip>       open it ready to install that file
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import palicons
import palinfo
import palinstall
import palmedia
import palmods
import palpaths
import palregistry
import palsafety
import palwindows

from palui import (open_link, BG, SURFACE, RAISED, HOVER, LINE, TEXT, DIM, FAINT, ACCENT, GOOD, WARN, BAD, PEND,
                   ON_ACCENT, ACCENT_HI, PROBLEM_BG, TITLE_FONT, BODY_FONT, STRONG_FONT,
                   icon, plural,
                   rounded, open_in_explorer, Toggle, Pill, Dot, button, scroller,
                   menu as dark_menu, dark_titlebar)


# Filters shown as tabs above the list. The point is to answer the two
# questions people actually open this for: what is broken, and what is on.
FILTERS = ("All", "Working", "Problems", "Off")


# ============================================================== setup
class SetupWindow(tk.Toplevel):
    """Point the app at a Palworld install.

    Shown automatically when no install can be found, and from Settings any
    time. Auto-detection covers Steam and Xbox; Browse covers everything else,
    and quietly corrects the folder if you pick Win64 or the Steam library.
    """

    def __init__(self, app, first_run=False):
        super().__init__(app.root)
        self.app, self.chosen = app, None
        self.title("Palworld folder")
        self.geometry("660x420")
        self.configure(bg=BG)
        self.transient(app.root)
        self.after(10, lambda: dark_titlebar(self))
        self.grab_set()

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=20, pady=(18, 0))
        tk.Label(head, text="Where is Palworld?", bg=BG, fg=TEXT,
                 font=app.f_title).pack(anchor="w")
        msg = ("Pick your install so the app knows where mods go."
               if not first_run else
               "Palworld was not found automatically. Pick the folder that "
               "contains Pal\\Binaries\\Win64.")
        # The last install is still on disk but the game itself is gone: that's
        # what uninstalling in Steam leaves behind (mods and UE4SS stay).
        saved = palpaths.load_settings().get("game_path")
        if first_run and saved and Path(saved).is_dir() and not palpaths.validate(saved)[0]:
            msg = (f"Palworld is no longer installed at {saved}. Your mods, UE4SS "
                   f"and saves are still there. Reinstall Palworld to the same "
                   f"folder in Steam and they'll be picked up again, or choose "
                   f"another install below.")
        tk.Label(head, text=msg, bg=BG, fg=DIM, font=app.f_small,
                 wraplength=600, justify="left").pack(anchor="w", pady=(4, 0))

        # Footer first: pack gives space in order, so an expanding body packed
        # before it would push the buttons off the bottom of a short window.
        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=20, pady=(0, 18))
        self.status = tk.Label(foot, text="", bg=BG, fg=DIM, font=app.f_small)
        self.status.pack(side="left")
        button(foot, "Use this folder", self._accept, "primary",
               app.f_name, (18, 8)).pack(side="right")
        button(foot, "Browse…", self._browse, "quiet", app.f_small,
               (14, 8)).pack(side="right", padx=8)
        button(foot, "Search again", self._scan, "ghost",
               app.f_small).pack(side="right")

        wrap, self.body = scroller(self, BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=14)
        self._scan()

    def _scan(self):
        for w in self.body.winfo_children():
            w.destroy()
        hits = palpaths.known_installs()
        current = palpaths.game()
        if not hits:
            tk.Label(self.body, text="No install found. Use Browse to pick it.",
                     bg=BG, fg=WARN, font=self.app.f_body).pack(anchor="w", pady=12)
            return
        for h in hits:
            self._option(h["path"], f"{h['label']}  ·  found via {h['source']}",
                         selected=current and Path(h["path"]) == Path(current))

    def _option(self, path, source, selected=False):
        row = tk.Frame(self.body, bg=RAISED if selected else SURFACE,
                       highlightthickness=1,
                       highlightbackground=ACCENT if selected else LINE)
        row.pack(fill="x", pady=4)
        inner = tk.Frame(row, bg=row["bg"])
        inner.pack(fill="x", padx=12, pady=9)
        tk.Label(inner, text=str(path), bg=row["bg"], fg=TEXT,
                 font=self.app.f_name, anchor="w").pack(fill="x")
        tk.Label(inner, text=source, bg=row["bg"], fg=FAINT,
                 font=self.app.f_small, anchor="w").pack(fill="x")
        for w in (row, inner, *inner.winfo_children()):
            w.bind("<Button-1>", lambda _e, p=path: self._pick(p))
            w.configure(cursor="hand2")
        if selected:
            self.chosen = Path(path)
            self.status.config(text="Currently in use.")

    def _pick(self, path):
        self.chosen = Path(path)
        self.status.config(text=f"Selected {Path(path).name}")
        self._scan_mark()

    def _scan_mark(self):
        for w in self.body.winfo_children():
            w.destroy()
        hits = palpaths.known_installs()
        for h in hits:
            self._option(h["path"], f"{h['label']}  ·  found via {h['source']}",
                         selected=Path(h["path"]) == self.chosen)
        if self.chosen and not any(Path(h["path"]) == self.chosen for h in hits):
            self._option(self.chosen, "you picked it", selected=True)

    def _browse(self):
        picked = filedialog.askdirectory(title="Select your Palworld folder")
        if not picked:
            return
        fixed = palpaths.normalise(picked)
        if not fixed:
            messagebox.showerror(
                "EZ Pal Mod Manager",
                "That is not a Palworld install.\n\nPick the folder that "
                "contains Pal\\Binaries\\Win64, usually …\\steamapps\\"
                "common\\Palworld.", parent=self)
            return
        self.chosen = fixed
        self._scan_mark()
        self.status.config(text=f"Selected {fixed}")

    def _accept(self):
        if not self.chosen:
            self.status.config(text="Pick a folder first.")
            return
        self.destroy()
        self.app.switch_install(self.chosen)


# ============================================================== installer
class InstallWindow(tk.Toplevel):
    """Show what an archive contains and where each piece would go.

    Nothing is written until Install is pressed, and each piece can be left
    out -- archives often bundle an optional extra you do not want.
    """

    def __init__(self, app, source, remaining=0):
        super().__init__(app.root)
        self.app, self.plan, self.vars = app, None, {}
        self.title("Install mod" + (f"  ({remaining} more after this)" if remaining else ""))
        self.geometry("760x640")
        self.minsize(620, 420)
        self.configure(bg=BG)
        self.transient(app.root)
        self.after(10, lambda: dark_titlebar(self))

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=20, pady=(18, 0))
        self.h1 = tk.Label(head, text=Path(source).name, bg=BG, fg=TEXT,
                           font=app.f_title, anchor="w")
        self.h1.pack(anchor="w")
        self.sub = tk.Label(head, text="Reading…", bg=BG, fg=DIM,
                            font=app.f_small, anchor="w", justify="left",
                            wraplength=700)
        self.sub.pack(anchor="w", pady=(4, 0))

        # Where the zip came from. Optional; a Nexus download fills it in from
        # the file name, a CurseForge one needs the page pasted.
        linkrow = tk.Frame(head, bg=BG)
        linkrow.pack(fill="x", pady=(12, 0))
        tk.Label(linkrow, text="Mod page", bg=BG, fg=DIM, font=app.f_small,
                 width=9, anchor="w").pack(side="left")
        self.link_var = tk.StringVar()
        self.link_entry = tk.Entry(linkrow, textvariable=self.link_var, bg=RAISED,
                                   fg=TEXT, insertbackground=TEXT, relief="flat",
                                   font=app.f_small)
        self.link_entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)
        button(linkrow, "Paste link", self._paste_link, "quiet", app.f_small,
               (10, 5)).pack(side="left", padx=(6, 0))
        self.link_note = tk.Label(head, text="", bg=BG, fg=FAINT, font=app.f_small,
                                  anchor="w")
        self.link_note.pack(fill="x", padx=(0, 0), pady=(3, 0))
        self._link_origin = ""
        self.link_var.trace_add("write", lambda *_: self._link_changed())

        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=20, pady=(0, 18))
        self.enable_var = tk.BooleanVar(value=True)
        tk.Checkbutton(foot, text="Turn on after installing",
                       variable=self.enable_var, bg=BG, fg=TEXT,
                       selectcolor=RAISED, activebackground=BG,
                       activeforeground=TEXT, font=app.f_small, bd=0,
                       highlightthickness=0, cursor="hand2").pack(side="left")
        self.go = button(foot, "Install", self._install, "primary",
                         app.f_name, (20, 8))
        self.go.pack(side="right")
        button(foot, "Cancel", self._close, "quiet", app.f_small,
               (14, 8)).pack(side="right", padx=8)

        wrap, self.body = scroller(self)
        wrap.pack(fill="both", expand=True, padx=20, pady=14)

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, lambda: self._load(source))

    def _load(self, source):
        try:
            self.plan = palinstall.inspect(source)
        except (palinstall.InstallError, OSError) as exc:
            self.sub.config(text=str(exc), fg=BAD)
            self.go.config(state="disabled")
            return
        self._render()

    def _render(self):
        plan = self.plan
        comps = plan["components"]
        guess = palregistry.from_filename(plan["source"])
        bits = [f"{plural(len(comps), 'mod')}, {plural(plan['total_files'], 'file')}"]
        if guess.get("source") == "Nexus":
            bits.append(f"Nexus mod {guess['id']}, version {guess.get('version','?')}")
        elif guess.get("version"):
            bits.append(f"version {guess['version']}")
        self.sub.config(text="   ·   ".join(bits), fg=DIM)
        self._prefill_link(comps, guess)

        if not comps:
            self.go.config(state="disabled")

        clashes = palinstall.conflicts(plan)
        for c in comps:
            self._component(c, clashes.get(palinstall.component_id(c), []))

        for w in plan["warnings"]:
            tk.Label(self.body, text="  !  " + w, bg=SURFACE, fg=WARN,
                     font=self.app.f_small, anchor="w", justify="left",
                     wraplength=660).pack(fill="x", padx=16, pady=3)

        extras = palmedia.archive_extras(plan["skipped"])
        kept = extras["readmes"][:1] + extras["images"]
        if kept:
            bits = (["its README as the description"] if extras["readmes"] else []) + \
                   ([plural(len(extras['images']), 'picture')] if extras["images"] else [])
            tk.Label(self.body,
                     text="Also kept as mod info: " + " and ".join(bits) + ".",
                     bg=SURFACE, fg=GOOD, font=self.app.f_small, anchor="w",
                     justify="left", wraplength=660).pack(fill="x", padx=16, pady=(8, 0))
        ignored = [f for f in plan["skipped"] if f not in kept]
        if ignored:
            are = "isn't" if len(ignored) == 1 else "aren't"
            tk.Label(self.body,
                     text=f"{plural(len(ignored), 'file')} in the archive {are} "
                          f"part of a mod and will be skipped "
                          f"({', '.join(ignored[:3])}"
                          f"{'…' if len(ignored) > 3 else ''})",
                     bg=SURFACE, fg=FAINT, font=self.app.f_small, anchor="w",
                     justify="left", wraplength=660).pack(fill="x", padx=16,
                                                          pady=(8, 4))

    def _component(self, c, clash):
        app = self.app
        card = tk.Frame(self.body, bg=RAISED, highlightthickness=1,
                        highlightbackground=LINE)
        card.pack(fill="x", padx=14, pady=6)
        top = tk.Frame(card, bg=RAISED)
        top.pack(fill="x", padx=12, pady=(10, 2))

        var = tk.BooleanVar(value=True)
        # By kind and name: a hybrid mod's Lua and PalSchema halves often
        # share a folder name, and each gets its own checkbox.
        self.vars[palinstall.component_id(c)] = (var, c)
        tk.Checkbutton(top, variable=var, bg=RAISED, fg=TEXT,
                       activebackground=RAISED, activeforeground=TEXT,
                       selectcolor=RAISED, bd=0, highlightthickness=0,
                       cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Label(top, text=c["name"], bg=RAISED, fg=TEXT,
                 font=app.f_name).pack(side="left")
        Pill(top, c["kind"], DIM, SURFACE, RAISED, app.f_pill).pack(side="left", padx=6)
        tk.Label(top, text=plural(len(c['files']), 'file'), bg=RAISED, fg=FAINT,
                 font=app.f_small).pack(side="right")

        tk.Label(card, text=f"→  {self._where(c['dest'])}", bg=RAISED, fg=TEXT,
                 font=app.f_small, anchor="w", justify="left", wraplength=660
                 ).pack(fill="x", padx=12, pady=(2, 0))
        if c["note"]:
            tk.Label(card, text=c["note"], bg=RAISED, fg=FAINT,
                     font=app.f_small, anchor="w").pack(fill="x", padx=12)
        if clash:
            tk.Label(card,
                     text=f"Replaces {plural(len(clash), 'existing file')}. The old "
                          f"copies are kept as .pmm-bak.",
                     bg=RAISED, fg=WARN, font=app.f_small, anchor="w"
                     ).pack(fill="x", padx=12, pady=(2, 0))

        files = tk.Frame(card, bg=RAISED)
        shown = [dst.name for _, dst in c["files"][:6]]
        tk.Label(files, text="   " + "  ·  ".join(shown)
                 + ("  …" if len(c["files"]) > 6 else ""),
                 bg=RAISED, fg=FAINT, font=app.f_small, anchor="w",
                 justify="left", wraplength=660).pack(fill="x")
        files.pack(fill="x", padx=12, pady=(4, 10))

    # ------------------------------------------------------------ mod page link
    def _prefill_link(self, comps, guess):
        """Fill the link from what's already known, most reliable first.

        Updating a mod keeps the page you linked last time; a Nexus file name
        names its own page. Otherwise the field stays empty -- but if the
        clipboard holds a mod page link (you likely just copied it from the
        address bar), the note offers it.
        """
        known = next((palregistry.url_for(c["name"]) for c in comps
                      if palregistry.url_for(c["name"])
                      and str(palregistry.url_for(c["name"])).startswith("http")), None)
        if known:
            self._link_origin = "kept from the last install"
            self.link_var.set(known)
        elif guess.get("source") == "Nexus" and guess.get("url"):
            self._link_origin = "from the Nexus file name"
            self.link_var.set(guess["url"])
        else:
            self._link_changed()

    def _clipboard_link(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return None
        if len(text) > 500 or "\n" in text:
            return None
        fields = palmedia.parse_link(text)
        return text if fields.get("source") in ("Nexus", "CurseForge") else None

    def _paste_link(self):
        link = self._clipboard_link()
        if not link:
            try:
                raw = self.clipboard_get().strip()
            except tk.TclError:
                raw = ""
            if not raw or "\n" in raw:
                self.link_note.config(
                    text="Copy the mod page's address from your browser first.",
                    fg=WARN)
                return
            link = raw
        self._link_origin = "pasted"
        self.link_var.set(link)

    def _link_changed(self):
        text = self.link_var.get().strip()
        if not text:
            clip = self._clipboard_link()
            if clip:
                src = palmedia.parse_link(clip)["source"]
                self.link_note.config(
                    text=f"Optional. There's a {src} link on your clipboard. "
                         f"Press Paste link to use it.", fg=GOOD)
            else:
                self.link_note.config(
                    text="Optional. Paste the Nexus or CurseForge page you "
                         "downloaded this from, so the mod links back to it.",
                    fg=FAINT)
            return
        fields = palinstall.link_fields(text)
        what = palinstall.describe_link(fields)
        origin = f" ({self._link_origin})" if self._link_origin else ""
        if fields["source"] in ("Nexus", "CurseForge"):
            self.link_note.config(text=f"Will link to {what}{origin}.", fg=GOOD)
        elif text.startswith(("http://", "https://")):
            self.link_note.config(text=f"Will link to this page{origin}.", fg=DIM)
        else:
            self.link_note.config(text="That doesn't look like a web address; "
                                       "it'll be saved as a note.", fg=WARN)
        self._link_origin = ""

    @staticmethod
    def _where(dest):
        """Destination as a game-relative path, which is what people recognise."""
        try:
            return str(Path(dest).relative_to(palmods.game_root()))
        except (ValueError, FileNotFoundError, OSError):
            return str(dest)

    def _install(self):
        chosen = [c for var, c in self.vars.values() if var.get()]
        if not chosen:
            messagebox.showinfo("EZ Pal Mod Manager", "Nothing selected.", parent=self)
            return
        try:
            lines = palinstall.apply(self.plan, chosen,
                                     enable=self.enable_var.get(),
                                     link=self.link_var.get())
        except OSError as exc:
            messagebox.showerror("EZ Pal Mod Manager",
                                 f"Install failed:\n\n{exc}", parent=self)
            return
        queued = bool(self.app._install_queue)
        self._close(advance=False)
        self.app.reload(full=True)
        self.app.flash(f"Installed {plural(len(chosen), 'mod')}. They load the next time you play.")
        # With more downloads queued, don't stop for a dialog after each one.
        if not queued:
            messagebox.showinfo("EZ Pal Mod Manager",
                                "\n".join(lines) +
                                "\n\nRestart Palworld for these to take effect.")
        self.app._next_install()

    def _close(self, advance=True):
        if self.plan:
            palinstall.discard(self.plan)
            self.plan = None
        self.destroy()
        if advance:
            # Cancelling one download moves on to the next queued one.
            self.app.root.after(50, self.app._next_install)


# ============================================================== details
class ConfigWindow(tk.Toplevel):
    """Editor for a mod's config files.

    key=value and JSON files get real controls and are written back in place,
    preserving comments and layout. Lua configs are code, so they are opened in
    the system editor instead -- rewriting them risks breaking a working mod.
    """

    def __init__(self, app, mod_name, configs):
        super().__init__(app.root)
        self.app, self.mod_name = app, mod_name
        self.configs = [Path(c) for c in configs]
        self.edits = {}          # path -> {field id: new value}

        self.title(f"{mod_name} settings")
        self.geometry("640x620")
        self.minsize(520, 380)
        self.configure(bg=BG)
        self.transient(app.root)
        self.after(10, lambda: dark_titlebar(self))

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(head, text=mod_name, bg=BG, fg=TEXT,
                 font=app.f_title).pack(side="left")
        tk.Label(head, text=plural(len(self.configs), "config file"), bg=BG,
                 fg=FAINT, font=app.f_small).pack(side="left", padx=(12, 0),
                                                  pady=(7, 0))

        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=18, pady=(0, 16))
        self.status = tk.Label(foot, text="", bg=BG, fg=DIM, font=app.f_small)
        self.status.pack(side="left")
        self.save_btn = tk.Button(foot, text="Save", command=self.save, bd=0,
                                  relief="flat", bg=RAISED, fg=FAINT,
                                  font=app.f_name, padx=20, pady=8,
                                  state="disabled", cursor="arrow")
        self.save_btn.pack(side="right")

        wrap, self.body = scroller(self)
        wrap.pack(fill="both", expand=True, padx=18, pady=14)
        self._build()

    def _build(self):
        app = self.app
        for path in self.configs:
            info = palmods.load_config(path)
            hdr = tk.Frame(self.body, bg=SURFACE)
            hdr.pack(fill="x", padx=16, pady=(14, 4))
            tk.Label(hdr, text=path.name, bg=SURFACE, fg=TEXT,
                     font=app.f_name).pack(side="left")
            tk.Label(hdr, text=f"  {info['kind']}", bg=SURFACE, fg=FAINT,
                     font=app.f_pill).pack(side="left")
            tk.Button(hdr, text="Open file", bd=0, relief="flat", bg=SURFACE,
                      fg=FAINT, font=app.f_small, cursor="hand2",
                      activebackground=SURFACE, activeforeground=ACCENT,
                      command=lambda p=path: self._open(p)).pack(side="right")

            if info["kind"] == "lua":
                tk.Label(self.body,
                         text="This is a Lua file, so it opens in your editor rather "
                              "than here, where a bad edit could break the mod.",
                         bg=SURFACE, fg=FAINT, font=app.f_small, anchor="w",
                         justify="left").pack(fill="x", padx=16, pady=(0, 4))
                continue
            if info["kind"] == "error":
                tk.Label(self.body, text="   " + info["error"], bg=SURFACE,
                         fg=BAD, font=app.f_small, anchor="w").pack(fill="x", padx=16)
                continue
            if not info["fields"]:
                tk.Label(self.body, text="   No editable settings found.",
                         bg=SURFACE, fg=FAINT, font=app.f_small,
                         anchor="w").pack(fill="x", padx=16)
                continue

            section = None
            for fld in info["fields"]:
                if fld["section"] != section:
                    section = fld["section"]
                    if section:
                        tk.Label(self.body, text="   [" + section + "]", bg=SURFACE,
                                 fg=FAINT, font=app.f_pill, anchor="w"
                                 ).pack(fill="x", padx=16, pady=(8, 2))
                self._field(path, fld)

    def _field(self, path, fld):
        app = self.app
        row = tk.Frame(self.body, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=2)
        tk.Label(row, text=fld["label"], bg=SURFACE, fg=DIM, font=app.f_small,
                 anchor="w", width=32).pack(side="left")

        if fld["type"] == "bool":
            def flip(v, p=path, f=fld):
                self.edits.setdefault(str(p), {})[f["id"]] = v
                self._touch()
            Toggle(row, bool(fld["value"]), flip, SURFACE).pack(side="left")
        else:
            var = tk.StringVar(value=str(fld["value"]))

            def changed(*_a, p=path, f=fld, v=var):
                raw = v.get()
                if f["type"] == "number":
                    try:
                        raw = float(raw) if "." in raw else int(raw)
                    except ValueError:
                        pass
                self.edits.setdefault(str(p), {})[f["id"]] = raw
                self._touch()

            var.trace_add("write", changed)
            tk.Entry(row, textvariable=var, bg=RAISED, fg=TEXT, relief="flat",
                     insertbackground=TEXT, font=app.f_small, width=26
                     ).pack(side="left", ipady=3, ipadx=6)

    def _touch(self):
        n = sum(len(v) for v in self.edits.values())
        self.status.config(text=f"{plural(n, 'setting')} changed")
        self.save_btn.config(state="normal", bg=ACCENT, fg=ON_ACCENT,
                             cursor="hand2", activebackground=ACCENT_HI,
                             activeforeground=ON_ACCENT)

    def _open(self, path):
        # Always a text editor: a plain startfile on a mod's config.lua would
        # *run* it if .lua is associated with an interpreter.
        try:
            subprocess.Popen(["notepad.exe", str(path)])
        except OSError as exc:
            messagebox.showerror("EZ Pal Mod Manager", str(exc))

    def save(self):
        msgs = []
        for spath, updates in self.edits.items():
            if updates:
                msgs.append(palmods.save_config(spath, updates))
        self.edits.clear()
        self.save_btn.config(state="disabled", bg=RAISED, fg=FAINT, cursor="arrow")
        self.status.config(text="Saved. Takes effect the next time you play.")
        if msgs:
            messagebox.showinfo("EZ Pal Mod Manager", "\n".join(msgs) +
                                "\n\nRestart Palworld for these to take effect.")


# ============================================================== main window
class App:
    def __init__(self, root, pending_install=None):
        self.root = root
        root.title("EZ Pal Mod Manager")
        root.geometry("1040x720")
        root.minsize(880, 520)
        root.configure(bg=SURFACE)

        # Icons and switches are drawn in pixels; match them to the screen.
        try:
            palicons.set_scale(root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            pass
        self.f_title = tkfont.Font(family=TITLE_FONT, size=17)
        self.f_head  = tkfont.Font(family=TITLE_FONT, size=12)
        self.f_body  = tkfont.Font(family=BODY_FONT, size=10)
        self.f_name  = tkfont.Font(family=STRONG_FONT, size=10)
        self.f_small = tkfont.Font(family=BODY_FONT, size=9)
        self.f_pill  = tkfont.Font(family=STRONG_FONT, size=8)
        self.f_play  = tkfont.Font(family=TITLE_FONT, size=12)

        self.rows = {}
        self._thumbs = {}            # (path, mtime) -> PhotoImage, kept across renders
        self._install_queue = []     # downloads waiting for their install window
        self.headers = {}
        self._order = []
        self._sig = None
        self._data = None
        self._paths = None
        self._issues = []
        self._entries_cache = []
        self._search_job = None
        self._flash_job = None
        self._filter = tk.StringVar(value="")
        self._tab = tk.StringVar(value="All")
        self._filter.trace_add("write", self._search_changed)

        # Play sessions. A background thread polls the process list; the UI
        # only ever reads its queue, since Tk must not be touched off-thread.
        self._events = queue.Queue()
        self._running = False
        self._launched_by_us = False
        self._session_start = None
        self._watch_game = None
        threading.Thread(target=self._watch_loop, daemon=True).start()

        self._chrome()

        if palpaths.game() is None:
            self.root.after(120, lambda: SetupWindow(self, first_run=True))
        else:
            self.reload(full=True)
            if pending_install:
                self.root.after(200, lambda: self.queue_installs(pending_install))

        root.bind("<FocusIn>", lambda e: self._poll(once=True))
        root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        root.bind("<F5>", lambda e: self.reload(full=True))
        root.after(2500, self._poll)
        root.after(700, self._drain_events)

    # ---------------------------------------------------------------- chrome
    def _chrome(self):
        # ---- header band: mark, title, status line, actions
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x")
        band = tk.Frame(top, bg=BG)
        band.pack(fill="x", padx=22, pady=16)

        # Actions are packed before the title so a narrow window squeezes
        # the title block, never the buttons.
        self.play_btn = button(band, "Play", self.play, "primary", self.f_play,
                               (22, 7), icon_name="play")
        self.play_btn.pack(side="right")
        button(band, "Install", self.install_dialog, "quiet", self.f_body,
               (14, 7), icon_name="download").pack(side="right", padx=8)
        more = button(band, "", self.more_menu, "quiet", self.f_body, (9, 7),
                      icon_name="more")
        more.pack(side="right")

        tk.Label(band, image=palicons.logo_photo(40), bg=BG).pack(side="left",
                                                                  padx=(0, 14))
        titles = tk.Frame(band, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text="EZ Pal Mod Manager", bg=BG, fg=TEXT,
                 font=self.f_title, anchor="w").pack(fill="x")
        metarow = tk.Frame(titles, bg=BG)
        metarow.pack(fill="x")
        self.meta_icon = tk.Label(metarow, bg=BG)
        self.meta_icon.pack(side="left", padx=(0, 5))
        self.meta = tk.Label(metarow, text="", bg=BG, fg=DIM,
                             font=self.f_small, anchor="w")
        self.meta.pack(side="left")
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

        # ---- tabs + search
        bar = tk.Frame(self.root, bg=SURFACE)
        bar.pack(fill="x", padx=22, pady=(12, 0))
        self.tabs = tk.Frame(bar, bg=SURFACE)
        self.tabs.pack(side="left", anchor="s")
        self._tab_btns = {}
        for name in FILTERS:
            holder = tk.Frame(self.tabs, bg=SURFACE, cursor="hand2")
            holder.pack(side="left", padx=(0, 20))
            lbl = tk.Label(holder, text=name, bg=SURFACE, fg=DIM,
                           font=self.f_body, cursor="hand2")
            lbl.pack(pady=(0, 6))
            line = tk.Frame(holder, bg=SURFACE, height=2)
            line.pack(fill="x")
            for w in (holder, lbl):
                w.bind("<Button-1>", lambda _e, n=name: self._set_tab(n))
            self._tab_btns[name] = (lbl, line)

        sf = tk.Frame(bar, bg=RAISED, highlightthickness=1,
                      highlightbackground=LINE, highlightcolor=LINE)
        sf.pack(side="right", pady=(0, 8))
        tk.Label(sf, image=icon("search", FAINT, 16), bg=RAISED).pack(
            side="left", padx=(10, 6), pady=6)
        self.search_entry = tk.Entry(sf, textvariable=self._filter, bg=RAISED,
                                     fg=TEXT, insertbackground=TEXT,
                                     relief="flat", font=self.f_body, width=24)
        self.search_entry.pack(side="left", padx=(0, 10), pady=6)
        self.placeholder = tk.Label(sf, text="Search mods", bg=RAISED,
                                    fg=FAINT, font=self.f_body)
        self.placeholder.place(in_=self.search_entry, x=2, y=0)
        self.placeholder.bind("<Button-1>",
                              lambda _e: self.search_entry.focus_set())
        self._filter.trace_add("write", self._placeholder)

        self.warnbox = tk.Frame(self.root, bg=SURFACE)
        self.warnbox.pack(fill="x", padx=22)

        # ---- footer (packed before the list so it can never be pushed off)
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(side="bottom", fill="x")
        tk.Frame(self.root, bg=LINE, height=1).pack(side="bottom", fill="x")
        inner = tk.Frame(foot, bg=BG)
        inner.pack(fill="x", padx=22, pady=10)
        self.status = tk.Label(inner, text="", bg=BG, fg=DIM, font=self.f_small,
                               anchor="w", justify="left")
        self.status.pack(side="left")
        self.apply_btn = button(inner, "Apply changes", self.apply, "light",
                                self.f_name, (16, 6))
        self.revert_btn = button(inner, "Undo", self.revert, "ghost",
                                 self.f_small, (10, 6), icon_name="undo")

        wrap, self.bodyf = scroller(self.root)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self._set_tab("All")

    def _placeholder(self, *_a):
        if self._filter.get():
            self.placeholder.place_forget()
        else:
            self.placeholder.place(in_=self.search_entry, x=2, y=0)

    def _set_tab(self, name):
        self._tab.set(name)
        for n, (lbl, line) in self._tab_btns.items():
            on = n == name
            lbl.config(fg=TEXT if on else DIM)
            line.config(bg=ACCENT if on else SURFACE)
        self._apply_filter()

    def flash(self, msg):
        """Say what just happened, in the status bar, without a dialog."""
        self.status.config(text=msg, fg=GOOD)
        if self._flash_job:
            self.root.after_cancel(self._flash_job)
        self._flash_job = self.root.after(6000, self._recount)

    # ---------------------------------------------------------------- data
    def reload(self, full=False):
        """Re-scan the game folders.

        `full` also refreshes the UE4SS conflict check, which hashes a DLL and
        so must never run on a repaint.
        """
        if palpaths.game() is None:
            return
        try:
            self._paths = palmods.discover()
            self._data = palmods.build(self._paths)
            palmods.write_modlist(self._paths, self._data)   # in-game panel
            self._sig = palmods.snapshot(self._paths)
            (palpaths.data_dir() / "manifest.json").write_text(
                json.dumps(self._data, indent=2), "utf8")
        except (SystemExit, FileNotFoundError) as exc:
            messagebox.showerror("EZ Pal Mod Manager", str(exc))
            SetupWindow(self, first_run=True)
            return
        except OSError as exc:
            messagebox.showerror("EZ Pal Mod Manager", str(exc))
            return

        if full:
            self._issues = palmods.doctor(False)[0]
        data = self._data
        self.meta.config(text=self._meta_text(data))
        ok = data["ue4ss"]["state"] == "ok"
        self.meta_icon.config(image=icon("check", GOOD, 14) if ok else
                              icon("alert", BAD if data["ue4ss"]["state"] in
                                   ("missing", "broken", "conflict") else WARN, 14))
        server = data["install"]["kind"] == "server"
        if not self._running:
            self.play_btn.config(text=" Start server" if server else " Play")
        self._entries_cache = self._build_entries()
        self.render()

    UE4SS_PLAIN = {"ok": "UE4SS ready", "warn": "UE4SS needs attention",
                   "missing": "UE4SS not installed", "broken": "UE4SS not working",
                   "conflict": "UE4SS installed twice"}

    def _meta_text(self, data):
        """One plain line under the title. Build numbers and layouts live in
        the banners that need them, not here."""
        from datetime import datetime
        when = (data["log"]["when"] or "").split(".")[0]
        try:
            played = "last played " + datetime.fromisoformat(when).strftime("%d %b, %H:%M")
        except ValueError:
            played = "not played with mods yet"
        return "   ·   ".join((data["install"]["label"],
                               self.UE4SS_PLAIN.get(data["ue4ss"]["state"], "UE4SS"),
                               played))

    def switch_install(self, path):
        """Point the app at another install (a second copy, or a server)."""
        if self._pending() and not messagebox.askyesno(
                "EZ Pal Mod Manager", "Switching discards changes you haven't "
                                   "applied. Continue?"):
            return
        ok, msg = palpaths.set_game(path)
        if not ok:
            messagebox.showerror("EZ Pal Mod Manager", msg)
            return
        palmods._doctor_cache.clear()
        self._watch_game = None
        self.rows.clear()
        self._paths = None
        self.reload(full=True)
        self.flash(f"Switched to {palpaths.label(path)}")

    def _build_entries(self):
        """Flatten both mod kinds into one list of display records.

        Built once per scan. The list view filters this; it must not do any
        disk work of its own.
        """
        data = self._data
        reg = data["registry"]
        # Switched on since the game last ran: they haven't had a chance yet.
        waiting = set(data["patch"].get("waiting", ()))
        conflicts, keys, patch = data["conflicts"], data["keybinds"], data["patch"]
        out = []

        def safety_notes(name, on, kind):
            """(notes, warn, problem) from conflicts, hotkeys and patches.

            File conflicts are between paks and hotkeys belong to UE4SS mods,
            so a row only hears about its own kind, even when a mod of
            another kind has the same name.
            """
            notes, warn, problem = [], False, False
            paks = kind == "pak"
            for idx in (conflicts["by_mod"].get(name, []) if paks else []):
                c = conflicts["pairs"][idx]
                other = c["mods"][1] if c["mods"][0] == name else c["mods"][0]
                n = c["assets"]
                if not on:
                    continue
                if c["live"]:
                    if c["winner"] == name:
                        notes.append(f"overrides {plural(n, 'file')} also in {other}")
                        warn = True
                    else:
                        notes.append(f"{other} overrides {n} of its {'file' if n == 1 else 'files'}"
                                     + ("" if c["sure"] else " (likely)"))
                        problem = True
                else:
                    notes.append(f"would clash with {other} over {plural(n, 'file')} "
                                 f"if that is turned on")
            for what in (on and paks and data.get("core_overrides", {}).get(name)) or []:
                notes.append(f"replaces {what}, so a game update can stop it "
                             f"loading or crash the game")
                warn = True
            if on and paks and name in conflicts["no_patch_suffix"]:
                notes.append("name doesn't end in _P, so it probably can't "
                             "replace the game's own files")
                warn = True
            shared = {}
            for k in (keys["by_mod"].get(name, []) if kind == "ue4ss" else []):
                if on and k["live"]:
                    for other in k["with"]:
                        shared.setdefault(other, []).append(k["key"])
            for other, ks in shared.items():
                notes.append(f"{', '.join(ks)} also bound by {other}")
                warn = True
            if name in patch["regressed"]:
                notes.append(f"loaded on {patch['regressed'][name]}, not since "
                             f"the game updated")
                problem = True
            return notes, warn, problem

        def after_patch(name, state, colour):
            """A mod last seen loading before the game updated."""
            if name in patch["unverified"] and state == "working":
                return "worked before update", DIM
            return state, colour

        for m in self._data["ue4ss_mods"]:
            if m["builtin"]:
                continue
            # Whether it is switched on now comes before what the last run
            # did: a mod turned off after a session it loaded in would
            # otherwise be reported as "loaded" while it is plainly off.
            if m["failures"] and m["enabled"]:
                state, colour, health = "error", BAD, "problem"
            elif not m["enabled"]:
                state, colour, health = "off", FAINT, "off"
            elif m["loaded"]:
                state, colour, health = "working", GOOD, "working"
            elif palregistry.mod_id("ue4ss", m["name"]) in waiting:
                state, colour, health = "starts next launch", DIM, "working"
            else:
                state, colour, health = "didn't start", WARN, "problem"
            notes = list(m["failures"]) if m["enabled"] else []
            if m.get("list_conflict"):
                notes.append(f"UE4SS's mods.txt and mods.json disagree about this "
                             f"mod; it went by {m.get('list_used') or 'mods.txt'}. "
                             f"Switching it on or off fixes both")
            if not m["enabled"] and m["loaded"]:
                notes.append("was loaded last session; off from the next launch")
            if m.get("also_in"):
                notes.append("duplicate copy in " + ", ".join(m["also_in"]))
            if m.get("inactive_root"):
                notes.append("in an inactive UE4SS folder, will not load")
                health = "problem"
            meta = reg.get(m["name"], {})
            if (age := palregistry.age_note(meta)) and "predate" in age:
                notes.append(age)
            extra_notes, warn, problem = safety_notes(m["name"], m["enabled"], "ue4ss")
            notes += extra_notes
            if problem:
                health = "problem"
            state, colour = after_patch(m["name"], state, colour)
            out.append(dict(
                warn=warn, id=palregistry.mod_id("ue4ss", m["name"]),
                group="UE4SS mods", name=m["name"], kind=m["kind"].lower(),
                where=m.get("location", "?"), extra=m["version"] or "",
                on=m["enabled"], state=state, colour=colour, health=health,
                note="; ".join(notes), path=m["path"], pak_path=None,
                configs=m.get("configs", []),
                source=palregistry.describe_source(m["name"], meta),
                url=palregistry.url_for(m["name"], meta),
                mine=meta.get("source") == "local"))

        for p in self._data["pak_mods"]:
            if p["misplaced"]:
                state, colour, health = "wrong folder", BAD, "problem"
            elif p["disabled"]:
                state, colour, health = "off", FAINT, "off"
            elif p["folder"] == "LogicMods":
                if p["loaded"]:
                    state, colour, health = "working", GOOD, "working"
                elif palregistry.mod_id("pak", p["name"]) in waiting:
                    state, colour, health = "starts next launch", DIM, "working"
                else:
                    state, colour, health = "didn't start", WARN, "problem"
            else:
                # Content paks never write to the log, so "on" is all anyone
                # can truthfully say without looking in game.
                state, colour, health = "on", DIM, "working"
            meta = reg.get(p["name"], {})
            notes = [n for n in (p.get("error"),
                                 palregistry.age_note(meta) if
                                 "predate" in (palregistry.age_note(meta) or "")
                                 else None) if n]
            if p["misplaced"]:
                notes.insert(0, f"its contents say it belongs in {p['expected_folder']}, "
                                f"not {p['folder']}")
            extra_notes, warn, problem = safety_notes(p["name"], not p["disabled"], "pak")
            notes += extra_notes
            if problem:
                health = "problem"
            state, colour = after_patch(p["name"], state, colour)
            out.append(dict(
                warn=warn, id=palregistry.mod_id("pak", p["name"]),
                group="Pak mods", name=p["name"], kind="pak",
                where=p["folder"], extra=f"v{p['pak_version']}",
                on=not p["disabled"], state=state, colour=colour,
                health=health, note="; ".join(notes), path=None,
                pak_path=p["path"], configs=[],
                source=palregistry.describe_source(p["name"], meta),
                url=palregistry.url_for(p["name"], meta),
                mine=meta.get("source") == "local"))

        for sm in data.get("palschema_mods", []):
            if not sm["enabled"]:
                state, colour, health = "off", FAINT, "off"
            elif not sm["framework"]:
                state, colour, health = "needs PalSchema", BAD, "problem"
            elif not sm["framework_on"]:
                state, colour, health = "PalSchema off", WARN, "problem"
            elif sm["loaded"]:
                state, colour, health = "working", GOOD, "working"
            else:
                state, colour, health = "on", DIM, "working"
            meta = reg.get(sm["name"], {})
            out.append(dict(
                warn=False, id=palregistry.mod_id("palschema", sm["name"]),
                group="PalSchema mods", name=sm["name"],
                kind="palschema", where="PalSchema",
                extra=", ".join(sm["sections"]), on=sm["enabled"], state=state,
                colour=colour, health=health,
                note=("PalSchema itself isn't installed" if not sm["framework"]
                      else ""),
                path=sm["path"], pak_path=None, configs=[],
                source=palregistry.describe_source(sm["name"], meta),
                url=palregistry.url_for(sm["name"], meta),
                mine=meta.get("source") == "local"))
        for e in out:
            meta = reg.get(e["name"], {})
            e["cover"] = palmedia.cover_path(e["name"], meta)
            e["search"] = " ".join((e["name"], e["source"],
                                    (meta.get("description") or "")[:4000])).lower()
        return out

    # ---------------------------------------------------------------- render
    def _search_changed(self, *_a):
        # Debounced only lightly: filtering now hides rows instead of rebuilding
        # them, so it is cheap enough to run while typing.
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(60, self._apply_filter)

    def render(self):
        """Rebuild every row from the last scan.

        Only called when the data itself changed. Filtering and searching go
        through _apply_filter, which just hides rows -- rebuilding the whole
        list on each keystroke cost a third of a second and, worse, threw away
        toggles that had been staged but not yet applied.
        """
        self._search_job = None
        staged = {mid: r["toggle"].value for mid, r in self.rows.items()
                  if r["toggle"].value != r["was"]}

        for w in self.bodyf.winfo_children():
            w.destroy()
        for w in self.warnbox.winfo_children():
            w.destroy()
        self.rows.clear()
        self.headers = {}
        self._order = []
        if not self._data:
            return

        self._banners()

        self._any_cover = any(e.get("cover") for e in self._entries_cache)
        self._order = []
        for group in ("UE4SS mods", "Pak mods", "PalSchema mods"):
            g = [e for e in self._entries_cache if e["group"] == group]
            if not g:
                continue
            self.headers[group] = self._header(group, g)
            self._order.append(("header", group, self.headers[group]["frame"]))
            for e in g:
                self._row(e)
                self._order.append(("row", e["id"], self.rows[e["id"]]["frame"]))

        self.empty = tk.Frame(self.bodyf, bg=SURFACE)
        self.empty_title = tk.Label(self.empty, text="Nothing here.", bg=SURFACE,
                                    fg=DIM, font=self.f_body)
        self.empty_title.pack()
        self.empty_hint = tk.Label(self.empty, text="", bg=SURFACE, fg=FAINT,
                                   font=self.f_small)
        self.empty_hint.pack(pady=(4, 0))

        # Toggles the user had flipped but not applied survive a rebuild.
        for mid, value in staged.items():
            if mid in self.rows:
                self._set_row(mid, value)
        self._apply_filter()

    BANNER = {"bad": ("#2a1b19", "#4d2c27", "#f2b0a7", "error"),
              "warn": ("#28231a", "#4a3d23", "#efd09a", "alert"),
              "info": ("#1c2226", "#2f3a40", "#c9d6dc", "dot")}

    def _banner(self, text, kind, actions=()):
        bg, edge, fg, glyph = self.BANNER[kind]
        b = tk.Frame(self.warnbox, bg=bg, highlightthickness=1,
                     highlightbackground=edge)
        b.pack(fill="x", pady=(10, 0))
        for label, cmd in reversed(actions):
            button(b, label, cmd, "quiet", self.f_small,
                   (10, 4)).pack(side="right", padx=(0, 8), pady=6)
        tk.Label(b, image=icon(glyph, fg, 16), bg=bg).pack(side="left", padx=(12, 8))
        lbl = tk.Label(b, text=text, bg=bg, fg=fg, font=self.f_small,
                       anchor="w", justify="left", wraplength=720)
        lbl.pack(side="left", fill="x", expand=True, pady=9)
        lbl.bind("<Configure>",
                 lambda e: e.widget.config(wraplength=max(200, e.width - 12)))

    def _banners(self):
        """The few things worth interrupting for, most serious first."""
        data = self._data
        ue = data["ue4ss"]

        # Repair's findings are technical (they name DLLs and folders); the
        # banner says what they mean, and Repair shows the specifics.
        if self._issues:
            if any("dwmapi.dll" in i for i in self._issues):
                text = ("The wrong version of UE4SS is being loaded, so most mods "
                        "won't work. Repair puts the right one back.")
            else:
                text = ("An older copy of UE4SS is left over in the game folder and "
                        "can interfere with mods. Repair tidies it away.")
            self._banner(text, "bad", [("Repair", self.repair)])

        if ue["state"] != "ok" and not (ue["state"] == "conflict" and self._issues):
            more = len(ue["problems"]) - 1
            text = ue["problems"][0] + (f"  (+{more} more)" if more > 0 else "")
            kind = "bad" if ue["state"] in ("missing", "broken", "conflict") else "warn"
            actions = [("Details", self._ue4ss_details)]
            # Missing, half-installed, or the flat build that current Palworld
            # mods don't load under: all fixed by fetching the right one.
            if ue["state"] in ("missing", "broken") or ue["layout"] == "flat":
                actions.insert(0, ("Install UE4SS", self.get_ue4ss))
            self._banner(text, kind, actions)

        # PalSchema mods are inert without the framework they patch through.
        orphans = [s["name"] for s in data.get("palschema_mods", [])
                   if s["enabled"] and not s["framework"]]
        if orphans:
            need = "needs" if len(orphans) == 1 else "need"
            self._banner(
                f"{plural(len(orphans), 'mod')} here {need} PalSchema, which "
                f"isn't installed: {', '.join(orphans[:3])}"
                + (" and more." if len(orphans) > 3 else "."),
                "bad", [("Install PalSchema", self.get_palschema)])

        patch = data["patch"]
        if patch["updated"]:
            n = len(patch["unverified"])
            text = (f"Palworld updated to {patch['build']} since your mods last ran "
                    f"(on {patch['last_run_build']}). ")
            have = "hasn't" if n == 1 else "haven't"
            text += (f"{plural(n, 'mod')} {have} loaded on this version yet. Play "
                     f"once to check." if n else "Play once to check your mods still work.")
            self._banner(text, "warn", [("Back up saves", self.open_backups),
                                        ("Play", self.play)])
        elif patch["regressed"]:
            names = ", ".join(patch["regressed"])
            self._banner(f"Stopped loading after the game updated: {names}. "
                         f"Check its page for an update.", "bad",
                         [("UE4SS log", self.open_log)])

        pairs = [c for c in data["conflicts"]["pairs"] if c["live"]]
        clashes = [c for c in data["keybinds"]["clashes"] if c["live"]]
        if pairs or clashes:
            bits = []
            if pairs:
                bits.append(f"{plural(len(pairs), 'pair')} of mods replace the same game files")
            if clashes:
                bits.append(f"{plural(len(clashes), 'hotkey')} used by more than one mod "
                            f"({', '.join(c['key'] for c in clashes[:3])})")
            self._banner(" · ".join(bits) + ".", "warn",
                         [("Review", self.open_conflicts)])

    def _ue4ss_details(self):
        ue = self._data["ue4ss"]
        body = "\n\n".join(ue["problems"])
        if ue["state"] == "missing":
            body += ("\n\nUE4SS is a script loader that most Palworld mods need. "
                     "Get the experimental-palworld build of RE-UE4SS and extract it "
                     "into Pal\\Binaries\\Win64, so that the ue4ss folder and "
                     "dwmapi.dll sit next to Palworld-Win64-Shipping.exe. Then "
                     "press Refresh.")
        messagebox.showinfo("UE4SS", body)

    def _matches(self, e, needle, tab):
        if needle and needle not in e.get("search", e["name"].lower()):
            return False
        if tab == "Working":
            return e["health"] == "working"
        if tab == "Problems":
            return e["health"] == "problem"
        if tab == "Off":
            return e["health"] == "off"
        return True

    def _apply_filter(self):
        """Show or hide already-built rows. No widgets are created here.

        Only rows whose visibility actually changed are re-packed: packing a
        widget that is already packed is not free, and doing it to the whole
        list on every keystroke is what made searching feel heavy. Re-shown
        rows are packed *before* the next still-visible widget so the list
        keeps its order instead of the row jumping to the bottom.
        """
        self._search_job = None
        if not self._order:
            return
        needle = self._filter.get().strip().lower()
        tab = self._tab.get()

        # Decide visibility for everything first, headers included.
        want, counts = {}, {}
        for kind, key, widget in self._order:
            if kind != "row":
                continue
            e = self.rows[key]["entry"]
            on = self._matches(e, needle, tab)
            want[id(widget)] = on
            counts[e["group"]] = counts.get(e["group"], 0) + (1 if on else 0)
        for kind, key, widget in self._order:
            if kind == "header":
                want[id(widget)] = counts.get(key, 0) > 0

        # Walk backwards so the anchor for `before` is always already correct.
        after = None
        for kind, key, widget in reversed(self._order):
            show = want.get(id(widget), False)
            packed = bool(widget.winfo_manager())
            if show and not packed:
                opts = (dict(fill="x", padx=18, pady=(16, 6)) if kind == "header"
                        else dict(fill="x", padx=10, pady=1))
                if after is not None:
                    opts["before"] = after
                widget.pack(**opts)
            elif packed and not show:
                widget.pack_forget()
            if show:
                after = widget

        for group, hdr in self.headers.items():
            hdr["count"].config(text="   " + str(counts.get(group, 0)))

        if not any(counts.values()):
            self.empty_hint.config(
                text="No mods match that filter."
                     if (needle or tab != "All") else
                     "Install one with the button at the top right.")
            if not self.empty.winfo_manager():
                self.empty.pack(fill="x", pady=40)
        elif self.empty.winfo_manager():
            self.empty.pack_forget()
        self._recount()

    # Group keys stay as they are internally; these are what people read.
    GROUP_TITLES = {"UE4SS mods": "Script mods (UE4SS)", "Pak mods": "Pak mods",
                    "PalSchema mods": "PalSchema mods"}

    def _header(self, title, group):
        h = tk.Frame(self.bodyf, bg=SURFACE)
        h.pack(fill="x", padx=22, pady=(14, 4))
        tk.Label(h, text=self.GROUP_TITLES.get(title, title), bg=SURFACE, fg=TEXT,
                 font=self.f_head).pack(side="left")
        count = tk.Label(h, text="  " + str(len(group)), bg=SURFACE, fg=FAINT,
                         font=self.f_small)
        count.pack(side="left", pady=(3, 0))
        # Bulk actions apply to what is currently on screen, which is what
        # makes them safe to use together with the Problems filter.
        for text, val in (("All off", False), ("All on", True)):
            button(h, text, lambda g=title, v=val: self._bulk_visible(g, v),
                   "ghost", self.f_small, (8, 2)).pack(side="right", padx=2)
        return {"frame": h, "count": count}

    def _bulk_visible(self, group, value):
        """Stage every visible row of a group on or off."""
        for mid, r in self.rows.items():
            if r["entry"]["group"] == group and r["frame"].winfo_manager():
                self._set_row(mid, value)
        self._recount()

    def _bulk(self, ids, value):
        for mid in ids:
            if mid in self.rows:
                self._set_row(mid, value)
        self._recount()

    def _set_row(self, mid, value):
        """Stage one row on or off. Rows are keyed by mod id ('ue4ss:Name')."""
        r = self.rows[mid]
        r["toggle"].set(value, pending=value != r["was"])
        r["name_lbl"].config(fg=TEXT if value else DIM)

    STATE_ICONS = {"working": "check", "didn't start": "alert", "error": "error",
                   "wrong folder": "alert", "worked before update": "clock",
                   "on": "dot", "needs PalSchema": "alert", "PalSchema off": "alert",
                   "starts next launch": "play"}

    def _row(self, e):
        base = PROBLEM_BG if e["health"] == "problem" else SURFACE
        f = tk.Frame(self.bodyf, bg=base)
        f.pack(fill="x")
        tk.Frame(f, bg=LINE, height=1).pack(fill="x", padx=(22, 0))
        inner = tk.Frame(f, bg=base)
        inner.pack(fill="x", padx=22, pady=9)

        tg = Toggle(inner, e["on"], lambda v, i=e["id"]: self._toggled(i, v), base)
        tg.pack(side="left", padx=(0, 14))

        # Once any mod has a picture, every row gets the slot, so names line up.
        if self._any_cover:
            thumb = tk.Frame(inner, bg=RAISED, width=round(56 * palicons.scale),
                             height=round(32 * palicons.scale), cursor="hand2")
            thumb.pack(side="left", padx=(0, 12))
            thumb.pack_propagate(False)
            img = self._thumb(e["cover"]) if e["cover"] else None
            pic = tk.Label(thumb, image=img or icon("photo", FAINT, 16), bd=0,
                           bg=RAISED, cursor="hand2")
            pic.pack(fill="both", expand=True)
            for w in (thumb, pic):
                w.bind("<Button-1>", lambda _e, ev=e: self.open_info(ev))

        menu_btn = button(inner, "", lambda ev=e: self._row_menu(ev), "ghost",
                          self.f_small, (6, 2), icon_name="more")
        menu_btn.pack(side="right", padx=(6, 0))
        cfg_btn = None
        if e["configs"]:
            cfg_btn = button(inner, "Configure",
                             lambda ev=e: ConfigWindow(self, ev["name"], ev["configs"]),
                             "ghost", self.f_small, (8, 2), icon_name="sliders")
            cfg_btn.pack(side="right", padx=(10, 0))

        state = e["state"][:1].upper() + e["state"][1:]
        name = self.STATE_ICONS.get(e["state"])
        state_img = icon(name, e["colour"], 16) if name else ""
        state_lbl = tk.Label(inner, text=(" " + state) if name else state, bg=base,
                             fg=e["colour"], font=self.f_small, image=state_img,
                             compound="left")
        state_lbl.pack(side="right")

        col = tk.Frame(inner, bg=base)
        col.pack(side="left", fill="x", expand=True)
        name_lbl = tk.Label(col, text=e["name"], bg=base, fg=TEXT if e["on"] else DIM,
                            font=self.f_name, anchor="w", cursor="hand2")
        name_lbl.pack(fill="x")
        name_lbl.bind("<Button-1>", lambda _e, ev=e: self.open_info(ev))

        # Second line: where it came from and which version, quietly.
        meta_line = tk.Frame(col, bg=base)
        meta_bits = []
        if e["url"] and str(e["url"]).startswith("http"):
            link = tk.Label(meta_line, text=e["source"] + " ", bg=base, fg=DIM,
                            font=self.f_small, image=icon("external", DIM, 12),
                            compound="right", cursor="hand2")
            link.bind("<Button-1>", lambda _e, u=e["url"]: open_link(u))
            link.bind("<Enter>", lambda _e, w=link: w.config(fg=TEXT))
            link.bind("<Leave>", lambda _e, w=link: w.config(fg=DIM))
            meta_bits.append(link)
        elif e["mine"]:
            meta_bits.append(tk.Label(meta_line, text="Your mod", bg=base, fg=DIM,
                                      font=self.f_small))
        version = (self._data["registry"].get(e["name"], {}).get("version")
                   or (e["extra"] if e["group"] == "UE4SS mods" else None))
        if version:
            meta_bits.append(tk.Label(meta_line, text=f"v{version}", bg=base, fg=FAINT,
                                      font=self.f_small))
        for i, w in enumerate(meta_bits):
            if i:
                tk.Label(meta_line, text="·", bg=base, fg=FAINT,
                         font=self.f_small).pack(side="left", padx=5)
            w.pack(side="left")
        extras = []
        if meta_bits:
            meta_line.pack(fill="x")
            extras += [meta_line] + list(meta_line.winfo_children())
        if e["note"]:
            n = tk.Label(col, text=e["note"], bg=base,
                         fg=(BAD if e["health"] == "problem"
                             else WARN if e.get("warn") else FAINT),
                         font=self.f_small, anchor="w", justify="left",
                         wraplength=560)
            n.pack(fill="x", pady=(1, 0))
            extras.append(n)

        plain = [f, inner, col, name_lbl, state_lbl, menu_btn] + extras
        if cfg_btn:
            plain.append(cfg_btn)
        custom = [tg]
        for w in plain:
            w.bind("<Enter>", lambda _e: self._hover(plain, custom, True, base), add="+")
            w.bind("<Leave>", lambda _e: self._hover(plain, custom, False, base), add="+")
            w.bind("<Button-3>", lambda ev, en=e: self._row_menu(en, ev), add="+")
        self.rows[e["id"]] = {"toggle": tg, "was": e["on"], "entry": e,
                              "name_lbl": name_lbl, "frame": f}

    def _thumb(self, path):
        """A 64x36 row thumbnail, built once per picture."""
        try:
            key = (str(path), path.stat().st_mtime)
        except OSError:
            return None
        if key not in self._thumbs:
            try:
                self._thumbs[key] = palinfo.photo(palmedia.thumbnail(path, 64, 36))
            except (palmedia.MediaError, OSError):
                self._thumbs[key] = None
        return self._thumbs[key]

    def open_info(self, e):
        # One window per mod: bring an open one forward instead of stacking.
        # Two kinds of mod with one name get one each; what is on disk differs.
        for w in self.root.winfo_children():
            if isinstance(w, palinfo.ModInfoWindow) and w.entry["id"] == e["id"]:
                w.deiconify()
                w.lift()
                w.focus_set()
                return
        palinfo.ModInfoWindow(self, e)

    def media_changed(self, name):
        """A mod's picture or description changed in its info window."""
        if not self._data:
            return
        self._data["registry"] = palregistry.load_registry()
        self._entries_cache = self._build_entries()
        self.render()

    def _hover(self, plain, custom, on, base=SURFACE):
        bg = HOVER if on and base == SURFACE else base
        for w in plain:
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass
        for w in custom:
            try:
                w.recolour(bg)
            except tk.TclError:
                pass

    # ---------------------------------------------------------------- menus
    def _row_menu(self, e, event=None):
        m = tk.Menu(self.root, tearoff=0, bg=RAISED, fg=TEXT,
                    activebackground=ACCENT, activeforeground=ON_ACCENT,
                    bd=0, font=self.f_small)
        target = e["path"] or e["pak_path"]
        if target:
            m.add_command(label="Open folder",
                          command=lambda: open_in_explorer(target))
        if e["url"]:
            m.add_command(label="Open mod page",
                          command=lambda: open_link(e["url"]))
        if e["configs"]:
            m.add_command(label="Configure…",
                          command=lambda: ConfigWindow(self, e["name"], e["configs"]))
        m.add_command(label="Mod info…", command=lambda: self.open_info(e))
        keys = (self._data["keybinds"]["keys"].get(e["name"])
                if e["group"] == "UE4SS mods" else None)
        if keys:
            m.add_command(label="Hotkeys: " + ", ".join(keys[:6])
                          + ("…" if len(keys) > 6 else ""), state="disabled")
        if e["group"] == "Pak mods" and e["where"] == "LogicMods":
            m.add_command(label="Load order…", command=self.open_load_order)
        if e["mine"] and e["path"]:
            m.add_separator()
            m.add_command(label="Package for sharing…",
                          command=lambda: self.package_mod(e))
        m.add_separator()
        m.add_command(label="Uninstall…", command=lambda: self.uninstall(e))
        try:
            if event is not None:
                m.tk_popup(event.x_root, event.y_root)
            else:
                m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            m.grab_release()

    def more_menu(self):
        """Everyday things at the top level; specialist tools one level down."""
        m = dark_menu(self.root, self.f_small)
        m.add_command(label="Refresh   F5", command=lambda: self.reload(full=True))
        m.add_separator()
        if self._data:
            profiles = dark_menu(m, self.f_small)
            self._fill_profile_menu(profiles)
            m.add_cascade(label="Profiles", menu=profiles)
            m.add_command(label="Save backups…", command=self.open_backups)
            share = dark_menu(m, self.f_small)
            share.add_command(label="Copy my modlist as text",
                              command=lambda: palwindows.copy_modlist(self))
            share.add_command(label="Export modlist file…",
                              command=lambda: palwindows.export_modlist(self))
            share.add_separator()
            share.add_command(label="Compare with a friend's modlist…",
                              command=lambda: palwindows.compare_modlist(self))
            m.add_cascade(label="Share modlist", menu=share)
            m.add_separator()

            tools = dark_menu(m, self.f_small)
            tools.add_command(label="Conflicts & hotkeys…", command=self.open_conflicts)
            tools.add_command(label="UE4SS log…", command=self.open_log)
            tools.add_command(label="Blueprint load order…", command=self.open_load_order)
            tools.add_command(label="Clean up leftovers…",
                              command=lambda: palwindows.CleanupWindow(self))
            tools.add_command(label="Check UE4SS install…", command=self.repair)
            tools.add_separator()
            tools.add_command(label="Install or update UE4SS…",
                              command=self.get_ue4ss)
            tools.add_command(label="Install or update PalSchema…",
                              command=self.get_palschema)
            tools.add_separator()
            tools.add_command(label="New mod of your own…", command=self.new_mod)
            m.add_cascade(label="Tools", menu=tools)

            folders = dark_menu(m, self.f_small)
            paths = self._paths
            for label, path in (
                ("Script mods (UE4SS)", paths["ue4ss_mods"]),
                ("Pak mods (~mods)", paths["paks"] / "~mods"),
                ("Blueprint mods (LogicMods)", paths["paks"] / "LogicMods"),
                ("Save games", palsafety.save_dir(paths["game"])),
                ("Game folder", paths["game"]),
                ("App data", palpaths.data_dir()),
            ):
                folders.add_command(label=label,
                                    state="normal" if path and Path(path).exists() else "disabled",
                                    command=lambda pp=path: open_in_explorer(pp))
            m.add_cascade(label="Open folder", menu=folders)

        installs = dark_menu(m, self.f_small)
        current = str(palpaths.game() or "").lower()
        for inst in palpaths.known_installs():
            mark = "✓  " if str(inst["path"]).lower() == current else "     "
            installs.add_command(label=f"{mark}{inst['label']}   {inst['path']}",
                                 command=lambda pp=inst["path"]: self.switch_install(pp))
        installs.add_separator()
        installs.add_command(label="Add another install…",
                             command=lambda: SetupWindow(self))
        m.add_cascade(label="Switch install", menu=installs)
        m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        m.grab_release()

    def open_log(self):
        palwindows.LogWindow(self)

    def open_conflicts(self):
        palwindows.ConflictsWindow(self)

    def open_load_order(self):
        palwindows.LoadOrderWindow(self)

    def open_backups(self):
        palwindows.BackupsWindow(self)

    def _open_log(self):
        log = self._paths["log"]
        if log.is_file():
            os.startfile(str(log))
        else:
            messagebox.showinfo("EZ Pal Mod Manager",
                                "No UE4SS.log yet. Play once to create it.")

    def _fill_profile_menu(self, m):
        names = palregistry.profile_names()
        for n in names:
            pr = palregistry.load_profile(n)
            m.add_command(label=f"Load  {n}  ({len(pr['enabled'])} on)",
                          command=lambda x=n: self.load_profile(x))
        if names:
            m.add_separator()
        else:
            m.add_command(label="No profiles saved yet", state="disabled")
        m.add_command(label="Save current set as…", command=self.save_profile)
        if names:
            delete = dark_menu(m, self.f_small)
            for n in names:
                delete.add_command(label=n, command=lambda x=n: self.delete_profile(x))
            m.add_cascade(label="Delete", menu=delete)

    def profile_menu(self):
        m = dark_menu(self.root, self.f_small)
        self._fill_profile_menu(m)
        m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        m.grab_release()

    # ---------------------------------------------------------------- state
    def _toggled(self, mid, value):
        if mid in self.rows:
            self._set_row(mid, value)
        self._recount()

    def _pending(self):
        """[(mod id, on)] for every toggle staged but not applied."""
        return [(mid, r["toggle"].value) for mid, r in self.rows.items()
                if r["toggle"].value != r["was"]]

    def _recount(self):
        self._flash_job = None
        total = len(self._entries_cache)
        on = sum(1 for e in self._entries_cache if e["on"])
        problems = sum(1 for e in self._entries_cache if e["health"] == "problem")
        pend = self._pending()
        lbl, _line = self._tab_btns["Problems"]
        lbl.config(text=f"Problems  {problems}" if problems else "Problems")
        if pend:
            msg = (f"{plural(len(pend), 'change')} not applied. "
                   f"They take effect the next time you play.")
            fg = TEXT
            self.apply_btn.pack(side="right")
            self.revert_btn.pack(side="right", padx=8)
        else:
            msg = f"{plural(total, 'mod')}, {on} on"
            if problems:
                need = "needs" if problems == 1 else "need"
                msg += f", {problems} {need} attention"
            fg = DIM
            self.apply_btn.pack_forget()
            self.revert_btn.pack_forget()
        self.status.config(text=msg, fg=fg)

    def _poll(self, once=False):
        # Never clobber toggles the user has not applied yet.
        try:
            if self._paths and not self._pending():
                sig = palmods.snapshot(self._paths)
                if sig != self._sig:
                    self.reload()
        except (SystemExit, OSError, FileNotFoundError):
            pass
        if not once:
            self.root.after(2500, self._poll)

    # ---------------------------------------------------------------- actions
    def apply(self):
        changes = self._pending()
        if not changes:
            return
        failed, switched_on = [], []
        for mid, on in changes:
            kind, name = palregistry.split_id(mid)
            try:
                palmods.set_enabled(name, on, kind)
            except OSError as exc:
                failed.append(f"{name}: {exc}")
            else:
                if on:
                    switched_on.append(mid)
        # Until the game runs, these read as starting next launch, not as
        # having failed to start in a session that ran before they were on.
        try:
            palsafety.switched_on(self._paths["game"], switched_on)
        except OSError:
            pass
        self.reload()
        if failed:
            messagebox.showerror("EZ Pal Mod Manager",
                                 "Some changes could not be made:\n\n"
                                 + "\n".join(failed))
        elif self._running:
            self.flash(f"Applied {plural(len(changes), 'change')}. Palworld is running, "
                       f"so they take effect the next time it starts.")
        else:
            self.flash(f"Applied {plural(len(changes), 'change')}. "
                       f"They take effect the next time you play.")

    def play(self):
        """Start the game with a safety net, then report back when it closes."""
        if self._running or not self._paths:
            return
        game = self._paths["game"]
        pend = self._pending()
        if pend:
            ans = messagebox.askyesnocancel(
                "EZ Pal Mod Manager", f"Apply your {plural(len(pend), 'change')} "
                                   f"before starting?")
            if ans is None:
                return
            if ans:
                self.apply()
        if palsafety.game_running(game):
            self.flash("Palworld is already running. Results appear when it closes.")
            self._watch(game, launched=True)
            return

        if (palpaths.load_settings().get("auto_backup", True)
                and palsafety.save_dir(game)
                and palsafety.needs_auto_backup(game, self._data)):
            try:
                meta = palsafety.backup_saves(game, "auto", self._data)
                self.flash(f"Backed up your saves ({meta['files']} files) "
                           f"before this new mod setup")
            except OSError as exc:
                if not messagebox.askyesno(
                        "EZ Pal Mod Manager", f"Couldn't back up your saves:\n\n"
                                           f"{exc}\n\nStart anyway?"):
                    return
        try:
            how = palsafety.launch(game)
        except (OSError, FileNotFoundError) as exc:
            messagebox.showinfo("EZ Pal Mod Manager", str(exc))
            self._watch(game, launched=True)
            return
        self._watch(game, launched=True)
        self.play_btn.config(text=" Starting…")
        self.status.config(text=f"Starting via {how}…", fg=DIM)
        # If the launch never happens (cancelled in Steam), don't stay stuck.
        self.root.after(120000, self._launch_timeout)

    def _launch_timeout(self):
        if not self._running and self.play_btn.cget("text").strip() == "Starting…":
            self._launched_by_us = False
            server = self._data and self._data["install"]["kind"] == "server"
            self.play_btn.config(text=" Start server" if server else " Play")
            self.status.config(text="Palworld didn't start.", fg=DIM)

    def _watch(self, game, launched):
        self._watch_game = game
        self._launched_by_us = self._launched_by_us or launched
        self._events.put(("poke", None))

    def _watch_loop(self):
        """Background thread: report the game starting and stopping.

        Always on, so a session started from Steam directly is noticed too.
        """
        was, idle = False, 0
        while True:
            game = self._watch_game or palpaths.game()
            try:
                now = bool(game) and palsafety.game_running(game)
            except Exception:
                now = was
            if now != was:
                self._events.put(("started" if now else "stopped", time.time()))
                was = now
            # Poll quickly just after a launch, lazily otherwise.
            time.sleep(2 if (now or self._launched_by_us) else 5)

    def _drain_events(self):
        try:
            while True:
                kind, when = self._events.get_nowait()
                if kind == "started":
                    self._running = True
                    self._session_start = when
                    self.play_btn.config(text=" Running", state="disabled",
                                         cursor="arrow")
                    self.status.config(text="Palworld is running. Changes you apply "
                                            "now take effect next launch.", fg=DIM)
                elif kind == "stopped" and self._running:
                    self._running = False
                    self._session_ended(when)
        except queue.Empty:
            pass
        self.root.after(700, self._drain_events)

    def _session_ended(self, when):
        server = self._data and self._data["install"]["kind"] == "server"
        self.play_btn.config(text=" Start server" if server else " Play",
                             state="normal", cursor="hand2")
        minutes = (round((when - self._session_start) / 60)
                   if self._session_start else None)
        launched, self._launched_by_us = self._launched_by_us, False
        # UE4SS may still be flushing the log as the process exits.
        self.root.after(1500, lambda: self._after_session(minutes, launched))

    def _after_session(self, minutes, launched):
        self.reload(full=True)
        if not self._data:
            return
        problems = sum(1 for e in self._entries_cache if e["health"] == "problem")
        if launched:
            palwindows.SessionWindow(self, minutes)
        else:
            need = "needs" if problems == 1 else "need"
            self.flash("Palworld closed. Mod status refreshed"
                       + (f", {problems} {need} attention" if problems else ""))

    def revert(self):
        for mid, r in self.rows.items():
            self._set_row(mid, r["was"])
        self._recount()

    def install_dialog(self):
        last = palpaths.load_settings().get("last_install_dir")
        picked = filedialog.askopenfilenames(
            title="Choose mod archives (you can pick several)",
            initialdir=last or str(Path.home() / "Downloads"),
            filetypes=[("Mod archives", "*.zip *.7z *.rar *.pak"),
                       ("Zip archive", "*.zip"), ("7-Zip archive", "*.7z"),
                       ("RAR archive", "*.rar"), ("Pak file", "*.pak"),
                       ("All files", "*.*")])
        if not picked:
            return
        palpaths.save_settings({"last_install_dir": str(Path(picked[0]).parent)})
        self.queue_installs(picked)

    def queue_installs(self, files):
        """Install several downloads one after another.

        Each gets its own window, so each can have its own mod page link.
        Files that can't be read are reported together instead of one by one.
        """
        bad = []
        for f in files:
            ok, why = palinstall.can_read(f)
            if ok:
                self._install_queue.append(f)
            else:
                bad.append(f"{Path(f).name}: {why}")
        if bad:
            messagebox.showerror("EZ Pal Mod Manager", "\n".join(bad))
        self._next_install()

    def _next_install(self):
        if any(isinstance(w, InstallWindow) for w in self.root.winfo_children()):
            return
        if self._install_queue:
            InstallWindow(self, self._install_queue.pop(0),
                          remaining=len(self._install_queue))

    def new_mod(self):
        name = simpledialog.askstring(
            "New mod", "Name for your mod:\n\n"
            "A working UE4SS Lua mod is created, switched on, and "
            "ready to edit.", parent=self.root)
        if not name:
            return
        try:
            dest = palinstall.scaffold(name)
        except (palinstall.InstallError, OSError) as exc:
            messagebox.showerror("EZ Pal Mod Manager", str(exc))
            return
        self.reload(full=True)
        self.flash(f"Created {dest.name}")
        if messagebox.askyesno("EZ Pal Mod Manager",
                               f"Created {dest}\n\nOpen the folder?"):
            open_in_explorer(dest)

    def package_mod(self, e):
        try:
            out = palinstall.package(e["path"])
        except (palinstall.InstallError, OSError) as exc:
            messagebox.showerror("EZ Pal Mod Manager", str(exc))
            return
        if messagebox.askyesno(
                "EZ Pal Mod Manager",
                f"Packaged as {out.name}\n\nIt extracts straight into a "
                f"Palworld folder, the same way Nexus mods do.\n\nShow it?"):
            open_in_explorer(out)

    def uninstall(self, e):
        kind, name = palregistry.split_id(e["id"])
        rec = palregistry.receipt(kind, name)
        detail = (f"{plural(len(rec['files']), 'tracked file')} will be deleted."
                  if rec else
                  "This mod was not installed by the app, so its whole folder "
                  "or .pak will be deleted.")
        # Pictures, like the page link, belong to every mod of this name and
        # stay while another is installed: the other half of a hybrid mod, or
        # the same mod in another install.
        here = (palpaths.install_key(self._paths["game"]), kind)
        twins = [x for x in self._entries_cache
                 if x["name"] == name and x["id"] != e["id"]]
        shared = bool(twins) or any(r != here for r in palregistry.receipts_for(name))
        what = f"{name} ({palmods.KIND_LABELS[kind]})" if twins else name
        if not messagebox.askyesno(
                "Uninstall",
                f"Remove {what}?\n\n{detail}"
                + ("\n\nIts pictures go to the Recycle Bin."
                   if e.get("cover") and not shared else "")
                + "\n\nThis cannot be undone."):
            return
        try:
            removed, notes = palinstall.uninstall(
                name, mod_path=e["path"], pak_path=e["pak_path"], kind=kind)
        except OSError as exc:
            messagebox.showerror("EZ Pal Mod Manager", str(exc))
            return
        self.reload(full=True)
        self.flash(f"Removed {e['name']} ({plural(len(removed), 'file')})")
        if notes:
            messagebox.showinfo("EZ Pal Mod Manager", "\n".join(notes))

    def save_profile(self):
        name = simpledialog.askstring(
            "Save profile", "Name this set of mods:\n\n"
            "Profiles remember which mods are on, so you can switch between "
            "(say) a modded solo save and a clean one for multiplayer.",
            parent=self.root)
        if not name:
            return
        on = [e["id"] for e in self._entries_cache if e["on"]]
        palregistry.save_profile(name, on, [e["id"] for e in self._entries_cache])
        self.flash(f"Saved profile '{name}' ({len(on)} mods on)")

    def load_profile(self, name):
        pr = palregistry.load_profile(name)
        if not pr:
            return
        staged = 0
        for e in self._entries_cache:
            kind, mod = palregistry.split_id(e["id"])
            target = palregistry.profile_wants(pr, kind, mod)
            row = self.rows.get(e["id"])
            if row and target is not None and target != row["was"]:
                self._set_row(e["id"], target)
                staged += 1
        # Older profiles list plain names, newer ones mod ids.
        present = ({e["id"] for e in self._entries_cache}
                   | {e["name"] for e in self._entries_cache})
        missing = sorted(set(pr["known"]) - present)
        self._recount()
        msg = f"Profile '{name}': {plural(staged, 'change')} ready. Press Apply changes to use them."
        if missing:
            msg += f" ({plural(len(missing), 'mod')} from it no longer installed.)"
        self.status.config(text=msg, fg=PEND)

    def delete_profile(self, name):
        if messagebox.askyesno("EZ Pal Mod Manager", f"Delete profile '{name}'?"):
            palregistry.delete_profile(name)
            self.flash(f"Deleted profile '{name}'")

    def get_ue4ss(self):
        palwindows.GetWindow(self, "ue4ss")

    def get_palschema(self):
        palwindows.GetWindow(self, "palschema")

    def repair(self):
        issues, _ = palmods.doctor(False)
        if not issues:
            messagebox.showinfo("EZ Pal Mod Manager", "No UE4SS conflict detected.")
            self._issues = []
            self.render()
            return
        if messagebox.askyesno("EZ Pal Mod Manager",
                               "Issues found:\n\n  " + "\n  ".join(issues) +
                               "\n\nRepair them now?"):
            _, actions = palmods.doctor(True)
            self.reload(full=True)
            messagebox.showinfo("EZ Pal Mod Manager",
                                "\n".join(actions) or "Nothing to do.")


def _icon_path():
    """Locate the .ico both when run from source and when frozen."""
    for b in (palpaths.bundled_dir(), Path(__file__).resolve().parent):
        for cand in (b / "palmodmanager.ico", b / "assets" / "palmodmanager.ico"):
            if cand.is_file():
                return str(cand)
    return None


def _dpi_aware():
    """Render at the display's real pixel density.

    Without this Windows scales the whole window up from 96 DPI, which on a
    125% or 150% display makes every label and icon visibly soft.
    """
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # per-monitor
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()        # Windows 7/8
    except (ImportError, AttributeError, OSError):
        pass


def _dark_titlebar(window):
    """Ask Windows for a dark title bar, so the frame matches the app."""
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        for attr in (20, 19):          # 20 on Windows 11/late 10, 19 before
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(ctypes.c_int(1)),
                    ctypes.sizeof(ctypes.c_int)) == 0:
                return
    except (ImportError, AttributeError, OSError):
        pass


# ============================================================== errors
ERROR_LOG = "error.log"


def scrub(text):
    """`text` with the home folder written as %USERPROFILE%.

    Tracebacks are full of paths, and the home folder is usually named after
    its owner. A repr()'d path doubles its backslashes, so those count too.
    """
    home = os.path.expanduser("~")
    parts = [p for p in re.split(r"[\\/]+", home) if p]
    # A Windows home starts at its drive letter, the first part. One that
    # starts at the root (/home/me) has a leading slash that belongs to it.
    rooted = home[:1] in ("\\", "/")
    if not os.path.isabs(home) or len(parts) < (1 if rooted else 2):
        return text
    sep = r"(?:\\\\|[\\/])"
    return re.sub((sep if rooted else "") + sep.join(map(re.escape, parts))
                  + r"(?![\w.-])", "%USERPROFILE%", text, flags=re.I)


def log_error(details):
    """Append a report to error.log. Returns the log's path, or None if even
    that failed: reporting an error must never raise one of its own."""
    try:
        win = getattr(sys, "getwindowsversion", lambda: None)()
        system = f"Windows {win.major}.{win.minor}.{win.build}" if win else sys.platform
        build = "exe" if getattr(sys, "frozen", False) else "source"
        log = palpaths.data_dir() / ERROR_LOG
        with open(log, "a", encoding="utf8") as f:
            f.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}   {system}   "
                    f"Python {sys.version.split()[0]} ({build})\n"
                    f"{details.rstrip()}\n\n")
        return log
    except Exception:                      # noqa: BLE001 - see docstring
        return None


def _message_box(details, log):
    """Windows' own dialog, for when Tk itself is what failed. Ctrl+C in it
    copies everything it says."""
    head = "Something went wrong." + (" Details were saved to error.log."
                                      if log else "")
    tail = "\n".join(details.strip().splitlines()[-12:])
    try:
        import ctypes
        MB_ICONERROR, MB_SETFOREGROUND, MB_TOPMOST = 0x10, 0x10000, 0x40000
        ctypes.windll.user32.MessageBoxW(
            None, f"{head}\n\nPress Ctrl+C to copy this message.\n\n{tail}",
            "EZ Pal Mod Manager", MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST)
    except (ImportError, AttributeError, OSError):
        pass


class ErrorDialog(tk.Toplevel):
    """'Something went wrong', with the details one click from a bug report."""

    def __init__(self, master, details, log):
        super().__init__(master)
        self.details = details
        self.title("EZ Pal Mod Manager")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="x", padx=22, pady=(18, 14))
        tk.Label(body, text="Something went wrong", bg=BG, fg=TEXT,
                 font=(TITLE_FONT, 14), anchor="w").pack(fill="x")
        tk.Label(body, text="Details were saved to error.log." if log else
                 "The details couldn't be saved, so copy them before you close "
                 "this.", bg=BG, fg=DIM, font=(BODY_FONT, 10), anchor="w",
                 justify="left", wraplength=400).pack(fill="x", pady=(4, 0))

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=22, pady=(0, 18))
        self.copy_btn = button(foot, "Copy details", self.copy, "primary",
                               (STRONG_FONT, 10), (16, 6))
        self.copy_btn.pack(side="right")
        if log:
            button(foot, "Show error.log", lambda: open_in_explorer(log),
                   "quiet", (BODY_FONT, 9), (12, 6)).pack(side="right", padx=8)
        button(foot, "Close", self.destroy, "ghost",
               (BODY_FONT, 9)).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(10, lambda: dark_titlebar(self))
        # A window holding the grab (Setup does) would swallow every click
        # meant for this one; borrow the grab and give it back after.
        self._prior_grab = self.grab_current()
        self.grab_set()
        self.lift()
        self.focus_force()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.details)
        self.copy_btn.config(text="Copied")

    def destroy(self):
        prior = getattr(self, "_prior_grab", None)
        super().destroy()
        try:
            if prior is not None and prior.winfo_exists():
                prior.grab_set()
        except tk.TclError:
            pass


class ErrorReporter:
    """Every unexpected error ends up in error.log and in front of the user.

    The release is a windowed build, so sys.stderr is None: Tk's default
    report_callback_exception, like the default thread and top-level hooks,
    prints its traceback to nowhere, and a broken button just does nothing.
    """

    def __init__(self):
        self.root = None
        self.seen = set()              # each distinct error is reported once
        self.showing = False
        self.later = queue.Queue()     # from other threads, for the Tk thread
        sys.excepthook = self.fatal
        threading.excepthook = lambda a: self.report(
            a.exc_type, a.exc_value, a.exc_traceback, thread=a.thread)

    def attach(self, root):
        self.root = root
        root.report_callback_exception = self.report
        self._drain()

    def report(self, kind, exc, tb, thread=None):
        if issubclass(kind, (SystemExit, KeyboardInterrupt)):
            return
        if sys.stderr:                 # run from a console: say it there too
            traceback.print_exception(kind, exc, tb)
        # One report per bug, not per occurrence: a failing repaint or timer
        # would otherwise bury the user in dialogs.
        where = (kind, tuple((f.filename, f.lineno)
                             for f in traceback.extract_tb(tb)))
        if where in self.seen:
            return
        self.seen.add(where)
        details = scrub("".join(traceback.format_exception(kind, exc, tb)))
        if thread is not None:
            details = f"In the {thread.name} thread:\n{details}"
        log = log_error(details)
        if thread is not None:
            self.later.put((details, log))      # Tk belongs to the main thread
        else:
            self.show(details, log)

    def fatal(self, kind, exc, tb):
        """sys.excepthook: the app can't carry on, so this is its last word."""
        self.report(kind, exc, tb)
        if self.root is not None:
            # Tk hands copied text over to Windows when its windows close;
            # left to the process exit, the clipboard would come up empty.
            try:
                self.root.destroy()
            except tk.TclError:
                pass

    def show(self, details, log):
        if self.showing:
            return                     # already in error.log; one at a time
        self.showing = True
        try:
            ErrorDialog(self.root, details, log).wait_window()
        except (tk.TclError, RuntimeError):
            _message_box(details, log)
        finally:
            self.showing = False

    def _drain(self):
        try:
            while True:
                self.show(*self.later.get_nowait())
        except queue.Empty:
            pass
        try:
            self.root.after(400, self._drain)
        except tk.TclError:
            pass                       # the app is closing


def main():
    _dpi_aware()
    errors = ErrorReporter()           # from here on nothing fails silently

    # Launched with files (several zips dragged onto the exe, or Open With):
    # go straight to the installer for each.
    pending = [a for a in sys.argv[1:] if Path(a).exists()] or None

    root = tk.Tk()
    errors.attach(root)
    try:
        # Tk sizes fonts in points against its own idea of DPI; match the
        # screen so text scales with the window rather than staying tiny.
        scale = root.winfo_fpixels("1i") / 72.0
        root.tk.call("tk", "scaling", scale)
    except tk.TclError:
        pass
    ico = _icon_path()
    if ico:
        try:
            root.iconbitmap(default=ico)       # default: dialogs get it too
        except tk.TclError:
            pass
    _dark_titlebar(root)
    App(root, pending_install=pending)
    root.mainloop()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A windowed PyInstaller build reports an exception that escapes the
        # script with a dialog of its own; give it to our hook first, so it
        # is logged and scrubbed the same way as every other error.
        sys.excepthook(*sys.exc_info())
        sys.exit(1)
