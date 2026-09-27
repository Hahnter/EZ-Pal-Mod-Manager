# EZ Pal Mod Manager

See every mod you have installed, turn them on or off, and get told when one is
in the wrong folder, without hand-editing files.

Two parts, and you can use either on its own:

- **EZPalModManager.exe**: the desktop app. Where you turn mods on and off.
- **In-game panel**: press `F8` in Palworld for a read-only list of what's active.

Toggling lives outside the game because UE4SS loads mods once at startup. A
switch flipped mid-session could not take effect until you restarted anyway, so
the natural place to change things is before you launch.

## The desktop app

Run `EZPalModManager.exe`. No install, no Python, nothing to configure, it finds
Palworld and reads your mods.

- A switch per mod. Hit **Apply changes**, then start the game.
- **Search** to filter a long list.
- Live status from the last session: `loaded`, `not loaded`, `failed to load`,
  `disabled`.
- Warnings for mods in the wrong folder, duplicates across folders, and mods
  sitting in an inactive UE4SS folder that will never load.
- **Repair UE4SS**: fixes the conflict that happens when the CurseForge app
  reinstalls its own UE4SS over an experimental build and silently reverts your
  mods.
- The list updates by itself as mods are added or removed.

## Configuring mods

Mods that ship a config file get a **Configure** button. Settings appear as real
controls (switches for on/off values, fields for numbers and text) grouped by
file and by section.

| Format | Handling |
|---|---|
| `.ini`, `.txt`, `.cfg` (`key = value`) | Edited in place; comments and layout preserved |
| `.json` | Edited structurally; untouched keys and nesting preserved |
| `.lua` | Opened in your editor. It is code, so it isn't rewritten |

Every save writes a `.bak` beside the original first, and only the lines you
changed are touched. Config changes apply on the next launch, same as toggles.

Mods with their own in-game settings screen, Pal Insight on `F6`, PalMiniMap on
`F5`, are usually better configured there. This is for the ones that have no UI
of their own.

## The in-game panel

| Key | Action |
|---|---|
| `F8` | Show / hide |
| `↑` `↓` | Scroll |
| `PageUp` / `PageDown` | Jump a screenful |

Green is enabled, grey is disabled. Read-only: use the desktop app to change
anything.

## What counts as a mod

Every folder Palworld can load one from:

| UE4SS mods | Pak mods |
|---|---|
| `Pal/Binaries/Win64/ue4ss/Mods` | `Pal/Content/Paks/~mods` |
| `Pal/Binaries/Win64/Mods` | `Pal/Content/Paks/LogicMods` |
| `Mods/NativeMods/UE4SS/Mods` | `Pal/Content/Paks` |
| | `Mods` (game root) |

Types are shown as `lua`, `c++` or `pak`. UE4SS's own built-in mods are hidden,
and the base game archive is never listed as a mod.

## How toggling works

Nothing is deleted. It flips exactly the switches you would by hand:

- UE4SS mods, creates or removes `enabled.txt`, and updates `mods.json`
- Pak mods, renames `Something.pak` to `Something.pak.disabled` and back

A mod turned off can always be turned back on, and the change is visible outside
the app if you would rather check yourself.

## Requirements

- Palworld 1.0
- For the in-game panel only:
  [RE-UE4SS, experimental Palworld build](https://github.com/Okaetsu/RE-UE4SS/releases/tag/experimental-palworld)

The desktop app works with any layout, including stable UE4SS 3.0.1. The
in-game panel needs the experimental build, like most current Palworld mods.

## Installation

**Desktop app**, put `EZPalModManager.exe` anywhere and run it.

**In-game panel**, extract the archive into your Palworld folder so it lands at:

```
Pal\Binaries\Win64\ue4ss\Mods\PalModManager\
    enabled.txt
    Scripts\main.lua
```

Delete that folder to uninstall.

## Known limitations

- **Toggles apply on the next launch.** A UE4SS limitation; no mod manager can
  work around it.
- The in-game panel reads pak mods from `modlist.txt`, which the desktop app
  writes. UE4SS's Lua API can list directories but not files, so pak mods are
  invisible from inside the game. Run the app once and the panel stays current.
- The panel attaches to Palworld's UI layout widget. If a patch renames it, `F8`
  logs `no UI layout widget found` rather than crashing.

## Troubleshooting

`F8` does nothing? Check `Pal\Binaries\Win64\ue4ss\UE4SS.log` for lines starting
`[PalModManager]`. If the mod isn't mentioned, it isn't loading, confirm
`enabled.txt` exists in its folder and that you're on the experimental UE4SS.

Mods stopped working after using the CurseForge app? Open the desktop app and
press **Repair UE4SS**.
