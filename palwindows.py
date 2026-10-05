#!/usr/bin/env python3
"""Secondary windows: log viewer, conflicts, load order, backups, cleanup,
modlist sharing, and the summary shown when a play session ends."""

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import palget
import palinstall
import palmods
import palpaths
import palregistry
import palsafety
import paltools
import palworkshop
from paltext import plural
from palui import (open_link, BG, SURFACE, RAISED, LINE, TEXT, DIM, FAINT, ACCENT, GOOD,
                   WARN, BAD, PEND, Pill, button, checkbox, human_size,
                   friendly_time, open_in_explorer, Window, ON_ACCENT, ThinScrollbar)

TITLE = "EZ Pal Mod Manager"


# ==========================================================================
# UE4SS log
# ==========================================================================
class LogWindow(Window):
    """UE4SS.log, live, with the startup noise filtered out.

    UE4SS writes hundreds of engine offsets on startup; the lines that matter
    -- which mods started, and what failed -- are a few dozen among them.
    """

    FILTERS = ("Mods", "Problems", "Everything")

    def __init__(self, app):
        super().__init__(app, "UE4SS log", "", size="980x640", scroll=False)
        self.path = app._paths["log"]
        self.lines, self.size, self.partial = [], 0, ""
        self.mode = tk.StringVar(value="Mods")
        self.session_only = tk.BooleanVar(value=True)
        self.follow = tk.BooleanVar(value=True)
        self.needle = tk.StringVar()

        bar = tk.Frame(self.body, bg=SURFACE)
        bar.pack(fill="x", padx=10, pady=8)
        self.tabs = {}
        for name in self.FILTERS:
            lbl = tk.Label(bar, text=name, bg=SURFACE, fg=DIM, font=app.f_small,
                           padx=10, pady=4, cursor="hand2")
            lbl.pack(side="left", padx=(0, 2))
            lbl.bind("<Button-1>", lambda _e, n=name: self._mode(n))
            self.tabs[name] = lbl
        checkbox(bar, self.session_only, SURFACE, app.f_small, "Last session only",
                 self.reload).pack(side="left", padx=(14, 0))
        checkbox(bar, self.follow, SURFACE, app.f_small, "Follow").pack(side="left", padx=8)
        entry = tk.Entry(bar, textvariable=self.needle, bg=RAISED, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=app.f_small,
                         width=22)
        entry.pack(side="right", ipady=3, ipadx=4)
        tk.Label(bar, text="Find", bg=SURFACE, fg=FAINT,
                 font=app.f_small).pack(side="right", padx=6)
        self.needle.trace_add("write", lambda *_: self._render())

        frame = tk.Frame(self.body, bg=SURFACE)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.text = tk.Text(frame, bg="#0d0f13", fg=DIM, insertbackground=TEXT,
                            relief="flat", font=("Consolas", 9), wrap="none",
                            padx=8, pady=6, state="disabled")
        # Themed scrollbars; the native ones draw white on this dark window.
        ys = ThinScrollbar(frame, self.text.yview, bg=SURFACE)
        xs = ThinScrollbar(frame, self.text.xview, bg=SURFACE, orient="horizontal")
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.text.pack(fill="both", expand=True)
        for tag, colour in (("problem", BAD), ("start", GOOD), ("mod", TEXT),
                            ("other", FAINT)):
            self.text.tag_configure(tag, foreground=colour)

        button(self.foot, "Open in editor", self._open, "quiet", app.f_small,
               (12, 7)).pack(side="right")
        self._mode("Mods")
        self.reload()
        self.after(900, self._tail)

    def _mode(self, name):
        self.mode.set(name)
        for n, lbl in self.tabs.items():
            lbl.config(fg=TEXT if n == name else DIM,
                       bg=RAISED if n == name else SURFACE)
        self._render()

    def _read(self):
        try:
            raw = self.path.read_bytes()
        except OSError:
            return None
        self.size = len(raw)
        return palmods.ANSI.sub("", raw.decode("utf8", "replace"))

    def reload(self):
        text = self._read()
        if text is None:
            self.lines = []
            self.subtitle.config(text="No UE4SS.log yet. Play once to create it.")
        else:
            lines = text.splitlines()
            if self.session_only.get():
                starts = [i for i, ln in enumerate(lines) if "UE4SS - v" in ln]
                if starts:
                    lines = lines[starts[-1]:]
            self.lines = [(ln, paltools.classify_log_line(ln)) for ln in lines]
            self.subtitle.config(text=str(self.path))
        self._render()

    def _visible(self, line, kind):
        mode, needle = self.mode.get(), self.needle.get().strip().lower()
        if needle and needle not in line.lower():
            return False
        if mode == "Problems":
            return kind == "problem"
        if mode == "Mods":
            return kind in ("problem", "start", "mod")
        return True

    def _render(self):
        shown = [(ln, k) for ln, k in self.lines if self._visible(ln, k)][-6000:]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for ln, k in shown:
            self.text.insert("end", ln + "\n", k)
        self.text.configure(state="disabled")
        if self.follow.get():
            self.text.see("end")
        problems = sum(1 for _, k in self.lines if k == "problem")
        self.status.config(text=f"{len(shown)} of {len(self.lines)} lines"
                                f"   ·   {plural(problems, 'problem line')}")

    def _tail(self):
        if not self.winfo_exists():
            return
        try:
            size = self.path.stat().st_size if self.path.is_file() else 0
        except OSError:
            size = self.size
        if size < self.size or (size and not self.lines):
            self.reload()                        # a new session started
        elif size > self.size:
            try:
                with open(self.path, "rb") as f:
                    f.seek(self.size)
                    chunk = f.read()
                self.size = size
                text = self.partial + palmods.ANSI.sub(
                    "", chunk.decode("utf8", "replace"))
                parts = text.split("\n")
                self.partial = parts.pop()
                if any("UE4SS - v" in p for p in parts) and self.session_only.get():
                    self.reload()
                else:
                    new = [(p.rstrip("\r"), paltools.classify_log_line(p))
                           for p in parts]
                    self.lines.extend(new)
                    self.text.configure(state="normal")
                    for ln, k in new:
                        if self._visible(ln, k):
                            self.text.insert("end", ln + "\n", k)
                    self.text.configure(state="disabled")
                    if self.follow.get():
                        self.text.see("end")
            except OSError:
                pass
        self.after(900, self._tail)

    def _open(self):
        if self.path.is_file():
            os.startfile(str(self.path))


