"""Steam Workshop mods: Palworld's own mod loader, its settings and its UE4SS.

Every install here is built to Pocketpair's published spec (PalworldModUploader,
docs/en/02-Package.md and 04-Tech.md): a package per subscribed item in the
Workshop folder, each with an Info.json; the game copies them into
Mods\\NativeMods\\UE4SS (its own UE4SS and the script mods it runs),
Pal\\Content\\Paks\\LogicMods and Pal\\Content\\Paks\\~WorkshopMods, and switches
them with ActiveModList lines in Mods\\PalModSettings.ini.
"""
import json
import os
import time
import tkinter as tk
from pathlib import Path

from helpers import (Checker, fake_pak, hidden_tk, lua_mod, make_game, sandbox, scan,
                     silence_dialogs, steam_library, ue4ss_log, use_game)

SB = sandbox("workshop")
import palinstall, palmods, palsafety, paltools, palworkshop    # noqa: E402

check = Checker()
now = int(time.time())


def item(root, item_id, info, files=None):
    """A Workshop package: <root>\\<item id>\\Info.json and its files."""
    d = Path(root) / str(item_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "Info.json").write_text(info if isinstance(info, str) else json.dumps(info),
                                 "utf8")
    for rel, body in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(body)
    return d


def lua(name, *, deps=(), title=None, version="1.0.0", main="print('x')"):
    return {"ModName": title or name, "PackageName": name, "Version": version,
            "Author": "someone", "Dependencies": list(deps), "Thumbnail": "thumbnail.png",
            "InstallRule": [{"Type": "Lua", "Targets": ["./Scripts"]}]}


def paks_info(name, kind="Paks", deps=(), title=None):
    folder = "./Paks/" if kind == "Paks" else "./LogicMods/"
    return {"ModName": title or name, "PackageName": name, "Version": "1",
            "Dependencies": list(deps),
            "InstallRule": [{"Type": kind, "Targets": [folder]}]}


# ==========================================================================
check.section("PalModSettings.ini, edited the way Mod Management does")
g = SB / "ini"
f = g / "Mods/PalModSettings.ini"
f.parent.mkdir(parents=True)
f.write_bytes(b"[OtherSection]\r\nKeep=me\r\n\r\n[PalModSettings]\r\nbGlobalEnableMod=True\r\n"
              b"WorkshopRootDir=C:\\Steam\\steamapps\\workshop\\content\\1623730\r\n"
              b"ActiveModList=UE4SS\r\nActiveModList=BetterBases\r\n; a comment\r\n")
s = palworkshop.read_settings(g)
check("reads the switch, the folder and the list",
      s["global_on"] and s["root"].endswith("1623730")
      and s["active"] == ["UE4SS", "BetterBases"], s)
palworkshop.set_active(g, "ShinyPals", True)
raw = f.read_bytes()
check("a mod switched on goes after the last one, with the file's line ends",
      b"ActiveModList=BetterBases\r\nActiveModList=ShinyPals\r\n; a comment" in raw, raw)
check("another section is left exactly as it was",
      raw.startswith(b"[OtherSection]\r\nKeep=me\r\n\r\n"), raw)
palworkshop.set_active(g, "BetterBases", False)
raw = f.read_bytes()
check("a mod switched off loses its line, and only that",
      b"BetterBases" not in raw
      and b"ActiveModList=UE4SS\r\nActiveModList=ShinyPals\r\n" in raw, raw)
palworkshop.set_active(g, "shinypals", True)
check("switching on what is on changes nothing", f.read_bytes() == raw)
palworkshop.set_global(g, False)
check("the switch for every mod is changed where it is",
      b"bGlobalEnableMod=False\r\nWorkshopRootDir" in f.read_bytes())
check("the version it replaced is kept", (f.parent / "PalModSettings.ini.bak").is_file())
f.unlink()
palworkshop.set_active(g, "BetterBases", True)
s = palworkshop.read_settings(g)
check("no file yet: made with the section, mods on, and the mod",
      s["exists"] and s["global_on"] and s["active"] == ["BetterBases"], f.read_bytes())
f.write_bytes("[PalModSettings]\r\nbGlobalEnableMod=True\r\nWorkshopRootDir=D:\\ゲーム\\1623730\r\n"
              "ActiveModList=A\r\n".encode("utf-16"))
s = palworkshop.read_settings(g)
check("UTF-16, as Unreal can write it, is read",
      s["root"] == "D:\\ゲーム\\1623730" and s["active"] == ["A"], s)
