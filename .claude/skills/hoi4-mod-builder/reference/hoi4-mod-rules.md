# HOI4 mod rules: folders, descriptors, loading, text and sprites

Read this when you need to place a file by hand, change how a mod loads, or check why something
is ignored. Source: the HOI4 community wiki (hoi4.paradoxwikis.com) "Modding" pages.

## Where mods live

The **user directory** holds mods, logs and saves:

| OS | Path |
|---|---|
| Windows | `C:\Users\<name>\Documents\Paradox Interactive\Hearts of Iron IV\` (may sit under OneDrive) |
| macOS | `~/Documents/Paradox Interactive/Hearts of Iron IV/` |
| Linux | `~/.local/share/Paradox Interactive/Hearts of Iron IV/` |

- Mod source folders: `<user dir>/mod/<mod folder>/`.
- Launcher descriptor (one per mod): `<user dir>/mod/<name>.mod`. The filename must not contain spaces.
- Never edit the game's own install folder. Put everything in the user directory.
- **The mod path must be ASCII only.** Non-ASCII characters in the path (accents, non-Latin
  letters) stop the mod from loading.

## Descriptors

Two files, which should match except for `path`:

`<user dir>/mod/my_mod.mod` (launcher, has `path`):
```
name="My Mod"
path="mod/my_mod"
version="1.0.0"
tags={
	"National Focuses"
}
supported_version="1.19.*"
```

`<user dir>/mod/my_mod/descriptor.mod` (inside the mod folder, **no** `path`):
```
name="My Mod"
version="1.0.0"
tags={
	"National Focuses"
}
supported_version="1.19.*"
```

- `path` is relative to the user directory, with forward slashes. An absolute path also works.
- `supported_version` only drives the "out of date" marker. Set it to the game version shown in the launcher. `1.19.*` matches any 1.19.x patch.
- `picture` is an image in the mod root, under 1 MB. Local mods do not show it in the launcher.
- `dependencies = { "Other Mod" }` loads this mod after another. Use it when your files must overwrite another mod's files.
- `replace_path = "history/states"` unloads the base game's files from that folder. Use it only for map or state overhauls.
- Mod names must be unique across installed mods.

## Folder layout (inside the mod folder)

| Folder | Holds |
|---|---|
| `common/national_focus/` | Focus trees (any `.txt` name). |
| `common/decisions/categories/` | Decision categories. |
| `common/decisions/` | Decisions, grouped under their category. |
| `common/ideas/` | Ideas and national spirits. |
| `common/scripted_effects/`, `common/scripted_triggers/`, `common/on_actions/` | Reusable script and game-event hooks. |
| `events/` | Event files. |
| `history/countries/`, `history/states/`, `history/units/` | Starting state of countries, states and armies. |
| `interface/*.gfx` | Sprite definitions. This folder is **not** the same as `gfx/interface/`. |
| `gfx/` | Image files (`.dds`, `.tga`, `.png`). |
| `localisation/english/` | English text, `*_l_english.yml`. |

The mod folder must mirror the base game's layout: `common/ideas/my_ideas.txt` sits directly under the mod
folder. An extra level (`my_mod/extra/common/ideas/...`) makes the game ignore those files.

## Loading and overwriting

- The base game loads first; mods load after it, in launcher order. Later files win.
- **Same filename in the same folder replaces the whole base-game file.** Example: `common/ideas/country.txt`
  overwrites the base game's country ideas. Use distinct names such as `my_mod_ideas.txt`. The
  generator prefixes every file with the mod slug for this reason.
- Filenames otherwise do not matter for most folders. Every `.txt` in `common/national_focus/` is read.
- Duplicate IDs (two focuses with the same ID, two events with the same ID) cause errors or
  broken lines. Keep IDs unique across the whole mod, and prefix them with the country tag.
- Files in the `history/` folder are linked by name from other files. Some of them, such as
  `history/units/TAG_1936.txt`, load only when a country history file names them with `oob = "..."`.

## Script basics

- Blocks are `key = { ... }`. Comments start with `#` and run to the end of the line.
- Booleans are `yes` and `no`. Numbers use `.`. Stability and war support are fractions (`0.02` = 2%).
- Triggers are AND by default. Use `OR = { }` and `NOT = { }` for other logic.
- Text is UTF-8. Keep script ASCII where you can.

## Localisation

The game reads `localisation/<language>/*_l_<language>.yml` files.

Rules, which the validator checks:

1. **Encoding: UTF-8 with BOM** (`UTF-8-BOM`). Plain UTF-8 can make the game ignore the file.
2. **Filename ends with `_l_english.yml`** (lowercase `l`, not capital `I`).
3. **First line is `l_english:`** (with the colon).
4. Entries are one per line, indented by one space: `KEY:0 "Text"`. The `:0` version number is optional and ignored.
5. Keys are letters, digits, `_`, `.` or `-`. No spaces.
6. Values are in double quotes. **Line breaks do not work inside a value.** Avoid raw `"` inside a value.
7. Use new files, not copies of base-game files, so the mod survives game updates.

Square-bracket dynamic text (for example `[ROOT.GetName]`) is supported in localisation values; check the wiki for
which scopes are available. Scripted localisation (`defined_text`) handles text variants.

## Sprites and images

Images alone do nothing. A **sprite** gives an image its name, and the game refers to the sprite name.

```
spriteTypes = {
	spriteType = {
		name = GFX_my_icon
		texturefile = gfx/interface/my_mod/my_icon.dds
	}
}
```

- Put the definition in `interface/<anything>.gfx`, inside `spriteTypes = { }`.
- `texturefile` is relative to the mod root, with forward slashes.
- DDS is typical. TGA and PNG are also accepted. The image must exist at that path, or the sprite shows as transparent.
- Name every sprite `GFX_...`. Some systems require the prefix.
- **Focus icons** need two sprites: `GFX_<icon>` and `GFX_<icon>_shine`. The shine sprite has the same
  texture plus an animation block. The builder writes both when you use `kind: "focus"`.
- Decision icons are referenced without the prefix: `icon = my_icon` means `GFX_decision_my_icon`.
- Idea pictures are referenced without the prefix: `picture = my_spirit` means `GFX_idea_my_spirit`.
- Event pictures are full names: `picture = GFX_report_event_...`.
- Base-game names worth reusing (seen in the wiki and in community mods): `GFX_goal_generic_construct_infrastructure`,
  `GFX_goal_generic_dangerous_deal`, `GFX_goal_generic_allies_build_infantry`,
  `GFX_report_event_generic_read_write`. If a name is not in the base game, the sprite shows as blank or as the default image.

## Testing a mod

1. Enable the mod in the launcher: "All installed mods" → enable it in your playset.
2. Turn on debug mode with the Steam launch option `-debug`. Add `-start_tag=POR` to start as that country.
   In debug mode, edits to files that existed at launch are reloaded automatically; new files need a restart.
   Debug mode also writes more errors to the log.
3. Start a game and open the national focus tree (or use `-start_tag`).
4. Fire events from the console with `event <event_id>` (the console key is usually `~` or `` ` ``; check your keyboard layout).
5. Read the log: `<user dir>/logs/error.log`. Errors mention the file and line. Search for your mod's filenames.

Most mistakes are silent. A bad event namespace or a missing sprite usually does not crash the game; the thing just
fails to appear or shows a placeholder. Run the validator before launching, and check `error.log` after.