# ==========================================================================
# conflicts & hotkeys
# ==========================================================================
class ConflictsWindow(Window):
    def __init__(self, app):
        super().__init__(app, "Conflicts & hotkeys",
                         "Mods that fight over the same game files or the same "
                         "keys. Only one of each can win.", size="760x620")
        button(self.foot, "Close", self.destroy, "quiet", app.f_small,
               (14, 7)).pack(side="right")
        self._build()

    def _build(self):
        app, data = self.app, self.app._data
        conflicts, keys = data["conflicts"], data["keybinds"]
        # Hotkeys are read from UE4SS mods, so only those rows answer for a
        # name; a pak or PalSchema mod can share it.
        scripts = [e for e in app._entries_cache if e["group"] == "UE4SS mods"]
        configs = {e["name"]: e["configs"] for e in scripts}

        pairs = sorted(conflicts["pairs"], key=lambda c: not c["live"])
        self.section("Mods replacing the same game files", len(pairs))
        if not pairs:
            self.note("None. No two paks replace the same asset.")
        for c in pairs:
            card = self.card()
            top = tk.Frame(card, bg=RAISED)
            top.pack(fill="x", padx=12, pady=(9, 2))
            tk.Label(top, text=f"{c['mods'][0]}  ×  {c['mods'][1]}", bg=RAISED,
                     fg=TEXT, font=app.f_name).pack(side="left")
            Pill(top, "both on" if c["live"] else "one is off",
                 WARN if c["live"] else FAINT, SURFACE, RAISED,
                 app.f_pill).pack(side="left", padx=8)
            tk.Label(top, text=plural(c['assets'], 'shared asset'), bg=RAISED,
                     fg=FAINT, font=app.f_small).pack(side="right")
            why = ("certain: only it has the _P suffix Unreal gives priority to"
                   if c["sure"] else
                   "likely: both are _P paks, so load order decides, and the "
                   "name that sorts last is normally read first")
            tk.Label(card, text=f"{c['winner']} wins  ({why})", bg=RAISED,
                     fg=GOOD, font=app.f_small, anchor="w", justify="left",
                     wraplength=640).pack(fill="x", padx=12)
            tk.Label(card, text="e.g. " + ",  ".join(e.split("/")[-1] for e in c["examples"]),
                     bg=RAISED, fg=FAINT, font=app.f_small, anchor="w",
                     wraplength=640).pack(fill="x", padx=12, pady=(0, 9))

        if conflicts["no_patch_suffix"]:
            self.section("Content paks without the _P suffix",
                         len(conflicts["no_patch_suffix"]))
            self.note("Unreal reads paks ending in _P before the game's own files. "
                      "These don't, so they can add new assets but probably can't "
                      "replace existing ones. Renaming to end in _P usually fixes a "
                      "mod that seems to do nothing.")
            for n in conflicts["no_patch_suffix"]:
                self.note(f"•  {n}.pak", TEXT)

        clashes = sorted(keys["clashes"], key=lambda c: not c["live"])
        self.section("Hotkeys claimed by more than one mod", len(clashes))
        if not clashes:
            self.note("None found.")
        for c in clashes:
            card = self.card()
            top = tk.Frame(card, bg=RAISED)
            top.pack(fill="x", padx=12, pady=9)
            tk.Label(top, text=c["key"], bg=RAISED, fg=TEXT, font=app.f_name,
                     width=10, anchor="w").pack(side="left")
            tk.Label(top, text="  ·  ".join(c["mods"]), bg=RAISED, fg=DIM,
                     font=app.f_small).pack(side="left")
            Pill(top, "all on" if c["live"] else f"{len(c['enabled'])} on",
                 WARN if c["live"] else FAINT, SURFACE, RAISED,
                 app.f_pill).pack(side="left", padx=8)
            for n in c["mods"]:
                if configs.get(n):
                    from palmods_gui import ConfigWindow
                    button(top, f"Change in {n}",
                           lambda nn=n: ConfigWindow(app, nn, configs[nn]),
                           "ghost", app.f_pill, (6, 2)).pack(side="right")
        if keys["unreadable"]:
            self.note("Couldn't read the hotkeys of: " + ", ".join(keys["unreadable"])
                      + ". They set keys in code, so clashes with them can't be checked.",
                      pady=(8, 4))

        self.section("Hotkeys by mod")
        on = {e["name"] for e in scripts if e["on"]}
        for name, ks in sorted(keys["keys"].items()):
            row = tk.Frame(self.body, bg=SURFACE)
            row.pack(fill="x", padx=22, pady=1)
            tk.Label(row, text=name, bg=SURFACE, fg=TEXT if name in on else FAINT,
                     font=app.f_small, width=24, anchor="w").pack(side="left")
            tk.Label(row, text=",  ".join(ks), bg=SURFACE, fg=DIM,
                     font=app.f_small, anchor="w", justify="left",
                     wraplength=480).pack(side="left", fill="x")


