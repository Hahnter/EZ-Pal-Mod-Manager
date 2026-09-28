#!/usr/bin/env python3
"""Descriptions and pictures for mods, kept locally.

Nothing here talks to Nexus or CurseForge. Both sites' terms forbid tools that
read or copy their pages (Nexus terms s.11; Overwolf/CurseForge s.3), so the
app never fetches them. (Once connected with an API key, palnexus can fill a
Nexus mod in from Nexus's official API instead -- that is the route their terms
provide.) Otherwise the information gets in the way a person would move it:

  clipboard   copy the description or right-click > Copy image on the mod page
              in your browser, then Paste in the app
  files       pick screenshots or artwork from disk
  archives    README and image files that ship inside a mod's download
  your mods   the README and preview image in the mod's own folder

Images are normalised on the way in (rotated upright, capped at 1920 px, saved
as PNG or JPEG) so the store stays small and Tk can always display them.
Everything lives under %LOCALAPPDATA%\\PalModManager\\media\\<mod>.
"""

import hashlib
import io
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import palpaths
import palregistry

try:
    import warnings
    from PIL import Image, ImageGrab, ImageOps
    HAVE_PIL = True
    # Pictures come from downloaded archives. A tiny file that declares a
    # gigantic canvas is a memory bomb; Pillow only warns about it by
    # default, so make the warning an error and cap the size outright.
    Image.MAX_IMAGE_PIXELS = 64_000_000
    warnings.simplefilter("error", Image.DecompressionBombWarning)
except ImportError:            # images are unavailable; text still works
    HAVE_PIL = False

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
MAX_EDGE = 1920
MAX_DESCRIPTION = 50_000
README_NAMES = re.compile(r"^(read ?me|description|about|info|mod ?info)"
                          r"([ _-].*)?\.(md|txt|markdown)$", re.I)
PREVIEW_NAMES = re.compile(r"^(preview|cover|thumbnail|thumb|banner|screenshot|"
                           r"image|logo|icon)", re.I)


class MediaError(Exception):
    pass


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def _safe(name):
    cleaned = re.sub(r"[^\w.-]+", "_", name).strip("._") or "mod"
    return cleaned[:80]


def media_dir(name, create=False):
    d = palpaths.data_dir() / "media" / _safe(name)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def info(name, entry=None):
    """{description, images: [Path], cover: Path|None} for one mod."""
    e = entry if entry is not None else palregistry.get(name)
    d = media_dir(name)
    images = [d / f for f in e.get("images") or [] if (d / f).is_file()]
    cover = d / e["cover"] if e.get("cover") and (d / e["cover"]).is_file() else None
    if cover is None and images:
        cover = images[0]
    return {"description": e.get("description") or "", "images": images,
            "cover": cover}


def cover_path(name, entry=None):
    return info(name, entry)["cover"]


def set_description(name, text):
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) > MAX_DESCRIPTION:
        text = text[:MAX_DESCRIPTION].rstrip() + "\n…"
    palregistry.set_entry(name, description=text or None)
    return text


def _register_image(name, filename, make_cover=False):
    entry = palregistry.get(name)
    images = list(entry.get("images") or [])
    if filename not in images:
        images.append(filename)
    fields = {"images": images}
    if make_cover or not entry.get("cover"):
        fields["cover"] = filename
    palregistry.set_entry(name, **fields)


def _store(name, img, digest):
    """Save a PIL image into the mod's media folder, once per content."""
    d = media_dir(name, create=True)
    existing = next((p for p in d.glob(f"img-{digest}.*")), None)
    if existing:
        _register_image(name, existing.name)
        return existing

    img = ImageOps.exif_transpose(img)
    if getattr(img, "is_animated", False):
        img.seek(0)
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    # Keep the picture, drop what rode along with it: camera and GPS EXIF,
    # XMP and C2PA provenance, generator prompts in PNG text, and JPEG
    # comments. Pillow copies some of those (the JPEG comment) into the new
    # file unless the image's info is emptied first.
    img.info = {}

    if has_alpha:
        out = d / f"img-{digest}.png"
        img.save(out, "PNG", optimize=True)
    else:
        out = d / f"img-{digest}.jpg"
        img.save(out, "JPEG", quality=90, optimize=True)
    _register_image(name, out.name)
    return out


def _need_pil():
    if not HAVE_PIL:
        raise MediaError("Images need the Pillow library, which isn't available "
                         "in this build.")


