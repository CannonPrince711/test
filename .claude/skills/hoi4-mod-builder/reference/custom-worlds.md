# Custom worlds

A custom world is a new Hearts of Iron IV map with its own countries, plus a start (a bookmark) that
uses it. The builder **generates** the map from a seed and a few sizes. Nobody draws it. The same spec
always writes the same files.

A world replaces the base game's map, so it is a standalone scenario. Read "What this does not do" before
you promise anything.

## Quick start

```
python3 <skill folder>/scripts/hoi4_mod.py build world.json --out ./atlantic_frontier --preview ./atlantic_frontier.png
python3 <skill folder>/scripts/hoi4_mod.py validate ./atlantic_frontier
```

`examples/world.example.json` builds a 1024 × 512 world with four countries in about 4 seconds. It
validates with 0 errors, 0 warnings and 0 notes. A 2048 × 2048 world with two countries took 41 seconds on
a quiet machine and validated clean. The same build took 8 minutes once, while other work was using the CPU.

`--preview PNG` writes a rough picture of the map: land in the country colours, sea in blues. Show it to
the user and say it is not the game's view.

## The `world` object

Add a `world` object to the spec. `countries` is the only required key. Other spec sections (focus trees,
events, decisions, ideas) can share the same spec. They should use the world's country tags. A focus tree
for one of the world's countries builds and validates; it has not been played.

| Key | Default | What it does |
|---|---|---|
| `seed` | `1` | Whole number, 0 to 2147483647. The same seed and sizes give the same files. |
| `width`, `height` | `1024`, `512` | Map size in pixels. Each is a multiple of 256 from 256 to 4096. Width × height is at most 4,194,304 (2048 × 2048). |
| `land_ratio` | `0.35` | Share of the map that is land, from 0.1 to 0.8. Approximate: land pieces smaller than a province become sea. |
| `province_size` | `400` | Target province size in pixels, from 20 to 20000. Smaller values give more provinces. At most 60,000 provinces. |
| `state_size` | `5` | Provinces per state, from 1 to 60. |
| `region_size` | `12` | Land provinces per strategic region, from 1 to 200. |
| `sea_region_size` | `24` | Sea provinces per strategic region, from 1 to 500. |
| `max_continents` | `6` | The largest land masses that become continents, from 1 to 12. Smaller land masses join the nearest continent. |
| `countries` | required | 1 to 40 countries (below). Each tag must be unique. |
| `start` | see below | The start bookmark. |

Each country:

- `tag`: required. Exactly 3 capital letters or digits, such as `ZAL`.
- `name`: required. Plain text with no quotes, slashes or `: * ? < > |`.
- `ideology`: `democratic`, `fascism`, `communism` or `neutrality`. If omitted, the four cycle in list order.
- `color`: `[red, green, blue]`, each 0 to 255. If omitted, a colour is drawn from the seed.

`start`:

- `date`: `1936.1.1.12` by default. Write `year.month.day`, with an optional `.hour`. `1936-01-01` is refused.
- `name`: the bookmark's title. Defaults to the mod name.
- `desc`: the bookmark's description. Defaults to "<mod name>, as it stands at the start."
- `default_country`: the country the player starts as. Defaults to the first country, and must be in `countries`.

## How the map is made

All randomness comes from `seed`, through the builder's own integer generator. The output should therefore
not depend on the Python version. The steps:

1. **Land and sea.** Smooth noise gives every pixel a height. The highest `land_ratio` share becomes land.
   Land pieces smaller than `max(20, province_size)` pixels are turned into sea.
2. **Provinces.** Land and sea are split separately, so no province crosses a coast. Provinces grow to about
   `province_size` pixels and stop before they span 1/8 of the map's width or height.
3. **Continents.** Connected land, largest first, up to `max_continents`. Smaller land masses join the
   nearest continent.
4. **Strategic regions.** Groups of about `region_size` land provinces, and `sea_region_size` sea provinces.
   Every province is in exactly one region. A sea region is `water_shallow_sea` when at least 30% of its
   provinces touch land, and `water_deep_ocean` otherwise.
5. **States.** Each is inside one region and holds about `state_size` land provinces. The victory point is
   the province nearest the state's centre, worth 5 in the capital state and 1 elsewhere. Manpower is 15,000
   per province. The category is `rural` for up to 2 provinces, `town` for 3 or 4, and `large_town` for more.
6. **Countries.** Each country starts from a state chosen far from the others, then grows into neighbouring
   states. The smallest country always grows next, so each country is one connected block where the map allows.
   Isolated states go to the nearest country. A country's capital is its largest state.
7. **Terrain.** Each province is mountain, hills, forest, plains, desert, jungle, marsh or urban, from its
   height, latitude and coast. Sea is ocean. `map/terrain.bmp` stores the base game's palette index for each.
8. **Other map files.** One supply node per state, at its victory point. One unit-stack position per
   province, but no units are placed. Two weather entries per region, `small` and `big`, at the region's centre.
   Rivers, trees, cities, buildings, railways and ambient objects are empty.

## The start (bookmark)

The bookmark has the title, the description, the date and the default country. Each country in the map has a
block there with its ideology and a start description. Each country's history file sets its capital, its
ruling party and an election dated the year before the start. Elections are allowed only for democratic
countries. The start uses the same country list as the map, and there is one start per world.

