#!/usr/bin/env python3
"""Shared look and widgets for every EZ Pal Mod Manager window.

The look: warm charcoal surfaces, one amber accent reserved for the actions
that matter (Play, switches that are on), hairline dividers instead of boxed
cards, and icons drawn by palicons rather than emoji. Tk has no rounded
rectangles, switches or themeable scrollbars, so those are drawn on canvases
here.
"""

import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import palicons
from paltext import plural  # noqa: F401  (re-exported for the windows)

# ---------------------------------------------------------------- palette
BG          = "#1a1d22"   # window chrome: header band, footer, dialogs
SURFACE     = "#15181c"   # content: the mod list, dialog bodies
RAISED      = "#23272d"   # inputs, cards, secondary buttons
HOVER       = "#1e2227"   # row under the pointer
LINE        = "#2b3037"   # hairline dividers
TEXT        = "#ece8df"
DIM         = "#a39e92"   # secondary text
FAINT       = "#6f6b62"   # tertiary text, off states
ACCENT      = "#f2b544"   # amber: Play, switches that are on, selection
ACCENT_HI   = "#f6c566"
ON_ACCENT   = "#16191d"   # text and knobs on amber
GOOD        = "#7fc48f"
WARN        = "#e6b45c"
BAD         = "#e5786d"
PEND        = ACCENT      # unapplied switches: amber outline, not a new colour
PROBLEM_BG  = "#1c1a16"   # warm tint behind rows that need attention
BUTTON_HI   = "#2c3138"

TITLE_FONT = "Bahnschrift SemiBold"     # ships with Windows 10 and 11
BODY_FONT = "Segoe UI"
STRONG_FONT = "Segoe UI Semibold"


def rounded(cv, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle on a Canvas -- Tk has no native one."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def open_link(url):
    """Open a web page in the browser -- and never anything that isn't one."""
    import webbrowser
    import palregistry
    safe = palregistry.web_link(url)
    if not safe:
        messagebox.showwarning("EZ Pal Mod Manager",
                               "That link isn't a web address, so it wasn't "
                               "opened.")
        return False
    webbrowser.open(safe)
    return True


def open_in_explorer(path):
    p = Path(path)
    try:
        if p.is_dir():
            os.startfile(str(p))
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])
    except OSError as exc:
        messagebox.showerror("EZ Pal Mod Manager", str(exc))


def icon(name, colour, size=16):
    """Tk image of an app icon (see palicons)."""
    return palicons.photo(name, size, colour)


def bg_of(widget, default=SURFACE):
    try:
        return widget.cget("bg")
    except tk.TclError:
        return default


