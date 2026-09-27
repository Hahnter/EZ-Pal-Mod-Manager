"""Installing from archives, scanning, toggling, profiles, scaffolding, uninstall."""
import zipfile

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

check.finish()