def add_image_file(name, path):
    """Add an image from disk. Returns the stored Path."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise MediaError(f"{p.name} couldn't be read.") from exc
    return add_image_bytes(name, raw, p.name)


def add_image_bytes(name, raw, label="The picture"):
    """Add an image from its encoded bytes (a file, or a download)."""
    _need_pil()
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MediaError(f"{label} claims to be far bigger than any real "
                         f"picture, so it wasn't opened.") from exc
    except (OSError, ValueError) as exc:
        raise MediaError(f"{label} isn't an image this app can read.") from exc
    return _store(name, img, hashlib.sha1(raw).hexdigest()[:12])


def add_image(name, img):
    """Add an in-memory PIL image (e.g. from the clipboard)."""
    _need_pil()
    digest = hashlib.sha1(img.tobytes()).hexdigest()[:12]
    return _store(name, img, digest)


def clipboard_image():
    """What's on the clipboard that could be an image.

    Returns ('image', PIL.Image), ('files', [paths]) or (None, None). Copying
    an image in a browser gives the former; copying files in Explorer the
    latter.
    """
    if not HAVE_PIL:
        return None, None
    try:
        grabbed = ImageGrab.grabclipboard()
    except Exception:           # clipboard busy or holding an odd format
        return None, None
    if isinstance(grabbed, Image.Image):
        return "image", grabbed
    if isinstance(grabbed, list):
        files = [f for f in grabbed if str(f).lower().endswith(IMAGE_SUFFIXES)]
        if files:
            return "files", files
    return None, None


def paste_images(name):
    """Add whatever image(s) the clipboard holds. Returns stored Paths."""
    kind, value = clipboard_image()
    if kind == "image":
        return [add_image(name, value)]
    if kind == "files":
        return [add_image_file(name, f) for f in value]
    raise MediaError("There's no image on the clipboard. In your browser, "
                     "right-click the picture and choose Copy image, then "
                     "try again.")


def remove_image(name, filename):
    entry = palregistry.get(name)
    images = [f for f in entry.get("images") or [] if f != filename]
    fields = {"images": images or None}
    if entry.get("cover") == filename:
        fields["cover"] = images[0] if images else None
    palregistry.set_entry(name, **fields)
    target = media_dir(name) / filename
    for thumb in (media_dir(name) / "thumbs").glob(f"{Path(filename).stem}-*"):
        thumb.unlink(missing_ok=True)
    target.unlink(missing_ok=True)


def set_cover(name, filename):
    palregistry.set_entry(name, cover=filename)


def forget(name):
    """Remove a mod's pictures from the store. Returns the removed folder."""
    d = media_dir(name)
    if not d.is_dir():
        return None
    try:
        import paltools
        if paltools.recycle([d]):
            return d
    except Exception:
        pass
    shutil.rmtree(d, ignore_errors=True)
    return d


# --------------------------------------------------------------------------
# thumbnails
# --------------------------------------------------------------------------
def thumbnail(path, width, height, fit="cover"):
    """Path to a cached, resized copy of an image.

    `cover` crops to fill the box (list thumbnails); `contain` fits inside it
    (the large preview). Cached by size and source mtime, so a replaced image
    never shows a stale thumbnail.
    """
    _need_pil()
    src = Path(path)
    stamp = int(src.stat().st_mtime)
    cache = src.parent / "thumbs"
    cache.mkdir(exist_ok=True)
    out = cache / f"{src.stem}-{width}x{height}-{fit}-{stamp}.png"
    if out.is_file():
        return out
    with Image.open(src) as img:
        img = img.convert("RGBA")
        if fit == "cover":
            img = ImageOps.fit(img, (width, height), Image.LANCZOS)
        else:
            img.thumbnail((width, height), Image.LANCZOS)
        img.save(out, "PNG")
    for old in cache.glob(f"{src.stem}-{width}x{height}-{fit}-*.png"):
        if old != out:
            old.unlink(missing_ok=True)
    return out


# --------------------------------------------------------------------------
# finding information that already exists
# --------------------------------------------------------------------------
def _read_text(p):
    raw = Path(p).read_bytes()[:MAX_DESCRIPTION * 2]
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf8", "replace")


def readme_in(folder):
    """The README-like text file directly in (or one level below) a folder."""
    root = Path(folder)
    if not root.is_dir():
        return None
    cands = [p for p in root.glob("*") if p.is_file() and README_NAMES.match(p.name)]
    cands += [p for p in root.glob("*/*") if p.is_file() and README_NAMES.match(p.name)
              and p.parent.name.lower() not in ("scripts", "dlls")]
    # DESCRIPTION.md is what the app writes from a description you typed, so
    # it beats a stock README shipped alongside it.
    return min(cands, key=lambda p: (len(p.relative_to(root).parts),
                                     not p.name.lower().startswith("description"),
                                     len(p.name)),
               default=None)