# ---------------------------------------------------------------- widgets
class Toggle(tk.Canvas):
    """The on/off switch.

    On is an amber track with a dark knob; off is a grey track. A change that
    hasn't been applied yet keeps the knob where it will end up but draws the
    track as an amber outline, so pending changes read as "not done yet"
    without a colour of their own.
    """

    W, H = 34, 19

    def __init__(self, parent, value, command, bg):
        s = palicons.scale
        super().__init__(parent, width=round(self.W * s), height=round(self.H * s),
                         bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.value, self.command = value, command
        self.pending = False
        self.bind("<Button-1>", self._click)
        self.draw()

    def draw(self):
        self.delete("all")
        s = palicons.scale
        w, h = self.W * s, self.H * s
        r = (h - 2) / 2
        if self.pending:
            rounded(self, 1.5, 1.5, w - 1.5, h - 1.5, r - 0.5, fill=bg_of(self),
                    outline=ACCENT, width=max(1.5, 1.5 * s))
            knob = ACCENT
        elif self.value:
            rounded(self, 1, 1, w - 1, h - 1, r, fill=ACCENT, outline="")
            knob = ON_ACCENT
        else:
            rounded(self, 1, 1, w - 1, h - 1, r, fill="#3a3f46", outline="")
            knob = "#8b877c"
        kr = h / 2 - 4 * s
        cx = w - h / 2 if self.value else h / 2
        self.create_oval(cx - kr, h / 2 - kr, cx + kr, h / 2 + kr, fill=knob, outline="")

    def set(self, value, pending=False):
        self.value, self.pending = value, pending
        self.draw()

    def recolour(self, bg):
        self.configure(bg=bg)
        if self.pending:
            self.draw()

    def _click(self, _e):
        self.value = not self.value
        self.draw()
        if self.command:
            self.command(self.value)


class Pill(tk.Canvas):
    """Small rounded tag."""

    def __init__(self, parent, text, fg, fill, surface, font, command=None):
        w = font.measure(text) + 16
        h = font.metrics("linespace") + 4
        super().__init__(parent, width=w, height=h, bg=surface,
                         highlightthickness=0, bd=0,
                         cursor="hand2" if command else "")
        # NB: never name this _w -- tkinter uses that for the widget pathname.
        self._fill, self._fg, self._txt, self._font = fill, fg, text, font
        self._pw, self._ph = w, h
        if command:
            self.bind("<Button-1>", lambda _e: command())
        self._paint()

    def _paint(self):
        self.delete("all")
        rounded(self, 0, 0, self._pw, self._ph, self._ph / 2, fill=self._fill, outline="")
        self.create_text(self._pw / 2, self._ph / 2, text=self._txt, fill=self._fg,
                         font=self._font)

    def recolour(self, bg):
        self.configure(bg=bg)
        self._paint()


class Dot(tk.Canvas):
    def __init__(self, parent, colour, surface):
        super().__init__(parent, width=8, height=8, bg=surface,
                         highlightthickness=0, bd=0)
        self._c = colour
        self._paint()

    def _paint(self):
        self.delete("all")
        self.create_oval(1, 1, 7, 7, fill=self._c, outline="")

    def recolour(self, bg):
        self.configure(bg=bg)
        self._paint()


BUTTON_STYLES = {
    #            bg,       fg,        hover bg,  hover fg,  border
    "primary": (ACCENT,    ON_ACCENT, ACCENT_HI, ON_ACCENT, None),
    "light":   (TEXT,      ON_ACCENT, "#ffffff", ON_ACCENT, None),
    "quiet":   (RAISED,    TEXT,      BUTTON_HI, TEXT,      LINE),
    "danger":  (RAISED,    BAD,       "#34231f", "#f19a90", LINE),
    "ghost":   (None,      DIM,       None,      TEXT,      None),
}


def button(parent, text, cmd, kind="ghost", font=None, pad=(12, 6), icon_name=None):
    """One place for button styling, so every button in the app matches.

    Ghost buttons take their parent's background, so they sit on any surface
    without being recoloured by hand.
    """
    bg, fg, hbg, hfg, border = BUTTON_STYLES[kind]
    parent_bg = bg_of(parent)
    bg = bg or parent_bg
    hbg = hbg or parent_bg
    img = icon(icon_name, fg, 16) if icon_name else None
    # An icon-only button sizes to the picture, not the font, and ends up
    # shorter than its neighbours; a single space gives it the text height.
    label = (" " + text) if (img and text) else (" " if img else text)
    b = tk.Button(parent, text=label,
                  command=cmd, bd=0, relief="flat", bg=bg, fg=fg, font=font,
                  padx=pad[0], pady=pad[1], activebackground=hbg,
                  activeforeground=hfg, cursor="hand2", image=img or "",
                  compound="left" if img else "none",
                  highlightthickness=1 if border else 0,
                  highlightbackground=border or bg, highlightcolor=border or bg)
    b._icon = img
    if img:
        hover_img = icon(icon_name, hfg, 16)
        b._hover_icon = hover_img
    b.bind("<Enter>", lambda _e: b.config(bg=hbg, fg=hfg,
                                          image=getattr(b, "_hover_icon", "") or ""))
    b.bind("<Leave>", lambda _e: b.config(bg=bg, fg=fg, image=b._icon or ""))
    return b


class ThinScrollbar(tk.Canvas):
    """A slim scrollbar drawn to match the theme.

    Tk's native Scrollbar on Windows ignores colours and draws a bright white
    strip down the side of a dark window. This one hides itself when there's
    nothing to scroll.
    """

    def __init__(self, parent, command, bg=SURFACE, orient="vertical"):
        s = palicons.scale
        size = round(10 * s)
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0,
                         **({"width": size} if orient == "vertical" else {"height": size}))
        self.command, self.orient = command, orient
        self.first, self.last = 0.0, 1.0
        self._drag = None
        self.bind("<Configure>", lambda _e: self._paint())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag", None))
        self.bind("<Enter>", lambda _e: self._paint(hover=True))
        self.bind("<Leave>", lambda _e: self._paint())

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._paint()

    def _length(self):
        return self.winfo_height() if self.orient == "vertical" else self.winfo_width()

    def _paint(self, hover=False):
        self.delete("all")
        if self.last - self.first >= 0.999:
            return
        s = palicons.scale
        length = self._length()
        a, b = self.first * length, self.last * length
        b = max(b, a + 24 * s)
        t = self.winfo_width() if self.orient == "vertical" else self.winfo_height()
        pad = 3 * s
        colour = "#5a5f66" if hover or self._drag is not None else "#3d4249"
        if self.orient == "vertical":
            rounded(self, pad, a + 2, t - pad, b - 2, (t - 2 * pad) / 2, fill=colour, outline="")
        else:
            rounded(self, a + 2, pad, b - 2, t - pad, (t - 2 * pad) / 2, fill=colour, outline="")

    def _pos(self, e):
        return (e.y if self.orient == "vertical" else e.x) / max(1, self._length())

    def _press(self, e):
        f = self._pos(e)
        if self.first <= f <= self.last:
            self._drag = f - self.first
        else:
            self._drag = (self.last - self.first) / 2
            self.command("moveto", max(0.0, f - self._drag))

    def _move(self, e):
        if self._drag is not None:
            self.command("moveto", max(0.0, self._pos(e) - self._drag))
            self._paint(hover=True)


