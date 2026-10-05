"""Keeping settings through a mod update, core-blueprint warnings, and the
UE4SS / PalSchema downloader (with GitHub faked -- no test touches the net).
"""
import io
import json
import zipfile
from pathlib import Path

from helpers import Checker, fake_pak, make_game, sandbox, scan, use_game

SB = sandbox("updates")
import palget, palinstall, palmods, palregistry, palsafety, paltools  # noqa: E402

check = Checker()
game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"


def zip_dir(src, out, prefix=""):
    with zipfile.ZipFile(out, "w") as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, prefix + p.relative_to(src).as_posix())
    return out


def mod_zip(tag, speed, main="print(1)"):
    """A UE4SS mod carrying a config file, as v1 or v2."""
    src = SB / f"src-{tag}"
    (src / "SpeedMod/Scripts").mkdir(parents=True, exist_ok=True)
    (src / "SpeedMod/Scripts/main.lua").write_text(main)
    (src / "SpeedMod/config.json").write_text(
        json.dumps({"Speed": speed, "Sound": True}))
    return zip_dir(src, SB / f"SpeedMod-{tag}.zip")


# ==========================================================================
check.section("what counts as a config file")
for rel, want in [("config.json", True), ("Settings.ini", True),
                  ("configs/keys.ini", True), ("config/anything.txt", True),
                  ("my_settings.lua", True), ("hotkeys.cfg", True),
                  ("Scripts/main.lua", False), ("data/Pal_Item.json", False),
                  ("readme.txt", False), ("mod.pak", False)]:
    check(f"{rel} -> {'config' if want else 'not config'}",
          palinstall.looks_like_config(rel) is want)

# ==========================================================================
check.section("a settings file you edited survives an update")
plan = palinstall.inspect(mod_zip("v1", 2))
palinstall.apply(plan)
palinstall.discard(plan)
cfg = win64 / "ue4ss/Mods/SpeedMod/config.json"
check("installed with the mod's own settings",
      json.loads(cfg.read_text())["Speed"] == 2)
check("the receipt remembers what was shipped",
      str(cfg) in palregistry.shipped_hashes("SpeedMod"))

cfg.write_text(json.dumps({"Speed": 9, "Sound": False}))      # the user edits
plan = palinstall.inspect(mod_zip("v2", 5, main="print(2)"))
out = palinstall.apply(plan)
palinstall.discard(plan)

check("your settings are still there",
      json.loads(cfg.read_text())["Speed"] == 9, cfg.read_text())
fresh = win64 / "ue4ss/Mods/SpeedMod/config.json.new"
check("the mod's new settings are beside it", fresh.is_file())
check("and they are the new version",
      fresh.is_file() and json.loads(fresh.read_text())["Speed"] == 5)
check("the mod's code was updated",
      (win64 / "ue4ss/Mods/SpeedMod/Scripts/main.lua").read_text() == "print(2)")
check("the install says so", any("Kept your settings" in r for r in out), out)

check.section("a settings file you never touched is just replaced")
cfg.write_text(fresh.read_text())      # accept the new one
fresh.unlink()
plan = palinstall.inspect(mod_zip("v3", 7))
out = palinstall.apply(plan)
palinstall.discard(plan)
check("replaced without fuss", json.loads(cfg.read_text())["Speed"] == 7)
check("no .new left behind",
      not (win64 / "ue4ss/Mods/SpeedMod/config.json.new").exists())
check("nothing claimed to be kept", not any("Kept your" in r for r in out), out)

check.section("uninstall still removes everything it wrote")
cfg.write_text('{"Speed": 99}')
plan = palinstall.inspect(mod_zip("v4", 8))
palinstall.apply(plan)
palinstall.discard(plan)
palinstall.uninstall("SpeedMod")
check("the mod folder is gone", not (win64 / "ue4ss/Mods/SpeedMod").exists())