palworkshop.set_active(g, "B", True)
raw = f.read_bytes()
check("and written back as UTF-16",
      raw.startswith(b"\xff\xfe")
      and "ActiveModList=A\r\nActiveModList=B\r\n" in raw.decode("utf-16"), raw[:40])
# As Palworld 1.0.5 writes it after Save in Mod Management, with no mod on.
real = (b"[PalModSettings]\r\nbGlobalEnableMod=True\r\n"
        b"WorkshopRootDir=D:\\SteamLibrary\\steamapps\\workshop\\content\\1623730\r\n"
        b"ConfigVersion=1.0\r\nbNeedShowErrorOnNextStart=True\r\n")
f.write_bytes(real)
s = palworkshop.read_settings(g)
check("the file Palworld 1.0.5 writes is read",
      s["global_on"] and s["active"] == []
      and s["root"] == "D:\\SteamLibrary\\steamapps\\workshop\\content\\1623730", s)
palworkshop.set_active(g, "DarkMagicianGirl", True)
check("a mod switched on in it goes in the section; the game's own lines stay",
      f.read_bytes() == real + b"ActiveModList=DarkMagicianGirl\r\n", f.read_bytes())
palworkshop.set_active(g, "DarkMagicianGirl", False)
check("and switched off, it is exactly as the game wrote it", f.read_bytes() == real,
      f.read_bytes())
f.write_bytes(b"[/Script/Pal.PalModSettings]\r\nbGlobalEnableMod=True\r\nActiveModList=A\r\n")
palworkshop.set_active(g, "B", True)
check("the section named as Unreal names a class's is the same section",
      palworkshop.read_settings(g)["active"] == ["A", "B"]
      and f.read_bytes().count(b"[") == 1, f.read_bytes())
f.write_bytes(b"bGlobalEnableMod=True\nActiveModList=A\nActiveModList=A\n")
palworkshop.set_active(g, "C", True)
check("a mod listed twice is listed once; no header is invented",
      f.read_bytes() == b"bGlobalEnableMod=True\nActiveModList=A\nActiveModList=C\n",
      f.read_bytes())


# ==========================================================================
check.section("Info.json, read the way Pocketpair's tools read it")
g2 = SB / "info"
root2 = SB / "info-workshop"
(g2 / "Mods").mkdir(parents=True)
(g2 / "Mods/PalModSettings.ini").write_text(
    f"[PalModSettings]\nbGlobalEnableMod=True\nWorkshopRootDir={root2}\n"
    f"ActiveModList=Commented\n")
item(root2, 101, '{\n  // written by hand\n  "packagename": "Commented",\n'
                 '  "ModName": "With comments",\n'
                 '  "InstallRule": [{"type": "lua", "targets": ["./Scripts",]},],\n}')
item(root2, 102, "{ this is not json")
item(root2, 103, {"PackageName": "Odd-Name", "InstallRule": [
    {"Type": "Paks", "Targets": ["./Paks/"]}]})
item(root2, 104, {"PackageName": "ServerOnly", "InstallRule": [
    {"Type": "Lua", "IsServer": True, "Targets": ["./Scripts"]}]})
item(root2, 105, {"PackageName": "Escape", "Thumbnail": "../../secret.png",
                  "InstallRule": [{"Type": "Paks",
                                   "Targets": ["../../../outside", "./Paks/"]}]})
item(root2, 106, {"PackageName": "Wordy", "ModName": "A" * 500 + "\nsecond line",
                  "Version": 2, "Author": ["not", "text"],
                  "InstallRule": [{"Type": "Paks", "Targets": ["./Paks/"]}]})
(root2 / "notapackage").mkdir()
(SB / "secret.png").write_bytes(b"x")
items = {it["id"]: it for it in palworkshop.packages(g2)}
check("comments, trailing commas and keys in any case",
      items["101"]["package"] == "Commented" and items["101"]["types"] == ["Lua"]
      and items["101"]["title"] == "With comments", items["101"])
check("on, by its ActiveModList line", items["101"]["listed"])
check("an unreadable Info.json is reported, not skipped",
      items["102"]["error"] == "its Info.json can't be read", items["102"])
check("a name the uploader wouldn't allow is left to the game's menu",
      not items["103"]["switchable"] and items["103"]["error"] is None, items["103"])
check("server rules don't apply to the game",
      items["104"]["for_other"] and items["104"]["types"] == [], items["104"])
check("a folder without Info.json is not a package", "notapackage" not in items)
check("a picture outside its package is ignored", items["105"]["thumbnail"] is None)
check("so is a target outside it",
      [p.name for p in palworkshop._targets(items["105"]["path"],
                                            items["105"]["rules"][0])] == ["Paks"])