# ==========================================================================
# BP load order
# ==========================================================================
class LoadOrderWindow(Window):
    """Edit BPModLoaderMod's load_order.txt without hand-typing pak names."""

    def __init__(self, app):
        super().__init__(app, "Blueprint load order",
                         "Only LogicMods blueprint mods have a load order. Mods in "
                         "the left list start first, top to bottom; everything "
                         "else starts after them in random order.",
                         size="760x520", scroll=False)
        self.paths = app._paths
        self.installed = [p["name"] for p in app._data["pak_mods"]
                          if p["folder"] == "LogicMods"]
        self.enabled = {p["name"] for p in app._data["pak_mods"]
                        if p["folder"] == "LogicMods" and not p["disabled"]}
        _, self.ordered = paltools.read_load_order(self.paths)
        self.can_save = paltools.load_order_file(self.paths).parent.is_dir()

        grid = tk.Frame(self.body, bg=SURFACE)
        grid.pack(fill="both", expand=True, padx=14, pady=14)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(2, weight=1)
        grid.rowconfigure(1, weight=1)
        tk.Label(grid, text="LOAD FIRST, IN THIS ORDER", bg=SURFACE, fg=FAINT,
                 font=app.f_pill, anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(grid, text="ANY ORDER", bg=SURFACE, fg=FAINT, font=app.f_pill,
                 anchor="w").grid(row=0, column=2, sticky="w")
        self.left = self._listbox(grid)
        self.left.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.right = self._listbox(grid)
        self.right.grid(row=1, column=2, sticky="nsew", pady=(4, 0))

        mid = tk.Frame(grid, bg=SURFACE)
        mid.grid(row=1, column=1, padx=10)
        for text, cmd in (("↑", self._up), ("↓", self._down),
                          ("← Add", self._add), ("Remove →", self._remove)):
            button(mid, text, cmd, "quiet", app.f_small, (10, 5)).pack(fill="x", pady=3)
        self.left.bind("<Double-Button-1>", lambda _e: self._remove())
        self.right.bind("<Double-Button-1>", lambda _e: self._add())

        self.save_btn = button(self.foot, "Save", self._save, "primary",
                               app.f_name, (20, 8))
        self.save_btn.pack(side="right")
        button(self.foot, "Cancel", self.destroy, "quiet", app.f_small,
               (14, 8)).pack(side="right", padx=8)
        if not self.can_save:
            self.save_btn.config(state="disabled")
            self.status.config(text="BPModLoaderMod isn't installed.", fg=WARN)
        self._fill()

    def _listbox(self, parent):
        return tk.Listbox(parent, bg=RAISED, fg=TEXT, selectbackground=ACCENT,
                          selectforeground=ON_ACCENT, relief="flat",
                          highlightthickness=0, activestyle="none",
                          font=self.app.f_body, exportselection=False)

    def _label(self, name):
        if name not in self.installed:
            return f"{name}   (not installed)"
        return name if name in self.enabled else f"{name}   (off)"

    def _fill(self, keep=None):
        self.left.delete(0, "end")
        self.right.delete(0, "end")
        for n in self.ordered:
            self.left.insert("end", self._label(n))
        self.rest = [n for n in self.installed if n not in self.ordered]
        for n in self.rest:
            self.right.insert("end", self._label(n))
        if keep is not None and 0 <= keep < len(self.ordered):
            self.left.selection_set(keep)
        if not self.installed and not self.ordered:
            self.status.config(text="No LogicMods blueprint mods installed.")

    def _sel(self, lb):
        s = lb.curselection()
        return s[0] if s else None

    def _up(self):
        i = self._sel(self.left)
        if i:
            self.ordered[i - 1], self.ordered[i] = self.ordered[i], self.ordered[i - 1]
            self._fill(i - 1)

    def _down(self):
        i = self._sel(self.left)
        if i is not None and i < len(self.ordered) - 1:
            self.ordered[i + 1], self.ordered[i] = self.ordered[i], self.ordered[i + 1]
            self._fill(i + 1)

    def _add(self):
        i = self._sel(self.right)
        if i is not None:
            self.ordered.append(self.rest[i])
            self._fill(len(self.ordered) - 1)

    def _remove(self):
        i = self._sel(self.left)
        if i is not None:
            self.ordered.pop(i)
            self._fill()

    def _save(self):
        try:
            paltools.write_load_order(self.paths, self.ordered)
        except OSError as exc:
            messagebox.showerror(TITLE, str(exc), parent=self)
            return
        self.app.flash(f"Load order saved ({len(self.ordered)} first). "
                       f"Takes effect the next time you play.")
        self.destroy()


# ==========================================================================
# save backups
# ==========================================================================
REASONS = {"auto": "Before a new mod setup", "manual": "Made by you",
           "before restore": "Before a restore"}


class BackupsWindow(Window):
    def __init__(self, app):
        super().__init__(app, "Save backups", "", size="780x560")
        self.game = app._paths["game"]
        self.auto = tk.BooleanVar(value=palpaths.load_settings().get("auto_backup", True))
        checkbox(self.foot, self.auto, BG, app.f_small,
                 "Back up automatically before launching a new mod setup",
                 lambda: palpaths.save_settings({"auto_backup": self.auto.get()})
                 ).pack(side="left", padx=(12, 0))
        button(self.foot, "Back up now", self._backup, "primary", app.f_name,
               (18, 8)).pack(side="right")
        self._build()

    def _build(self):
        self.clear()
        src = palsafety.save_dir(self.game)
        if src is None:
            self.subtitle.config(text="Couldn't find this install's SaveGames folder. "
                                      "Start the game and create a world first.")
        else:
            # The full path is long enough to wrap mid-folder; shorten the part
            # everyone shares.
            local = os.environ.get("LOCALAPPDATA", "")
            shown = str(src)
            if local and shown.lower().startswith(local.lower()):
                shown = "%LOCALAPPDATA%" + shown[len(local):]
            self.subtitle.config(text=f"Worlds are copied from {shown}")
        backups = palsafety.list_backups(self.game)
        self.section("Backups", len(backups))
        if not backups:
            self.note("None yet. One is made automatically the first time you "
                      "press Play with a mod setup you haven't played before.")
        for b in backups:
            card = self.card()
            row = tk.Frame(card, bg=RAISED)
            row.pack(fill="x", padx=12, pady=9)
            # Buttons first: a text column packed before them expands and
            # squeezes them to nothing ("Restore" was rendering as "sto").
            for text, cmd, kind in (
                ("Delete", lambda bb=b: self._delete(bb), "ghost"),
                ("Open", lambda bb=b: open_in_explorer(bb["path"]), "ghost"),
                ("Restore", lambda bb=b: self._restore(bb), "quiet"),
            ):
                button(row, text, cmd, kind, self.app.f_small, (10, 4)).pack(
                    side="right", padx=2)
            col = tk.Frame(row, bg=RAISED)
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=friendly_time(b.get("when")), bg=RAISED, fg=TEXT,
                     font=self.app.f_name, anchor="w").pack(fill="x")
            bits = [REASONS.get(b.get("reason"), b.get("reason", "")),
                    plural(len(b.get('mods') or []), "mod") + " on" if b.get("setup") else None,
                    b.get("build"), human_size(b.get("size", 0))]
            tk.Label(col, text="   ·   ".join(x for x in bits if x), bg=RAISED,
                     fg=FAINT, font=self.app.f_small, anchor="w").pack(fill="x")

    def _backup(self):
        try:
            meta = palsafety.backup_saves(self.game, "manual", self.app._data)
        except (OSError, FileNotFoundError) as exc:
            messagebox.showerror(TITLE, str(exc), parent=self)
            return
        self.status.config(text=f"Backed up {human_size(meta['size'])}.", fg=GOOD)
        self._build()

    def _restore(self, b):
        if not messagebox.askyesno(
                "Restore saves",
                f"Replace your current saves with the backup from "
                f"{friendly_time(b.get('when'))}?\n\nWhat's there now is backed "
                f"up first, so this can be undone.", parent=self):
            return
        try:
            palsafety.restore_backup(self.game, b["id"])
        except (OSError, RuntimeError, FileNotFoundError) as exc:
            messagebox.showerror(TITLE, str(exc), parent=self)
            return
        self.status.config(text="Restored. Your previous saves are the newest backup.",
                           fg=GOOD)
        self._build()

    def _delete(self, b):
        if not messagebox.askyesno(TITLE, f"Move the backup from "
                                   f"{friendly_time(b.get('when'))} to the Recycle Bin?",
                                   parent=self):
            return
        if not paltools.recycle([b["path"]]):
            messagebox.showerror(TITLE, "Couldn't move it to the Recycle Bin.", parent=self)
        self._build()


