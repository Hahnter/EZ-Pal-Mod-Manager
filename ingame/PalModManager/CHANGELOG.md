# Changelog

## Unreleased

**Fixes**

- Updating a PalSchema mod while it was switched off put the new version in
  `PalSchema\mods` and left the old one in `PalSchema\disabled-mods`. With a
  copy in both folders, the mod could no longer be switched on or off. The
  update now replaces the copy you have and keeps your settings in it, the
  same way as for other mods.
- PalSchema mods now follow *Turn on after installing*. With it unticked, the
  mod is installed switched off; before, it was switched on either way. With
  it ticked (the default), updating a switched-off mod turns it back on, as it
  already did for UE4SS mods.
- If an earlier version already left two copies, installing the mod again
  removes the copy that is still exactly as it was installed and updates the
  other one. If both copies have changes, the install skips that mod and asks
  you to delete one of them.

## 1.0.0 - first public release

**It can set up UE4SS and PalSchema for you**

- **Install UE4SS** fetches the current Palworld build from Okaetsu's own
  GitHub releases and puts it in `Pal\Binaries\Win64`. It appears on the
  banner whenever UE4SS is missing, half-installed, or the flat official
  build that current Palworld mods don't load under, and under
  **… → Tools**. Nothing is downloaded until you read what it is and press
  the button; the window names the release, the file, its size and where it
  comes from first.
- Whatever UE4SS was there is kept as `ue4ss.pmm-old-<date>` rather than
  deleted, so you can put it back. Your mods and their settings are in
  `ue4ss\Mods` and are not touched. **Clean up leftovers** lists the old copy
  when you no longer want it.
- **Install PalSchema** does the same for PalSchema, which installs like any
  other mod. A banner offers it when you have PalSchema mods but not
  PalSchema.
- If GitHub can't be reached, the window says so and offers the release page
  so you can do it by hand. Downloads are checked for length and for actually
  being a zip; a UE4SS zip without `ue4ss\UE4SS.dll` in it is refused.
- This is the only part of the app that uses the network, it only ever talks
  to those two repositories, and it only runs when you press the button.

**Updating a mod keeps your settings**

- Install a newer version of a mod you've configured and your settings file
  stays as you left it. The version from the new download lands beside it as
  `<name>.new` so you can see what changed, and the install says which files
  were kept.
- A settings file you never edited is simply replaced, as before.
- The app now records what a mod shipped, which is how it tells your edits
  from the mod's own defaults.

**Warnings**

- A pak that replaces one of the game's core blueprints (the player
  character, controller, state, game mode) is flagged. These are the mods
  most likely to break or crash after a game patch, and two of them can
  never work together.

**Security hardening**

- Links open only if they are web pages. Before, a stored mod link was
  handed straight to Windows, so a program path or `file://` address in a
  shared modlist or registry would have run instead of opening a browser.
- Archive extraction now checks paths properly (a folder named `Win64evil`
  no longer passes as being inside `Win64`), refuses zip bombs and archives
  over 8 GB or 20,000 files, and stops a file that unpacks larger than its
  header claims. Whatever 7-Zip unpacks is checked afterwards, links included.
- Downloads are limited to GitHub over HTTPS, every redirect is checked,
  the file is verified against GitHub's published SHA-256, and a download
  larger than promised is stopped part way.
- Pictures added to a mod no longer keep their JPEG comment. Everything else
  (EXIF, GPS, XMP, C2PA, PNG text such as AI prompts) was already dropped by
  the re-encode; a test now proves all of it. Pictures claiming more than 64
  megapixels are refused.
- New `test_hardening.py` covers all of the above and fails if any tracked
  file ever contains invisible Unicode characters.
- README has a *Privacy and security* section.

**Fixes**

- Uninstalling a mod that had been updated left `enabled.txt` behind, and
  with it the mod's folder. The receipt now carries files forward across an
  update.
- Long text in dialogs ran off the right edge instead of wrapping.

## 0.8.0

**A look of its own**

- New palette: warm charcoal surfaces and one amber accent, reserved for Play,
  switches that are on, and the selected tab. Replaces the generic blue-grey
  dark theme.
- New app mark and window icon, an amber tile holding a switch. The previous
  icon, a sphere with a switch across it, looked too much like a Poké Ball.
- A header band like a game launcher: the mark, the title, one status line
  with a check or warning icon, and Install and Play buttons.
- Mod rows are separated by hairline dividers instead of sitting on cards.
  Each shows the switch, a thumbnail, the name, a quiet second line (source
  link and version), and the state as an icon plus a word. Rows that need
  attention get a warm tint.
