"""Nexus Mods: the API key, update checks, details, nxm:// links and downloads.

Nexus is faked throughout: every request goes to a stand-in that answers like
the real API, and records what it was sent. No test touches the network.
"""
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import zipfile
from pathlib import Path

from helpers import Checker, lua_mod, make_game, picture, sandbox, use_game

SB = sandbox("nexus")
import palhandoff, palinstall, palmedia, palnexus, palpaths, palregistry  # noqa: E402

check = Checker()
game = use_game(make_game(SB))
win64 = game / "Pal/Binaries/Win64"
KEY = "A" * 40 + "=="
NOW = int(time.time())


# --------------------------------------------------------------------------
# a stand-in for Nexus
# --------------------------------------------------------------------------
def zip_bytes(name, main="print(1)"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}/Scripts/main.lua", main)
    return buf.getvalue()


PIC = io.BytesIO()
picture(SB / "pic.png", size=(320, 180))
PIC = (SB / "pic.png").read_bytes()

HARVEST_V2 = zip_bytes("PalHarvest", "print(2)")
FILES = {5233: {"files": [
    {"file_id": 100, "name": "PalHarvest", "version": "2.1.0", "category_name": "OLD_VERSION",
     "is_primary": False, "size_kb": 1, "file_name": "PalHarvest-5233-2-1-0-1700000000.zip",
     "uploaded_timestamp": 1700000000},
    {"file_id": 200, "name": "PalHarvest", "version": "2.3.0", "category_name": "MAIN",
     "is_primary": True, "size_in_bytes": len(HARVEST_V2),
     "file_name": "PalHarvest-5233-2-3-0-1750000000.zip", "uploaded_timestamp": 1750000000},
], "file_updates": [{"old_file_id": 100, "new_file_id": 200}]}}
MODS = {5233: {"mod_id": 5233, "name": "Pal Harvest", "summary": "Harvest faster.",
               "description": "[b]Harvest[/b] faster.<br />[url=https://x.example]Docs[/url]",
               "picture_url": "https://staticdelivery.nexusmods.com/mods/6063/images/5233/1.png",
               "version": "2.3.0", "author": "Someone", "available": True,
               "updated_timestamp": 1750000000},
        4549: {"mod_id": 4549, "name": "Gone", "available": False, "version": ""}}
PAYLOADS = {"https://cf-files.nexus-cdn.com/5233/200/PalHarvest.zip": HARVEST_V2,
            MODS[5233]["picture_url"]: PIC}
FRESH = zip_bytes("PalFresh")
MODS[6000] = {"mod_id": 6000, "name": "Pal Fresh", "version": "1.4", "available": True}
FILES[6000] = {"files": [{"file_id": 300, "name": "PalFresh", "version": "1.4",
                          "category_name": "MAIN", "is_primary": True,
                          "size_in_bytes": len(FRESH), "file_name": "PalFresh-6000-1-4-1.zip",
                          "uploaded_timestamp": 1750000000}], "file_updates": []}
MD5S = {hashlib.md5(HARVEST_V2).hexdigest(): (5233, 200),
        hashlib.md5(FRESH).hexdigest(): (6000, 300)}
state = {"premium": True, "updated": [{"mod_id": 5233, "latest_file_update": NOW,
                                       "latest_mod_activity": NOW}],
         "fail": None}
calls = []


class Resp(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(b"{}"))


def fake_open(url, headers, api):
    palnexus.check_url(url, api=api)
    calls.append((url, dict(headers), api))
    if state["fail"]:
        raise http_error(url, state["fail"])
    if not api:
        if url not in PAYLOADS:
            raise http_error(url, 404)
        return Resp(PAYLOADS[url])
    if headers.get("apikey") != KEY:
        raise http_error(url, 401)
    path = url.split("/v1", 1)[1].split("?")[0]
    quota = {"x-rl-hourly-remaining": "480", "x-rl-daily-remaining": "19000"}

    def ok(obj):
        return Resp(json.dumps(obj).encode(), quota)
    if path == "/users/validate":
        return ok({"user_id": 7, "name": "tester", "is_premium": state["premium"],
                   "is_supporter": False})
    if path == "/games/palworld/mods/updated":
        return ok(state["updated"])
    if m := re.fullmatch(r"/games/palworld/mods/md5_search/(\w+)", path):
        hit = MD5S.get(m.group(1))
        if not hit:
            raise http_error(url, 404)
        mod, fid = hit
        f = next(f for f in FILES[mod]["files"] if f["file_id"] == fid)
        return ok([{"mod": MODS[mod], "file_details": f}])
    if m := re.fullmatch(r"/games/palworld/mods/(\d+)/files/(\d+)/download_link", path):
        if not state["premium"] and "key=" not in url:
            raise http_error(url, 403)
        return ok([{"URI": "https://cf-files.nexus-cdn.com/5233/200/PalHarvest.zip",
                    "name": "CDN", "short_name": "cdn"}])
    if m := re.fullmatch(r"/games/palworld/mods/(\d+)/files", path):
        return ok(FILES.get(int(m.group(1)), {"files": [], "file_updates": []}))
    if m := re.fullmatch(r"/games/palworld/mods/(\d+)", path):
        mod = MODS.get(int(m.group(1)))
        if mod is None:
            raise http_error(url, 404)
        return ok(mod)
    raise http_error(url, 404)


