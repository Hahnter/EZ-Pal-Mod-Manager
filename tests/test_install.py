"""Installing from archives, scanning, toggling, profiles, scaffolding, uninstall."""
import json
import shutil
import zipfile
from pathlib import Path

from helpers import Checker, fake_pak, make_game, sandbox, scan, use_game

SB = sandbox("install")
import palinstall, palmods, palregistry     # noqa: E402

check = Checker()
game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"
paks = game / "Pal/Content/Paks"


def zip_dir(src, out, prefix=""):
    with zipfile.ZipFile(out, "w") as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, prefix + p.relative_to(src).as_posix())
    return out


check.section("hybrid archive with the full game path")
src = SB / "src1"
mod = src / "Pal/Binaries/Win64/ue4ss/Mods/CoolMod"
(mod / "Scripts").mkdir(parents=True)
(mod / "Scripts/main.lua").write_text("print('hi')")
(mod / "config.json").write_text('{"Speed": 2}')
fake_pak(src / "Pal/Content/Paks/LogicMods/CoolModBP_P.pak", "../../../",
         ["Pal/Content/Mods/CoolMod/ModActor.uasset"])
(src / "__MACOSX").mkdir()
(src / "__MACOSX/junk").write_text("x")
(src / "notes.txt").write_text("hello")
arc = zip_dir(src, SB / "CoolMod-4821-1-2-0-1756000000.zip")

plan = palinstall.inspect(arc)
kinds = {c["name"]: c["kind"] for c in plan["components"]}
check("two components found", kinds == {"CoolMod": palinstall.UE4SS_MOD,
                                        "CoolModBP_P": palinstall.LOGIC_PAK}, kinds)
check("mac junk ignored, stray file reported", plan["skipped"] == ["notes.txt"], plan["skipped"])
check("no warnings", plan["warnings"] == [], plan["warnings"])
palinstall.apply(plan)
palinstall.discard(plan)
check("lua mod installed and enabled",
      (win64 / "ue4ss/Mods/CoolMod/Scripts/main.lua").is_file()
      and (win64 / "ue4ss/Mods/CoolMod/enabled.txt").is_file())
check("blueprint pak routed to LogicMods", (paks / "LogicMods/CoolModBP_P.pak").is_file())
meta = palregistry.get("CoolMod")
check("Nexus id/version read from the file name",
      meta.get("source") == "Nexus" and meta.get("id") == 4821 and meta.get("version") == "1.2.0",
      meta)

check.section("archive holding only a mod's insides")
src2 = SB / "src2"
(src2 / "Scripts").mkdir(parents=True)
(src2 / "Scripts/main.lua").write_text("print('bare')")
plan = palinstall.inspect(zip_dir(src2, SB / "BareMod.zip"))
check("name taken from the archive", [c["name"] for c in plan["components"]] == ["BareMod"])
palinstall.apply(plan)
palinstall.discard(plan)

check.section("bare .pak classified by its contents")
loose = fake_pak(SB / "TextureSwap.pak", "../../../", ["Pal/Content/Pal/Texture/T_Grass.uasset"])
plan = palinstall.inspect(loose)
check("content pak -> ~mods", [(c["name"], c["kind"]) for c in plan["components"]]
      == [("TextureSwap", palinstall.CONTENT_PAK)])
palinstall.apply(plan)
palinstall.discard(plan)

check.section("scan")
paths, data = scan(game)
ue = {m["name"]: m for m in data["ue4ss_mods"]}
pk = {p["name"]: p for p in data["pak_mods"]}
check("both UE4SS mods enabled", ue["CoolMod"]["enabled"] and ue["BareMod"]["enabled"])
check("config file found", len(ue["CoolMod"]["configs"]) == 1)
check("paks in the right folders, none misplaced",
      pk["CoolModBP_P"]["folder"] == "LogicMods" and pk["TextureSwap"]["folder"] == "~mods"
      and not any(p["misplaced"] for p in pk.values()))

check.section("toggle")
palmods.set_enabled("CoolMod", False)
check("disable renames enabled.txt", (win64 / "ue4ss/Mods/CoolMod/enabled.txt.disabled").is_file()
      and not (win64 / "ue4ss/Mods/CoolMod/enabled.txt").exists())
palmods.set_enabled("CoolMod", True)
check("enable restores it", (win64 / "ue4ss/Mods/CoolMod/enabled.txt").is_file())
palmods.set_enabled("TextureSwap", False)
check("pak disable renames to .pak.disabled", (paks / "~mods/TextureSwap.pak.disabled").is_file())
palmods.set_enabled("TextureSwap", True)
check("pak enable renames back", (paks / "~mods/TextureSwap.pak").is_file())

check.section("profiles")
palregistry.save_profile("test", ["CoolMod"], ["CoolMod", "BareMod", "TextureSwap"])
check("saved", palregistry.profile_names() == ["test"]
      and palregistry.load_profile("test")["enabled"] == ["CoolMod"])

check.section("scaffold + package")
dest = palinstall.scaffold("MyFirstMod")
check("scaffold writes main.lua, README, enabled.txt",
      sorted(p.name for p in dest.rglob("*") if p.is_file())
      == ["README.md", "enabled.txt", "main.lua"])
check("scaffold registered as your mod", palregistry.get("MyFirstMod").get("source") == "local")
out = palinstall.package(dest, out_dir=SB / "out")
with zipfile.ZipFile(out) as z:
    names = z.namelist()
check("package laid out under the game path",
      all(n.startswith("Pal/Binaries/Win64/ue4ss/Mods/MyFirstMod/") for n in names), names[:2])

