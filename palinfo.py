#!/usr/bin/env python3
"""The mod info window: pictures, description, and where the mod came from."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import palmedia
import palregistry
from paltext import plural
from palui import (open_link, BG, SURFACE, RAISED, LINE, TEXT, DIM, FAINT, ACCENT, GOOD,
                   WARN, BAD, Pill, button, dark_titlebar, menu as dark_menu,
                   open_in_explorer, Window, ON_ACCENT)

TITLE = "EZ Pal Mod Manager"

try:
    from PIL import ImageTk
except ImportError:
    ImageTk = None


def photo(path):
    """A Tk image for a file on disk, or None."""
    if ImageTk is None:
        return None
    try:
        return ImageTk.PhotoImage(file=str(path))
    except Exception:
        return None


# ==========================================================================
# full-size viewer
# ==========================================================================
class ImageViewer(tk.Toplevel):
    """One picture at a time, sized to the screen. Arrows step, Esc closes."""

    def __init__(self, parent, images, index=0):
        super().__init__(parent)
        self.images, self.index, self._img = list(images), index, None
        self.configure(bg="#08090c")
        self.title("Picture")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.box = (int(sw * 0.8), int(sh * 0.8))
        self.geometry(f"{self.box[0]}x{self.box[1] + 30}+{int(sw * .1)}+{int(sh * .07)}")
        self.label = tk.Label(self, bg="#08090c", cursor="hand2")
        self.label.pack(fill="both", expand=True)
        self.caption = tk.Label(self, bg="#08090c", fg=FAINT, font=("Segoe UI", 9))
        self.caption.pack(fill="x", pady=(0, 8))
        self.label.bind("<Button-1>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Right>", lambda _e: self.step(1))
        self.bind("<Left>", lambda _e: self.step(-1))
        self.after(10, lambda: dark_titlebar(self))
        self.show()
        self.focus_set()

    def step(self, delta):
        if len(self.images) > 1:
            self.index = (self.index + delta) % len(self.images)
            self.show()

    def show(self):
        path = self.images[self.index]
        try:
            thumb = palmedia.thumbnail(path, *self.box, fit="contain")
        except (palmedia.MediaError, OSError):
            thumb = path
        self._img = photo(thumb)
        self.label.config(image=self._img or "", text="" if self._img else path.name)
        more = f"{self.index + 1} of {len(self.images)}   ·   ← → to browse   ·   " \
            if len(self.images) > 1 else ""
        self.caption.config(text=f"{more}click or Esc to close")


# ==========================================================================
# the info window
# ==========================================================================
class ModInfoWindow(Window):
    HERO = (760, 340)
    THUMB = (128, 72)

    def __init__(self, app, entry):
        self.mod = entry["name"]
        self.entry = entry
        meta = palregistry.get(self.mod)
        # The list rows stay lean; type, folder and version are shown here.
        kind = {"lua": "Lua script mod", "c++": "C++ script mod",
                "palschema": "PalSchema mod"}.get(entry["kind"])
        if kind is None:
            kind = "blueprint pak" if entry.get("where") == "LogicMods" else "pak mod"
        bits = [f"{kind} in {entry.get('where', '?')}",
                palregistry.describe_source(self.mod, meta)]
        version = meta.get("version") or (entry.get("extra")
                                          if entry["group"] == "UE4SS mods" else None)
        if version:
            bits.append(f"v{version}")
        bits.append(entry["state"][:1].upper() + entry["state"][1:])
        sub = "   ·   ".join(bits)
        super().__init__(app, self.mod, sub, size="840x820")
        self.minsize(700, 520)
        self._photos = []
        self.shown = None                   # image shown in the hero area
        self.mod_path = entry.get("path")

        button(self.foot, "Save", self._save, "primary", app.f_name,
               (22, 8)).pack(side="right")
        self.page_btn = button(self.foot, "Open mod page", self._open_page,
                               "quiet", app.f_small, (14, 8))
        self.page_btn.pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Control-s>", lambda _e: self._save())
        self.bind("<Control-v>", self._ctrl_v)

        self._build_pictures()
        self._build_description(meta)
        self._build_source(meta)
        self._build_install(meta)
        self._baseline = self._snapshot()
        self._refresh_page_button()
        self.bind("<FocusIn>", lambda _e: self._clipboard_hint())

    # ------------------------------------------------------------ pictures
    def _build_pictures(self):
        app = self.app
        self.section("Pictures")
        self.pic_frame = tk.Frame(self.body, bg=SURFACE)
        self.pic_frame.pack(fill="x", padx=22)

        tools = tk.Frame(self.body, bg=SURFACE)
        tools.pack(fill="x", padx=22, pady=(8, 0))
        self.paste_img_btn = button(tools, "Paste image", self._paste_image,
                                    "quiet", app.f_small, (12, 5))
        self.paste_img_btn.pack(side="left")
        button(tools, "Add pictures…", self._add_files, "quiet", app.f_small,
               (12, 5)).pack(side="left", padx=6)
        self.clip_note = tk.Label(tools, text="", bg=SURFACE, fg=GOOD,
                                  font=app.f_small)
        self.clip_note.pack(side="left", padx=8)
        if not palmedia.HAVE_PIL:
            self.paste_img_btn.config(state="disabled")
            self.clip_note.config(text="Pictures need Pillow, which this build lacks.",
                                  fg=WARN)

        self.suggest = tk.Frame(self.body, bg=SURFACE)
        self.suggest.pack(fill="x", padx=22)
        self._render_pictures()

    def _render_pictures(self):
        for w in self.pic_frame.winfo_children():
            w.destroy()
        for w in self.suggest.winfo_children():
            w.destroy()
        self._photos.clear()
        media = palmedia.info(self.mod)
        images = media["images"]
        if self.shown not in images:
            self.shown = media["cover"]

        hero = tk.Frame(self.pic_frame, bg="#0d0f13", height=self.HERO[1],
                        highlightthickness=1, highlightbackground=LINE)
        hero.pack(fill="x")
        hero.pack_propagate(False)
        if self.shown:
            try:
                img = photo(palmedia.thumbnail(self.shown, *self.HERO, fit="contain"))
            except (palmedia.MediaError, OSError):
                img = None
            self._photos.append(img)
            lbl = tk.Label(hero, image=img or "", bg="#0d0f13", cursor="hand2",
                           text="" if img else "Couldn't display this picture",
                           fg=FAINT)
            lbl.pack(fill="both", expand=True)
            lbl.bind("<Button-1>", lambda _e: ImageViewer(
                self, images, images.index(self.shown)))
        else:
            empty = tk.Frame(hero, bg="#0d0f13")
            empty.place(relx=.5, rely=.5, anchor="center")
            tk.Label(empty, text="No pictures yet", bg="#0d0f13", fg=DIM,
                     font=self.app.f_body).pack()
            tk.Label(empty, text="Copy one from the mod page and press Paste image,"
                                 "\nor add screenshots from your PC.",
                     bg="#0d0f13", fg=FAINT, font=self.app.f_small,
                     justify="center").pack(pady=(4, 0))

        if images:
            strip = tk.Frame(self.pic_frame, bg=SURFACE)
            strip.pack(fill="x", pady=(8, 0))
            for i, path in enumerate(images):
                self._thumb(strip, images, i, path, path == media["cover"])

        sug = palmedia.suggestions(self.mod, self.mod_path)
        if sug["images"]:
            self._suggestion(
                f"Found {plural(len(sug['images']), 'picture')} in the mod's folder.",
                "Add them", lambda s=sug["images"]: self._add_paths(s))

    def _thumb(self, strip, images, i, path, is_cover):
        cell = tk.Frame(strip, bg=ACCENT if path == self.shown else SURFACE,
                        padx=2, pady=2)
        cell.grid(row=0, column=i, padx=(0, 6))
        try:
            img = photo(palmedia.thumbnail(path, *self.THUMB))
        except (palmedia.MediaError, OSError):
            img = None
        self._photos.append(img)
        lbl = tk.Label(cell, image=img or "", text="" if img else "?", bg=RAISED,
                       fg=FAINT, width=self.THUMB[0] if img else 12,
                       cursor="hand2")
        lbl.pack()
        if is_cover:
            tk.Label(cell, text="Cover", bg=SURFACE, fg=DIM,
                     font=self.app.f_pill).pack(fill="x")
        lbl.bind("<Button-1>", lambda _e, p=path: self._show(p))
        lbl.bind("<Double-Button-1>", lambda _e: ImageViewer(self, images, i))
        lbl.bind("<Button-3>", lambda ev, p=path: self._thumb_menu(ev, images, p))

    def _thumb_menu(self, event, images, path):
        m = dark_menu(self, self.app.f_small)
        m.add_command(label="View full size",
                      command=lambda: ImageViewer(self, images, images.index(path)))
        m.add_command(label="Use as cover",
                      command=lambda: self._set_cover(path))
        m.add_command(label="Show in folder", command=lambda: open_in_explorer(path))
        m.add_separator()
        m.add_command(label="Remove", command=lambda: self._remove(path))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _show(self, path):
        self.shown = path
        self._render_pictures()

    def _set_cover(self, path):
        palmedia.set_cover(self.mod, path.name)
        self.shown = path
        self._changed_media("Cover set.")

    def _remove(self, path):
        palmedia.remove_image(self.mod, path.name)
        if self.shown == path:
            self.shown = None
        self._changed_media("Picture removed.")

    def _paste_image(self):
        try:
            added = palmedia.paste_images(self.mod)
        except palmedia.MediaError as exc:
            self.status.config(text=str(exc), fg=WARN)
            return
        self.shown = added[-1]
        self._changed_media(f"Added {plural(len(added), 'picture')}.")

    def _add_files(self):
        picked = filedialog.askopenfilenames(
            parent=self, title="Add pictures",
            filetypes=[("Pictures", " ".join(f"*{s}" for s in palmedia.IMAGE_SUFFIXES)),
                       ("All files", "*.*")])
        if picked:
            self._add_paths(picked)

    def _add_paths(self, paths):
        added, failed = [], []
        for p in paths:
            try:
                added.append(palmedia.add_image_file(self.mod, p))
            except palmedia.MediaError:
                failed.append(Path(p).name)
        if added:
            self.shown = added[-1]
        msg = f"Added {plural(len(added), 'picture')}."
        if failed:
            msg += f" Couldn't read: {', '.join(failed)}."
        self._changed_media(msg, WARN if failed else GOOD)

    def _changed_media(self, msg, fg=GOOD):
        self._render_pictures()
        self.status.config(text=msg + "  Pictures are saved as you add them.", fg=fg)
        self.app.media_changed(self.mod)

    def _suggestion(self, text, action, cmd):
        row = tk.Frame(self.suggest, bg="#1a2233", highlightthickness=1,
                       highlightbackground="#2b3a57")
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="  " + text, bg="#1a2233", fg="#b9cdfa",
                 font=self.app.f_small, anchor="w").pack(side="left", pady=6)
        button(row, action, cmd, "quiet", self.app.f_small, (10, 3)).pack(
            side="right", padx=6, pady=4)
        return row

    def _clipboard_hint(self):
        """When the window regains focus, say what the clipboard can offer."""
        if not self.winfo_exists() or not palmedia.HAVE_PIL:
            return
        kind, _ = palmedia.clipboard_image()
        if kind:
            self.clip_note.config(text="← there's a picture on your clipboard", fg=GOOD)
        else:
            self.clip_note.config(text="")

    # ------------------------------------------------------------ description
    def _build_description(self, meta):
        app = self.app
        self.section("Description")
        self.note(palmedia.page_hint(meta), pady=(0, 6))

        frame = tk.Frame(self.body, bg=SURFACE)
        frame.pack(fill="x", padx=22)
        # No Scrollbar: Tk's native one can't be themed and draws bright white.
        # The wheel scrolls the box, and it grows to fit (see _text_modified).
        self.text = tk.Text(frame, height=10, wrap="word", bg=RAISED, fg=TEXT,
                            insertbackground=TEXT, relief="flat", padx=10, pady=8,
                            font=app.f_body, undo=True, selectbackground=ACCENT,
                            selectforeground=ON_ACCENT)
        self.text.pack(fill="x", expand=True)
        self.text.insert("1.0", meta.get("description") or "")
        self.text.edit_reset()
        # Keep the wheel for the text box while the pointer is over it.
        self.text.bind("<MouseWheel>", lambda e: (
            self.text.yview_scroll(int(-e.delta / 120), "units"), "break")[1])
        self.text.bind("<<Modified>>", self._text_modified)

        tools = tk.Frame(self.body, bg=SURFACE)
        tools.pack(fill="x", padx=22, pady=(8, 0))
        button(tools, "Paste text", self._paste_text, "quiet", app.f_small,
               (12, 5)).pack(side="left")
        button(tools, "Clear", lambda: self.text.delete("1.0", "end"), "ghost",
               app.f_small, (10, 5)).pack(side="left", padx=6)
        self.count = tk.Label(tools, text="", bg=SURFACE, fg=FAINT, font=app.f_small)
        self.count.pack(side="right")
        self._text_modified()

        sug = palmedia.suggestions(self.mod, self.mod_path)
        if sug["readme"]:
            holder = tk.Frame(self.body, bg=SURFACE)
            holder.pack(fill="x", padx=22)
            row = tk.Frame(holder, bg="#1a2233", highlightthickness=1,
                           highlightbackground="#2b3a57")
            row.pack(fill="x", pady=(8, 0))
            tk.Label(row, text=f"  The mod ships a {sug['readme_path'].name} "
                               f"({len(sug['readme'])} characters).",
                     bg="#1a2233", fg="#b9cdfa", font=app.f_small,
                     anchor="w").pack(side="left", pady=6)
            button(row, "Use it", lambda: (self._set_text(sug["readme"]),
                                           row.destroy()),
                   "quiet", app.f_small, (10, 3)).pack(side="right", padx=6, pady=4)

    def _text_modified(self, _e=None):
        self.text.edit_modified(False)
        body = self.text.get("1.0", "end")
        words = len(body.split())
        self.count.config(text=f"{words} words" if words else "")
        # Grow with the text up to 24 lines; the page scrolls, not the box.
        lines = sum(max(1, len(ln) // 90 + 1) for ln in body.splitlines())
        self.text.configure(height=max(10, min(24, lines + 1)))

    def _set_text(self, value):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value.strip())
        self._text_modified()

    def _paste_text(self):
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            clip = ""
        clip = clip.replace("\r\n", "\n").strip()
        if not clip:
            self.status.config(text="There's no text on the clipboard.", fg=WARN)
            return
        if self.text.tag_ranges("sel"):
            self.text.delete("sel.first", "sel.last")
            self.text.insert("insert", clip)
        elif self.text.get("1.0", "end").strip():
            self.text.insert("end", "\n\n" + clip)
        else:
            self.text.insert("1.0", clip)
        self._text_modified()
        self.status.config(text="Pasted. Press Save to keep it.", fg=DIM)

    def _ctrl_v(self, event):
        # Ctrl+V in the text box pastes text as usual. Anywhere else in the
        # window, a copied picture is added.
        if event.widget is self.text or isinstance(event.widget, tk.Entry):
            return None
        kind, _ = palmedia.clipboard_image()
        if kind:
            self._paste_image()
            return "break"
        return None

    # ------------------------------------------------------------ source
    def _build_source(self, meta):
        app = self.app
        self.section("Where it came from")
        box = tk.Frame(self.body, bg=SURFACE)
        box.pack(fill="x", padx=22)
        box.columnconfigure(1, weight=1)

        def label(r, text):
            tk.Label(box, text=text, bg=SURFACE, fg=DIM, font=app.f_small,
                     anchor="w", width=12).grid(row=r, column=0, sticky="w", pady=4)

        self.vars = {}
        label(0, "Mod page")
        self.vars["url"] = tk.StringVar(value=meta.get("url") or "")
        link = tk.Entry(box, textvariable=self.vars["url"], bg=RAISED, fg=TEXT,
                        relief="flat", insertbackground=TEXT, font=app.f_small)
        link.grid(row=0, column=1, sticky="ew", ipady=5, ipadx=6)
        self.link_note = tk.Label(box, text="Paste the page's address. The source "
                                            "and ID fill in from the link itself.",
                                  bg=SURFACE, fg=FAINT, font=app.f_pill, anchor="w")
        self.link_note.grid(row=1, column=1, sticky="w")
        self.vars["url"].trace_add("write", lambda *_: self._link_changed())

        label(2, "Source")
        self.source = tk.StringVar(value=meta.get("source") or "unknown")
        radios = tk.Frame(box, bg=SURFACE)
        radios.grid(row=2, column=1, sticky="w")
        for s in palregistry.SOURCES:
            tk.Radiobutton(radios, text="your mod" if s == "local" else s, value=s,
                           variable=self.source, bg=SURFACE, fg=DIM,
                           selectcolor=RAISED, activebackground=SURFACE,
                           activeforeground=TEXT, font=app.f_small, bd=0,
                           highlightthickness=0,
                           command=self._refresh_page_button).pack(side="left", padx=(0, 8))

        for r, (key, text) in enumerate((("id", "Mod ID"), ("version", "Version"),
                                         ("released", "Released"),
                                         ("note", "Private notes")), start=3):
            label(r, text)
            self.vars[key] = tk.StringVar(value=str(meta.get(key) or ""))
            tk.Entry(box, textvariable=self.vars[key], bg=RAISED, fg=TEXT,
                     relief="flat", insertbackground=TEXT, font=app.f_small
                     ).grid(row=r, column=1, sticky="ew", ipady=4, ipadx=6)

    def _link_changed(self):
        parsed = palmedia.parse_link(self.vars["url"].get())
        if parsed.get("source") in ("Nexus", "CurseForge"):
            self.source.set(parsed["source"])
            if parsed.get("id"):
                self.vars["id"].set(str(parsed["id"]))
            what = f"{parsed['source']} mod {parsed['id']}" if parsed.get("id") \
                else f"{parsed['source']} page"
            self.link_note.config(text=f"Recognised: {what}", fg=GOOD)
        elif self.vars["url"].get().strip():
            self.link_note.config(text="Saved as a link.", fg=FAINT)
        self._refresh_page_button()

    def _page_url(self):
        url = self.vars["url"].get().strip()
        if url:
            return palmedia.parse_link(url).get("url", url)
        fields = {"source": self.source.get(), "id": self.vars["id"].get().strip()}
        return palregistry.url_for(self.mod, {k: v for k, v in fields.items() if v})

    def _refresh_page_button(self):
        url = self._page_url()
        ok = bool(url) and str(url).startswith(("http://", "https://"))
        self.page_btn.config(state="normal" if ok else "disabled")

    def _open_page(self):
        url = self._page_url()
        if url:
            open_link(url)
            self.status.config(text="Copy the description or a picture there, then "
                                    "come back and paste.", fg=DIM)

    # ------------------------------------------------------------ install info
    def _build_install(self, meta):
        rec = palregistry.receipt(self.mod)
        lines = []
        if meta.get("installed"):
            lines.append(f"Installed {meta['installed']}"
                         + (f" from {Path(meta['installed_from']).name}"
                            if meta.get("installed_from") else ""))
        lines.append(f"{plural(len(rec['files']), 'file')} tracked, so it uninstalls cleanly"
                     if rec else "Not installed by this app. Uninstall removes "
                                 "its folder or pak.")
        where = self.entry.get("path") or self.entry.get("pak_path")
        self.section("On disk")
        self.note("\n".join(lines))
        if where:
            row = tk.Frame(self.body, bg=SURFACE)
            row.pack(fill="x", padx=22, pady=(0, 16))
            tk.Label(row, text=where, bg=SURFACE, fg=FAINT, font=self.app.f_small,
                     anchor="w", wraplength=600, justify="left").pack(side="left")
            show = button(row, "Show", lambda: open_in_explorer(where), "ghost",
                          self.app.f_small, (8, 2))
            show.configure(bg=SURFACE)
            show.pack(side="right")

    # ------------------------------------------------------------ saving
    def _snapshot(self):
        return (self.text.get("1.0", "end").strip(), self.source.get(),
                tuple(v.get().strip() for v in self.vars.values()))

    def _save(self, close=False):
        vals = {k: (v.get().strip() or None) for k, v in self.vars.items()}
        if vals.get("id"):
            try:
                vals["id"] = int(vals["id"])
            except ValueError:
                messagebox.showerror(TITLE, "Mod ID must be a number.", parent=self)
                return False
        if vals.get("url"):
            vals["url"] = palmedia.parse_link(vals["url"]).get("url", vals["url"])
        palregistry.set_entry(self.mod, source=self.source.get(), **vals)
        palmedia.set_description(self.mod, self.text.get("1.0", "end"))
        self._baseline = self._snapshot()
        self.status.config(text="Saved.", fg=GOOD)
        self.app.media_changed(self.mod)
        if close:
            self.destroy()
        return True

    def _close(self):
        if self._snapshot() != self._baseline:
            ans = messagebox.askyesnocancel(TITLE, "Save your changes to the "
                                           "description and details?", parent=self)
            if ans is None:
                return
            if ans:
                if self._save():
                    self.destroy()
                return
        self.destroy()