REAL_OPEN = palnexus._open
palnexus._open = fake_open


def api_calls():
    return [c for c in calls if c[2]]


# ==========================================================================
check.section("the version matches the release")
lua = (Path(__file__).resolve().parent.parent / "ingame/PalModManager/Scripts/main.lua")
m = re.search(r'local VERSION\s*=\s*"([^"]+)"', lua.read_text("utf8"))
check("palnexus names the same version Nexus is told about",
      m and m.group(1) == palnexus.APP_VERSION, (m and m.group(1), palnexus.APP_VERSION))

# ==========================================================================
check.section("nothing is asked of Nexus without a key")
check("not connected to start with", not palnexus.connected())
try:
    palnexus.mod_info(5233)
    check("a request without a key is refused", False)
except palnexus.NexusError as exc:
    check("a request without a key is refused", exc.code == "no-key", str(exc))
check("and nothing was sent", not calls)
check("key-shaped text is recognised", palnexus.looks_like_key(KEY))
for bad in ("", "short", "has spaces in it which keys never have at all", "x" * 500):
    check(f"not a key: {bad[:20]!r}", not palnexus.looks_like_key(bad))

# ==========================================================================
check.section("the key")
try:
    palnexus.validate("B" * 40)
    check("a wrong key is refused, in words", False)
except palnexus.NexusError as exc:
    check("a wrong key is refused, in words", exc.code == 401 and "refused" in str(exc))
acct = palnexus.validate(KEY)
check("a good key names its account", acct["name"] == "tester" and acct["premium"])
palnexus.set_key(KEY)
check("connected once the key is stored", palnexus.connected()
      and palnexus.get_key() == KEY)
settings_text = (palpaths.data_dir() / "settings.json").read_text() \
    if (palpaths.data_dir() / "settings.json").exists() else ""
check("the key is not in settings.json", KEY not in settings_text)
check("the key is not in the cache", KEY not in (palpaths.data_dir() / "nexus.json").read_text())
if os.name != "nt":
    mode = (palpaths.data_dir() / palnexus.KEY_FILE).stat().st_mode & 0o777
    check("the fallback key file is private to its owner", mode == 0o600, oct(mode))
check("requests carry the app's name",
      api_calls()[-1][1].get("Application-Name") == palnexus.APP_NAME
      and api_calls()[-1][1].get("Application-Version") == palnexus.APP_VERSION)
check("the rate limit is read from the answers",
      palnexus.quota["hourly"] == 480 and palnexus.quota["daily"] == 19000)

# ==========================================================================
check.section("the key only ever goes to api.nexusmods.com")
for url, api, ok in [("https://api.nexusmods.com/v1/users/validate", True, True),
                     ("http://api.nexusmods.com/v1/users/validate", True, False),
                     ("https://staticdelivery.nexusmods.com/x.png", True, False),
                     ("https://api.nexusmods.com.evil.example/v1", True, False),
                     ("https://cf-files.nexus-cdn.com/a.zip", False, True),
                     ("https://staticdelivery.nexusmods.com/x.png", False, True),
                     ("https://nexus-cdn.com.evil.example/a.zip", False, False),
                     ("https://evil.example/nexusmods.com/a.zip", False, False),
                     ("file:///C:/a.zip", False, False)]:
    try:
        palnexus.check_url(url, api=api)
        got = True
    except palnexus.NexusError:
        got = False
    check(f"{'api' if api else 'file'} {url} -> {'allowed' if ok else 'refused'}",
          got is ok)