- Icons are drawn by the app at 4× and scaled down, so they're sharp and
  consistent. They replace the emoji and symbols (  ＋ … ↗ ✕) used before.
  No icon files ship with the app.
- Titles and section headings use Bahnschrift, which ships with Windows 10 and
  11, so nothing is downloaded or bundled. Section headings are in sentence
  case instead of spaced capitals.
- Unapplied changes draw the switch as an amber outline instead of a purple
  track. Apply changes and Undo only appear in the footer when there's
  something to apply, instead of sitting there disabled.
- Tabs are underlined, and the Problems tab shows its count.
- A slim scrollbar drawn to match the theme replaces the bright white Windows
  one, in the list and in the UE4SS log.
- Every dialog gets the dark title bar and the app icon.

**Wording**

- No more "mod(s)" and "file(s)": counts read "1 mod" and "3 files". A test
  keeps it that way.
- Fewer em dashes; messages are short sentences ("Installed 2 mods. They load
  the next time you play.").

**Fixes**

- In Save backups, Restore was squeezed to "sto" by the text beside it.
- The SaveGames path in Save backups no longer wraps mid-folder.
- The test runner no longer crashes when a failure message contains a
  character the Windows console can't print.

## 0.7.0, unreleased

**Fixed: mods switched on in mods.txt showed as off**

- UE4SS keeps its list of mods to start in `mods.txt` or `mods.json`, and
  Palworld's UE4SS reads `mods.txt`. The app let `mods.json` override it, so a
  mod on in one and off in the other was shown as off while UE4SS started it
  every launch, and switching it off in the app changed nothing. Found on a
  real install with NoMoreHoldButton.
- The app now goes by the list the UE4SS log says it read (`mods.txt` when
  there's no log yet), marks mods where the two lists disagree, and toggles
  update both files. Rewriting `mods.txt` keeps its comments and its Windows
  line endings.

**Simpler main window**

- The line under the title is plain: which install, whether UE4SS is ready,
  and when you last played. Build numbers and UE4SS layouts only appear in the
  banners that need them.
- Rows show just the switch, the name, a link to the mod's page (when there is
  one) and its state. Type, folder and version moved to the mod's info window,
  and the "source unknown" tag is gone.
- Plain states: *working*, *didn't start*, *error*, *off*, *on*, *wrong
  folder*, *worked before update*.
- "UE4SS mods" is now "Script mods (UE4SS)".
- The … menu is down to seven entries: Refresh, Profiles, Save backups, Share
  modlist, Tools, Open folder and Switch install. Conflicts, the UE4SS log, load
  order, cleanup, the UE4SS check and New mod are under Tools. Profiles moved
  into the menu from the header.
- Unapplied changes are explained in the status bar ("1 change not applied
  yet (the purple switches), press Apply changes"), and Revert is now Undo.
- The Repair banner says what's wrong in plain words; the technical details
  stay in the Repair dialog.
- If Palworld has been uninstalled but its folder (mods, UE4SS) remains, the
  setup window says so, instead of just "not found".

## 0.6.1, unreleased

**Linking downloaded zips to their mod pages**

- The install window has an optional *Mod page* field. It fills itself in for
  Nexus downloads, from the file name. For CurseForge, *Paste link* takes the
  address you copied, and the window says when your clipboard already holds a
  Nexus or CurseForge link.
- The link is applied to every part of a hybrid mod, and the install summary
  confirms it ("Linked to its CurseForge page").
- Updating a mod from a newer zip prefills the link you added last time.
- *Install mod* accepts several files at once, as does dropping them on the
  exe. They open one at a time, without a dialog between each.
- CLI: `install <zip> --link URL`.
- Nothing is fetched from either site; only the address itself is read.

**Fixes**

- Updating a CurseForge-linked mod from a zip reset its source to "manual".
  A non-Nexus file name no longer overwrites a source you set.

## 0.6.0, unreleased

**Descriptions and pictures**

- Every mod has an info window with a picture gallery, a cover, a description,
  and its source details. Click a mod's name or its thumbnail to open it; the
  old Details window is gone.
- Add pictures by pasting a copied image, including with Ctrl+V; by picking
  files (PNG, JPEG, WebP, GIF or BMP); or with one click from images already in
  the mod's folder. Pictures are stored upright, at most 1920 px, and the same
  picture is only stored once.
- Paste a description copied from the mod page, or write your own. When a mod
  ships a README, the window offers it.
- Installing from a download keeps its README as the description and its
  pictures as the gallery, unless you've already written a description.
- Pasting a Nexus or CurseForge page address fills in the source and mod ID
  from the link alone.
- Mods with a picture get a thumbnail in the main list. Search matches
  description text.
- *Package for sharing* includes your description (`DESCRIPTION.md`) and
  pictures (`images/`, with the cover as `preview`). Installing that package
  brings them back, and the description you wrote beats a stock README.
- Uninstalling a mod moves its pictures to the Recycle Bin.
- No page is fetched from Nexus or CurseForge: both sites' terms forbid it.
  Pillow is now bundled, for image support.

## 0.5.0, unreleased

**Game-update safety**

- **Play** starts the game or server through Steam. When it closes the app
  rescans and opens a summary of the session: loaded, failed (with reasons),
  on-but-never-started. Sessions launched outside the app are noticed as well.
- **Save backups**: `SaveGames` is copied automatically the first time a mod
  setup is launched, with one-click restore that backs up the current saves
  first. Manual backups from **… → Save backups** or `palmods.py backup`.
- **Patch tracking**: the Steam build each mod last loaded on is remembered.
  A patch raises a banner listing mods not yet seen working on the new build;
  after playing, mods that worked before the patch and not after are named.
- **File conflicts**: overlapping assets between paks are found from their
  indexes, with the winner shown, certain when only one is a `_P` patch pak,
  *likely* when load order decides. Content paks without `_P` are flagged.
- **Hotkeys**: keys are read from `RegisterKeyBind` calls, `config.lua` tables
  and `[keys]`-style ini sections; clashes between enabled mods are flagged.
  On this install that found BaseDoorControl and PalInsightSettings both on F6
  and F7.

**UE4SS detection**

- The app no longer refuses to start when UE4SS isn't installed, pak mods
  don't need it. A banner explains what's missing.
- Detects a broken install (no `dwmapi.dll`), two installs at once, the flat
  3.0.1 layout, and a missing `MemberVariableLayout.ini`.
- `doctor` no longer reports "experimental layout missing" as a repairable
  fault on installs that simply use a different UE4SS.
- Installing a UE4SS or blueprint mod into a game without UE4SS warns first.

**Tools**

- Live **UE4SS log** viewer with Mods / Problems filters that ignore the
  startup offset dump.
- **Blueprint load order** editor for BPModLoaderMod's `load_order.txt`.
- **Clean up leftovers**: orphaned configs and IoStore files, empty mod
  folders, parked UE4SS copies, removed to the Recycle Bin.
- **Share modlist**: copy as text, export a file, compare against a friend's
  and stage the changes to match.
- **PalSchema mods** are listed and toggled.
- **Dedicated servers** are detected and can be switched to alongside the
  game; **… → Switch install**.
- CLI: `check`, `backup list|create|restore`, `export`.

**Fixes**

- Mouse-wheel scrolling only worked with the pointer over gaps between rows.
- Hotkey scanning results are cached per file; rescans went from ~130 ms to
  ~15 ms for that step.

## 0.4.0, unreleased

**The game folder is no longer hard-coded**

- Palworld is found automatically: every Steam library (via `libraryfolders.vdf`
  and the appid), Xbox Game Pass installs under `XboxGames\Palworld\Content`,
  and the usual loose locations. Pick between them, or browse, from
  **… → Change Palworld folder**.
- Browsing to the wrong-but-nearby folder now works: Win64, Paks, `steamapps`
  and the Steam library root all resolve to the install they belong to.
- Settings, registry, install receipts and profiles moved to
  `%LOCALAPPDATA%\PalModManager`. They used to be written next to the program,
  which in the released one-file build is a temp folder deleted on exit, so
  nothing the packaged app recorded actually survived. An existing
  `registry.json` is imported on first run.

**Installing mods**

- **Install mod** takes a `.zip`, `.7z`, `.rar`, a folder, or a bare `.pak`,
  works out what is inside, and shows where each piece will go before writing
  anything. One archive can hold several mods; each is listed and can be left
  out.
- Handles the layouts mods actually ship in: the mod folder itself, just its
  insides, or the full `Pal/Binaries/Win64/ue4ss/Mods/…` path. Paks are routed
  by reading their index (blueprint mods to `LogicMods`, content to `~mods`) 
  and the author's own folder choice wins when the archive states one.
  IoStore paks keep their `.ucas`/`.utoc` companions.
- Files that already exist are backed up as `.pmm-bak` rather than clobbered,
  and archive members that would escape the target folder are refused.
- Dropping a mod archive on the .exe, or opening one with it, goes straight to
  the installer.

**Where a mod came from**

- Every mod carries a source badge, **Nexus 3915**, **CurseForge**, **your
  mod**, which links to its page.
- Nexus fills itself in: their downloads encode the mod id, version and release
  date in the filename, so anything installed from one is recorded without
  being typed in.
- **Details…** on any mod to set or correct the source, id, version, page and
  notes by hand.

**Making and removing mods**

- **New mod** scaffolds a working UE4SS Lua mod, `Scripts/main.lua`, a README,
  and the `enabled.txt` UE4SS needs, switched on and ready to edit.
- **Package for sharing** zips one of your own mods laid out to extract
  straight into a Palworld install, the way Nexus mods are shipped.
- **Uninstall** deletes exactly the files an install wrote, tracked per mod.
  For anything installed before this app, it falls back to removing the mod's
  own folder or pak, and says so first.

**Turning mods on and off**

- Filter tabs (All / Working / Problems / Off) and a search box that also
  matches the source.
- **all on** / **all off** per group, applying to whatever the filter is
  showing.
- **Profiles**: save the current set of enabled mods under a name and restore
  it later. Loading one stages the changes for review rather than writing
  immediately.
- Staged changes show as a purple switch, can be reverted in one click, and now
  survive searching, filtering and a background rescan, they used to be
  silently discarded.
- A mod switched off after a session it loaded in reads as **off**, with a note,
  instead of claiming to be loaded.

**Fixes and polish**

- The Install, Setup, Details and Configure windows drew an empty body: the
  scroll container was packed incorrectly, so nothing inside it was ever shown.
- Those windows' buttons could be pushed off the bottom of the window.
- Checkboxes in the installer drew their tick in black on a dark background,
  so a ticked box looked empty.
- Searching no longer rebuilds every row, it hides and shows the ones already
  built, cutting a keystroke from ~360 ms to ~20 ms.
- The UE4SS conflict check hashes a DLL and was running on every repaint; it
  now runs only on a real refresh.
- Each mod's config files are found once per scan instead of once per row per
  repaint.
- Per-monitor DPI awareness and a dark title bar.
- CLI gained `path`, `install`, `uninstall`, `new`, `source` and `profile`.

## 0.3.1, unreleased

- Fixed content mods being wrongly reported as "wrong folder → LogicMods".
  Any pak with a path containing `Mods/` was treated as a blueprint mod, but
  plenty of content mods namespace their assets under `/Game/Mods/<author>/…`.
  Detection now requires an actual `ModActor` asset, the thing BPModLoaderMod
  looks for, or a mount point of `Content/Mods/<Name>/`. The old rule told
  people to move working mods out of the folder they belonged in.

## 0.3.0, unreleased

**Mod configuration**

- A **Configure** button on any mod that ships a config file, with real controls
  per setting (switches for booleans, fields for numbers and text) grouped by
  file and section.
- `key = value` files (`.ini`, `.txt`, `.cfg`) are edited line by line, so
  comments, ordering and formatting survive untouched.
- `.json` files are edited structurally; keys not being changed, and any nested
  structures, are left exactly as they were.
- `.lua` configs are code, so they are opened in the system editor rather than
  rewritten, a bad write there would break a working mod.
- Every save writes a `.bak` beside the original first.

## 0.2.0, unreleased

Reworked into a desktop app plus a read-only in-game panel. Toggling moved out
of the game, since UE4SS loads mods once at startup and an in-game switch could
never apply before a restart anyway.

**Desktop app (new)**

- `PalModManager.exe`, standalone, no Python required.
- Switch per mod, applied on demand; Apply is enabled only when something is
  actually pending.
- Search filter, live status from the last session, and colour-coded state.
- Warns about mods in the wrong folder, duplicate copies across folders, and
  mods in an inactive UE4SS folder that will never load.
- **Repair UE4SS** for the CurseForge conflict that silently reverts mods.
- Auto-refreshes as mods are added or removed, without discarding unapplied
  changes.

**Coverage**

- Scans all seven mod locations rather than three: three UE4SS roots and four
  pak folders, skipping any that don't exist.
- Toggles work in whichever folder a mod actually lives in.
- The base game archive is no longer listed as a mod.

**In-game panel**

- Now read-only. `F8` to show, arrows to scroll. Writes nothing during play.
- UE4SS mods are discovered live. Pak mods come from `modlist.txt`, because
  UE4SS's Lua API lists directories but not files.

**Fixes**

- Pak parsing handles legacy formats. Versions ≥ 10 use the path-hash index,
  earlier ones inline their entries, getting this wrong made working v3 and v8
  mods look broken.
- An empty `Win64\Mods`, which UE4SS recreates on every launch, is no longer
  reported as a conflict.
- Old pak formats are only flagged when the mod is also not confirmed loaded.

## 0.1.0, unreleased

First build: an in-game `F8` panel listing installed mods, with toggling by
number key. Superseded by 0.2.0 before release.