check("names from strangers are kept to one short line",
      len(items["106"]["title"]) == 100 and "\n" not in items["106"]["title"]
      and items["106"]["version"] == "2" and items["106"]["author"] == "",
      items["106"]["title"])
check("an item id gives its Workshop page",
      items["101"]["url"] == "https://steamcommunity.com/sharedfiles/filedetails/?id=101")
served = {it["id"]: it for it in palworkshop.packages(g2, server=True)}
check("a dedicated server reads the IsServer rules",
      served["104"]["types"] == ["Lua"] and served["101"]["for_other"], served["104"])


# ==========================================================================
check.section("a game whose UE4SS comes from the Steam Workshop")
common = steam_library(SB / "lib", "Palworld", "1623730", "1000", now - 86400)
game = use_game(make_game(common, ue4ss=None))
wroot = SB / "lib/steamapps/workshop/content/1623730"
native = game / "Mods/NativeMods/UE4SS"
paks = game / "Pal/Content/Paks"

# The packages Steam keeps.
item(wroot, 2001, {"ModName": "UE4SS", "PackageName": "UE4SS", "Version": "3.0.1",
                   "InstallRule": [{"Type": "UE4SS", "Targets": ["./UE4SS/"]}]},
     {"UE4SS/UE4SS.dll": "x", "UE4SS/Mods/BPModLoaderMod/Scripts/main.lua": "x",
      "UE4SS/Mods/WorkshopExtra/Scripts/main.lua": "x"})
item(wroot, 2002, lua("BetterBases", deps=["UE4SS"], title="Better Bases"),
     {"Scripts/main.lua": "RegisterKeyBind(Key.F6, function() end)",
      "thumbnail.png": "not really a png"})
item(wroot, 2003, paks_info("ShinyPals", title="Shiny Pals"))
fake_pak(wroot / "2003/Paks/ShinyPals_P.pak", "../../../",
         ["Pal/Content/Pal/Texture/Pal/Lamball.uasset"])
item(wroot, 2004, paks_info("SimpleDPS", kind="LogicMods"))
fake_pak(wroot / "2004/LogicMods/SimpleDPS.pak", "../../../Pal/Content/Mods/SimpleDPS/",
         ["ModActor.uasset"])
item(wroot, 2005, {"ModName": "PalSchema", "PackageName": "PalSchema",
                   "InstallRule": [{"Type": "Lua", "Targets": ["./dlls"]}]},
     {"dlls/main.dll": "x"})
item(wroot, 2006, {"ModName": "Better Rates", "PackageName": "Rates",
                   "Dependencies": ["PalSchema"],
                   "InstallRule": [{"Type": "PalSchema", "Targets": ["./PalSchema/"]}]},
     {"PalSchema/raw/rates.json": "{}"})
item(wroot, 2007, lua("Unlisted"), {"Scripts/main.lua": "x"})
item(wroot, 2008, paks_info("NeedsLib", deps=["MissingLib"]))
fake_pak(wroot / "2008/Paks/NeedsLib_P.pak", "../../../", ["Pal/Content/Pal/A.uasset"])
item(wroot, 2009, paks_info("TwinMod", title="Twin one"))
item(wroot, 2010, paks_info("TwinMod", title="Twin two"))
item(wroot, 2011, paks_info("CoreSwap"))
fake_pak(wroot / "2011/Paks/CoreSwap_P.pak", "../../../",
         ["Pal/Content/Pal/Blueprint/Character/Player/BP_PalPlayerCharacter.uasset"])
item(wroot, 2012, lua("HalfDeployed"), {"Scripts/main.lua": "x"})
item(wroot, 2013, paks_info("Odd-Name"))

# What the game copied into its own folders.
(native / "UE4SS.dll").parent.mkdir(parents=True)
(native / "UE4SS.dll").write_bytes(b"x")
lua_mod(native / "Mods", "BPModLoaderMod")
lua_mod(native / "Mods", "WorkshopExtra")
lua_mod(native / "Mods", "BetterBases", main="RegisterKeyBind(Key.F6, function() end)")
(native / "Mods/PalSchema/dlls").mkdir(parents=True)
(native / "Mods/PalSchema/dlls/main.dll").write_bytes(b"x")
(native / "Mods/PalSchema/enabled.txt").write_text("")
(native / "Mods/PalSchema/mods/Rates/raw").mkdir(parents=True)
(native / "Mods/PalSchema/mods/Rates/raw/rates.json").write_text("{}")
(native / "Mods/HalfDeployed").mkdir(parents=True)
(native / "Mods/HalfDeployed/enabled.txt").write_text("")
fake_pak(paks / "~WorkshopMods/ShinyPals/ShinyPals_P.pak", "../../../",
         ["Pal/Content/Pal/Texture/Pal/Lamball.uasset"])