import urllib.request                                    # noqa: E402
req = urllib.request.Request("https://api.nexusmods.com/v1/x", headers={"apikey": KEY})
for api, target in ((True, "https://cf-files.nexus-cdn.com/a.zip"),
                    (False, "https://evil.example/a.zip")):
    try:
        palnexus._CheckedRedirects(api).redirect_request(req, None, 302, "", {}, target)
        check(f"a redirect to {target} is refused", False)
    except palnexus.NexusError:
        check(f"a redirect to {target} is refused", True)

# ==========================================================================
check.section("comparing versions")
for latest, have, want in [("2.3.0", "2.1.0", True), ("2.1", "2.1.0", False),
                           ("v1.10", "1.9", True), ("1.0", "1.2", False),
                           ("1.2b", "1.2a", None), ("Beta", "Alpha", None),
                           ("", "1.0", None)]:
    check(f"{latest!r} vs {have!r} -> {want}", palnexus.newer(latest, have) is want)

# ==========================================================================
check.section("update checks")
src = SB / "src"
lua_mod(src, "PalHarvest", enabled=False)
old_zip = SB / "PalHarvest-5233-2-1-0-1700000000.zip"
with zipfile.ZipFile(old_zip, "w") as z:
    z.write(src / "PalHarvest/Scripts/main.lua", "PalHarvest/Scripts/main.lua")
plan = palinstall.inspect(old_zip)
palinstall.apply(plan)
palinstall.discard(plan)
palregistry.set_entry("Removed", source="Nexus", id=4549, version="1.0")
palregistry.set_entry("Local", source="local")
reg = palregistry.load_registry()
check("the Nexus mods are found in the registry",
      palnexus.nexus_mods(reg) == {5233: ["PalHarvest"], 4549: ["Removed"]})

calls.clear()
found = palnexus.check_updates(reg)
check("an update is found", "PalHarvest" in found
      and found["PalHarvest"]["version"] == "2.3.0"
      and found["PalHarvest"]["file"]["id"] == 200, found.get("PalHarvest"))
check("a removed mod is reported as removed", found.get("Removed", {}).get("removed"))
check("a local mod is left alone", "Local" not in found)
n_first = len(api_calls())
check("one request for what changed, then two per mod", n_first == 1 + 2 * 2, n_first)
check("the key went with every API request",
      all(h.get("apikey") == KEY for _u, h, _a in api_calls()))

calls.clear()
state["updated"] = []
palnexus.check_updates(reg)
check("a second check only asks what changed", len(api_calls()) == 0
      or all("/mods/updated" in u for u, _h, _a in api_calls()), api_calls())
check("the answer is remembered without asking",
      palnexus.updates(reg)["PalHarvest"]["version"] == "2.3.0")

calls.clear()
state["updated"] = [{"mod_id": 5233, "latest_file_update": int(time.time()) + 60,
                     "latest_mod_activity": 0}]
palnexus._save_cache(dict(palnexus._load_cache(), updated={}))
palnexus.check_updates(reg)
asked = [u for u, _h, _a in api_calls()]
check("a mod Nexus says changed is asked about again",
      any(u.endswith("/mods/5233") for u in asked)
      and not any(u.endswith("/mods/4549") for u in asked), asked)

check.section("deciding what counts as an update")
info, files = MODS[5233], palnexus.mod_files(5233)
tinfo = palnexus._trim_mod(info)
check("the same version isn't an update",
      palnexus.decide({"id": 5233, "version": "2.3.0"}, tinfo, files) is None)
check("installing the newest file isn't an update",
      palnexus.decide({"id": 5233, "version": "odd", "nexus_file_id": 200},
                      tinfo, files) is None)
check("an old file linked to its replacement is",
      palnexus.decide({"id": 5233, "version": "odd", "nexus_file_id": 100},
                      tinfo, files)["file"]["id"] == 200)
check("unreadable versions fall back to upload dates",
      palnexus.decide({"id": 5233, "version": "beta", "released": "2020-01-01"},
                      dict(tinfo, version="gamma"), files) is not None)
check("and a newer install isn't flagged by date",
      palnexus.decide({"id": 5233, "version": "beta", "released": "2030-01-01"},
                      dict(tinfo, version="gamma"), files) is None)