def scroller(parent, bg=SURFACE):
    """Scrollable body frame. Returns (outer, inner)."""
    wrap = tk.Frame(parent, bg=bg, highlightthickness=0)
    cv = tk.Canvas(wrap, bg=bg, highlightthickness=0, bd=0)
    inner = tk.Frame(cv, bg=bg)
    win = cv.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
    bar = ThinScrollbar(wrap, cv.yview, bg=bg)
    bar.pack(side="right", fill="y")
    cv.pack(side="left", fill="both", expand=True)
    cv.configure(yscrollcommand=bar.set)

    def wheel(e):
        # Only scroll when there is something to scroll.
        if cv.yview() != (0.0, 1.0):
            cv.yview_scroll(int(-e.delta / 120), "units")

    # Rows cover the canvas, so a binding on the canvas alone never fires.
    # Take the wheel for the whole app while the pointer is over this list.
    wrap.bind("<Enter>", lambda _e: wrap.bind_all("<MouseWheel>", wheel))
    wrap.bind("<Leave>", lambda _e: wrap.unbind_all("<MouseWheel>"))
    inner._canvas = cv
    return wrap, inner


# ---------------------------------------------------------------- helpers
def dark_titlebar(window):
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


def menu(root, font):
    return tk.Menu(root, tearoff=0, bg=RAISED, fg=TEXT, activebackground=BUTTON_HI,
                   activeforeground=TEXT, bd=0, font=font, disabledforeground=FAINT,
                   relief="flat")


def checkbox(parent, var, bg, font=None, text="", command=None):
    # Tk draws the tick in fg; a dark fg on a dark indicator looks unticked.
    return tk.Checkbutton(parent, text=text, variable=var, command=command,
                          bg=bg, fg=TEXT, selectcolor=RAISED,
                          activebackground=bg, activeforeground=TEXT,
                          font=font, bd=0, highlightthickness=0, cursor="hand2")


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def friendly_time(iso):
    from datetime import datetime
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    days = (datetime.now().date() - t.date()).days
    if days == 0:
        return f"Today {t:%H:%M}"
    if days == 1:
        return f"Yesterday {t:%H:%M}"
    return f"{t:%d %b %Y, %H:%M}"


def wrap_to_width(label, margin=12):
    """Keep a wrapping label inside its window however the window is sized.

    A fixed wraplength is a guess about the window width, and the guess is
    wrong the moment anything is resized -- the text then runs off the edge
    rather than wrapping.
    """
    label.bind("<Configure>",
               lambda e: e.widget.config(wraplength=max(160, e.width - margin)))
    return label


class Window(tk.Toplevel):
    """A dialog with the app's chrome: title block, scrolling body, footer.

    The footer is packed before the body. Pack hands out space in order, so
    an expanding body packed first pushes the buttons off a short window.
    """

    def __init__(self, app, title, subtitle="", size="720x560", scroll=True):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.geometry(size)
        self.minsize(520, 380)
        self.configure(bg=BG)
        self.transient(app.root)

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=22, pady=(18, 12))
        tk.Label(head, text=title, bg=BG, fg=TEXT, font=app.f_title,
                 anchor="w").pack(fill="x")
        self.subtitle = tk.Label(head, text=subtitle, bg=BG, fg=DIM,
                                 font=app.f_small, anchor="w", justify="left",
                                 wraplength=660)
        self.subtitle.pack(fill="x", pady=(2, 0))
        wrap_to_width(self.subtitle)

        self.foot = tk.Frame(self, bg=BG)
        self.foot.pack(side="bottom", fill="x", padx=22, pady=12)
        tk.Frame(self, bg=LINE, height=1).pack(side="bottom", fill="x")
        self.status = tk.Label(self.foot, text="", bg=BG, fg=DIM,
                               font=app.f_small, anchor="w")
        self.status.pack(side="left")

        tk.Frame(self, bg=LINE, height=1).pack(fill="x")
        if scroll:
            wrap, self.body = scroller(self)
            wrap.pack(fill="both", expand=True)
        else:
            self.body = tk.Frame(self, bg=SURFACE)
            self.body.pack(fill="both", expand=True)
        self.after(10, lambda: dark_titlebar(self))

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def section(self, text, count=None):
        h = tk.Frame(self.body, bg=SURFACE)
        h.pack(fill="x", padx=22, pady=(18, 6))
        tk.Label(h, text=text, bg=SURFACE, fg=TEXT,
                 font=self.app.f_head).pack(side="left")
        if count is not None:
            tk.Label(h, text=f"  {count}", bg=SURFACE, fg=FAINT,
                     font=self.app.f_small).pack(side="left", pady=(2, 0))
        return h

    def note(self, text, fg=DIM, parent=None, pady=(0, 4), icon_name=None):
        img = icon(icon_name, fg, 16) if icon_name else ""
        lbl = tk.Label(parent or self.body, text=(" " + text) if img else text,
                       bg=SURFACE, fg=fg, image=img, compound="left",
                       font=self.app.f_small, anchor="w", justify="left",
                       wraplength=640)
        lbl.pack(fill="x", padx=22, pady=pady)
        wrap_to_width(lbl)
        return lbl

    def card(self):
        c = tk.Frame(self.body, bg=RAISED, highlightthickness=1,
                     highlightbackground=LINE)
        c.pack(fill="x", padx=20, pady=4)
        return c