# ==========================================================================
check.section("mods that replace the game's core blueprints")
fake_pak(game / "Pal/Content/Paks/~mods/BetterPlayer_P.pak", "../../../",
         ["Pal/Content/Pal/Blueprint/Character/Player/BP_PalPlayerCharacter.uasset",
          "Pal/Content/Pal/Blueprint/Character/Player/BP_PalPlayerCharacter.uexp"])
fake_pak(game / "Pal/Content/Paks/~mods/NiceHat_P.pak", "../../../",
         ["Pal/Content/Pal/Texture/Hat.uasset"])
paths, data = scan(game)
risky = data["core_overrides"]
check("the player-character mod is flagged",
      risky.get("BetterPlayer_P") == ["the player character"], risky)
check("an ordinary texture mod is not", "NiceHat_P" not in risky)
check("both halves of one asset count once",
      len(risky.get("BetterPlayer_P", [])) == 1)

# ==========================================================================
check.section("finding UE4SS on GitHub")
RELEASES = {
    "Okaetsu/RE-UE4SS": [
        {"tag_name": "2281fa31", "name": "Palworld (2281fa31)",
         "published_at": "2026-09-03T10:00:00Z", "draft": False,
         "html_url": "https://example.invalid/ue4ss",
         "assets": [
             {"name": "UE4SS-Palworld-g2281fa31-zDev.zip", "size": 43_800_000,
              "browser_download_url": "https://example.invalid/dev.zip"},
             {"name": "UE4SS-Palworld-g2281fa31.zip", "size": 8_600_000,
              "browser_download_url": "https://example.invalid/ue4ss.zip"}]},
        {"tag_name": "experimental-palworld", "name": "experimental-palworld",
         "published_at": "2025-02-20T10:00:00Z", "draft": False,
         "html_url": "https://example.invalid/old",
         "assets": [{"name": "UE4SS-Palworld.zip", "size": 8_500_000,
                     "browser_download_url": "https://example.invalid/old.zip"}]},
    ],
    "Okaetsu/PalSchema": [
        {"tag_name": "0.6.71", "name": "0.6.71",
         "published_at": "2026-09-09T14:45:21Z", "draft": False,
         "html_url": "https://example.invalid/ps",
         "assets": [
             {"name": "PalSchema_0.6.71_Dev.zip", "size": 9_440_754,
              "browser_download_url": "https://example.invalid/psdev.zip"},
             {"name": "PalSchema_0.6.71.zip", "size": 829_883,
              "browser_download_url": "https://example.invalid/ps.zip"}]},
    ],
}

# A fake UE4SS download: the real zips hold ue4ss\ and the proxy DLL, and
# ship the built-in mods with their lists in ue4ss\Mods.
DEFAULT_ORDER = ("\r\n".join(paltools.DEFAULT_ORDER_HEADER) + "\r\n").encode()
ue4ss_zip = io.BytesIO()
with zipfile.ZipFile(ue4ss_zip, "w") as z:
    z.writestr("ue4ss/UE4SS.dll", "new dll")
    z.writestr("ue4ss/MemberVariableLayout.ini", "[layout]")
    z.writestr("ue4ss/Mods/BPModLoaderMod/Scripts/main.lua", "print('bp')")
    z.writestr("ue4ss/Mods/BPModLoaderMod/load_order.txt", DEFAULT_ORDER)
    z.writestr("ue4ss/Mods/mods.txt",
               "BPModLoaderMod : 1\r\nConsoleEnablerMod : 1\r\nKeybinds : 1\r\n")
    z.writestr("ue4ss/Mods/mods.json", json.dumps(
        [{"mod_name": n, "mod_enabled": True}
         for n in ("BPModLoaderMod", "ConsoleEnablerMod", "Keybinds")], indent=4))
    z.writestr("dwmapi.dll", "proxy")
UE4SS_BYTES = ue4ss_zip.getvalue()
# The fake zip is a few hundred bytes; say so, or the size check trips.
RELEASES["Okaetsu/RE-UE4SS"][0]["assets"][1]["size"] = len(UE4SS_BYTES)