## Names

Region and state names are placeholders. Regions read "Land region 1" or "Sea region 1". States read
"<Country> 1", "<Country> 2" and so on. Continents read "Continent 1". The keys use the upper-case mod slug as a
prefix, for example `ATLANTIC_FRONTIER_STATE_1`. The spec cannot rename them yet. Say so if the user cares.

## What the build writes

| Files | Contents |
|---|---|
| `map/provinces.bmp`, `map/definition.csv` | Province colours, land or sea, coastal flag, terrain and continent |
| `map/heightmap.bmp`, `map/terrain.bmp` | Height, and terrain palette indices |
| `map/rivers.bmp`, `map/trees.bmp`, `map/cities.bmp` | Empty (all zero) |
| `map/world_normal.bmp` | Flat normal map at half size |
| `map/default.map`, `map/continent.txt`, `map/adjacencies.csv`, `map/adjacency_rules.txt`, `map/seasons.txt`, `map/cities.txt` | Map settings. The climate line is commented out, as in the base game |
| `map/strategicregions/<id>.txt`, `map/supply_nodes.txt`, `map/unitstacks.txt`, `map/weatherpositions.txt` | Regions, supply, positions and weather |
| `map/ambient_object.txt`, `map/buildings.txt`, `map/railways.txt`, `map/positions.txt` | Empty |
| `history/states/<id>-<country>.txt`, `history/countries/<TAG> - <Name>.txt` | States and country starts |
| `common/countries/<TAG>.txt`, `common/country_tags/00_<slug>_countries.txt` | Country colours and tags |
| `common/bookmarks/<slug>_bookmarks.txt` | The start |
| `localisation/english/<slug>_l_english.yml` | Country, region, state, continent and start text |
| `descriptor.mod` | `replace_path` for the eight folders the world replaces: `map`, `map/strategicregions`, `map/supplyareas`, `history/states`, `history/countries`, `common/country_tags`, `common/countries`, `common/bookmarks` |

## Checks

`validate` runs the world checks on any map folder, so it also covers hand-made maps. The level shows how
serious each finding is.

| Check | Level |
|---|---|
| A province is in no strategic region, or in two | ERROR |
| A province is in two states, or a state lists a sea province, has no provinces, or spans two regions | ERROR |
| A land province is in no state | WARN (hand-made maps may leave some out) |
| Two provinces share a colour, or provinces.bmp uses a colour no province defines | ERROR |
| A land province has continent 0, or a sea province has a continent other than 0 | ERROR |
| provinces.bmp is not 24-bit, or its size is not a multiple of 256, or a province spans more than 1/8 of the map | ERROR |
| heightmap, terrain, rivers or cities bitmap is not 8-bit, or differs in size from provinces.bmp | ERROR (a missing one is a WARN) |
| A state's owner is not a defined country, or a capital is a state its country does not own, or `capital` names no state | ERROR |
| The bookmark's `default_country` or a listed country is not defined, or its date is in a wrong form | ERROR |
| A country has no `common/countries` file and no block for it | WARN |
| A region has no `small` or no `big` weather entry, or a size other than those two | WARN |
| `default.map` names a missing file (an ERROR when it is the `map` folder that is replaced, otherwise a WARN) | ERROR or WARN |
| A supply node is on sea | WARN |
| trees.bmp is a different size from provinces.bmp (Beyond Earth ships a smaller one), or a sea region has naval terrain on land | INFO |

## What this does not do

- **Not tested in the game.** The builder cannot run HOI4. The rules come from the community wiki and a real
  custom-map mod (Beyond Earth), so loading, playability and balance are unverified.
- **Replaces the base map.** The world replaces the base game's map, states, strategic regions, country
  tags, countries, bookmarks and supply areas. Other map mods cannot be combined with it. Base-game focus
  trees for other tags will not match the world's countries.
- **Procedural only.** The user cannot draw coastlines, place provinces or use custom terrain textures. There
  are no rivers, cities, buildings, railways or units.
- **Weather sizes are unverified.** The wiki says `small` and `large`, and it says one of each is needed or the
  game crashes. The Nudger and Beyond Earth use `big`. The builder writes `small` and `big`.
- **Some palette and sprite details are unverified.** The terrain indices were checked against the Project
  IRIS terrain file and a sample of Beyond Earth's terrain.bmp, not in the game. The bookmark picture
  `GFX_select_date_1939` is a base-game name and has not been seen in the game.
- **Size limits.** The generator stops at 2048 × 2048 pixels. The engine allows more (13,238,272 pixels), so the
  limit is conservative.

## Testing it with the user

Give the user these steps, and say that they have not been tried in the game:

1. Add the mod in the launcher, under *All installed mods*, to the active playset.
2. Start a new game and pick the start bookmark. Check that the default country starts with a capital.
3. Set `-debug` in the Steam launch options. Load the start, then read `<user dir>/logs/error.log`. The
   wiki says debug mode is needed to see MAP_ERROR messages.
4. Note what was not checked: balance, AI behaviour, and how the map looks at close range.

If the map fails to load, the usual causes are a province missing from its region or state, or a colour used
twice. Run `validate` first, then fix the ERRORs.