# ==========================================================================
# fetching UE4SS and PalSchema
# ==========================================================================
class GetWindow(Window):
    """Download UE4SS or PalSchema from its own GitHub release and install it.

    Nothing is fetched until the user reads what it is and presses the button,
    so the window is three states in one: looking, ready, and done.
    """

    WHAT = {
        "ue4ss": {
            "title": "Install UE4SS",
            "blurb": ("UE4SS is the script loader that Lua mods, blueprint "
                      "mods and PalSchema all need. Palworld needs Okaetsu's "
                      "build of it, not the official release."),
        },
        "palschema": {
            "title": "Install PalSchema",
            "blurb": ("PalSchema lets mods change items, Pals and recipes "
                      "with small JSON files instead of paks, so two mods "
                      "changing the same table can both work. It needs UE4SS."),
        },
    }

    def __init__(self, app, kind):
        what = self.WHAT[kind]
        super().__init__(app, what["title"], what["blurb"], size="680x520")
        self.kind = kind
        self.rel = None
        self.q = queue.Queue()
        self.go = button(self.foot, "Download and install", self._start,
                         "primary", app.f_name, (18, 8))
        self.go.pack(side="right")
        self.go.config(state="disabled")
        self.page_btn = button(self.foot, "Release page", self._open_page,
                               "quiet", app.f_small, (12, 6))
        if ((app._data or {}).get("ue4ss") or {}).get("layout") == "workshop":
            self._show_workshop()
            return
        self._show_looking()
        threading.Thread(target=self._look, daemon=True).start()
        self.after(80, self._pump)

    # -- background work ------------------------------------------------
    def _look(self):
        try:
            self.q.put(("found", palget.latest(self.kind)))
        except palget.GetError as exc:
            self.q.put(("failed", str(exc)))

    def _fetch(self):
        try:
            zip_path = palget.download(
                self.rel, palpaths.data_dir() / "downloads",
                progress=lambda d, t: self.q.put(("progress", (d, t))))
            if self.kind == "ue4ss":
                results, _ = palget.install_ue4ss(zip_path, self.app._paths)
            else:
                plan = palinstall.inspect(zip_path)
                try:
                    results = palinstall.apply(plan)
                finally:
                    palinstall.discard(plan)
            self.q.put(("done", results))
        except (palget.GetError, palinstall.InstallError) as exc:
            self.q.put(("failed", str(exc)))
        except OSError as exc:
            self.q.put(("failed", f"Could not write the files: {exc}"))

    def _pump(self):
        """Background threads report here; only this thread touches widgets."""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "found":
                    self.rel = payload
                    self._show_ready()
                elif kind == "progress":
                    done, total = payload
                    self.status.config(
                        text=f"Downloading   {human_size(done)} of "
                             f"{human_size(total)}" if total else
                             f"Downloading   {human_size(done)}")
                elif kind == "done":
                    self._show_done(payload)
                elif kind == "failed":
                    self._show_failed(payload)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(80, self._pump)

    # -- the three states -----------------------------------------------
    def _show_workshop(self):
        """UE4SS here is Palworld's own, from the Steam Workshop."""
        self.clear()
        self.section("This comes from the Steam Workshop here")
        if self.kind == "ue4ss":
            self.note("Palworld installs this UE4SS itself, from the Steam "
                      "Workshop, and keeps it up to date. Installing another by "
                      "hand would load UE4SS twice, which can load mods twice "
                      "or crash the game.", TEXT, pady=(2, 6))
        else:
            server = ((self.app._data or {}).get("workshop") or {}).get("server")
            self.note("With UE4SS from the Steam Workshop, PalSchema comes from "
                      "there too: subscribe to PalSchema on the Workshop, then "
                      f"switch it on in {palworkshop.menu(server)}. Palworld "
                      "keeps it up to date.", TEXT, pady=(2, 6))
        self.status.config(text="", fg=DIM)
        self.go.config(text="Close", state="normal", command=self.destroy)

    def _show_looking(self):
        self.clear()
        self.note("Asking GitHub what the current release is…", DIM,
                  pady=(18, 4))

    def _show_ready(self):
        self.clear()
        rel = self.rel
        paths = self.app._paths
        dest = (paths["win64"] if self.kind == "ue4ss"
                else paths["ue4ss_mods"] / "PalSchema")
        # The full path is long enough to wrap mid-folder. Which install it
        # is, plus the part inside it, says the same thing and fits.
        try:
            where = (f"{palpaths.label(paths['game'])}   ·   "
                     f"{dest.relative_to(paths['game'])}")
        except ValueError:
            where = str(dest)

        self.section("What will be downloaded")
        card = self.card()
        for label, value in (
                ("Release", f"{rel['name']}   ·   {palget.when(rel)}"),
                ("File", rel["asset"]["name"]),
                ("Size", human_size(rel["asset"]["size"])),
                ("From", f"github.com/{rel['repo']}"),
                ("Goes to", where),
        ):
            row = tk.Frame(card, bg=RAISED)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, bg=RAISED, fg=FAINT,
                     font=self.app.f_small, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=RAISED, fg=TEXT, font=self.app.f_small,
                     anchor="w", justify="left", wraplength=460).pack(
                         side="left", fill="x", expand=True)
        tk.Frame(card, bg=RAISED, height=6).pack()

        if self.kind == "ue4ss":
            ue = self.app._data["ue4ss"]
            if ue.get("from_workshop") or ue.get("workshop") not in (None, "none"):
                self.note("Your Steam Workshop script mods won't run in this "
                          "UE4SS: they need the one from the Workshop, and "
                          "running both can crash the game.", WARN,
                          pady=(10, 2), icon_name="alert")
            if ue["installed"]:
                self.note("Your current UE4SS is kept as a folder named "
                          "ue4ss.pmm-old-<date>, so you can go back to it.",
                          DIM, pady=(10, 2), icon_name="undo")
            self.note("Your mods carry over with their settings and stay on "
                      "or off as they are now. UE4SS's own mods, such as "
                      "BPModLoaderMod, are updated, but your load order is "
                      "kept.", DIM, pady=(0 if ue["installed"] else 10, 2))
        else:
            self.note("PalSchema installs like any other mod, into "
                      "ue4ss\\Mods\\PalSchema, and can be switched off from "
                      "the main list.", DIM, pady=(10, 2))
        self.note("Downloaded from the author's own GitHub releases. This app "
                  "does not host or bundle either project.", FAINT, pady=(6, 2))

        self.page_btn.pack(side="right", padx=(0, 8))
        self.go.config(state="normal")
        self.status.config(text="", fg=DIM)

    def _show_done(self, results):
        self.clear()
        self.section("Installed")
        for line in results:
            self.note(line, TEXT, pady=(2, 2), icon_name="check")
        if self.kind == "ue4ss":
            self.note("Play once to check it loads. The session summary will "
                      "say which mods started.", DIM, pady=(10, 2))
        self.status.config(text="", fg=DIM)
        self.go.config(text="Close", state="normal", command=self.destroy)
        self.app.reload(full=True)
        self.app.flash(f"Installed {'UE4SS' if self.kind == 'ue4ss' else 'PalSchema'}")

    def _show_failed(self, message):
        self.clear()
        self.section("That didn't work")
        self.note(message, BAD, pady=(2, 6), icon_name="error")
        self.note("You can still do it by hand: open the release page, "
                  "download the zip, and " +
                  ("extract it into Pal\\Binaries\\Win64."
                   if self.kind == "ue4ss" else
                   "install it here like any other mod."), DIM, pady=(4, 2))
        self.page_btn.pack(side="right", padx=(0, 8))
        self.status.config(text="", fg=DIM)
        self.go.config(text="Try again", state="normal", command=self._retry)

    # -- actions ---------------------------------------------------------
    def _retry(self):
        self.go.config(text="Download and install", state="disabled",
                       command=self._start)
        self._show_looking()
        threading.Thread(target=self._look, daemon=True).start()

    def _start(self):
        if palsafety.game_running(self.app._paths["game"]):
            messagebox.showwarning(TITLE, "Close Palworld first. Its files are "
                                   "in use while it runs.", parent=self)
            return
        self.go.config(state="disabled")
        self.page_btn.pack_forget()
        self.status.config(text="Downloading…")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _open_page(self):
        url = (self.rel or {}).get("page") or \
            f"https://github.com/{palget.UE4SS_REPO}/releases"
        open_link(url)