fake_pak(paks / "LogicMods/SimpleDPS.pak", "../../../Pal/Content/Mods/SimpleDPS/",
         ["ModActor.uasset"])
(paks / "LogicMods/SimpleDPS.ucas").write_bytes(b"x")       # its IoStore half
(paks / "LogicMods/SimpleDPS").mkdir()                       # its settings folder
fake_pak(paks / "LogicMods/Organized/Tidy.pak", "../../../Pal/Content/Mods/Tidy/",
         ["ModActor.uasset"])

# Mods from elsewhere, in the same game.
lua_mod(native / "Mods", "MyOwnMod", main="RegisterKeyBind(Key.F6, function() end)")
(native / "Mods/PalSchema/mods/MyTweaks/raw").mkdir(parents=True)
(native / "Mods/PalSchema/mods/MyTweaks/raw/x.json").write_text("{}")
fake_pak(paks / "~mods/MyLamball_P.pak", "../../../",
         ["Pal/Content/Pal/Texture/Pal/Lamball.uasset"])
(paks / "LogicMods/Ghost.modconfig.json").write_text("{}")

(game / "Mods/PalModSettings.ini").write_text(
    "[PalModSettings]\nbGlobalEnableMod=True\n"
    + "".join(f"ActiveModList={n}\n" for n in (
        "UE4SS", "BetterBases", "ShinyPals", "SimpleDPS", "PalSchema", "Rates",
        "NeedsLib", "TwinMod", "CoreSwap", "HalfDeployed", "Odd-Name")))
RUN = dict(started=["BetterBases", "PalSchema", "MyOwnMod"],
           extra=["[BPModLoaderMod] Name == SimpleDPS", "[PalSchema] Loading mod Rates"])
ue4ss_log(native / "UE4SS.log", when_offset=-600, **RUN)

paths, data = scan(game)
ue = data["ue4ss"]
check("the Workshop's UE4SS is the one in use",
      paths["layout"] == palmods.WORKSHOP_LAYOUT and paths["ue4ss_root"] == native,
      paths["layout"])
check("UE4SS reads as ready, from the Workshop",
      ue["installed"] and ue["state"] == "ok" and ue["layout"] == "workshop"
      and "from the Steam Workshop" in ue["summary"], ue)
check("its log is the one read",
      data["log"]["found"] and "BetterBases" in data["log"]["started"])
check("found in the Steam library, without WorkshopRootDir",
      data["workshop"]["root"] == str(wroot), data["workshop"])
names = {m["name"]: m for m in data["ue4ss_mods"]}
check("a mod you put in its Mods folder is listed, and started",
      names.get("MyOwnMod", {}).get("loaded")
      and not names["MyOwnMod"]["inactive_root"], names.get("MyOwnMod"))
check("the game's copies of Workshop mods aren't listed twice",
      not {"BetterBases", "PalSchema", "WorkshopExtra", "HalfDeployed"} & set(names),
      sorted(names))
check("UE4SS's own mods are still its built-ins",
      names.get("BPModLoaderMod", {}).get("builtin"), sorted(names))
pak_names = [p["name"] for p in data["pak_mods"]]
check("nor is the game's copy of a Workshop blueprint pak",
      "SimpleDPS" not in pak_names and "MyLamball_P" in pak_names, pak_names)
schema = {x["name"]: x for x in data["palschema_mods"]}
check("your PalSchema mod is listed; the Workshop's isn't", set(schema) == {"MyTweaks"},
      sorted(schema))
check("PalSchema itself is the Workshop's",
      schema["MyTweaks"]["framework"] and schema["MyTweaks"]["framework_on"],
      schema["MyTweaks"])

ws = {w["item"]: w for w in data["workshop_mods"]}
by = {w["name"]: w for w in data["workshop_mods"]}
check("a row per package name: two items sharing one share a row",
      len(ws) == 12 and "2010" not in ws, sorted(ws))
check("script mod: on, and started",
      by["BetterBases"]["enabled"] and by["BetterBases"]["loggable"]
      and by["BetterBases"]["loaded"], by["BetterBases"])