asked = []


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_open(url):
    asked.append(url)
    if "api.github.com" in url:
        repo = url.split("/repos/")[1].split("/releases")[0]
        return FakeResponse(json.dumps(RELEASES[repo]).encode())
    if url.endswith("ue4ss.zip"):
        return FakeResponse(UE4SS_BYTES)
    raise AssertionError(f"unexpected download: {url}")


palget._open = fake_open

rel = palget.latest("ue4ss")
check("picks the newest release", rel["tag"] == "2281fa31", rel["tag"])
check("picks the plain build, not zDev",
      rel["asset"]["name"] == "UE4SS-Palworld-g2281fa31.zip")
check("the dev build is available if asked for",
      palget.latest("ue4ss", dev=True)["asset"]["name"].endswith("-zDev.zip"))
check("PalSchema too",
      palget.latest("palschema")["asset"]["name"] == "PalSchema_0.6.71.zip")
check("the date reads plainly", palget.when(rel) in ("3 Sep 2026", "4 Sep 2026"),
      palget.when(rel))

before = len(asked)
palget.latest("ue4ss")
check("a second look uses the cache", len(asked) == before)

check.section("installing what was downloaded")
seen = []
zip_path = palget.download(rel, SB / "downloads",
                           progress=lambda d, t: seen.append((d, t)))
check("the file arrived", zip_path.is_file() and zipfile.is_zipfile(zip_path))
check("progress was reported", bool(seen) and seen[-1][0] == len(UE4SS_BYTES))

# What a real install holds by the time UE4SS is updated: a mod installed
# here with its settings changed, PalSchema with one mod on and one off, a
# blueprint load order, and mods.txt and mods.json edited by hand.
mods_dir = win64 / "ue4ss/Mods"
plan = palinstall.inspect(mod_zip("v5", 3))
palinstall.apply(plan)
palinstall.discard(plan)
cfg.write_text(json.dumps({"Speed": 9, "Sound": False}))
receipt_files = palregistry.receipt("SpeedMod")["files"]
schema = mods_dir / "PalSchema"
(schema / "dlls").mkdir(parents=True)
(schema / "dlls/main.dll").write_bytes(b"palschema")
(schema / "enabled.txt").write_text("")
for folder, name in (("mods", "BiggerBags"), ("disabled-mods", "CheaperBeds")):
    (schema / folder / name / "items").mkdir(parents=True)
    (schema / folder / name / "items/patch.json").write_text("{}")
(mods_dir / "BPModLoaderMod/Scripts").mkdir(parents=True)
(mods_dir / "BPModLoaderMod/Scripts/main.lua").write_text("print('old bp')")
(mods_dir / "BPModLoaderMod/load_order.txt").write_bytes(
    DEFAULT_ORDER + b"BetterPlayer_P\r\n")
(mods_dir / "mods.txt").write_bytes(
    b"BPModLoaderMod : 1\r\nKeybinds : 0\r\nSpeedMod : 1\r\n")
(mods_dir / "mods.json").write_text(json.dumps(
    [{"mod_name": "BPModLoaderMod", "mod_enabled": True},
     {"mod_name": "Keybinds", "mod_enabled": False},
     {"mod_name": "SpeedMod", "mod_enabled": True}], indent=4))

results, parked = palget.install_ue4ss(zip_path, paths)
check("the new UE4SS is in place",
      (win64 / "ue4ss/UE4SS.dll").read_text() == "new dll")
check("the proxy DLL came with it", (win64 / "dwmapi.dll").is_file())
check("BPModLoaderMod came with it",
      (win64 / "ue4ss/Mods/BPModLoaderMod/Scripts/main.lua").is_file())
check("the old install was kept, not deleted",
      len(parked) == 1 and parked[0].is_dir()
      and (parked[0] / "UE4SS.dll").read_bytes() == b"x", parked)