# ==========================================================================
# cleanup
# ==========================================================================
class CleanupWindow(Window):
    def __init__(self, app):
        super().__init__(app, "Clean up leftovers",
                         "Files that belong to no installed mod. Everything "
                         "removed goes to the Recycle Bin.", size="820x560")
        self.go = button(self.foot, "Move to Recycle Bin", self._clean, "primary",
                         app.f_name, (18, 8))
        self.go.pack(side="right")
        self._build()

    def _build(self):
        self.clear()
        paths, data = self.app._paths, self.app._data
        self.items = paltools.find_leftovers(paths, data)
        self.vars = []
        if not self.items:
            self.note("Nothing to clean up.", TEXT, pady=(16, 4))
            self.go.config(state="disabled")
            self.status.config(text="")
            return
        game = paths["game"]
        for it in self.items:
            var = tk.BooleanVar(value=it["checked"])
            self.vars.append(var)
            card = self.card()
            row = tk.Frame(card, bg=RAISED)
            row.pack(fill="x", padx=10, pady=8)
            checkbox(row, var, RAISED, command=self._count).pack(side="left", padx=(0, 8))
            col = tk.Frame(row, bg=RAISED)
            col.pack(side="left", fill="x", expand=True)
            top = tk.Frame(col, bg=RAISED)
            top.pack(fill="x")
            try:
                rel = str(Path(it["path"]).relative_to(game))
            except ValueError:
                rel = it["path"]
            tk.Label(top, text=Path(it["path"]).name, bg=RAISED, fg=TEXT,
                     font=self.app.f_name).pack(side="left")
            # An old UE4SS holding mods that aren't installed may be the only
            # copy of them.
            Pill(top, it["kind"], WARN if it.get("missing") else DIM, SURFACE,
                 RAISED, self.app.f_pill).pack(side="left", padx=8)
            tk.Label(top, text=human_size(it["size"]), bg=RAISED, fg=FAINT,
                     font=self.app.f_small).pack(side="right")
            tk.Label(col, text=it["why"], bg=RAISED, fg=DIM, font=self.app.f_small,
                     anchor="w", wraplength=620, justify="left").pack(fill="x")
            tk.Label(col, text=rel, bg=RAISED, fg=FAINT, font=self.app.f_small,
                     anchor="w", wraplength=620, justify="left").pack(fill="x")
        self._count()

    def _count(self):
        chosen = [it for it, v in zip(self.items, self.vars) if v.get()]
        self.status.config(text=f"{len(chosen)} selected   ·   "
                                f"{human_size(sum(i['size'] for i in chosen))}",
                           fg=DIM)
        self.go.config(state="normal" if chosen else "disabled")

    def _clean(self):
        chosen = [it["path"] for it, v in zip(self.items, self.vars) if v.get()]
        if not chosen:
            return
        if palsafety.game_running(self.app._paths["game"]):
            messagebox.showwarning(TITLE, "Close Palworld first. Some of these "
                                   "files may be in use.", parent=self)
            return
        if paltools.recycle(chosen):
            self.app.flash(f"Moved {plural(len(chosen), 'leftover')} to the Recycle Bin")
        else:
            messagebox.showerror(TITLE, "Some items couldn't be moved to the "
                                 "Recycle Bin.", parent=self)
        self.app.reload()
        self._build()