check("blueprint mod: started by BPModLoaderMod", by["SimpleDPS"]["loaded"])
check("pak mod: on, and silent",
      by["ShinyPals"]["enabled"] and not by["ShinyPals"]["loggable"], by["ShinyPals"])
check("UE4SS itself: ran", by["UE4SS"]["loaded"])
check("PalSchema mod: mentioned by PalSchema", by["Rates"]["loaded"])
check("not on the game's list: off",
      not by["Unlisted"]["listed"] and not by["Unlisted"]["enabled"])
check("a dependency nobody subscribed to",
      by["NeedsLib"]["deps_missing"] == ["MissingLib"], by["NeedsLib"])
check("which names the other item",
      by["TwinMod"]["duplicate"] == ["Twin two"], by["TwinMod"]["duplicate"])
pairs = {tuple(c["mods"]) for c in data["conflicts"]["pairs"]}
check("a Workshop pak and yours replacing the same file",
      ("MyLamball_P", "ShinyPals_P (Workshop)") in pairs, pairs)
check("a Workshop pak replacing a core blueprint",
      "CoreSwap_P (Workshop)" in data["core_overrides"], data["core_overrides"])
f6 = [c for c in data["keybinds"]["clashes"] if c["key"] == "F6"]
check("a hotkey shared with a Workshop script mod",
      f6 and set(f6[0]["mods"]) == {"BetterBases", "MyOwnMod"}, data["keybinds"]["clashes"])
try:
    json.dumps(data)
    plain = True
except TypeError as exc:
    plain = str(exc)
check("the scan is plain JSON, for manifest.json", plain is True, plain)
text = palmods.report(data)
check("the text report has the Workshop mods",
      "STEAM WORKSHOP MODS" in text and "Better Bases" in text)

left = {Path(i["path"]).name: i for i in paltools.find_leftovers(paths, data)}
check("nothing the game put there for the Workshop is a leftover",
      not {"SimpleDPS.ucas", "SimpleDPS", "Organized", "HalfDeployed"} & set(left),
      sorted(left))
check("a real leftover still is", "Ghost.modconfig.json" in left, sorted(left))


# ==========================================================================
check.section("switching Workshop mods")
check("a package name is a kind of mod", palmods.kinds_of("BetterBases") == ["workshop"])
msg = palmods.set_enabled("BetterBases", False)
s = palworkshop.read_settings(game)
check("off: its ActiveModList line goes, the rest stays",
      "BetterBases" not in s["active"] and "ShinyPals" in s["active"] and s["global_on"]
      and s["root"] is None, (msg, s))
check("the game's copy is not touched",
      (native / "Mods/BetterBases/Scripts/main.lua").is_file()
      and (native / "Mods/BetterBases/enabled.txt").is_file())
palmods.set_enabled("BetterBases", True)
check("on again", "BetterBases" in palworkshop.read_settings(game)["active"])

real_running = palsafety.game_running
palsafety.game_running = lambda _g: True
try:
    palmods.set_enabled("ShinyPals", False)
    refused = False
except PermissionError as exc:
    refused = "Close Palworld" in str(exc)
palsafety.game_running = real_running
check("not while Palworld runs: it keeps its own list then",
      refused and "ShinyPals" in palworkshop.read_settings(game)["active"])
try:
    palmods.set_enabled("Odd-Name", False)
    refused = False
except PermissionError:
    refused = True
check("a name the uploader wouldn't allow is left to the game's menu",
      refused and "Odd-Name" in palworkshop.read_settings(game)["active"])
try:
    palinstall.uninstall("BetterBases", kind="workshop")
    refused = False
except palinstall.InstallError as exc:
    refused = "Unsubscribe" in str(exc)
check("uninstalling one is left to Steam",
      refused and (native / "Mods/BetterBases").is_dir())


# ==========================================================================
check.section("installing next to Workshop mods")
src = SB / "download"
lua_mod(src, "BetterBases")                  # the same name as the Workshop's
lua_mod(src, "BrandNew")
fake_pak(src / "SimpleDPS.pak", "../../../Pal/Content/Mods/SimpleDPS/", ["ModActor.uasset"])
plan = palinstall.inspect(src)
got = sorted(c["name"] for c in plan["components"])
check("the Workshop's copies are left out of an install", got == ["BrandNew"], got)
check("and the install says why",
      any("from the Steam Workshop" in w and "BetterBases" in w and "SimpleDPS" in w
          for w in plan["warnings"]), plan["warnings"])
check("new script mods go into the Workshop's UE4SS",
      [c["dest"] for c in plan["components"]] == [native / "Mods/BrandNew"],
      [c["dest"] for c in plan["components"]])
