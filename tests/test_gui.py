"""Main window: filters, search, staged toggles, bulk actions, profiles."""
import time

from helpers import (Checker, fake_pak, hidden_tk, lua_mod, make_game, sandbox,
                     silence_dialogs, use_game, write_log)

SB = sandbox("gui")
import palregistry                         # noqa: E402

check = Checker()
game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"
mods = win64 / "ue4ss/Mods"
paks = game / "Pal/Content/Paks"

lua_mod(mods, "PalMiniMap", extra={"config.ini": "[keys]\nmenu = F5\n"})
lua_mod(mods, "BaseDoorControl")
lua_mod(mods, "OffMod", enabled=False)
lua_mod(mods, "BrokenMod")
fake_pak(paks / "~mods/NiceSky_P.pak", "../../../", ["Pal/Content/Sky/T_Sky.uasset"])
fake_pak(paks / "~mods/OldOutfit_P.pak.disabled", "../../../", ["Pal/Content/Outfit/T_O.uasset"])
write_log(win64, ["PalMiniMap", "BaseDoorControl"])       # BrokenMod never started

root, pump, errors = hidden_tk()
import palmods_gui as G                    # noqa: E402
silence_dialogs(G)

app = G.App(root)
pump(0.6)


def visible():
    return sorted(n for n, r in app.rows.items() if r["frame"].winfo_manager())


check.section("list")
names = sorted(e["name"] for e in app._entries_cache)
check("every mod listed", names == ["BaseDoorControl", "BrokenMod", "NiceSky_P",
                                    "OffMod", "OldOutfit_P", "PalMiniMap"], names)
states = {e["name"]: e["state"] for e in app._entries_cache}
check("plain states: working / didn't start / off / on",
      states["PalMiniMap"] == "working" and states["BrokenMod"] == "didn't start"
      and states["OffMod"] == "off" and states["NiceSky_P"] == "on"
      and states["OldOutfit_P"] == "off", states)

check.section("simple layout")
meta = app.meta.cget("text")
check("header line is plain", "UE4SS ready" in meta and "build" not in meta
      and "layout" not in meta, meta)


def row_texts(name):
    out, stack = [], [app.rows[name]["frame"]]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        try:
            out.append(w.cget("text"))
        except tk.TclError:
            pass
    return [t for t in out if t]


import tkinter as tk                        # noqa: E402
texts = row_texts("PalMiniMap")
check("rows don't show type, folder or version tags",
      not any(t in ("lua", "ue4ss/Mods", "~mods", "pak") for t in texts), texts)
check("no 'source unknown' tag", "source unknown" not in " ".join(texts))
headers = [h["frame"].winfo_children()[0].cget("text") for h in app.headers.values()]
check("group titles are readable, not shouted", "Script mods (UE4SS)" in headers, headers)

opened = []
tk.Menu.tk_popup = lambda self, *a: opened.append(self)      # don't show it
app.more_menu()
menu = opened[-1]
top = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
       if menu.type(i) in ("command", "cascade")]
check("⋯ menu: seven top-level entries",
      top == ["Refresh   F5", "Profiles", "Save backups…", "Share modlist", "Tools",
              "Open folder", "Switch install"], top)
tools_menu = next(menu.nametowidget(menu.entrycget(i, "menu"))
                  for i in range(menu.index("end") + 1)
                  if menu.type(i) == "cascade" and menu.entrycget(i, "label") == "Tools")
tool_labels = [tools_menu.entrycget(i, "label") for i in range(tools_menu.index("end") + 1)
               if tools_menu.type(i) == "command"]
check("specialist tools grouped under Tools",
      {"Conflicts & hotkeys…", "UE4SS log…", "Blueprint load order…",
       "Clean up leftovers…", "Check UE4SS install…"} <= set(tool_labels), tool_labels)