# ==========================================================================
# modlists
# ==========================================================================
def copy_modlist(app):
    doc = paltools.export_modlist(app._data)
    app.root.clipboard_clear()
    app.root.clipboard_append(paltools.modlist_text(doc))
    app.flash(f"Copied a list of {plural(len(doc['mods']), 'mod')}. Paste it anywhere.")


def export_modlist(app):
    out = filedialog.asksaveasfilename(
        title="Export modlist", defaultextension=".json",
        initialfile="palworld-modlist.json",
        filetypes=[("EZ Pal Mod Manager modlist", "*.json")])
    if not out:
        return
    doc = paltools.export_modlist(app._data)
    Path(out).write_text(json.dumps(doc, indent=2) + "\n", "utf8")
    app.flash(f"Exported {plural(len(doc['mods']), 'mod')}. Send the file to a friend "
              f"to compare setups.")


class CompareWindow(Window):
    """A friend's modlist against yours: what to download, turn on, turn off."""

    def __init__(self, app, doc, source):
        super().__init__(app, "Compare modlists",
                         f"{Path(source).name}"
                         + (f"   ·   {doc['game']}" if doc.get("game") else "")
                         + (f"   ·   {doc['ue4ss']}" if doc.get("ue4ss") else ""),
                         size="760x600")
        self.doc = doc
        self.result = paltools.compare_modlist(doc, app._data)
        r = self.result
        stage = button(self.foot, "Match their setup", self._stage, "primary",
                       app.f_name, (18, 8))
        stage.pack(side="right")
        if not (r["turn_on"] or r["turn_off"]):
            stage.config(state="disabled")
        self.status.config(text=f"{len(r['matched'])} of {len(r['want_on'])} "
                                f"of their mods already on")

        mine_build = (app._data.get("build") or {}).get("label")
        if doc.get("game") and mine_build and doc["game"] != mine_build:
            self.note(f"They're on {doc['game']}; you're on {mine_build}. "
                      f"Mod versions may need to differ.", WARN, pady=(12, 0))

        self.section("You need to install", len(r["missing"]))
        if not r["missing"]:
            self.note("Nothing. You have every mod they use.")
        for m in r["missing"]:
            card = self.card()
            row = tk.Frame(card, bg=RAISED)
            row.pack(fill="x", padx=12, pady=8)
            tk.Label(row, text=m.get("title") or m["name"], bg=RAISED, fg=TEXT,
                     font=app.f_name).pack(side="left")
            Pill(row, m.get("kind", "mod"), DIM, SURFACE, RAISED,
                 app.f_pill).pack(side="left", padx=8)
            if m.get("version"):
                tk.Label(row, text=f"v{m['version']}", bg=RAISED, fg=FAINT,
                         font=app.f_small).pack(side="left")
            if palregistry.web_link(m.get("url")):
                button(row, "Open page", lambda u=m["url"]: open_link(u),
                       "quiet", app.f_small, (10, 4)).pack(side="right")

        for title, names in (("You have but is off", r["turn_on"]),
                             ("You run but they don't", r["turn_off"])):
            self.section(title, len(names))
            self.note(",  ".join(names) if names else "None.",
                      TEXT if names else FAINT)
        if r["versions"]:
            self.section("Different versions", len(r["versions"]))
            for name, theirs, mine in r["versions"]:
                self.note(f"{name}:  theirs v{theirs},  yours v{mine}", TEXT)

    def _stage(self):
        app, r = self.app, self.result
        # A shared modlist names mods, like the registry does, so every mod
        # of a name follows it: both halves of a hybrid mod together.
        staged = 0
        for names, value in ((r["turn_on"], True), (r["turn_off"], False)):
            for mid, row in app.rows.items():
                if row["entry"]["name"] in names:
                    app._set_row(mid, value)
                    staged += row["was"] != value
        app._recount()
        app.status.config(text=f"{plural(staged, 'change')} ready to match their setup. "
                               f"Press Apply changes to use "
                               f"{'it' if staged == 1 else 'them'}.", fg=TEXT)
        self.destroy()


