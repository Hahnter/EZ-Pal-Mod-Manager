"""The mod info window and list thumbnails. Windows stay hidden and the real
clipboard is never read or written."""
from helpers import (Checker, FakeMessageBox as Box, hidden_tk, make_game,
                     sandbox, silence_dialogs, use_game)

SB = sandbox("info_gui")
import tkinter as tk                       # noqa: E402
from PIL import Image                      # noqa: E402
import palmedia, palregistry               # noqa: E402

check = Checker()
root, pump, errors = hidden_tk()

game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"
mods = win64 / "ue4ss/Mods"
for n in ("DoorMod", "MiniMap", "Plain"):
    (mods / n / "Scripts").mkdir(parents=True)
    (mods / n / "Scripts/main.lua").write_text("print(1)")
    (mods / n / "enabled.txt").write_text("")
(mods / "DoorMod/README.md").write_text("# DoorMod\n\nOpens all base doors with F6.")
Image.new("RGB", (800, 450), (90, 60, 200)).save(mods / "DoorMod/preview.png")

pic = SB / "shot.jpg"
Image.new("RGB", (1600, 900), (200, 140, 30)).save(pic)
palmedia.add_image_file("MiniMap", pic)
palmedia.set_description("MiniMap", "A live minimap with pal and chest markers.")

import palmods_gui as G                    # noqa: E402
import palinfo                             # noqa: E402

silence_dialogs(G, palinfo)

app = G.App(root)
pump(0.8)
entries = {e["name"]: e for e in app._entries_cache}
check("MiniMap entry has a cover", entries["MiniMap"]["cover"] is not None)
check("row thumbnail slot shown once any mod has a picture", app._any_cover)
check("thumbnail image built for MiniMap row", any(v for v in app._thumbs.values()))

app._filter.set("chest markers"); app._apply_filter(); pump(0.1)
visible = [n for n, r in app.rows.items() if r["frame"].winfo_manager()]
check("search matches description text", visible == ["MiniMap"], visible)
app._filter.set(""); app._apply_filter()

# ---- DoorMod: nothing stored, README + preview in its folder
app.open_info(entries["DoorMod"])
pump(0.5)
wins = [w for w in root.winfo_children() if isinstance(w, palinfo.ModInfoWindow)]
w = wins[0]
check("info window opened", w.mod == "DoorMod")
app.open_info(entries["DoorMod"]); pump(0.2)
check("opening again reuses the window",
      len([x for x in root.winfo_children() if isinstance(x, palinfo.ModInfoWindow)]) == 1)

texts = []
def walk(widget):
    for c in widget.winfo_children():
        try:
            t = c.cget("text")
            if t:
                texts.append(t)
        except tk.TclError:
            pass
        walk(c)
walk(w)
check("README suggestion offered", any("ships a README.md" in t for t in texts))
check("folder picture suggestion offered", any("1 picture in the mod's folder" in t for t in texts))
check("empty state shown when no pictures", any("No pictures yet" in t for t in texts))

# Accept both suggestions through their buttons.
def click(label):
    for b in [c for c in all_widgets(w) if isinstance(c, tk.Button)]:
        if b.cget("text") == label:
            b.invoke(); pump(0.2); return True
    return False
def all_widgets(widget):
    out = []
    for c in widget.winfo_children():
        out.append(c); out.extend(all_widgets(c))
    return out
check("'Use it' fills description", click("Use it")
      and "Opens all base doors" in w.text.get("1.0", "end"))
check("'Add them' adds the folder picture", click("Add them")
      and len(palmedia.info("DoorMod")["images"]) == 1)

# Paste an image via the (mocked) clipboard.
palmedia.ImageGrab.grabclipboard = lambda: Image.new("RGB", (1280, 720), (20, 180, 90))
w._paste_image(); pump(0.2)
check("pasted image added and shown", len(palmedia.info("DoorMod")["images"]) == 2
      and w.shown == palmedia.info("DoorMod")["images"][-1])
check("main list got DoorMod's thumbnail without a rescan",
      {e["name"]: e for e in app._entries_cache}["DoorMod"]["cover"] is not None)

# Link field fills source + id from a pasted address.
w.vars["url"].set("https://www.nexusmods.com/palworld/mods/4321?tab=description")
pump(0.1)
check("nexus link recognised", w.source.get() == "Nexus" and w.vars["id"].get() == "4321",
      (w.source.get(), w.vars["id"].get()))
check("open page button enabled", str(w.page_btn.cget("state")) == "normal")

# Unsaved changes prompt, then save.
w.text.insert("end", "\n\nPress F6 near your base.")
check("unsaved changes detected", w._snapshot() != w._baseline)
Box.answers["askyesnocancel"] = None
w._close(); pump(0.1)
check("cancel keeps the window open", w.winfo_exists())
Box.answers["askyesnocancel"] = True
w._close(); pump(0.3)
check("yes saves and closes", not w.winfo_exists())
meta = palregistry.get("DoorMod")
check("description saved", "Press F6 near your base." in meta.get("description", ""))
check("source + canonical url saved", meta.get("source") == "Nexus" and meta.get("id") == 4321
      and meta.get("url") == "https://www.nexusmods.com/palworld/mods/4321", meta.get("url"))

# ---- cover change + removal through the window
w2 = palinfo.ModInfoWindow(app, {e["name"]: e for e in app._entries_cache}["DoorMod"])
pump(0.4)
imgs = palmedia.info("DoorMod")["images"]
w2._set_cover(imgs[1]); pump(0.2)
check("set cover", palmedia.info("DoorMod")["cover"] == imgs[1])
w2._remove(imgs[1]); pump(0.2)
check("remove picture", len(palmedia.info("DoorMod")["images"]) == 1
      and palmedia.info("DoorMod")["cover"] == imgs[0])
viewer = palinfo.ImageViewer(w2, palmedia.info("DoorMod")["images"], 0)
pump(0.2)
check("full-size viewer builds", viewer._img is not None)
viewer.destroy(); w2.destroy()

# Plain mod with nothing: window builds, no suggestions, save of nothing is fine.
w3 = palinfo.ModInfoWindow(app, {e["name"]: e for e in app._entries_cache}["Plain"])
pump(0.3)
check("plain mod: page button disabled", str(w3.page_btn.cget("state")) == "disabled")
w3._close(); pump(0.1)
check("plain mod: closes without prompting", not w3.winfo_exists())

root.destroy()
check.finish(errors)