opt = {"files": files["files"] + [{"id": 150, "name": "No sound", "version": "1.0",
                                   "category": "OPTIONAL", "primary": False,
                                   "size": 1, "size_exact": True, "file_name": "",
                                   "uploaded": 1600000000, "description": ""}],
       "updates": files["updates"]}
check("a current optional file isn't out of date because the main one moved on",
      palnexus.decide({"id": 5233, "version": "1.0", "nexus_file_id": 150},
                      tinfo, opt) is None)
check("archived files are never offered",
      palnexus.newest_file([{"id": 1, "category": "ARCHIVED", "primary": False,
                             "uploaded": 9}]) is None)

# ==========================================================================
check.section("errors in words")
for code, words in ((429, "limit"), (500, "isn't answering"), (404, "removed")):
    state["fail"] = code
    try:
        palnexus._api("/games/palworld/mods/5233")
        check(f"{code} -> a message", False)
    except palnexus.NexusError as exc:
        check(f"{code} -> a message", exc.code == code and words in str(exc), str(exc))
state["fail"] = None
os.environ["PMM_NO_NETWORK"] = "1"
try:
    REAL_OPEN("https://api.nexusmods.com/v1/x", {}, True)
    check("PMM_NO_NETWORK stops every request", False)
except palnexus.NexusError as exc:
    check("PMM_NO_NETWORK stops every request", "PMM_NO_NETWORK" in str(exc))
finally:
    os.environ.pop("PMM_NO_NETWORK")

# ==========================================================================
check.section("descriptions and pictures")
text = palnexus.bbcode_to_text(
    "[center][size=5][b]Title[/b][/size][/center]<br />Line &amp; more<br /><br /><br />"
    "[url=https://a.example]the docs[/url] [url]https://b.example[/url]"
    "[list][*]one[*]two[/list][img]https://i.example/x.png[/img][line]"
    "[youtube]abc123[/youtube][spoiler]hidden[/spoiler]")
check("formatting tags are dropped", "[" not in text and "<" not in text, text)
check("line breaks survive, without runs of blank lines",
      "Title\nLine & more\n\nthe docs" in text, text)
check("links keep their address", "the docs (https://a.example)" in text
      and "https://b.example" in text)
check("lists become bullets", "• one" in text and "• two" in text)
check("pictures are dropped", "i.example" not in text)
check("videos become links", "https://youtu.be/abc123" in text)
details = palnexus.fetch_details(5233)
check("details bring the summary and description",
      details["description"].startswith("Harvest faster.")
      and "Docs (https://x.example)" in details["description"], details["description"])
check("and the picture", details["picture"] == PIC)
got = palnexus.apply_details("PalHarvest", details)
media = palmedia.info("PalHarvest")
check("stored as the mod's description and cover",
      set(got) == {"description", "picture"} and media["cover"]
      and media["description"].startswith("Harvest"), got)
check("the author is recorded", palregistry.get("PalHarvest").get("author") == "Someone")
palmedia.set_description("PalHarvest", "my own words")
check("what you wrote isn't replaced unasked",
      palnexus.apply_details("PalHarvest", details) == []
      and palmedia.info("PalHarvest")["description"] == "my own words")
calls.clear()
try:
    palnexus.fetch_picture("https://evil.example/x.png")
    check("pictures only come from Nexus", False)
except palnexus.NexusError:
    check("pictures only come from Nexus", not calls)
check("picture requests carry no key",
      all("apikey" not in h for u, h, a in calls if not a))

# ==========================================================================
check.section("recognising a renamed download")
renamed = SB / "harvest (1).zip"
renamed.write_bytes(HARVEST_V2)
fields = palnexus.identify(renamed)
check("found by checksum", fields and fields["id"] == 5233
      and fields["nexus_file_id"] == 200 and fields["version"] == "2.3.0", fields)
other = SB / "other.zip"
other.write_bytes(zip_bytes("Other"))
check("an unknown file is just unknown", palnexus.identify(other) is None)

# ==========================================================================
check.section("nxm:// links")
link = palnexus.parse_nxm("nxm://palworld/mods/5233/files/200?key=abc-D_1"
                          f"&expires={NOW + 600}&user_id=7")
check("a link names the mod, file and key",
      link["mod_id"] == 5233 and link["file_id"] == 200 and link["key"] == "abc-D_1"
      and link["user_id"] == 7)
