# JSON spec format

`scripts/hoi4_mod.py build SPEC.json` turns this file into a complete mod. Start from
`examples/spec.example.json`, or from `examples/world.example.json` for a custom world (see
`custom-worlds.md`). Unknown keys are rejected with a "did you mean" hint, and the
build writes nothing if the spec has errors.

Every ID must match `[A-Za-z_][A-Za-z0-9_]*` (event IDs: `<namespace>.<integer>`).
Every text value is plain English text with **no double quotes** (use `'` or curly quotes).

## Top level

| Key | Required | Notes |
|---|---|---|
| `mod` | yes | Mod metadata (below). |
| `focus_trees` | no | List of national focus trees. |
| `events` | no | List of event namespaces, each with events. |
| `decisions` | no | List of decision categories, each with decisions. |
| `ideas` | no | List of idea categories (national spirits are category `country`). |
| `sprites` | no | Extra sprite definitions for textures you ship in the mod. |
| `localisation` | no | Extra `KEY: "text"` pairs written to the English loc file. |
| `world` | no | A generated custom map with countries and a start bookmark. See the `world` section below and `custom-worlds.md`. |

## `mod`

| Key | Default | Notes |
|---|---|---|
| `name` | required | Shown in the launcher. |
| `slug` | derived from name | `^[a-z][a-z0-9_]*$`. Prefixes every generated file name. |
| `version` | `"1.0.0"` | Free text. |
| `supported_version` | `"1.19.*"` | Game version it targets. The last part may be `*`. |
| `tags` | auto | Only use launcher tags such as `"National Focuses"`, `"Events"`, `"Gameplay"`, `"Alternative History"`. |
| `picture` | none | Image file in the mod root (under 1 MB). |

## Raw script lines

Several fields take **raw HOI4 script**: a string or a list of strings. Each string is placed
inside the block the field belongs to (`available`, `completion_reward`, `trigger`, ...). Multi-line
strings are fine; the builder re-indents them. Write effects and triggers exactly as they
appear in game files:

```json
"completion_reward": [
  "add_political_power = 50",
  "hidden_effect = {\n    set_country_flag = por_done\n}"
]
```

Raw lines are not semantically checked. Brace balance and reference problems are caught by the validator.

## `focus_trees[]`

| Key | Default | Notes |
|---|---|---|
| `id` | required | Unique tree ID, e.g. `POR_lusitanian_path_focus`. |
| `country` | required | 3-character tag. The tree is scored for this tag and its civil-war breakaways. |
| `default` | `false` | Leave `false`. The game already has a default tree. |
| `score` | `10` | Tree selection score for the tag (`factor = 0`, `add = score`). |
| `focuses` | required | Non-empty list. |

### `focuses[]`

| Key | Default | Notes |
|---|---|---|
| `id` | required | Globally unique. Prefix with the country tag: `POR_...`. |
| `name` | none | Loc text for the id. Without it the raw id shows in game. |
| `desc` | none | Loc text for `id_desc`. |
| `icon` | `GFX_goal_generic_construct_infrastructure` | Full sprite name. Vanilla `GFX_goal_generic_*` names need no sprite entry. |
| `cost` | `5` | About one week per unit by default (`cost = 5` is about five weeks). |
| `x`, `y` | `0` | Grid position. One unit is 96 px across and 130 px down. |
| `relative_to` | none | Focus ID: `x` and `y` are then offsets from that focus. Must be in the same tree. |
| `prerequisites` | `[]` | A string is one required focus. A list of strings is an OR group (any one). Put separate entries for AND. |
| `mutually_exclusive` | `[]` | Focus IDs that lock this one out once completed. |
| `search_filters` | `[]` | e.g. `["FOCUS_FILTER_POLITICAL"]`. See focus-trees.md for the list. |
| `available` | `[]` | Raw triggers. All must be true (AND). |
| `ai_will_do` | `[]` | Raw lines, e.g. `["factor = 10"]` or `["base = 10"]`. |
| `completion_reward` | `[]` | Raw effects run when the focus completes. |

## `events[]`

Each block is one namespace. The builder writes one event file per namespace.

```json
{ "namespace": "por_events", "events": [ { "id": "por_events.1", ... } ] }
```

| Key | Default | Notes |
|---|---|---|
| `namespace` | required | Letters, digits, underscores, dots allowed. |
| `events[].id` | required | Must start with `<namespace>.` and end in an integer. |
| `events[].type` | `country_event` | Or `news_event`. |
| `title`, `desc` | none | Loc text. A visible event needs one of them. |
| `picture` | none | Sprite name, e.g. `GFX_report_event_generic_read_write` (vanilla) or your own sprite. |
| `major` | `false` | `news_event` only: shows to all countries. |
| `hidden` | `false` | Hidden events need no title or options. |
| `fire_only_once` | `false` | |
| `is_triggered_only` | `true` unless `mean_time_to_happen` is set | Fires only through effects or focuses. |
| `trigger` | `[]` | Raw triggers for the event. |
| `mean_time_to_happen` | none | Raw lines, e.g. `["days = 60"]`, for automatic firing. |
| `immediate` | none | Raw effects that run as soon as the event fires. |
| `options[]` | required unless hidden | Each option: `text` (required), `trigger`, `ai_chance`, `effects`. Max 26. |