check("it says what it did", any("Kept your old UE4SS" in r for r in results),
      results)

check.section("updating UE4SS keeps your mods")
check("your mod is still there, with the settings you changed",
      cfg.is_file() and json.loads(cfg.read_text())["Speed"] == 9,
      cfg.read_text() if cfg.is_file() else "missing")
check("at the paths its install receipt names",
      all(Path(f).exists() for f in receipt_files), receipt_files)
data = palmods.build(palmods.discover())
names = {m["name"] for m in data["ue4ss_mods"]}
check("the main list still shows it, and PalSchema",
      {"SpeedMod", "PalSchema"} <= names, sorted(names))
on_off = {s["name"]: s["enabled"] for s in data["palschema_mods"]}
check("PalSchema's mods came along, one on and one off",
      on_off == {"BiggerBags": True, "CheaperBeds": False}, on_off)
txt = (mods_dir / "mods.txt").read_bytes()
check("mods.txt keeps your lines and choices, and gains the new built-in",
      txt == b"BPModLoaderMod : 1\r\nConsoleEnablerMod : 1\r\n"
             b"Keybinds : 0\r\nSpeedMod : 1\r\n", txt)
listed = json.loads((mods_dir / "mods.json").read_text())
check("mods.json does the same, in the same order",
      [(e["mod_name"], e["mod_enabled"]) for e in listed]
      == [("BPModLoaderMod", True), ("ConsoleEnablerMod", True),
          ("Keybinds", False), ("SpeedMod", True)], listed)
check("BPModLoaderMod has the new code",
      (mods_dir / "BPModLoaderMod/Scripts/main.lua").read_text() == "print('bp')")
order = mods_dir / "BPModLoaderMod/load_order.txt"
check("but keeps your load order",
      order.read_bytes() == DEFAULT_ORDER + b"BetterPlayer_P\r\n",
      order.read_bytes())
check("with the release's copy beside it",
      order.with_name("load_order.txt.new").read_bytes() == DEFAULT_ORDER)
check("the install says what it kept",
      {"Kept your 2 mods and their settings", "Kept your 2 PalSchema mods"}
      <= set(results), results)
check("the parked UE4SS is still whole, mods and all",
      (parked[0] / "Mods/SpeedMod/config.json").is_file()
      and (parked[0] / "Mods/PalSchema/mods/BiggerBags").is_dir())

check.section("an install that stops part way")
(win64 / "ue4ss/UE4SS.dll").write_text("the one you have")
before = sorted(p.name for p in win64.iterdir())
real_carry_over = palget.carry_over


def disk_full(old, new):
    real_carry_over(old, new)
    raise OSError(28, "No space left on device")


palget.carry_over = disk_full
try:
    palget.install_ue4ss(zip_path, paths)
    check("the failure is passed on", False)
except OSError as exc:
    check("the failure is passed on", "No space" in str(exc), str(exc))
palget.carry_over = real_carry_over
check("the UE4SS you had is back in place",
      (win64 / "ue4ss/UE4SS.dll").read_text() == "the one you have")
check("with your mods and their settings",
      cfg.is_file() and json.loads(cfg.read_text())["Speed"] == 9)
check("and nothing new is left beside it",
      sorted(p.name for p in win64.iterdir()) == before,
      sorted(p.name for p in win64.iterdir()))

palmods._doctor_cache.clear()
st = palmods.ue4ss_status(palmods.discover())
check("the app now sees a working UE4SS",
      st["installed"] and st["layout"] == "experimental" and not st["problems"],
      st["problems"])

check.section("downloads that go wrong")
short = dict(rel)
short["asset"] = dict(rel["asset"], size=len(UE4SS_BYTES) + 500)
try:
    palget.download(short, SB / "downloads2")
    check("a truncated download is refused", False)
except palget.GetError as exc:
    check("a truncated download is refused", "ended early" in str(exc), str(exc))