check("upper-case scheme works",
      palnexus.parse_nxm("NXM://Palworld/mods/1/files/2")["file_id"] == 2)
for bad, why in (("nxm://skyrimspecialedition/mods/1/files/2", "not Palworld"),
                 ("nxm://palworld/mods/x/files/2", "isn't a Nexus"),
                 ("https://www.nexusmods.com/palworld/mods/1", "isn't a Nexus"),
                 ("nxm://palworld/mods/1/files/2?key=a%22b", "damaged")):
    try:
        palnexus.parse_nxm(bad)
        check(f"refused: {bad}", False)
    except palnexus.NexusError as exc:
        check(f"refused: {bad}", why in str(exc), str(exc))
check("an old link is expired",
      palnexus.link_expired({"expires": NOW - 1}) and not palnexus.link_expired(link))

# ==========================================================================
check.section("downloads")
into = SB / "dl"
calls.clear()
path, f = palnexus.download(5233, 200, into)
check("a Premium member can download directly", path.read_bytes() == HARVEST_V2
      and path.name == "PalHarvest-5233-2-3-0-1750000000.zip", path)
check("no partial file is left", not list(into.glob("*.part")))
check("the file server was sent no key",
      all("apikey" not in h for u, h, a in calls if not a))

state["premium"] = False
try:
    palnexus.download(5233, 200, SB / "dl-free")
    check("a free account without a link is told how", False)
except palnexus.NexusError as exc:
    check("a free account without a link is told how",
          exc.code == 403 and "Mod Manager Download" in str(exc))
calls.clear()
path, _ = palnexus.download(5233, 200, SB / "dl-free", link=link)
check("with a Mod Manager Download link, anyone can",
      path.is_file() and any("key=abc-D_1" in u and f"expires={NOW + 600}" in u
                             for u, _h, _a in calls), [u for u, _h, _a in calls])
state["premium"] = True
try:
    palnexus.download(5233, 200, SB / "dl-old", link=dict(link, expires=NOW - 5))
    check("an expired link is refused before downloading", False)
except palnexus.NexusError as exc:
    check("an expired link is refused before downloading", exc.code == 410)

tampered = HARVEST_V2[:-1] + b"X"
PAYLOADS["https://cf-files.nexus-cdn.com/5233/200/PalHarvest.zip"] = tampered
try:
    palnexus.download(5233, 200, SB / "dl-bad")
    check("a download Nexus doesn't recognise is refused", False)
except palnexus.NexusError as exc:
    check("a download Nexus doesn't recognise is refused",
          "checksum" in str(exc) and not any((SB / "dl-bad").iterdir()), str(exc))
PAYLOADS["https://cf-files.nexus-cdn.com/5233/200/PalHarvest.zip"] = HARVEST_V2 + b"extra"
try:
    palnexus.download(5233, 200, SB / "dl-big")
    check("a download bigger than listed is stopped", False)
except palnexus.NexusError as exc:
    check("a download bigger than listed is stopped", "bigger" in str(exc), str(exc))
PAYLOADS["https://cf-files.nexus-cdn.com/5233/200/PalHarvest.zip"] = HARVEST_V2
for name, want in (("..\\..\\x.zip", "x.zip"), ("../../y.zip", "y.zip"),
                   ('a<b>:"c".zip', "a_b_c_.zip"), ("", "download.zip")):
    check(f"file name {name!r} -> {want}", palnexus.safe_name(name) == want,
          palnexus.safe_name(name))

# ==========================================================================
check.section("handling Mod Manager Download links (Windows registry, faked)")


class FakeReg:
    HKEY_CURRENT_USER, HKEY_CLASSES_ROOT, REG_SZ = "HKCU", "HKCR", 1

    def __init__(self):
        self.keys = {}

    def _path(self, root, sub):
        if root == "HKCR":
            root, sub = "HKCU", "Software\\Classes\\" + sub
        return (root, sub.lower())

    class _Key:
        def __init__(self, reg, path):
            self.reg, self.path = reg, path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def CreateKey(self, root, sub):
        p = self._path(root, sub)
        self.keys.setdefault(p, {})
        return self._Key(self, p)

    def OpenKey(self, root, sub):
        p = self._path(root, sub)
        if p not in self.keys:
            raise FileNotFoundError(sub)
        return self._Key(self, p)

    def SetValueEx(self, key, name, _r, _t, value):
        self.keys[key.path][name] = value

    def QueryValueEx(self, key, name):
        if name not in self.keys[key.path]:
            raise FileNotFoundError(name)
        return self.keys[key.path][name], 1

    def DeleteKey(self, root, sub):
        if self.keys.pop(self._path(root, sub), None) is None:
            raise FileNotFoundError(sub)


