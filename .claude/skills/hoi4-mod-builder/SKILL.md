---
name: hoi4-mod-builder
description: Build, edit and check mods for Hearts of Iron IV (HOI4, "Hearts of Iron 4") - national focus trees, events, decisions, national spirits (ideas), English localisation, sprite definitions and custom worlds (a generated map with countries and a start date). Writes correct game script from a simple JSON spec and validates it for syntax and reference errors. Use whenever the user wants to create, extend, debug or test anything for Hearts of Iron IV, including a focus tree, event chain, decision, national spirit, mod scaffold, HOI4 translation, custom map or new world.
---

# Hearts of Iron IV mod builder

This skill turns a plan into working HOI4 mod files and then checks them. It uses Python 3 and the
standard library only. `<skill folder>` below means the folder that contains this SKILL.md (for example
`.claude/skills/hoi4-mod-builder`). On Windows, use `py -3` if `python3` is not found.

## Start here

Work out what the user wants. Ask briefly, and only for what changes the build:

- **What to make**: a focus tree, events, decisions, a national spirit, a full mod, a custom world (a generated
  map with countries and a start date), or a fix to an existing mod.
- **Country tag** (3 letters such as `POR` or `GER`) and **mod name**.
- **Tone**: historical, alternate history, or flavour. Choose a sensible default if none is given.
- **Where it goes**: the HOI4 user folder (`--user-dir`) or a project folder (`--out`). Ask before you
  write into the user's game folder.

If the request is vague, propose a short plan, build it, and refine it after the user reacts.
Write names and descriptions in the language the user wants. The builder writes the English
localisation file only.

## Workflow

1. **Plan the content.** For focus trees, sketch branches and grid positions (`reference/focus-trees.md`).
   For events, decide triggers and options (`reference/events.md`).
2. **Write the spec** as `mod-spec.json` in the working folder. Start from `examples/spec.example.json`
   (or `examples/world.example.json` for a custom world) and follow `reference/spec-format.md`. Prefix every
   ID with the country tag, e.g. `POR_naval_bridge`.
3. **Build.** This writes the files and then validates them:
   ```
   python3 <skill folder>/scripts/hoi4_mod.py build mod-spec.json --out ./<slug>                  # project folder
   python3 <skill folder>/scripts/hoi4_mod.py build mod-spec.json --user-dir "<HOI4 user folder>"  # game mod folder
   python3 <skill folder>/scripts/hoi4_mod.py validate ./<slug>                                   # check any mod folder
   ```
4. **Fix every ERROR.** Read the WARN lines too. A reference to a base-game focus, event or sprite shows as
   a warning, because the validator cannot see the base game. Rebuild after each change. The build removes
   files that the new spec no longer produces.
5. **Read one generated file.** Validation proves the structure, not the design. Confirm the focus tree or
   event reads the way you intended.
6. **Hand over** using the checklist below.

## Custom worlds

Use a `world` object when the user wants a new map with its own countries and a start date. The builder
generates the land from a seed and a few sizes, so the user cannot draw it. Then:

1. Ask only what changes the build: the countries (tag, name, ideology), the start date and default country,
   and the map size (1024 × 512 is the default).
2. Write the spec from `examples/world.example.json`, then build with `--preview PNG`. Show the user the
   preview. It is a rough picture, not the game's view.
3. If the layout is wrong, change `seed`, `province_size` or `land_ratio` and rebuild. Never hand-edit the
   generated map files.
4. Validate, fix every ERROR, and hand over. Say that the world has not been loaded in the game.

Read `reference/custom-worlds.md` before you write a world. It lists what is generated, which checks apply,
and what has not been verified.

## Hand-over checklist

Tell the user:

- **Where it is**, and how to enable it: launcher → *All installed mods* → add it to the active playset.
- **How to test**: add `-debug` to the Steam launch options (add `-start_tag=POR` to start as that country).
  Fire an event with the `event <id>` console command. Read `<user dir>/logs/error.log` for errors.
- **What is missing**: custom art (custom icons need DDS textures), other languages, balance testing.
- **What was not checked in the game.** The validator checks structure and references only.
- **For a custom world**: that it replaces the base map (so other map mods cannot be combined with it), that
  the start bookmark is the way in, and the test steps in `reference/custom-worlds.md`.

## Rules that break mods silently

The builder handles these. Follow them too when writing files by hand:

- **Localisation**: UTF-8 **with BOM**; filename ends in `_l_english.yml`; first line `l_english:`; entries
  `KEY:0 "text"`; one line per value; no raw double quotes inside values.
- **Events**: `add_namespace = <namespace>` comes before the events, and every event ID is `<namespace>.<integer>`.
- **IDs are unique** across the whole mod (focuses, events, decisions, ideas). Prefix them with the country tag.
- **Prerequisites** must be in the same tree and placed above the focus that needs them.
- **Custom focus icons** need both `GFX_<name>` and `GFX_<name>_shine` sprites. Vanilla `GFX_goal_generic_*` icons need nothing.
- **Decisions need `ai_will_do`**, or the AI never takes them. `on_add` effects of ideas do not run from history files.
- **Every focus tree needs a `country` score** using `original_tag`, and `default = no` (the base game has a default tree).
- **Never overwrite base-game files.** Put the mod slug in every filename (the builder does this). Never edit the
  game's install folder.
- **Paths**: the mod folder path must be ASCII only. Sprite paths use forward slashes.
- **Edit the spec, not the generated files.** Hand edits are overwritten on the next build.
- **Maps**: every province is in one strategic region, and every land province is in one state. Each colour in
  `provinces.bmp` is unique to one province, and land provinces have continent 1 or more while sea provinces
  have 0. The builder makes these true. `validate` checks them on any map folder.

## Reference files

Read the one you need before writing content:

- `reference/spec-format.md`: the JSON spec, field by field. Read this first when building.
- `reference/hoi4-mod-rules.md`: folders, descriptors, load order, localisation and sprite rules, testing.
- `reference/focus-trees.md`: focus fields, prerequisites (AND and OR), layout, rewards, icons, search filters.
- `reference/events.md`: event types, triggering, options, firing from other content, common mistakes.
- `reference/decisions-and-ideas.md`: decision categories and timers; national spirits and idea parts.
- `reference/scripting-cheatsheet.md`: triggers and effects with examples. Only names that were checked.
- `reference/custom-worlds.md`: procedural custom worlds. The `world` object, how the map is made, the start
  bookmark, the map checks and what is not verified. Read it before writing a `world`.
- `reference/troubleshooting.md`: symptom → cause → fix, and how to read validator output.

## Existing mods

`validate <mod folder>` works on any HOI4 mod, not only generated ones. It reports unbalanced braces,
localisation encoding and filename problems, duplicate IDs, missing prerequisites, undeclared event
namespaces, and missing sprites. On a map folder it also checks provinces, strategic regions, states,
countries, the start bookmark and weather. Edit the existing files directly, then validate again.

## Limits

- The builder covers focus trees, events, decisions, ideas, sprites, English localisation and procedural
  custom worlds (map, countries and start). For a hand-drawn map, unit orders, technologies or custom GUI,
  write the files by hand from the references, and say that the validator checks only what it understands.
- A custom world has not been run in the game. Say so every time you hand one over.
- The rules come from the HOI4 community wiki and from real community mods, checked against game version
  1.19. If the user's game is newer, trust their `error.log` and the current wiki over this skill.
- If you cannot run commands here, write the files by hand following the spec and rules, and say that the
  validator was not run.
