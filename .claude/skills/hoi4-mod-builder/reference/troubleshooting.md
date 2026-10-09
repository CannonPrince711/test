# Troubleshooting

Start with the log. Run the game with `-debug` and open `<user dir>/logs/error.log`. Errors name the
file and the line. Search it for your mod's file names and ID prefixes.

Run the validator first: `python3 <skill folder>/scripts/hoi4_mod.py validate <mod folder>`. It catches most of the
problems below before the game starts.

| Symptom | Likely cause | Fix |
|---|---|---|
| Mod missing from the launcher | `.mod` file not in `<user dir>/mod/`, or `path` wrong, or name clashes with another mod | Put `<name>.mod` in `mod/`, make `path="mod/<folder>"` point at the folder, rename the mod. |
| Launcher says "out of date" | `supported_version` is older than the game | Set it to the launcher's version, e.g. `1.19.*`. |
| Mod path won't load at all | Path has non-ASCII characters (accents, non-Latin letters) | Move the mod to an ASCII-only folder and point `path` there. |
| Focus tree never appears for your country | No `country = { modifier = { ... } } ` score, another tree scores higher, or the tree is `default` by mistake | Add the score block with `original_tag = TAG`; keep `default = no`. |
| Focus icon is a blank or "unknown" image | Sprite name typo, missing `_shine` sprite, or wrong `texturefile` path | Check the sprite name matches exactly; add `GFX_<name>_shine`; confirm the texture exists at the path. |
| Focus shows the raw id instead of a name | Loc key missing, file not UTF-8 with BOM, or filename not ending in `_l_english.yml` | Fix the loc file; run the validator. |
| Prerequisite lines are missing or wrong | Focus IDs reused across trees, prerequisite placed below its focus, or prerequisite in another tree | Make IDs unique; place prerequisites above; keep prerequisites in the same tree. |
| Focus completes but its effects seem missing | Effects check `has_completed_focus` for their own focus, which is still false during the reward | Use a flag set in the reward, or a hidden event with no delay. |
| Event never fires | Namespace not declared, malformed ID, trigger never true, `fire_only_once` already used, or no `is_triggered_only` / `mean_time_to_happen` decision | Declare `add_namespace`; check the ID; test the trigger with the `event` console command in debug mode. |
| Event shows raw keys (`por_events.1.t`) | Loc key missing or loc file broken | Add the keys; fix encoding; run the validator. |
| Event option shows a raw key | Option's `name` loc key is missing | Give every option a `name` with a loc key. |
| Decision not visible | `allowed` or `visible` false, or the category has no visible decisions | Check `original_tag` in `allowed`; add `visible_when_empty = yes` to the category. |
| Decision shows raw key or default icon | Missing loc, or sprite named without the `GFX_decision_` prefix | Add loc; name the sprite `GFX_decision_<icon>` when the icon is `<icon>`. |
| AI never takes a decision | No `ai_will_do` block (the AI skips decisions without one) | Add `ai_will_do = { factor = 5 }`. |
| Idea has no picture | Sprite not named `GFX_idea_<id>` (or `GFX_idea_<picture>`) | Name the sprite correctly, or set `picture` to the short name. |
| Idea effects do not happen on start | `on_add` runs only when the idea is added after the game starts | Repeat the effects in the history file. |
| Localisation text shows a literal `\n` or breaks | Line breaks do not work inside localisation values | Keep each value on one line; split into several keys if needed. |
| Game crashes on the main menu | Unbalanced braces, shared focus referenced but not defined, duplicate IDs | Run the validator; check `error.log` for the first error. |
| Game crashes or freezes at load with a mod that worked before | Base game update renamed something | Check the wiki's changelog, and whether the sprite or effect name still exists. |
| Mod changes not showing | Debug mode reloads only files that existed at launch; a new file needs a restart | Restart the game after adding files. |
| Two mods overwrite each other | Same filename in the same folder; the later mod wins | Rename your files with a unique prefix, or use `dependencies` in the descriptor. |

## Validator messages

- **ERROR**: the game will misbehave or crash. Fix before testing.
- **WARN**: often fine. A reference to a base-game focus, event or sprite shows as a warning because the validator
  cannot read the base game. Confirm the name is real before ignoring it.
- **INFO**: a note, usually about optional descriptions or pictures.

Use `validate --strict` to fail on warnings too.

## When you cannot test in the game

Say so in the answer. Tell the user what was checked (validator passed; files, IDs and references checked) and what
was not (in-game behaviour, balance, art). Ask them to paste the relevant `error.log` lines if something misbehaves.