reg_fake = FakeReg()
palnexus._winreg = reg_fake
vortex = '"C:\\Program Files\\Black Tree Gaming Ltd\\Vortex\\Vortex.exe" -d "%1"'
with reg_fake.CreateKey("HKCU", palnexus.COMMAND_KEY) as k:
    reg_fake.SetValueEx(k, "", 0, 1, vortex)
st = palnexus.handler_status()
check("the current owner is recognised", st["owner"] == "Vortex" and not st["ours"])
was = palnexus.register_handler()
st = palnexus.handler_status()
check("turning it on points links here", st["ours"]
      and st["command"] == palnexus.launch_command() and was == "Vortex")
check("and remembers what it replaced",
      palpaths.load_settings()["nxm_previous"] == vortex)
palnexus.register_handler()
check("turning it on twice keeps the original",
      palpaths.load_settings()["nxm_previous"] == vortex)
check("the link is passed on as one argument", st["command"].endswith('"%1"'))
with reg_fake.CreateKey("HKCU", palnexus.COMMAND_KEY) as k:
    reg_fake.SetValueEx(k, "", 0, 1, '"D:\\old place\\EZPalModManager.exe" "%1"')
check("a moved exe is noticed", palnexus.handler_status()["stale"])
check("and fixed on launch", palnexus.refresh_handler()
      and not palnexus.handler_status()["stale"])
back = palnexus.unregister_handler()
check("turning it off hands links back", back == "Vortex"
      and palnexus.handler_status()["command"] == vortex)
check("and doesn't steal them back on launch", not palnexus.refresh_handler())
reg_fake.keys.clear()
palnexus.register_handler()
palnexus.unregister_handler()
check("with nothing before, turning it off removes the registration",
      palnexus.handler_status()["command"] is None)
palnexus.register_handler()
with reg_fake.CreateKey("HKCU", palnexus.COMMAND_KEY) as k:
    reg_fake.SetValueEx(k, "", 0, 1, vortex)
palnexus.unregister_handler()
check("turning it off after another app took over leaves that app alone",
      palnexus.handler_status()["command"] == vortex)

# ==========================================================================
check.section("handing work to a copy that is already open")
check("nothing else running", not palhandoff.other_running())
palhandoff.heartbeat()
check("our own heartbeat doesn't count", not palhandoff.other_running())
beat = palpaths.data_dir() / palhandoff.BEAT_FILE
beat.write_text(json.dumps({"pid": -1, "beat": time.time()}))
check("another copy's heartbeat does", palhandoff.other_running())
beat.write_text(json.dumps({"pid": -1, "beat": time.time() - 60}))
check("a stale heartbeat doesn't", not palhandoff.other_running())
palhandoff.send(["nxm://palworld/mods/5233/files/200", str(old_zip)])
palhandoff.send(["second"])
got = palhandoff.receive()
check("items arrive in order", got == ["nxm://palworld/mods/5233/files/200",
                                       str(old_zip), "second"], got)
check("and only once", palhandoff.receive() == [])

# ==========================================================================
check.section("the app")
from helpers import hidden_tk, silence_dialogs               # noqa: E402

root, pump, errors = hidden_tk()
import palinfo, palsafety                                    # noqa: E402
import palmods_gui as G                                      # noqa: E402
import palnexuswin as NW                                     # noqa: E402
silence_dialogs(G, NW, palinfo)
palsafety.game_running = lambda game: False
palregistry.forget("Removed")
palmedia.set_description("PalHarvest", "")
opened = []
G.open_link = NW.open_link = lambda url: opened.append(url)

calls.clear()
state["updated"] = [{"mod_id": 5233, "latest_file_update": int(time.time()) + 60,
                     "latest_mod_activity": 0}]
app = G.App(root)
pump(2.6)
banners = " ".join(w.cget("text") for b in app.warnbox.winfo_children()
                   for w in b.winfo_children() if isinstance(w, G.tk.Label))
check("the update check runs when the app opens", any(a for _u, _h, a in calls))
check("a banner says what can be updated",
      "newer version on Nexus: PalHarvest" in banners, banners)