check.section("uninstall")
removed, notes = palinstall.uninstall("CoolMod")
check("receipt removes exactly its files", len(removed) == 3 and notes == [], (len(removed), notes))
check("folder gone", not (win64 / "ue4ss/Mods/CoolMod").exists())
check("separate pak component untouched", (paks / "LogicMods/CoolModBP_P.pak").is_file())
palinstall.uninstall("CoolModBP_P")
check("pak removed", not (paks / "LogicMods/CoolModBP_P.pak").exists())

# A disabled mod renames enabled.txt; uninstall must still take everything.
plan = palinstall.inspect(arc)
palinstall.apply(plan)
palinstall.discard(plan)
palmods.set_enabled("CoolMod", False)
palinstall.uninstall("CoolMod")
check("disabled mod fully uninstalled", not (win64 / "ue4ss/Mods/CoolMod").exists())

check.section("update a switched-off PalSchema mod")
# Switching one off moves its folder to disabled-mods. An update installed a
# second copy in mods\ beside it, and then the mod could be switched neither
# on nor off. The copy that is there is the one to update.
schema = win64 / "ue4ss/Mods/PalSchema"
rates_on = schema / "mods/DropRates"
rates_off = schema / "disabled-mods/DropRates"


def drop_rates(version):
    """A PalSchema mod with a patch and a settings file, inspected. Version
    1.0 also has a file that later versions dropped."""
    out = SB / f"DropRates-{version}.zip"
    base = "Pal/Binaries/Win64/ue4ss/Mods/PalSchema/mods/DropRates/"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(base + "raw/rates.json", json.dumps({"Rate": version}))
        z.writestr(base + "config.json", json.dumps({"Speed": version}))
        if version == "1.0":
            z.writestr(base + "raw/old.json", "{}")
    return palinstall.inspect(out)


def read(path):
    return path.read_text() if path.is_file() else None


def install(plan, **kw):
    out = palinstall.apply(plan, **kw)
    palinstall.discard(plan)
    return out


install(drop_rates("1.0"))
palmods.set_enabled("DropRates", False)
(rates_off / "raw/rates.json").write_text('{"Rate": "mine"}')     # the user edits
(rates_off / "config.json").write_text('{"Speed": "mine"}')
plan = drop_rates("1.1")
clashes = palinstall.conflicts(plan)
check("the install window counts the files it replaces",
      len(clashes.get("DropRates", [])) == 2, clashes)
out = install(plan)
check("one copy, switched back on", rates_on.is_dir() and not rates_off.exists())
check("the new version is in place",
      read(rates_on / "raw/rates.json") == '{"Rate": "1.1"}')
check("your settings are kept, with the new ones beside them",
      read(rates_on / "config.json") == '{"Speed": "mine"}'
      and read(rates_on / "config.json.new") == '{"Speed": "1.1"}')
check("your edit to the patch is kept as a backup",
      read(rates_on / "raw/rates.json.pmm-bak") == '{"Rate": "mine"}')
check("the install says so",
      "backups kept" in out[0] and any("Kept your settings" in r for r in out), out)
check("it switches off and on again",
      "-> disabled" in palmods.set_enabled("DropRates", False)
      and "-> enabled" in palmods.set_enabled("DropRates", True))

# Left switched off, an update stays out of mods\.
palmods.set_enabled("DropRates", False)
out = install(drop_rates("1.2"), enable=False)
check("updated and still switched off, one copy",
      rates_off.is_dir() and not rates_on.exists()
      and read(rates_off / "raw/rates.json") == '{"Rate": "1.2"}')
check("the install says where it went", str(rates_off) in out[0], out)
rec = palregistry.receipt("DropRates")
check("the receipt names mods\\, as for a mod switched off later",
      rec["roots"] == [str(rates_on)]
      and all(Path(f).is_relative_to(rates_on) for f in rec["files"]), rec)
check("it switches on again", "-> enabled" in palmods.set_enabled("DropRates", True))
removed, notes = palinstall.uninstall("DropRates")
check("uninstall removes all of it, the file 1.0 had included",
      notes == [] and not rates_on.exists() and not rates_off.exists(),
      (removed, notes))

check.section("two copies of a PalSchema mod, left by an earlier version")
# What an update used to leave: the copy just installed in mods\, and the old
# one, perhaps with your edits, still in disabled-mods.
install(drop_rates("1.0"))
shutil.copytree(rates_on, rates_off)
(rates_off / "config.json").write_text('{"Speed": "mine"}')
out = install(drop_rates("1.1"))
check("the copy still as installed makes way for yours",
      rates_on.is_dir() and not rates_off.exists()
      and read(rates_on / "config.json") == '{"Speed": "mine"}', out)
check("which is updated as usual",
      read(rates_on / "raw/rates.json") == '{"Rate": "1.1"}')

# Changed since in both: only the user can say which to keep.
shutil.copytree(rates_on, rates_off)
(rates_on / "config.json").write_text('{"Speed": "also mine"}')
out = install(drop_rates("1.2"))
check("with changes in both, neither copy is touched",
      read(rates_on / "config.json") == '{"Speed": "also mine"}'
      and read(rates_off / "config.json") == '{"Speed": "mine"}'
      and read(rates_on / "raw/rates.json") == '{"Rate": "1.1"}')
check("and the install says why",
      len(out) == 1 and out[0].startswith("Skipped DropRates:"), out)
shutil.rmtree(rates_off)
palinstall.uninstall("DropRates")

check.finish()