check("which Palworld manages, as the install says",
      any("Palworld manages that folder" in w for w in plan["warnings"]), plan["warnings"])
palinstall.discard(plan)


# ==========================================================================
check.section("the Workshop's UE4SS, switched off or not there yet")
palworkshop.set_global(game, False)
paths, data = scan(game)
ue = data["ue4ss"]
check("every mod off in Mod Management: UE4SS says so",
      ue["state"] == "warn" and ue["problems"][0].startswith("Mods are switched off"),
      ue["problems"])
by = {w["name"]: w for w in data["workshop_mods"]}
check("listed mods aren't on while every mod is off",
      by["BetterBases"]["listed"] and not by["BetterBases"]["enabled"])
palworkshop.set_global(game, True)

palmods.set_enabled("PalSchema", False, "workshop")
paths, data = scan(game)
by = {w["name"]: w for w in data["workshop_mods"]}
check("a PalSchema mod with PalSchema switched off says it needs it, once",
      by["Rates"]["needs"] == "needs PalSchema, from the Steam Workshop"
      and not by["Rates"]["deps_off"], by["Rates"])
palmods.set_enabled("PalSchema", True, "workshop")

palmods.set_enabled("UE4SS", False, "workshop")
paths, data = scan(game)
by = {w["name"]: w for w in data["workshop_mods"]}
check("UE4SS switched off in Mod Management",
      data["ue4ss"]["workshop"] == palworkshop.SWITCHED_OFF
      and data["ue4ss"]["state"] == "warn", data["ue4ss"])
check("so its script mods can't start, and say why, once",
      "switched off" in (by["BetterBases"]["needs"] or "")
      and not by["BetterBases"]["loggable"] and not by["BetterBases"]["deps_off"],
      by["BetterBases"])
palmods.set_enabled("UE4SS", True, "workshop")

native.rename(native.with_name("UE4SS-away"))
paths, data = scan(game)
check("on, but not copied in yet: it installs when the game next starts",
      data["ue4ss"]["workshop"] == palworkshop.PENDING and data["ue4ss"]["state"] == "ok"
      and "next starts" in data["ue4ss"]["summary"], data["ue4ss"])
native.with_name("UE4SS-away").rename(native)


# ==========================================================================
check.section("switched on in the game's own menu")
paths, data = scan(game)                  # the app has seen the list as it is
ini = palworkshop.settings_file(game)
ini.write_text(ini.read_text() + "ActiveModList=Unlisted\n")   # Mod Management
paths, data = scan(game)
check("a mod switched on in the game waits for the next launch",
      "workshop:Unlisted" in data["patch"]["waiting"], data["patch"]["waiting"])
# The session it was switched on in goes on: the same run, a later write.
log = native / "UE4SS.log"
log.write_text(log.read_text() + "[later] still the same session\n")
os.utime(log, (now + 120, now + 120))
paths, data = scan(game)
check("the run it was switched on during doesn't count",
      "workshop:Unlisted" in data["patch"]["waiting"], data["patch"]["waiting"])
ue4ss_log(log, when_offset=300, **RUN)
paths, data = scan(game)
by = {w["name"]: w for w in data["workshop_mods"]}
check("the next run does", "workshop:Unlisted" not in data["patch"]["waiting"],
      data["patch"]["waiting"])
check("and in it, it didn't start",
      by["Unlisted"]["loggable"] and not by["Unlisted"]["loaded"], by["Unlisted"])
check("records from before go by when the log was written",
      palsafety._had_its_chance(100.0, "run", 200.0)
      and not palsafety._had_its_chance(300.0, "run", 200.0))
check("new ones by which run it was",
      palsafety._had_its_chance({"when": 1, "run": "a"}, "b", 0)
      and not palsafety._had_its_chance({"when": 1, "run": "a"}, "a", 999))
check("and a log without times by when it was written",
      palsafety._had_its_chance({"when": 1, "run": None}, None, 5)
      and not palsafety._had_its_chance({"when": 9, "run": None}, None, 5))


# ==========================================================================
check.section("sharing a modlist")
doc = paltools.export_modlist(data)
shared = [m for m in doc["mods"] if m["kind"] == paltools.WORKSHOP]
check("Workshop mods are in it, with their pages",
      any(m["name"] == "BetterBases" and m["url"].endswith("?id=2002") for m in shared),
      shared)
check("by title in the text version", "- Better Bases" in paltools.modlist_text(doc))
theirs = dict(doc, mods=doc["mods"] + [{"name": "FriendsMod", "title": "Friend's mod",
                                        "kind": paltools.WORKSHOP, "enabled": True}])