row = app.rows["PalHarvest"]["entry"]
check("the row carries the update", row["update"] and row["update"]["version"] == "2.3.0")

upd = NW.UpdatesWindow(app)
pump(0.2)
check("the updates window lists it", "1 mod with a newer version" in upd.subtitle.cget("text"),
      upd.subtitle.cget("text"))
upd.destroy()

nw = NW.NexusWindow(app)
pump(0.3)
texts = " ".join(w.cget("text") for w in nw.body.winfo_children()
                 if isinstance(w, G.tk.Label))
check("the Nexus window shows the account", "Connected as tester" in texts, texts)
nw.destroy()

check.section("updating from the app")
app.update_mod("PalHarvest")
pump(0.6)
dl = next((w for w in root.winfo_children() if isinstance(w, NW.DownloadWindow)), None)
check("Premium: Update opens the download window", dl is not None)
check("it names the file first", dl and dl.file and dl.file["id"] == 200
      and str(dl.go.cget("state")) == "normal")
dl._start()
pump(0.8)
inst = next((w for w in root.winfo_children() if isinstance(w, G.InstallWindow)), None)
check("then the usual install window opens", inst is not None)
check("linked to the mod without being asked",
      inst and inst.link_var.get() == palnexus.MOD_PAGE.format(id=5233)
      and "downloaded from Nexus" in inst.link_note.cget("text"),
      inst and inst.link_note.cget("text"))
inst._install()
pump(0.8)
e = palregistry.get("PalHarvest")
check("installed with the Nexus file recorded",
      e.get("version") == "2.3.0" and e.get("nexus_file_id") == 200, e)
check("and it's no longer listed as out of date",
      "PalHarvest" not in app._nexus_updates, app._nexus_updates)
check("its description was filled in from Nexus",
      palmedia.info("PalHarvest")["description"].startswith("Harvest"),
      palmedia.info("PalHarvest")["description"][:40])

state["premium"] = False
palnexus.validate()
palnexus._save_cache(dict(palnexus._load_cache(),
                          mods={}, files={}))      # forget the answers
palregistry.set_entry("PalHarvest", version="2.1.0", nexus_file_id=100)
app.check_nexus_updates(force=True)
pump(1.0)
opened.clear()
app.update_mod("PalHarvest")
check("free account: Update opens the Files tab",
      opened == [palnexus.FILES_PAGE.format(id=5233)], opened)

check.section("a Mod Manager Download link")
palhandoff.send([f"nxm://palworld/mods/5233/files/200?key=abc&expires={NOW + 600}"])
app._poll(once=False)
pump(0.6)
dl = next((w for w in root.winfo_children() if isinstance(w, NW.DownloadWindow)), None)
check("a link sent from a second copy opens the download window",
      dl is not None and dl.link and dl.link["key"] == "abc")
if dl:
    dl.destroy()
app.open_nxm("nxm://skyrim/mods/1/files/2")
check("a link for another game is refused with a message",
      any("not Palworld" in str(a) for k, a in G.messagebox.calls if k == "showerror"))

check.section("a renamed download is recognised on install")
fresh = SB / "fresh download.zip"
fresh.write_bytes(FRESH)
app.queue_installs([str(fresh)])
pump(1.0)
inst = next((w for w in root.winfo_children() if isinstance(w, G.InstallWindow)), None)
check("the install window links it by checksum",
      inst and inst.link_var.get() == palnexus.MOD_PAGE.format(id=6000)
      and "checksum" in inst.link_note.cget("text"),
      inst and (inst.link_var.get(), inst.link_note.cget("text")))
if inst:
    inst._install()
    pump(0.6)
e = palregistry.get("PalFresh")
check("and records which Nexus file it is",
      e.get("source") == "Nexus" and e.get("id") == 6000
      and e.get("nexus_file_id") == 300 and e.get("version") == "1.4", e)

check.section("disconnecting")
palnexus.clear_key()
app.nexus_changed()
pump(0.2)
check("no key left", not palnexus.connected()
      and not (palpaths.data_dir() / palnexus.KEY_FILE).exists())
check("no update badges without a connection", not app._nexus_updates)
calls.clear()
app.check_nexus_updates(force=True)
pump(0.3)
check("and nothing more is asked", not calls)

root.destroy()
check.finish(errors)