Option text is stored as `<id>.a`, `<id>.b`, ... automatically.

## `decisions[]`

Each entry is a category. The builder writes `common/decisions/categories/...` and
`common/decisions/...`.

| Key | Default | Notes |
|---|---|---|
| `category` | required | Category ID. |
| `name`, `desc` | none | Loc text for the category. |
| `icon` | game default | Sprite name for the category. |
| `priority` | none | Integer. Higher shows first. |
| `visible_when_empty` | `false` | Keep the category visible when no decisions are available. |
| `allowed`, `visible`, `available` | `[]` | Category-level raw triggers. |
| `items[]` | required | The decisions. |

Each decision in `items[]`: `id` (required), `name`, `desc`, `icon` (short name; the game adds
`GFX_decision_`), `cost` (political power), `fire_only_once`, `days_remove`, and raw lists
`allowed`, `visible`, `available`, `complete_effect`, `remove_effect`, `ai_will_do`.

## `ideas[]`

| Key | Default | Notes |
|---|---|---|
| `category` | `country` | `country` = national spirits. Other categories exist; see decisions-and-ideas.md. |
| `items[]` | required | Each item: `id` (required), `name`, `desc`, `picture`, `allowed`, `modifier`. |

`modifier` is raw lines inside the modifier block, e.g. `["stability_factor = 0.05"]`.
`picture` is the short name: `"picture": "por_spirit"` uses sprite `GFX_idea_por_spirit`.
A value starting with `GFX_idea_` is accepted and the prefix is stripped.

## `sprites[]`

| Key | Notes |
|---|---|
| `name` | Must start with `GFX_`. |
| `texture` | Relative path with forward slashes, ending in `.dds` (recommended), `.tga` or `.png`. |
| `kind` | `plain` (default) or `focus`. `focus` also writes the required `GFX_<name>_shine` sprite. |

The texture file must exist in the mod folder. The build writes the sprite definition
regardless, so a missing file shows up as a warning, not an error.

## `world`

Generates a whole map with countries and a start bookmark from a seed. The full guide, including what
is generated and what is not, is `custom-worlds.md`. Every key is optional except `countries`.

| Key | Default | Notes |
|---|---|---|
| `seed` | `1` | Whole number, 0 to 2147483647. The same seed and sizes give the same files. |
| `width`, `height` | `1024`, `512` | Multiples of 256, from 256 to 4096 each. Width × height at most 4194304. |
| `land_ratio` | `0.35` | Land share, 0.1 to 0.8. Approximate. |
| `province_size` | `400` | Target province size in pixels, 20 to 20000. Smaller means more provinces (60,000 at most). |
| `state_size` | `5` | Provinces per state, 1 to 60. |
| `region_size` | `12` | Land provinces per strategic region, 1 to 200. |
| `sea_region_size` | `24` | Sea provinces per strategic region, 1 to 500. |
| `max_continents` | `6` | Largest land masses that become continents, 1 to 12. |
| `countries[]` | required | 1 to 40 countries. Each has `tag` (required; 3 capital letters or digits, unique), `name` (required; no quotes, slashes or `: * ? < > \|`), `ideology` (`democratic`, `fascism`, `communism` or `neutrality`; if omitted they cycle in list order) and `color` (`[red, green, blue]`, 0 to 255; if omitted, drawn from the seed). |
| `start.date` | `1936.1.1.12` | `year.month.day`, with an optional `.hour`. `1936-01-01` is refused. |
| `start.name`, `start.desc` | mod name; "<mod name>, as it stands at the start." | The bookmark's title and description. |
| `start.default_country` | first country | The country the player starts as. Must be in `countries`. |

A world replaces the base game's map. Other sections in the same spec (focus trees, events, decisions,
ideas) should use the world's country tags.

## What `build` writes

For slug `por_path` (namespace `por_events`):

```
descriptor.mod
common/national_focus/por_path_<tree_id>.txt
common/decisions/categories/por_path_<category>.txt
common/decisions/por_path_<category>.txt
common/ideas/por_path_ideas.txt
events/por_path_<namespace>.txt
interface/por_path_sprites.gfx          (only if sprites are given)
localisation/english/por_path_l_english.yml
.hoi4-builder-manifest.json             (lists the files this build made)
```

With a `world`, the build also writes the map folder, the strategic regions and states, the country files
and a start bookmark (see `custom-worlds.md`). `--preview PNG` writes a rough picture of the map.

With `--user-dir DIR` the mod folder is `DIR/mod/<slug>/` and the launcher file is `DIR/mod/<slug>.mod`.
Re-running `build` overwrites these generated files and deletes files from a previous build that the
new spec no longer produces. Edit the spec and rebuild rather than hand-editing generated files.