cmp = paltools.compare_modlist(theirs, data)
check("a friend's Workshop mod you don't have is missing",
      [m["name"] for m in cmp["missing"]] == ["FriendsMod"], cmp["missing"])


# ==========================================================================
check.section("UE4SS by hand, and the Workshop's too")
common2 = steam_library(SB / "lib2", "Palworld", "1623730", "1000", now - 86400)
game2 = use_game(make_game(common2))
w2 = SB / "w2"
item(w2, 3001, lua("BetterBases"), {"Scripts/main.lua": "x"})
native2 = game2 / "Mods/NativeMods/UE4SS"
lua_mod(native2 / "Mods", "BetterBases")
(native2 / "UE4SS.dll").write_bytes(b"x")
(game2 / "Mods/PalModSettings.ini").write_text(
    f"[PalModSettings]\nbGlobalEnableMod=True\nWorkshopRootDir={w2}\n"
    f"ActiveModList=BetterBases\n")
ue4ss_log(native2 / "UE4SS.log", ["BetterBases"])
lua_mod(game2 / "Pal/Binaries/Win64/ue4ss/Mods", "NexusMod")
ue4ss_log(game2 / "Pal/Binaries/Win64/ue4ss/UE4SS.log", ["NexusMod"])
paths, data = scan(game2)
ue = data["ue4ss"]
check("yours stays the UE4SS in use", paths["layout"].startswith("experimental"),
      paths["layout"])
check("both loading is a conflict, said plainly",
      ue["state"] == "conflict" and ue["twice"] and ue["problems"][0] == palmods.TWICE,
      ue["problems"])
by = {w["name"]: w for w in data["workshop_mods"]}
check("Workshop script mods are judged by the Workshop's log",
      by["BetterBases"]["loaded"], by["BetterBases"])
(native2 / "UE4SS.dll").rename(native2 / "UE4SS.dll.off")
paths, data = scan(game2)
by = {w["name"]: w for w in data["workshop_mods"]}
check("its UE4SS.dll renamed away, as players do: no conflict",
      data["ue4ss"]["state"] == "ok" and not data["ue4ss"]["twice"], data["ue4ss"])
check("and its script mods say why they can't run",
      "installed by hand" in (by["BetterBases"]["needs"] or ""), by["BetterBases"])
(native2 / "UE4SS.dll.off").rename(native2 / "UE4SS.dll")


# ==========================================================================
check.section("a dedicated server")
srv = use_game(make_game(SB / "srv", server=True, ue4ss=None))
(srv / "Mods").mkdir()
(srv / "Mods/PalModSettings.ini").write_text(
    "[PalModSettings]\nbGlobalEnableMod=True\nActiveModList=ServerOnly\n")
paths, data = scan(srv)
wsd = data["workshop"]
check("its list names Workshop mods, but not where they are",
      wsd["server"] and wsd["active"] == ["ServerOnly"] and wsd["root"] is None, wsd)
palworkshop.set_root(srv, root2)
paths, data = scan(srv)
by = {w["name"]: w for w in data["workshop_mods"]}
check("told, it reads their IsServer rules",
      by["ServerOnly"]["types"] == ["Lua"] and by["ServerOnly"]["applies"],
      by.get("ServerOnly"))
check("and game-only items say so",
      by["Commented"]["for_other"] and not by["Commented"]["applies"], by["Commented"])


# ==========================================================================
check.section("the app")
use_game(game)
root, pump, errors = hidden_tk()
import palmods_gui as G                       # noqa: E402
import palwindows as W                        # noqa: E402
import palinfo                                # noqa: E402
silence_dialogs(G, W, palinfo)
app = G.App(root)
pump(0.6)
rows = {e["id"]: e for e in app._entries_cache}
check("a Steam Workshop section",
      "Workshop mods" in app.headers
      and sum(e["group"] == "Workshop mods" for e in app._entries_cache) == 12
      and len(app.rows) == len(app._entries_cache))
check("rows show the mod's own name",
      app.rows["workshop:BetterBases"]["name_lbl"].cget("text") == "Better Bases")
states = {k: rows[f"workshop:{k}"]["state"] for k in (
    "BetterBases", "ShinyPals", "SimpleDPS", "Rates", "Unlisted", "NeedsLib")}
check("states only claim what the log shows", states == {
    "BetterBases": "working", "ShinyPals": "on", "SimpleDPS": "working",
    "Rates": "working", "Unlisted": "didn't start", "NeedsLib": "needs another mod"},
    states)