check.section("filters")
app._set_tab("Working"); pump(0.1)
check("Working", visible() == ["BaseDoorControl", "NiceSky_P", "PalMiniMap"], visible())
app._set_tab("Problems"); pump(0.1)
check("Problems", visible() == ["BrokenMod"], visible())
app._set_tab("Off"); pump(0.1)
check("Off", visible() == ["OffMod", "OldOutfit_P"], visible())
app._set_tab("All"); pump(0.1)
check("All", len(visible()) == 6)

app._filter.set("door"); app._apply_filter(); pump(0.1)
check("search", visible() == ["BaseDoorControl"], visible())
app._filter.set("nothing-matches"); app._apply_filter(); pump(0.1)
check("empty state shown", visible() == [] and bool(app.empty.winfo_manager()))
app._filter.set(""); app._apply_filter(); pump(0.1)
check("search cleared", len(visible()) == 6)

check.section("staged changes")
app.rows["OffMod"]["toggle"]._click(None); pump(0.1)
check("toggle is staged, not written", app._pending() == [("OffMod", True)]
      and not (mods / "OffMod/enabled.txt").exists())
check("status says it isn't applied, without '(s)'",
      app.status.cget("text").startswith("1 change not applied")
      and "(s)" not in app.status.cget("text"), app.status.cget("text"))
check("Apply and Undo only appear once there's something to apply",
      bool(app.apply_btn.winfo_manager()) and bool(app.revert_btn.winfo_manager()))
app._set_tab("Off"); app._set_tab("All"); app._filter.set("x"); app._filter.set("")
app._apply_filter(); pump(0.1)
check("staged change survives filtering", app._pending() == [("OffMod", True)])
app.render(); pump(0.1)
check("staged change survives a rebuild", app._pending() == [("OffMod", True)])
app.revert()
check("revert clears it", app._pending() == [])

app._bulk_visible("UE4SS mods", False)
check("'all off' stages every visible UE4SS mod",
      sorted(n for n, _ in app._pending()) == ["BaseDoorControl", "BrokenMod", "PalMiniMap"])
app.revert()

app.rows["OffMod"]["toggle"]._click(None)
app.apply(); pump(0.3)
check("apply writes the change", (mods / "OffMod/enabled.txt").is_file())
check("nothing pending after apply", app._pending() == [])

check.section("profiles")
palregistry.save_profile("solo", ["PalMiniMap"], [e["name"] for e in app._entries_cache])
app.load_profile("solo"); pump(0.1)
pending = dict(app._pending())
check("loading a profile stages its differences",
      pending.get("BaseDoorControl") is False and pending.get("OffMod") is False
      and "PalMiniMap" not in pending, pending)
app.revert()

check.section("windows open")
entry = next(e for e in app._entries_cache if e["name"] == "PalMiniMap")
cw = G.ConfigWindow(app, "PalMiniMap", entry["configs"]); pump(0.2)
check("config window", cw.winfo_exists()); cw.destroy()
sw = G.SetupWindow(app); pump(0.2)
check("setup window", sw.winfo_exists()); sw.grab_release(); sw.destroy()

# Uninstalling in Steam leaves mods and UE4SS behind but removes the game.
import palpaths                              # noqa: E402
leftover = SB / "Uninstalled/Palworld"
(leftover / "Pal/Binaries/Win64/ue4ss/Mods").mkdir(parents=True)
palpaths.save_settings({"game_path": str(leftover)})
sw = G.SetupWindow(app, first_run=True); pump(0.2)
labels = [c.cget("text") for c in sw.winfo_children()[0].winfo_children()
          if isinstance(c, tk.Label)]
check("uninstalled game explained, mods still there",
      any("no longer installed" in t and "still there" in t for t in labels), labels)
sw.grab_release(); sw.destroy()
palpaths.save_settings({"game_path": None})

check.section("speed (informational)")
t = time.perf_counter()
for i in range(10):
    app._filter.set("mini" if i % 2 else "")
    app._apply_filter(); root.update()
print(f"      filter per keystroke: {(time.perf_counter() - t) * 100:.0f} ms")
t = time.perf_counter()
app.reload(full=True)
print(f"      full reload: {(time.perf_counter() - t) * 1000:.0f} ms")

root.destroy()
check.finish(errors)