def compare_modlist(app):
    src = filedialog.askopenfilename(title="Open a friend's modlist",
                                     filetypes=[("EZ Pal Mod Manager modlist", "*.json")])
    if not src:
        return
    try:
        doc = paltools.load_modlist(src)
    except ValueError as exc:
        messagebox.showerror(TITLE, str(exc))
        return
    CompareWindow(app, doc, src)


# ==========================================================================
# play session summary
# ==========================================================================
class SessionWindow(Window):
    """What happened in the session that just ended."""

    def __init__(self, app, minutes=None):
        data = app._data
        # Switched on during that session, they start with the next one.
        waiting = set(data["patch"].get("waiting", ()))
        user = [m for m in data["ue4ss_mods"] if not m["builtin"] and m["enabled"]
                and palregistry.mod_id("ue4ss", m["name"]) not in waiting]
        logic = [p for p in data["pak_mods"]
                 if not p["disabled"] and p["folder"] == "LogicMods"
                 and palregistry.mod_id("pak", p["name"]) not in waiting]
        workshop = [w for w in data.get("workshop_mods", []) if w["loggable"]
                    and palregistry.mod_id("workshop", w["name"]) not in waiting]
        loaded = [m["name"] for m in user if m["loaded"] and not m["failures"]] + \
                 [p["name"] for p in logic if p["loaded"]] + \
                 [w["title"] for w in workshop if w["loaded"] and not w["failures"]]
        failed = [(m["name"], "; ".join(m["failures"])) for m in user if m["failures"]] + \
                 [(w["title"], "; ".join(w["failures"])) for w in workshop if w["failures"]]
        missing = [m["name"] for m in user if not m["loaded"] and not m["failures"]] + \
                  [p["name"] for p in logic if not p["loaded"]] + \
                  [w["title"] for w in workshop if not w["loaded"] and not w["failures"]]
        content = [p["name"] for p in data["pak_mods"]
                   if not p["disabled"] and p["folder"] != "LogicMods"] + \
                  [w["title"] for w in data.get("workshop_mods", [])
                   if w["enabled"] and w["applies"] and w["types"] == ["Paks"]]
        regressed = data["patch"]["regressed"]
        # Regressions are noted by package name; the list shows titles.
        regressed = dict(regressed, **{w["title"]: regressed[w["name"]]
                                       for w in workshop if w["name"] in regressed})

        head = "Everything you had on loaded." if not (failed or missing) else \
            f"{plural(len(failed) + len(missing), 'mod')} didn't load."
        when = f"Session of about {minutes} min   ·   " if minutes else ""
        super().__init__(app, "Play session ended",
                         f"{when}{data['patch']['build']}   ·   {head}",
                         size="660x520")
        if failed or missing:
            button(self.foot, "Show problems", self._problems, "primary",
                   app.f_name, (18, 8)).pack(side="right")
        button(self.foot, "UE4SS log", lambda: LogWindow(app), "quiet",
               app.f_small, (12, 8)).pack(side="right", padx=8)

        if failed:
            self.section("Failed", len(failed))
            for name, why in failed:
                self.note(name, BAD, pady=(0, 0), icon_name="error")
                self.note(why, DIM, pady=(0, 8))
        if missing:
            self.section("On, but didn't start", len(missing))
            for name in missing:
                note = (f": worked on {regressed[name]}, not since the update"
                        if name in regressed else "")
                self.note(f"{name}{note}", WARN, icon_name="alert")
        self.section("Loaded", len(loaded))
        self.note(",  ".join(loaded) if loaded else "No UE4SS or blueprint mods "
                  "were on.", GOOD if loaded else FAINT,
                  icon_name="check" if loaded else None)
        if content:
            self.section("Content paks", len(content))
            self.note("These never write to the log, so whether they worked can "
                      "only be seen in game: " + ",  ".join(content))

    def _problems(self):
        self.app._set_tab("Problems")
        self.destroy()