not_a_zip = dict(rel)
not_a_zip["asset"] = {"name": "x.zip", "size": 0,
                      "url": "https://example.invalid/ue4ss.zip"}
palget._open = lambda url: FakeResponse(b"this is not a zip")
try:
    palget.download(not_a_zip, SB / "downloads3")
    check("a file that isn't a zip is refused", False)
except palget.GetError as exc:
    check("a file that isn't a zip is refused", "not a zip" in str(exc), str(exc))

palget._open = fake_open
wrong = io.BytesIO()
with zipfile.ZipFile(wrong, "w") as z:
    z.writestr("readme.txt", "hello")
(SB / "wrong.zip").write_bytes(wrong.getvalue())
try:
    palget.install_ue4ss(SB / "wrong.zip", paths)
    check("a zip without UE4SS in it is refused", False)
except palget.GetError as exc:
    check("a zip without UE4SS in it is refused", "UE4SS.dll" in str(exc), str(exc))


# ==========================================================================
check.section("the install window")
from helpers import hidden_tk, silence_dialogs           # noqa: E402

palget._open = fake_open
root, pump, errors = hidden_tk()
import palmods_gui as G                                  # noqa: E402
import palwindows as W                                   # noqa: E402
silence_dialogs(G, W)
palsafety.game_running = lambda game: False

app = G.App(root)
pump(0.6)
win = W.GetWindow(app, "ue4ss")
pump(0.8)
text = " ".join(w.cget("text") for w in win.body.winfo_children()
                if "text" in w.keys())
cards = [w for w in win.body.winfo_children() if isinstance(w, W.tk.Frame)]
labels = []
for c in cards:
    for row in c.winfo_children():
        labels += [w.cget("text") for w in row.winfo_children()
                   if "text" in w.keys()]
check("the window says what it found", "UE4SS-Palworld-g2281fa31.zip" in labels,
      labels)
from palui import human_size                          # noqa: E402
check("and how big it is", human_size(rel["asset"]["size"]) in labels, labels)
check("and where it comes from",
      any("github.com/Okaetsu/RE-UE4SS" in str(t) for t in labels))
check("the button is ready", str(win.go.cget("state")) == "normal")

win._start()
pump(1.2)
check("it installed and says so",
      "Close" in str(win.go.cget("text")), win.go.cget("text"))
check("UE4SS is in place after the window ran",
      (win64 / "ue4ss/UE4SS.dll").read_text() == "new dll")
check("and your mods came through that update too",
      cfg.is_file() and json.loads(cfg.read_text())["Speed"] == 9
      and (win64 / "ue4ss/Mods/PalSchema/mods/BiggerBags").is_dir())
win.destroy()

check.section("the banner offers it when UE4SS is missing")
gone = win64 / "ue4ss"
gone.rename(win64 / "ue4ss-away")
app.reload(full=True)
pump(0.8)


def banner_buttons():
    out = []
    for b in app.warnbox.winfo_children():
        out += [w.cget("text").strip() for w in b.winfo_children()
                if isinstance(w, W.tk.Button)]
    return out


check("the missing-UE4SS banner offers to install it",
      "Install UE4SS" in banner_buttons(), banner_buttons())
(win64 / "ue4ss-away").rename(gone)
app.reload(full=True)
pump(0.5)
check("and goes away once it is there",
      "Install UE4SS" not in banner_buttons(), banner_buttons())

check.section("when GitHub can't be reached")
def dead(url):
    raise palget.GetError("Could not reach GitHub: unreachable")
palget._open = dead
palget._cache_file().unlink(missing_ok=True)
win = W.GetWindow(app, "palschema")
pump(0.8)
shown = " ".join(str(w.cget("text")) for w in win.body.winfo_children()
                 if "text" in w.keys())
check("it says so plainly", "Could not reach GitHub" in shown, shown)
check("and offers to try again", "Try again" in str(win.go.cget("text")))
win.destroy()
root.destroy()

check.finish(errors)