def images_in(folder, limit=12):
    root = Path(folder)
    if not root.is_dir():
        return []
    found = [p for p in root.rglob("*") if p.is_file()
             and p.suffix.lower() in IMAGE_SUFFIXES
             and "thumbs" not in p.parts]
    # A mod's own UI icons (PalMiniMap ships 300) are not screenshots; only
    # take images at the top level, or ones named like a preview.
    chosen = [p for p in found if p.parent == root or PREVIEW_NAMES.match(p.name)]
    return sorted(chosen, key=lambda p: (not PREVIEW_NAMES.match(p.name), p.name))[:limit]


def suggestions(name, mod_path=None):
    """Description/images the app could use but hasn't stored yet."""
    out = {"readme": None, "readme_path": None, "images": []}
    if not mod_path or not Path(mod_path).is_dir():
        return out
    have = info(name)
    readme = readme_in(mod_path)
    if readme and not have["description"]:
        text = _read_text(readme).strip()
        if text:
            out["readme"], out["readme_path"] = text, readme
    if not have["images"]:
        out["images"] = images_in(mod_path)
    return out


def capture_from_archive(names, tmp_root, skipped):
    """Keep the README and pictures a download ships with.

    `skipped` are the archive files the installer did not install. They are
    attached to every installed component that has nothing yet, so a hybrid
    mod's Lua half and pak half both show the same information.
    """
    root = Path(tmp_root)
    files = [root / rel for rel in skipped]
    readmes = sorted((f for f in files if README_NAMES.match(f.name)),
                     key=lambda f: (len(f.relative_to(root).parts), len(f.name)))
    pictures = [f for f in files if f.suffix.lower() in IMAGE_SUFFIXES][:12]
    added = {"description": False, "images": 0}
    for name in names:
        have = info(name)
        if readmes and not have["description"]:
            text = _read_text(readmes[0]).strip()
            if text:
                set_description(name, text)
                added["description"] = True
        if pictures and not have["images"] and HAVE_PIL:
            for pic in pictures:
                try:
                    add_image_file(name, pic)
                    added["images"] += 1
                except MediaError:
                    continue
    return added


def archive_extras(skipped):
    """Which skipped archive files would be kept as mod info."""
    return {
        "readmes": [s for s in skipped if README_NAMES.match(Path(s).name)],
        "images": [s for s in skipped if Path(s).suffix.lower() in IMAGE_SUFFIXES][:12],
    }


# --------------------------------------------------------------------------
# mod page links
# --------------------------------------------------------------------------
def parse_link(text):
    """Turn a pasted mod page link into registry fields, offline.

    Only the URL itself is read -- the page is never fetched.
    """
    text = (text or "").strip()
    if not text:
        return {}
    if not re.match(r"^[a-z]+://", text, re.I):
        if re.match(r"^(www\.)?(nexusmods|curseforge)\.com/", text, re.I):
            text = "https://" + text
        else:
            return {"url": text}
    u = urlparse(text)
    host = u.netloc.lower()
    if host.endswith("nexusmods.com"):
        m = re.search(r"/([\w-]+)/mods/(\d+)", u.path)
        if m:
            return {"source": "Nexus", "id": int(m.group(2)),
                    "url": f"https://www.nexusmods.com/{m.group(1)}/mods/{m.group(2)}"}
        return {"source": "Nexus", "url": text}
    if host.endswith("curseforge.com"):
        m = re.search(r"^/(palworld)/([\w-]+)/([\w-]+)", u.path)
        if m and m.group(2) != "search":
            return {"source": "CurseForge",
                    "url": f"https://www.curseforge.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"}
        return {"source": "CurseForge", "url": text}
    return {"source": "manual", "url": text}


def page_hint(entry):
    """How to copy information over from wherever this mod came from."""
    src = (entry or {}).get("source")
    if src in ("Nexus", "CurseForge"):
        return (f"Open the {src} page, select the description and copy it, then "
                f"press Paste text. For a picture, right-click it and choose "
                f"Copy image, then press Paste image.")
    if src == "local":
        return ("This is your mod. Write the description here and add your own "
                "screenshots — they're included when you package it for sharing.")
    return ("Link the mod's page below, or add a description and pictures of "
            "your own.")