check("the winning pak says so; the losing one is a problem",
      "overrides 1 file also in MyLamball_P" in rows["workshop:ShinyPals"]["note"]
      and rows["pak:MyLamball_P"]["health"] == "problem"
      and "overrides 1 of its files" in rows["pak:MyLamball_P"]["note"],
      rows["pak:MyLamball_P"]["note"])
check("two items sharing a package name: one row, saying so",
      "Twin two has the same package name" in rows["workshop:TwinMod"]["note"],
      rows["workshop:TwinMod"]["note"])
check("a Workshop picture becomes its cover",
      str(rows["workshop:BetterBases"]["cover"]).endswith("thumbnail.png"))
app._set_row("workshop:Odd-Name", False)
check("a row the game's menu must switch can't be switched here", not app._pending())

app._set_row("workshop:ShinyPals", False)
app.apply()
pump(0.3)
check("switching one off edits the game's own list",
      "ShinyPals" not in palworkshop.read_settings(game)["active"])
app._set_row("workshop:Unlisted", False)
app._set_row("workshop:HalfDeployed", False)
app.apply()
app._set_row("workshop:HalfDeployed", True)
app.apply()
pump(0.3)
rows = {e["id"]: e for e in app._entries_cache}
check("switched on here: starts next launch",
      rows["workshop:HalfDeployed"]["state"] == "starts next launch",
      rows["workshop:HalfDeployed"]["state"])

palworkshop.set_global(game, False)
app.reload(full=True)
pump(0.3)


def banners():
    out = {}
    for b in app.warnbox.winfo_children():
        text = b.winfo_children()[-1].cget("text")
        out[text] = [w for w in b.winfo_children() if isinstance(w, tk.Button)]
    return out


hit = [(t, btns) for t, btns in banners().items() if t.startswith("Mods are switched off")]
check("every mod off: a banner, with a way to switch them on",
      hit and any(b.cget("text").strip() == "Switch on" for b in hit[0][1]), banners())
if hit:
    next(b for b in hit[0][1] if b.cget("text").strip() == "Switch on").invoke()
    pump(0.3)
check("which Palworld's own switch then is", palworkshop.read_settings(game)["global_on"])

gw = W.GetWindow(app, "ue4ss")
pump(0.3)
check("Install UE4SS is refused for the Workshop's",
      gw.rel is None and gw.go.cget("text") == "Close")
gw.destroy()
iw = palinfo.ModInfoWindow(app, rows["workshop:BetterBases"])
pump(0.3)
check("its info window", iw.title() == "Better Bases"
      and str(iw.page_btn.cget("state")) == "normal")
iw.destroy()


def texts(widget):
    out = []
    for c in widget.winfo_children():
        if isinstance(c, tk.Label):
            out.append(str(c.cget("text")))
        out += texts(c)
    return out


# A session ends; then one more mod is switched on, after it.
ue4ss_log(native / "UE4SS.log", when_offset=900, **RUN)
app.reload(full=True)
pump(0.2)
app._set_row("workshop:HalfDeployed", False)
app.apply()
app._set_row("workshop:HalfDeployed", True)
app.apply()
pump(0.2)
sw = W.SessionWindow(app, 5)
pump(0.2)
said = texts(sw)
check("the session summary lists Workshop mods that loaded, by name",
      any("Better Bases" in t for t in said), said)
check("but not one switched on since, as if it failed",
      not any("HalfDeployed" in t for t in said), said)
sw.destroy()

use_game(game2)
app.reload(full=True)
pump(0.3)
check("UE4SS twice: a banner of its own",
      any(t.startswith("UE4SS is set up twice") for t in banners()), list(banners()))

(srv / "Mods/PalModSettings.ini").write_text(
    "[PalModSettings]\nbGlobalEnableMod=True\nActiveModList=ServerOnly\n")
use_game(srv)
app.reload(full=True)
pump(0.3)
check("a server not told where its Workshop mods are",
      any("doesn't say which folder" in t for t in banners()), list(banners()))
G.filedialog.askdirectory = lambda **_k: str(root2)
app.workshop_folder()
pump(0.3)
check("advice for a server names its settings file, not a game menu",
      any("ActiveModList=UE4SS to its Mods\\PalModSettings.ini" in t
          for t in banners()), list(banners()))
check("Choose folder… tells it",
      palworkshop.read_settings(srv)["root"] == str(root2)
      and not any("doesn't say which folder" in t for t in banners()), list(banners()))

root.destroy()
check.finish(errors)
