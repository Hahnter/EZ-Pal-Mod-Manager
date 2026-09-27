#!/usr/bin/env python3
"""The app's icons, drawn in code.

One set, one stroke weight, drawn at 4x on a 24-unit grid and scaled down, so
they stay crisp at any size and match each other -- unlike the mix of emoji
and Unicode symbols they replace. No icon files ship with the app, and the
app mark is the same drawing as the .ico.
"""

from PIL import Image, ImageDraw

SS = 4          # supersampling factor
GRID = 24       # icons are designed on a 24x24 grid
STROKE = 2.0    # in grid units

_cache = {}
scale = 1.0     # UI scale; set once from the screen DPI (see set_scale)


def set_scale(value):
    global scale
    scale = max(1.0, float(value))
    _cache.clear()


def _rgba(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


class _Pen:
    """Drawing in grid units on a supersampled canvas."""

    def __init__(self, px, colour):
        self.k = px * SS / GRID
        self.img = Image.new("RGBA", (px * SS, px * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.c = _rgba(colour)
        self.w = max(1, round(STROKE * self.k))

    def p(self, x, y):
        return (x * self.k, y * self.k)

    def line(self, *pts):
        xy = [self.p(*pt) for pt in pts]
        self.d.line(xy, fill=self.c, width=self.w, joint="curve")
        r = self.w / 2
        for x, y in (xy[0], xy[-1]):                 # round caps
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=self.c)

    def circle(self, cx, cy, r, fill=False):
        x, y = self.p(cx, cy)
        rr = r * self.k
        if fill:
            self.d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=self.c)
        else:
            self.d.ellipse((x - rr, y - rr, x + rr, y + rr), outline=self.c, width=self.w)

    def rect(self, x1, y1, x2, y2, radius=2, fill=None):
        box = (*self.p(x1, y1), *self.p(x2, y2))
        if fill is None:
            self.d.rounded_rectangle(box, radius * self.k, outline=self.c, width=self.w)
        else:
            self.d.rounded_rectangle(box, radius * self.k, fill=_rgba(fill))

    def poly(self, *pts):
        self.d.polygon([self.p(*pt) for pt in pts], outline=self.c, width=self.w)

    def done(self, px):
        return self.img.resize((px, px), Image.LANCZOS)


def _play(g):
    g.line((8, 5), (19, 12), (8, 19), (8, 5))


def _download(g):
    g.line((12, 4), (12, 15))
    g.line((7.5, 10.5), (12, 15), (16.5, 10.5))
    g.line((4, 16), (4, 19), (20, 19), (20, 16))


def _search(g):
    g.circle(10.5, 10.5, 6)
    g.line((15, 15), (20, 20))


def _more(g):
    for x in (6, 12, 18):
        g.circle(x, 12, 1.6, fill=True)


def _check(g):
    g.line((5, 12.5), (10, 17.5), (19.5, 7))


def _alert(g):
    g.line((12, 4), (21, 19.5), (3, 19.5), (12, 4))
    g.line((12, 10), (12, 14))
    g.circle(12, 17, 1.1, fill=True)


def _error(g):
    g.circle(12, 12, 8.5)
    g.line((9, 9), (15, 15))
    g.line((15, 9), (9, 15))


def _dot(g):
    g.circle(12, 12, 8.5)
    g.circle(12, 12, 2.6, fill=True)


def _clock(g):
    g.circle(12, 12, 8.5)
    g.line((12, 7.5), (12, 12), (15, 14))


def _external(g):
    g.line((13, 5), (19, 5), (19, 11))
    g.line((19, 5), (11, 13))
    g.line((16, 14), (16, 19), (5, 19), (5, 8), (10, 8))


def _photo(g):
    g.rect(4, 5, 20, 19, radius=2.5)
    g.circle(15, 9.5, 1.4, fill=True)
    g.line((4.5, 17), (9.5, 12), (15, 17.5))
    g.line((13, 15.5), (15.5, 13), (19.5, 17))


def _sliders(g):
    for y, x in ((6, 15), (12, 8), (18, 13)):
        g.line((4, y), (20, y))
        g.circle(x, y, 2.2, fill=True)


def _folder(g):
    g.line((4, 7), (4, 18), (20, 18), (20, 9), (12, 9), (10, 6.5), (4.5, 6.5))


def _undo(g):
    g.line((9, 7), (5, 11), (9, 15))
    g.line((5, 11), (14, 11))
    g.line((14, 11), (16.5, 11.5), (18.5, 13.5), (19, 16), (18.5, 18))


def _x(g):
    g.line((6, 6), (18, 18))
    g.line((18, 6), (6, 18))


DRAW = {"play": _play, "download": _download, "search": _search, "more": _more,
        "check": _check, "alert": _alert, "error": _error, "dot": _dot,
        "clock": _clock, "external": _external, "photo": _photo,
        "sliders": _sliders, "folder": _folder, "undo": _undo, "x": _x}


def image(name, size, colour):
    """A PIL image of an icon, `size` logical pixels square."""
    px = max(8, round(size * scale))
    pen = _Pen(px, colour)
    DRAW[name](pen)
    return pen.done(px)


def photo(name, size, colour):
    """A cached Tk image of an icon. Needs a Tk root to exist."""
    from PIL import ImageTk
    key = (name, size, colour, scale)
    if key not in _cache:
        _cache[key] = ImageTk.PhotoImage(image(name, size, colour))
    return _cache[key]


# --------------------------------------------------------------------------
# the app mark
# --------------------------------------------------------------------------
AMBER = (242, 181, 68, 255)
INK = (22, 25, 29, 255)


def logo(px, detailed=True):
    """The app mark: an amber tile holding a switch, on.

    Original, and deliberately unlike any capture sphere. `detailed` is kept
    for callers but the mark is simple enough to need no small-size variant.
    """
    big = px * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = big * 0.04
    d.rounded_rectangle((pad, pad, big - pad, big - pad), big * 0.22, fill=AMBER)
    # the switch track
    tw, th = big * 0.62, big * 0.30
    tx, ty = (big - tw) / 2, (big - th) / 2
    d.rounded_rectangle((tx, ty, tx + tw, ty + th), th / 2, fill=INK)
    # the knob, on the right: switched on
    r = th * 0.34
    cx, cy = tx + tw - th / 2, ty + th / 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=AMBER)
    return img.resize((px, px), Image.LANCZOS)


def logo_photo(size):
    from PIL import ImageTk
    key = ("logo", size, scale)
    if key not in _cache:
        px = max(16, round(size * scale))
        _cache[key] = ImageTk.PhotoImage(logo(px, detailed=px >= 32))
    return _cache[key]
