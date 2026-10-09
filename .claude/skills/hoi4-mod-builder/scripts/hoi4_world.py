"""
hoi4_world.py - procedural custom worlds for hoi4_mod.py (standard library only).

A world is a generated map (provinces, terrain, continents, strategic regions,
states, supply, unit and weather positions) plus the countries and a start
bookmark that use it. Everything is derived from a seed and a few sizes, so the
same spec always writes the same files.

The file formats and rules follow the Hearts of Iron IV map-modding wiki and
real custom-map mods (see reference/custom-worlds.md). Nothing here can run the
game: build_world() enforces the rules the wiki says cause crashes, and
check_world() verifies them on any map folder. In-game behaviour is not tested.
"""

import array
import re
import struct
import zlib
from collections import deque
from pathlib import Path

GOLDEN = 0x9E3779B97F4A7C15
MASK64 = (1 << 64) - 1

LAND_TERRAINS = ("plains", "forest", "hills", "mountain", "desert", "marsh", "jungle", "urban")
KNOWN_TERRAINS = LAND_TERRAINS + ("ocean", "lakes", "unknown")
# terrain.bmp palette index of each terrain. The base game's common/terrain/00_terrain.txt maps these
# indices to terrain types, and Beyond Earth's terrain.bmp uses the same index for the same terrain.
TERRAIN_INDEX = {"plains": 0, "forest": 1, "hills": 2, "desert": 3, "mountain": 6, "marsh": 9,
                 "lakes": 14, "urban": 13, "jungle": 21, "ocean": 15, "unknown": 0}
NAVAL_TERRAINS = ("water_shallow_sea", "water_deep_ocean")
IDEOLOGIES = ("democratic", "fascism", "communism", "neutrality")
BOOKMARK_PICTURE = "GFX_select_date_1939"
DEFAULT_START_DATE = "1936.1.1.12"
ENGINE_MAX_PIXELS = 13238272     # wiki: the total area of provinces.bmp cannot exceed this
GENERATOR_MAX_PIXELS = 4194304   # 2048 x 2048; keeps pure-Python generation reasonable
MAX_PROVINCES = 60000
DATE_RE = re.compile(r"^(\d{1,4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d{1,2}))?$")   # year.month.day[.hour]
# country_tags lines: TAG = "countries/X.txt" or TAG = @ALIAS (Beyond Earth uses both)
TAG_LINE_RE = re.compile(r'^\s*([A-Z0-9]{3})\s*=\s*(?:"([^"]+)"|(@?[A-Za-z0-9_]+))', re.MULTILINE)
TAG_VAR_RE = re.compile(r'^\s*(@[A-Za-z0-9_]+)\s*=\s*"([^"]+)"', re.MULTILINE)
# a tag defined as a block in common/countries (colours, cosmetics), e.g. "D01 = {"
COUNTRY_BLOCK_RE = re.compile(r"^\s*([A-Z0-9]{3})\s*=\s*\{", re.MULTILINE)
WEATHER_SIZES = ("small", "big")   # Nudger and Beyond Earth use big; the wiki says large (unverified)
# Folders the generated mod replaces, so base-game states, regions, tags and bookmarks do not mix in.
REPLACE_PATHS = (
    "map",
    "map/strategicregions",
    "map/supplyareas",
    "history/states",
    "history/countries",
    "common/country_tags",
    "common/countries",
    "common/bookmarks",
)

# Copied from a working custom-map mod (Hanntheccho/HOI4-Beyond-Earth), with our file names.
DEFAULT_MAP_TEXT = """definitions = "definition.csv"
provinces = "provinces.bmp"
positions = "positions.txt"
terrain = "terrain.bmp"
rivers = "rivers.bmp"
heightmap = "heightmap.bmp"
tree_definition = "trees.bmp"
continent = "continent.txt"
adjacency_rules = "adjacency_rules.txt"
adjacencies = "adjacencies.csv"
#climate = "climate.txt"
ambient_object = "ambient_object.txt"
seasons = "seasons.txt"

# Define which indices in trees.bmp palette which should count as trees for automatic terrain assignment
tree = { 3 4 7 10 }
"""
CITIES_TEXT = 'types_source = "map/cities.bmp"\npixel_step_x = 1\npixel_step_y = 1\n'
ADJACENCY_HEADER = "From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment\n"


class WorldError(Exception):
    """The settings cannot produce a usable map, for example too many countries for the map size."""


class Rng:
    """SplitMix64. Pure integer arithmetic, so a seed gives the same numbers on every Python version."""

    def __init__(self, seed):
        self.state = (int(seed) * GOLDEN + 12345) & MASK64

    def next_u64(self):
        self.state = (self.state + GOLDEN) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def random(self):
        return (self.next_u64() >> 11) / 9007199254740992.0

    def randrange(self, n):
        return self.next_u64() % n

    def uniform(self, a, b):
        return a + (b - a) * self.random()

    def randint(self, a, b):
        return a + self.randrange(b - a + 1)

    def shuffle(self, items):
        for i in range(len(items) - 1, 0, -1):
            j = self.randrange(i + 1)
            items[i], items[j] = items[j], items[i]


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def value_noise(width, height, rng, cell):
    """Smooth random field in [0, 1): bilinear interpolation of a random lattice with spacing `cell`."""
    gw = width // cell + 2
    gh = height // cell + 2
    lattice = [rng.random() for _ in range(gw * gh)]
    columns = []
    for x in range(width):
        i, f = divmod(x, cell)
        columns.append((i, _smooth(f / cell)))
    out = []
    for y in range(height):
        j, f = divmod(y, cell)
        ty = _smooth(f / cell)
        r0 = j * gw
        r1 = r0 + gw
        for i, tx in columns:
            a = lattice[r0 + i]
            b = lattice[r0 + i + 1]
            c = lattice[r1 + i]
            d = lattice[r1 + i + 1]
            top = a + (b - a) * tx
            out.append(top + ((c + (d - c) * tx) - top) * ty)
    return out


def elevation(width, height, rng):
    """Three octaves of value noise, normalised to [0, 1]."""
    big = max(8, max(width, height) // 3)
    total = [0.0] * (width * height)
    for cell, weight in ((big, 1.0), (max(4, big // 2), 0.5), (max(2, big // 4), 0.25)):
        field = value_noise(width, height, rng, cell)
        total = [t + weight * f for t, f in zip(total, field)]
    lo, hi = min(total), max(total)
    span = (hi - lo) or 1.0
    return [(v - lo) / span for v in total]


def neighbours(i, width, n):
    """4-connected neighbours of pixel index i (no wrap-around)."""
    x = i % width
    out = []
    if x:
        out.append(i - 1)
    if x < width - 1:
        out.append(i + 1)
    if i >= width:
        out.append(i - width)
    if i + width < n:
        out.append(i + width)
    return out


def partition_pixels(width, n, domain, pid, boxes, rng, target, max_w, max_h):
    """Grow groups of connected pixels over `domain` (1 = eligible).

    pid[i] receives the group id (0 = unassigned); boxes[gid] = [x0, x1, y0, y1].
    No group may be max_w or more pixels wide, or max_h or more high (the 1/8-of-map rule).
    """
    order = [i for i in range(n) if domain[i]]
    rng.shuffle(order)

    def fits(box, x, y):
        return (max(box[1], x) - min(box[0], x) < max_w) and (max(box[3], y) - min(box[2], y) < max_h)

    def claim(gid, box, i):
        x = i % width
        y = i // width
        pid[i] = gid
        box[0] = min(box[0], x)
        box[1] = max(box[1], x)
        box[2] = min(box[2], y)
        box[3] = max(box[3], y)

    def start(seed):
        gid = len(boxes)
        x = seed % width
        y = seed // width
        box = [x, x, y, y]
        boxes.append(box)
        pid[seed] = gid
        goal = max(1, int(target * rng.uniform(0.6, 1.4)))
        return {"gid": gid, "box": box, "area": 1, "goal": goal, "frontier": [seed]}

    def grow_all(groups):
        """Grow the groups side by side: each step extends one randomly chosen group by one pixel."""
        active = list(groups)
        while active:
            k = rng.randrange(len(active))
            g = active[k]
            if g["area"] >= g["goal"] or not g["frontier"]:
                active[k] = active[-1]
                active.pop()
                continue
            frontier = g["frontier"]
            j = rng.randrange(len(frontier))
            frontier[j], frontier[-1] = frontier[-1], frontier[j]
            cur = frontier.pop()
            for nb in neighbours(cur, width, n):
                if g["area"] >= g["goal"]:
                    break
                if not domain[nb] or pid[nb]:
                    continue
                if not fits(g["box"], nb % width, nb // width):
                    continue
                claim(g["gid"], g["box"], nb)
                g["area"] += 1
                frontier.append(nb)

    def attach():
        """Give free pixels to a neighbouring group where the group's size limits allow it."""
        queue = deque(i for i in order if pid[i])
        while queue:
            cur = queue.popleft()
            gid = pid[cur]
            box = boxes[gid]
            for nb in neighbours(cur, width, n):
                if not domain[nb] or pid[nb]:
                    continue
                if not fits(box, nb % width, nb // width):
                    continue
                claim(gid, box, nb)
                queue.append(nb)

    # about one group per `target` pixels, seeded at random points, then grown together
    seeds = order[:max(1, round(len(order) / target))]
    grow_all([start(seed) for seed in seeds])
    while True:
        attach()
        left = [i for i in order if not pid[i]]
        if not left:
            break
        for seed in left:
            if not pid[seed]:
                grow_all([start(seed)])


def partition_graph(nodes, adj, rng, target):
    """Group graph nodes into connected groups of about `target` nodes.

    `adj` must only link nodes that are in `nodes`. Returns (group_of, groups),
    where groups is a list of member lists.
    """
    group_of = {}
    groups = []

    def start(seed):
        k = len(groups)
        groups.append([seed])
        group_of[seed] = k
        goal = max(1, int(round(target * rng.uniform(0.6, 1.4))))
        return {"k": k, "goal": goal, "frontier": [seed]}

    def grow_all(active):
        active = list(active)
        while active:
            i = rng.randrange(len(active))
            g = active[i]
            members = groups[g["k"]]
            if len(members) >= g["goal"] or not g["frontier"]:
                active[i] = active[-1]
                active.pop()
                continue
            frontier = g["frontier"]
            j = rng.randrange(len(frontier))
            frontier[j], frontier[-1] = frontier[-1], frontier[j]
            cur = frontier.pop()
            for nb in sorted(adj.get(cur, ())):
                if len(members) >= g["goal"]:
                    break
                if nb in group_of:
                    continue
                group_of[nb] = g["k"]
                members.append(nb)
                frontier.append(nb)

    order = sorted(nodes)
    rng.shuffle(order)
    # about one group per `target` nodes, grown side by side from random seeds
    grow_all([start(seed) for seed in order[:max(1, round(len(order) / target))]])
    for seed in order:
        if seed not in group_of:
            grow_all([start(seed)])
    return group_of, groups


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def assign_states(centroids, state_adj, k, rng):
    """Split states among k countries by growing territories from spread-out seeds.

    Returns owner[s] = country index. Every state gets an owner; states unreachable
    from any seed (islands) go to the country of the nearest owned state.
    """
    count = len(centroids)
    seeds = [rng.randrange(count)]
    mind = [_dist2(centroids[s], centroids[seeds[0]]) for s in range(count)]
    while len(seeds) < k:
        chosen = set(seeds)
        best = max((s for s in range(count) if s not in chosen), key=lambda s: (mind[s], -s))
        seeds.append(best)
        for s in range(count):
            mind[s] = min(mind[s], _dist2(centroids[s], centroids[best]))
    owner = [-1] * count
    sizes = [0] * k
    frontier = [set() for _ in range(k)]
    for c, s in enumerate(seeds):
        owner[s] = c
        sizes[c] = 1
        frontier[c] |= state_adj[s]
    free = count - k
    while free > 0:
        options = [c for c in range(k) if any(owner[t] < 0 for t in frontier[c])]
        if not options:
            break
        c = min(options, key=lambda c: (sizes[c], c))
        candidates = sorted(t for t in frontier[c] if owner[t] < 0)
        t = candidates[rng.randrange(len(candidates))]
        owner[t] = c
        sizes[c] += 1
        free -= 1
        frontier[c] |= state_adj[t]
    while -1 in owner:
        s = owner.index(-1)
        owned = [t for t in range(count) if owner[t] >= 0]
        t = min(owned, key=lambda t: (_dist2(centroids[s], centroids[t]), t))
        owner[s] = owner[t]
    return owner


def pick_terrain(rng, elevation_mean, lat, coastal):
    """Pick a land terrain. Every rule draws its own number, so an earlier rule cannot hide a later one."""
    if elevation_mean > 0.8:
        return "mountain" if rng.random() < 0.6 else "hills"
    if elevation_mean > 0.62 and rng.random() < 0.45:
        return "hills"
    if coastal and rng.random() < 0.12:
        return "marsh"
    if lat < 0.3 and rng.random() < 0.4:
        return "jungle"
    if 0.35 < lat < 0.7 and rng.random() < 0.5:
        return "desert"
    roll = rng.random()
    if roll < 0.06:
        return "urban"
    if roll < 0.4:
        return "forest"
    return "plains"


def weather_block(lat, land):
    """One weather period covering the whole year (between = { 0.0 30.11 } is day.month 0.0 to 30.11)."""
    t_lo = round(24.0 - 38.0 * lat + (0.0 if land else 3.0), 1)
    t_hi = round(t_lo + 12.0, 1)
    lines = [
        "\tweather = {",
        "\t\tperiod = {",
        "\t\t\tbetween = { 0.0 30.11 }",
        f"\t\t\ttemperature = {{ {t_lo:.1f} {t_hi:.1f} }}",
        "\t\t\ttemperature_day_night = { -0.0 0.0 }",
        f"\t\t\tno_phenomenon = {max(0.0, 0.6 - 0.2 * lat):.3f}",
        "\t\t\train_light = 0.250",
        f"\t\t\train_heavy = {0.02 + 0.10 * (1.0 - lat):.3f}",
        f"\t\t\tsnow = {0.5 * lat * lat:.3f}",
        f"\t\t\tblizzard = {0.1 * lat * lat:.3f}",
        f"\t\t\tarctic_water = {0.3 * lat * lat:.3f}",
        f"\t\t\tmud = {0.05 * (1.0 - lat):.3f}",
        "\t\t\tsandstorm = 0.000",
        f"\t\t\tmin_snow_level = {0.1 if lat > 0.8 else 0.0:.3f}",
        "\t\t}",
        "\t}",
    ]
    return lines


class World:
    """Plain data produced by build_world(); see build_world for the fields."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def summary(self):
        land = sum(1 for p in self.provinces[1:] if p["land"])
        return (f"{self.width}x{self.height} map, {len(self.provinces) - 1} provinces ({land} land), "
                f"{len(self.regions)} strategic regions, {len(self.states)} states, "
                f"{len(self.countries)} countries, {self.continents} continents")


def build_world(cfg):
    """Generate the world described by cfg (already validated by hoi4_mod.normalise_world).

    Returns a World with: width, height, pid (array of province ids, top row first),
    heights (bytearray for heightmap.bmp), provinces (index = id, index 0 unused),
    regions, states, countries, continents, prefix and cfg.
    """
    width = cfg["width"]
    height = cfg["height"]
    n = width * height
    rng = Rng(cfg["seed"])

    elev = elevation(width, height, rng)
    ordered = sorted(elev)
    cut = ordered[int((1.0 - cfg["land_ratio"]) * (n - 1))]
    land = bytearray(1 if v >= cut else 0 for v in elev)
    _drop_small_islands(width, n, land, max(20, cfg["province_size"]))
    if not any(land):
        raise WorldError("the generated map has no land; raise land_ratio")
    sea = bytearray(1 - v for v in land)

    pid = array.array("I", bytes(4 * n))
    boxes = [None]
    max_w = max(2, width // 8 - 1)   # provinces over 1/8 of the map width or height are unstable
    max_h = max(2, height // 8 - 1)
    partition_pixels(width, n, land, pid, boxes, rng, cfg["province_size"], max_w, max_h)
    land_count = len(boxes) - 1
    partition_pixels(width, n, sea, pid, boxes, rng, cfg["province_size"], max_w, max_h)
    count = len(boxes) - 1
    if pid.count(0):
        raise WorldError("internal error: some pixels were not assigned to a province")
    if count > MAX_PROVINCES:
        raise WorldError(f"the map would have {count} provinces (limit {MAX_PROVINCES}); "
                         "raise province_size or shrink the map")

    area = [0] * (count + 1)
    sx = [0] * (count + 1)
    sy = [0] * (count + 1)
    se = [0.0] * (count + 1)
    for i in range(n):
        g = pid[i]
        area[g] += 1
        sx[g] += i % width
        sy[g] += i // width
        se[g] += elev[i]

    adj = [set() for _ in range(count + 1)]
    for i in range(n):
        g = pid[i]
        if i % width != width - 1:
            h = pid[i + 1]
            if h != g:
                adj[g].add(h)
                adj[h].add(g)
        if i + width < n:
            h = pid[i + width]
            if h != g:
                adj[g].add(h)
                adj[h].add(g)

    is_land = [False] + [g <= land_count for g in range(1, count + 1)]
    coastal = [False] + [any(is_land[h] != is_land[g] for h in adj[g]) for g in range(1, count + 1)]
    land_ids = list(range(1, land_count + 1))
    sea_ids = list(range(land_count + 1, count + 1))
    land_adj = {g: {h for h in adj[g] if is_land[h]} for g in land_ids}
    sea_adj = {g: {h for h in adj[g] if not is_land[h]} for g in sea_ids}

    # ---- continents: connected land masses, largest first, small ones join the nearest ----
    continent = [0] * (count + 1)
    comps = _components(land_ids, land_adj)
    comps.sort(key=lambda c: (-sum(area[g] for g in c), min(c)))
    keep = comps[:cfg["max_continents"]]
    keep_centre = []
    for k, comp in enumerate(keep):
        for g in comp:
            continent[g] = k + 1
        total = sum(area[g] for g in comp)
        keep_centre.append((sum(sx[g] for g in comp) / total, sum(sy[g] for g in comp) / total))
    for comp in comps[len(keep):]:
        total = sum(area[g] for g in comp)
        centre = (sum(sx[g] for g in comp) / total, sum(sy[g] for g in comp) / total)
        k = min(range(len(keep)), key=lambda k: (_dist2(centre, keep_centre[k]), k))
        for g in comp:
            continent[g] = k + 1

    # ---- terrain and colours -------------------------------------------------------------
    terrain = ["ocean"] * (count + 1)
    cy_of = [0.0] * (count + 1)
    lat_of = [0.0] * (count + 1)
    for g in range(1, count + 1):
        cy_of[g] = sy[g] / area[g]
        lat_of[g] = abs(cy_of[g] / height - 0.5) * 2.0
    for g in land_ids:
        terrain[g] = pick_terrain(rng, se[g] / area[g], lat_of[g], coastal[g])
    rgb = [None] * (count + 1)
    used = set()
    for g in range(1, count + 1):
        colour = (rng.randint(1, 255), rng.randint(1, 255), rng.randint(1, 255))
        while colour in used:
            colour = (rng.randint(1, 255), rng.randint(1, 255), rng.randint(1, 255))
        used.add(colour)
        rgb[g] = colour

    # ---- strategic regions: land regions, then sea regions ---------------------------------
    regions = []
    _, land_groups = partition_graph(land_ids, land_adj, rng, cfg["region_size"])
    for members in land_groups:
        regions.append({"id": len(regions) + 1, "land": True, "provinces": sorted(members)})
    _, sea_groups = partition_graph(sea_ids, sea_adj, rng, cfg["sea_region_size"])
    for members in sea_groups:
        regions.append({"id": len(regions) + 1, "land": False, "provinces": sorted(members)})
    region_of = [0] * (count + 1)
    for region in regions:
        for g in region["provinces"]:
            region_of[g] = region["id"]
    for region in regions:
        members = region["provinces"]
        region["area"] = sum(area[g] for g in members)
        region["cy"] = sum(sy[g] for g in members) / region["area"]
        region["cx"] = sum(sx[g] for g in members) / region["area"]
        region["lat"] = abs(region["cy"] / height - 0.5) * 2.0
        if region["land"]:
            region["naval"] = None
        else:
            share = sum(1 for g in members if coastal[g]) / len(members)
            region["naval"] = "water_shallow_sea" if share >= 0.3 else "water_deep_ocean"

    # ---- states: inside one strategic region each (wiki rule) ------------------------------
    states = []
    state_of = [0] * (count + 1)
    for region in regions:
        if not region["land"]:
            continue
        members = region["provinces"]
        member_set = set(members)
        local_adj = {g: {h for h in adj[g] if h in member_set} for g in members}
        _, groups = partition_graph(members, local_adj, rng, cfg["state_size"])
        for group in groups:
            sid = len(states) + 1
            states.append({"id": sid, "region": region["id"], "provinces": sorted(group)})
            for g in group:
                state_of[g] = sid
    for state in states:
        members = state["provinces"]
        total = sum(area[g] for g in members)
        state["cx"] = sum(sx[g] for g in members) / total
        state["cy"] = sum(sy[g] for g in members) / total
        state["manpower"] = len(members) * 15000
        if len(members) <= 2:
            state["category"] = "rural"
        elif len(members) <= 4:
            state["category"] = "town"
        else:
            state["category"] = "large_town"
        state["vp"] = min(members, key=lambda g: (_dist2((sx[g] / area[g], sy[g] / area[g]),
                                                       (state["cx"], state["cy"])), g))

    # ---- countries ----------------------------------------------------------------------------
    countries_cfg = cfg["countries"]
    k = len(countries_cfg)
    if len(states) < k:
        raise WorldError(f"the map has {len(states)} states for {k} countries; use a larger width/height, "
                         "a smaller state_size, or fewer countries")
    centroids = [(s["cx"], s["cy"]) for s in states]
    state_adj = [set() for _ in states]
    for g in land_ids:
        for h in adj[g]:
            if is_land[h] and state_of[g] != state_of[h]:
                state_adj[state_of[g] - 1].add(state_of[h] - 1)
    owner = assign_states(centroids, state_adj, k, rng)

    countries = []
    for c, entry in enumerate(countries_cfg):
        owned = [s for s in states if owner[s["id"] - 1] == c]
        if not owned:
            raise WorldError(f"internal error: country {entry['tag']} received no states")
        capital = max(owned, key=lambda s: (len(s["provinces"]), -s["id"]))
        colour = tuple(entry["color"]) if entry.get("color") else (
            rng.randint(40, 230), rng.randint(40, 230), rng.randint(40, 230))
        countries.append({
            "index": c, "tag": entry["tag"], "name": entry["name"],
            "ideology": entry["ideology"], "color": colour,
            "capital": capital["id"], "states": [s["id"] for s in owned],
        })
    for state in states:
        state["owner"] = owner[state["id"] - 1]
        state["capital"] = countries[state["owner"]]["capital"] == state["id"]

    provinces = [None]
    for g in range(1, count + 1):
        provinces.append({
            "id": g, "rgb": rgb[g], "land": is_land[g], "coastal": coastal[g],
            "terrain": terrain[g] if is_land[g] else "ocean",
            "continent": continent[g], "area": area[g], "region": region_of[g],
            "state": state_of[g], "cx": sx[g] / area[g], "cy": cy_of[g],
        })

    heights = bytearray(n)
    for i in range(n):
        v = elev[i]
        if land[i]:
            heights[i] = 105 + int(55 * min(1.0, max(0.0, (v - cut) / max(1e-9, 1.0 - cut))))
        else:
            heights[i] = 30 + int(60 * min(1.0, max(0.0, v / max(1e-9, cut))))

    return World(width=width, height=height, pid=pid, heights=heights, provinces=provinces,
                 regions=regions, states=states, countries=countries, continents=len(keep),
                 prefix=cfg["prefix"], cfg=cfg, count=count)


def _drop_small_islands(width, n, land, min_size):
    seen = bytearray(n)
    for start in range(n):
        if land[start] and not seen[start]:
            comp = [start]
            seen[start] = 1
            k = 0
            while k < len(comp):
                cur = comp[k]
                k += 1
                for nb in neighbours(cur, width, n):
                    if land[nb] and not seen[nb]:
                        seen[nb] = 1
                        comp.append(nb)
            if len(comp) < min_size:
                for c in comp:
                    land[c] = 0


def _components(nodes, adj):
    seen = set()
    comps = []
    for start in nodes:
        if start in seen:
            continue
        seen.add(start)
        comp = [start]
        k = 0
        while k < len(comp):
            cur = comp[k]
            k += 1
            for nb in sorted(adj.get(cur, ())):
                if nb not in seen:
                    seen.add(nb)
                    comp.append(nb)
        comps.append(comp)
    return comps


# ============================================================================
# Binary and text writers
# ============================================================================

def _bmp(width, height, bits, row_bytes, palette=b""):
    """Uncompressed BMP with a BITMAPINFOHEADER. row_bytes(y) returns the packed top-down row y."""
    stride = ((width * bits + 31) // 32) * 4
    pad = b"\x00" * (stride - width * bits // 8)
    data_size = stride * height
    offset = 14 + 40 + len(palette)
    head = struct.pack("<2sIHHI", b"BM", offset + data_size, 0, 0, offset)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, bits, 0, data_size, 2835, 2835,
                       len(palette) // 4, 0)
    parts = [head, info, palette]
    for y in range(height - 1, -1, -1):  # BMP stores the bottom row first
        parts.append(row_bytes(y) + pad)
    return b"".join(parts)


def grey_palette():
    return b"".join(bytes((i, i, i, 0)) for i in range(256))


def bmp24_rows(width, height, row_bytes):
    return _bmp(width, height, 24, row_bytes)


def bmp8_bytes(width, height, row_bytes):
    return _bmp(width, height, 8, row_bytes, grey_palette())


def _png(width, height, rows):
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def preview_png(world):
    """A picture of the map: countries in their colours, sea in blue, province borders darkened."""
    width, height, pid = world.width, world.height, world.pid
    colour_of = [(0, 0, 0)] * (len(world.provinces))
    for p in world.provinces[1:]:
        if p["land"]:
            owner = world.countries[world.states[p["state"] - 1]["owner"]]
            jitter = (p["rgb"][0] - 128) // 8
            colour_of[p["id"]] = tuple(max(0, min(255, c + jitter)) for c in owner["color"])
        else:
            shade = 20 + p["rgb"][1] % 40 + (30 if p["coastal"] else 0)
            colour_of[p["id"]] = (shade // 2, 80 + shade, 150 + p["rgb"][2] % 60)
    rows = []
    for y in range(height):
        out = bytearray()
        base = y * width
        for x in range(width):
            i = base + x
            g = pid[i]
            r, gg, b = colour_of[g]
            if (x + 1 < width and pid[i + 1] != g) or (y + 1 < height and pid[i + width] != g):
                r, gg, b = r // 2, gg // 2, b // 2
            out.append(r)
            out.append(gg)
            out.append(b)
        rows.append(bytes(out))
    return _png(width, height, rows)


def _province_rows(world):
    width = world.width
    pid = world.pid
    bgr = [None] + [bytes((p["rgb"][2], p["rgb"][1], p["rgb"][0])) for p in world.provinces[1:]]

    def row(y):
        base = y * width
        return b"".join(bgr[pid[base + x]] for x in range(width))
    return row


def _terrain_rows(world):
    """Rows of terrain.bmp palette indices: every pixel takes the index of its province's terrain."""
    width = world.width
    pid = world.pid
    index = [0] + [TERRAIN_INDEX[p["terrain"]] for p in world.provinces[1:]]

    def row(y):
        base = y * width
        return bytes(index[pid[base + x]] for x in range(width))
    return row


def definition_csv(world):
    lines = ["0;0;0;0;land;false;unknown;0"]
    for p in world.provinces[1:]:
        r, g, b = p["rgb"]
        lines.append(f"{p['id']};{r};{g};{b};{'land' if p['land'] else 'sea'};"
                     f"{'true' if p['coastal'] else 'false'};{p['terrain']};{p['continent']}")
    return "\n".join(lines) + "\n"


def _loc_key(world, suffix):
    return f"{world.prefix}_{suffix}"


def world_files(world):
    """Return (files, loc, replace_paths): files maps relative path -> bytes, loc is a list of (key, text)."""
    cfg = world.cfg
    width, height = world.width, world.height
    slug = cfg["slug"]
    files = {}
    files["map/provinces.bmp"] = bmp24_rows(width, height, _province_rows(world))
    heights = world.heights
    files["map/heightmap.bmp"] = bmp8_bytes(width, height,
                                            lambda y: bytes(heights[y * width:(y + 1) * width]))
    zeros = bytes(width)
    for name in ("rivers", "trees", "cities"):
        files[f"map/{name}.bmp"] = bmp8_bytes(width, height, lambda y: zeros)
    files["map/terrain.bmp"] = bmp8_bytes(width, height, _terrain_rows(world))
    flat = bytes((255, 128, 128)) * (width // 2)  # flat normals: no shading from the normal map
    files["map/world_normal.bmp"] = bmp24_rows(width // 2, height // 2, lambda y: flat)

    files["map/definition.csv"] = definition_csv(world).encode("utf-8")
    files["map/default.map"] = DEFAULT_MAP_TEXT.encode("utf-8")
    files["map/cities.txt"] = CITIES_TEXT.encode("utf-8")
    files["map/adjacencies.csv"] = ADJACENCY_HEADER.encode("utf-8")
    files["map/adjacency_rules.txt"] = b"\n"
    files["map/seasons.txt"] = b"\n"
    for name in ("ambient_object.txt", "buildings.txt", "railways.txt", "positions.txt"):
        files[f"map/{name}"] = b""  # empty: no base-game objects, buildings or rail that would name base provinces
    continent_keys = [_loc_key(world, f"CONTINENT_{k}") for k in range(1, world.continents + 1)]
    continent_lines = ["continents = {"] + [f"\t{key}" for key in continent_keys] + ["}"]
    files["map/continent.txt"] = ("\n".join(continent_lines) + "\n").encode("utf-8")

    supply = []
    unitstacks = []
    for p in world.provinces[1:]:
        scale = min(3.0, max(0.5, (p["area"] ** 0.5) / 20.0))
        unitstacks.append(f"{p['id']};0;{p['cx']:.2f};9.50;{height - p['cy']:.2f};0.00;{scale:.2f}")
    for state in world.states:
        supply.append(f"1 {state['vp']}")
    files["map/supply_nodes.txt"] = ("\n".join(supply) + "\n").encode("utf-8")
    files["map/unitstacks.txt"] = ("\n".join(unitstacks) + "\n").encode("utf-8")

    weather_positions = []
    for region in world.regions:
        z = height - region["cy"]
        weather_positions.append(f"{region['id']};{region['cx']:.2f};9.90;{z:.2f};small")
        weather_positions.append(f"{region['id']};{region['cx']:.2f};9.90;{z:.2f};big")
    files["map/weatherpositions.txt"] = ("\n".join(weather_positions) + "\n").encode("utf-8")

    loc = [(key, f"Continent {k}") for k, key in enumerate(continent_keys, 1)]
    for country in world.countries:
        loc.append((country["tag"], country["name"]))
    for region in world.regions:
        rid = region["id"]
        kind = "Land" if region["land"] else "Sea"
        region_key = _loc_key(world, f"REGION_{rid}")
        loc.append((region_key, f"{kind} region {rid}"))
        lines = [
            "strategic_region = {",
            f"\tid = {rid}",
            f"\tname = {region_key}",
            "\tprovinces = { " + " ".join(str(g) for g in region["provinces"]) + " }",
        ]
        if region["naval"]:
            lines.append(f"\tnaval_terrain = {region['naval']}")
        lines += weather_block(region["lat"], region["land"])
        lines.append("}")
        files[f"map/strategicregions/{rid}.txt"] = ("\n".join(lines) + "\n").encode("utf-8")

    counts = {c["index"]: 0 for c in world.countries}
    for state in world.states:
        sid = state["id"]
        country = world.countries[state["owner"]]
        counts[country["index"]] += 1
        ordinal = counts[country["index"]]
        state_key = _loc_key(world, f"STATE_{sid}")
        loc.append((state_key, f"{country['name']} {ordinal}"))
        name_slug = re.sub(r"[^a-z0-9]+", "_", country["name"].lower()).strip("_") or "state"
        owner_tag = country["tag"]
        lines = [
            "state = {",
            f"\tid = {sid}",
            f"\tname = {state_key}",
            f"\tmanpower = {state['manpower']}",
            f"\tstate_category = {state['category']}",
            "\thistory = {",
            f"\t\towner = {owner_tag}",
            f"\t\tvictory_points = {{ {state['vp']} {5 if state['capital'] else 1} }}",
            "\t\tbuildings = {",
            f"\t\t\tinfrastructure = {1 if state['category'] == 'rural' else 2}",
            "\t\t}",
            f"\t\tadd_core_of = {owner_tag}",
            "\t}",
            "\tprovinces = {",
            "\t\t" + " ".join(str(g) for g in state["provinces"]),
            "\t}",
            "}",
        ]
        files[f"history/states/{sid}-{name_slug}.txt"] = ("\n".join(lines) + "\n").encode("utf-8")

    tag_lines = ["# Countries of this custom world (generated by hoi4_mod.py)"]
    # Keys and loc references are written bare, the same way the shipped custom-world mods write them.
    bookmark = [
        "bookmarks = {",
        "\tbookmark = {",
        f"\t\tname = {_loc_key(world, 'BOOKMARK_NAME')}",
        f"\t\tdesc = {_loc_key(world, 'BOOKMARK_DESC')}",
        f"\t\tdate = {cfg['start']['date']}",
        f"\t\tpicture = {BOOKMARK_PICTURE}",
        f"\t\tdefault_country = {cfg['start']['default_country']}",
        "\t\tdefault = yes",
        "",
    ]
    for country in world.countries:
        tag = country["tag"]
        tag_lines.append(f'{tag} = "countries/{tag}.txt"')
        files[f"common/countries/{tag}.txt"] = (
            f"color = {{ {country['color'][0]} {country['color'][1]} {country['color'][2]} }}\n").encode("utf-8")
        year = int(cfg["start"]["date"].split(".")[0]) - 1
        history = [
            f"capital = {country['capital']}",
            "",
            "set_politics = {",
            f"\truling_party = {country['ideology']}",
            f'\tlast_election = "{year}.1.1"',
            "\telection_frequency = 48",
            f"\telections_allowed = {'yes' if country['ideology'] == 'democratic' else 'no'}",
            "}",
        ]
        files[f"history/countries/{tag} - {country['name']}.txt"] = ("\n".join(history) + "\n").encode("utf-8")
        loc.append((f"{tag}_{world.prefix}_START", f"{country['name']} at the start of this world."))
        bookmark += [
            f"\t\t{tag} = {{",
            f"\t\t\thistory = {tag}_{world.prefix}_START",
            f"\t\t\tideology = {country['ideology']}",
            "\t\t\tavailable = { always = yes }",
            "\t\t\tideas = { }",
            "\t\t\tfocuses = { }",
            "\t\t}",
        ]
    bookmark += ["\t}", "}"]
    files["common/country_tags/00_" + slug + "_countries.txt"] = ("\n".join(tag_lines) + "\n").encode("utf-8")
    files[f"common/bookmarks/{slug}_bookmarks.txt"] = ("\n".join(bookmark) + "\n").encode("utf-8")
    loc.append((_loc_key(world, "BOOKMARK_NAME"), cfg["start"]["name"]))
    loc.append((_loc_key(world, "BOOKMARK_DESC"), cfg["start"]["desc"]))
    return files, loc, list(REPLACE_PATHS)


# ============================================================================
# Validation (any map folder)
# ============================================================================

def read_bmp(path):
    """Return (info dict, bytes) for a BMP file, or raise ValueError with a readable reason."""
    data = Path(path).read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("not a BMP file")
    offset = struct.unpack_from("<I", data, 10)[0]
    header_size = struct.unpack_from("<I", data, 14)[0]
    if header_size < 40:
        raise ValueError("unsupported BMP header; HOI4 needs the BITMAPINFOHEADER (40-byte) format")
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    info = {"width": width, "height": abs(height), "top_down": height < 0, "bpp": bpp,
            "compression": compression, "offset": offset}
    return info, data


def check_world(root, rep, st, parse):
    """Check the map, countries and bookmarks of a mod folder against the documented rules.

    `parse(text)` returns (nodes, errors) like hoi4_mod.parse_script. `st.loc` is the
    localisation table gathered by validate_mod. Problems are added to rep.
    """
    root = Path(root)

    def add(level, rel, msg, line=0):
        rep.add(level, rel, line, msg)

    def text_of(rel):
        path = root / rel
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            add("ERROR", rel, 0, "file is not valid UTF-8")
            return None

    # ---- province definitions ----------------------------------------------------------
    defs = {}
    rgb_owner = {}
    text = text_of("map/definition.csv") or ""
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split(";")
        if len(parts) < 8:
            add("ERROR", "map/definition.csv", "definition row needs 8 fields: ID;R;G;B;type;coastal;terrain;continent", lineno)
            continue
        try:
            pid = int(parts[0])
            colour = (int(parts[1]), int(parts[2]), int(parts[3]))
            continent = int(parts[7])
        except ValueError:
            add("ERROR", "map/definition.csv", "ID, colour values and continent must be whole numbers", lineno)
            continue
        kind, coastal, terrain = parts[4], parts[5], parts[6]
        if pid in defs:
            add("ERROR", "map/definition.csv", f"province {pid} is defined twice", lineno)
            continue
        if any(not 0 <= v <= 255 for v in colour):
            add("ERROR", "map/definition.csv", f"province {pid} has a colour value outside 0-255", lineno)
        if colour in rgb_owner:
            add("ERROR", "map/definition.csv", f"colour {colour} is used by provinces {rgb_owner[colour]} and {pid}", lineno)
        rgb_owner.setdefault(colour, pid)
        if kind not in ("land", "sea", "lake"):
            add("ERROR", "map/definition.csv", f"province {pid}: type must be land, sea or lake", lineno)
        if coastal not in ("true", "false"):
            add("ERROR", "map/definition.csv", f"province {pid}: coastal must be true or false", lineno)
        if terrain not in KNOWN_TERRAINS:
            add("WARN", "map/definition.csv", f"province {pid}: terrain '{terrain}' is not a base-game terrain "
                "name (fine only if your mod defines it in common/terrain)", lineno)
        if kind == "land" and continent < 1 and pid != 0:  # province 0 is the reserved 'unknown' entry
            add("ERROR", "map/definition.csv", f"land province {pid} needs a continent number of 1 or more", lineno)
        if kind == "sea" and continent != 0:
            add("ERROR", "map/definition.csv", f"sea province {pid} must have continent 0", lineno)
        defs[pid] = {"kind": kind, "land": kind == "land", "colour": colour, "continent": continent}

    # ---- provinces.bmp ----------------------------------------------------------------------
    width = height = None
    try:
        info, data = read_bmp(root / "map/provinces.bmp")
    except (OSError, ValueError) as exc:
        add("ERROR", "map/provinces.bmp", f"cannot read the province map: {exc}")
        info = None
    if info:
        width, height = info["width"], info["height"]
        if info["bpp"] != 24 or info["compression"] != 0:
            add("ERROR", "map/provinces.bmp", "provinces.bmp must be 24-bit and uncompressed")
        if width % 256 or height % 256:
            add("ERROR", "map/provinces.bmp", f"map size {width}x{height}: width and height must both be multiples of 256")
        if width * height > ENGINE_MAX_PIXELS:
            add("ERROR", "map/provinces.bmp", "map is larger than the engine limit (13,238,272 pixels)")
        stride = ((width * 3 + 3) // 4) * 4
        max_pid = max(defs) if defs else 0
        counts = [0] * (max_pid + 1)
        bx0 = [width] * (max_pid + 1)
        bx1 = [-1] * (max_pid + 1)
        by0 = [height] * (max_pid + 1)
        by1 = [-1] * (max_pid + 1)
        lookup = {(d["colour"][0] << 16) | (d["colour"][1] << 8) | d["colour"][2]: p for p, d in defs.items()}
        unknown = 0
        first_unknown = None
        offset = info["offset"]
        for file_row in range(height):
            y = file_row if info["top_down"] else height - 1 - file_row
            start = offset + file_row * stride
            line = data[start:start + width * 3]
            for x in range(width):
                k = (line[3 * x + 2] << 16) | (line[3 * x + 1] << 8) | line[3 * x]
                p = lookup.get(k)
                if p is None:
                    unknown += 1
                    if first_unknown is None:
                        first_unknown = (x, y)
                    continue
                counts[p] += 1
                if x < bx0[p]:
                    bx0[p] = x
                if x > bx1[p]:
                    bx1[p] = x
                if y < by0[p]:
                    by0[p] = y
                if y > by1[p]:
                    by1[p] = y
        if unknown:
            add("ERROR", "map/provinces.bmp", f"{unknown} pixel(s) use a colour that no province defines "
                f"(first at x={first_unknown[0]}, y={first_unknown[1]}); the game will rewrite or reject the map")
        for p, d in sorted(defs.items()):
            if counts[p] == 0:
                if d["colour"] != (0, 0, 0):
                    add("WARN", "map/provinces.bmp", f"province {p} has no pixels in provinces.bmp")
                continue
            w_span = bx1[p] - bx0[p] + 1
            h_span = by1[p] - by0[p] + 1
            if w_span * 8 > width or h_span * 8 > height:
                add("ERROR", "map/provinces.bmp", f"province {p} spans more than 1/8 of the map "
                    f"({w_span}x{h_span} pixels); large provinces are unstable in game")

    # ---- other bitmaps must match the province map size -------------------------------
    if width and height:
        for name in ("heightmap", "terrain", "rivers", "trees", "cities"):
            rel = f"map/{name}.bmp"
            if not (root / rel).is_file():
                add("WARN", rel, "missing: the base-game file (different size) would be used and may not match")
                continue
            try:
                other, _ = read_bmp(root / rel)
            except (OSError, ValueError) as exc:
                add("ERROR", rel, f"cannot read: {exc}")
                continue
            if other["bpp"] != 8 or other["compression"] != 0:
                add("ERROR", rel, "must be an 8-bit, uncompressed bitmap")
            if (other["width"], other["height"]) != (width, height):
                if name == "trees":   # Beyond Earth ships a smaller tree map on purpose
                    add("INFO", rel, f"size {other['width']}x{other['height']} differs from provinces.bmp "
                        f"({width}x{height}); fine if the tree map is meant to be smaller")
                else:
                    add("ERROR", rel, f"size {other['width']}x{other['height']} does not match provinces.bmp "
                        f"({width}x{height})")
        normal = root / "map/world_normal.bmp"
        if normal.is_file():
            try:
                other, _ = read_bmp(normal)
                if (other["width"], other["height"]) not in ((width, height), (width // 2, height // 2)):
                    add("WARN", "map/world_normal.bmp", "size is neither the map size nor half of it")
            except (OSError, ValueError) as exc:
                add("ERROR", "map/world_normal.bmp", f"cannot read: {exc}")

    # ---- default.map and continents ----------------------------------------------------------
    default_text = text_of("map/default.map")
    replaces_map = bool(re.search(r'replace_path\s*=\s*"map"', text_of("descriptor.mod") or ""))
    if default_text is not None:
        for key, value in re.findall(r'^\s*(\w+)\s*=\s*"([^"]+)"', default_text, re.MULTILINE):
            if key in ("definitions", "provinces", "positions", "terrain", "rivers", "heightmap",
                       "tree_definition", "continent", "adjacency_rules", "adjacencies",
                       "ambient_object", "seasons") and not (root / "map" / value).is_file():
                if replaces_map:   # the base-game copy is not used, so the game needs this file
                    add("ERROR", "map/default.map", f"{key} points to map/{value}, which is missing")
                else:
                    add("WARN", "map/default.map", f"{key} points to map/{value}, which is missing; "
                        "the base-game file would be used")
    continents = 0
    cont_text = text_of("map/continent.txt")
    if cont_text is None:
        if any(d["land"] for d in defs.values()):
            add("ERROR", "map/continent.txt", "missing: land provinces need continents")
    else:
        body = re.search(r"\{(.*?)\}", cont_text, re.DOTALL)
        continents = len(body.group(1).split()) if body else 0
    max_cont = max((d["continent"] for d in defs.values() if d["land"]), default=0)
    if max_cont > continents:
        add("ERROR", "map/continent.txt", f"provinces use continent {max_cont} but only {continents} are listed")

    # ---- strategic regions ----------------------------------------------------------------
    region_of = {}
    region_ids = {}
    region_dir = root / "map/strategicregions"
    for path in sorted(region_dir.glob("*.txt")) if region_dir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        nodes, _ = parse(path.read_text(encoding="utf-8-sig"))
        for node in nodes:
            if node.key != "strategic_region" or not node.is_block:
                continue
            rid = _int_value(node, "id")
            if rid is None:
                add("ERROR", rel, "strategic_region has no numeric id", node.line)
                continue
            if rid in region_ids:
                add("ERROR", rel, f"strategic region id {rid} is used twice", node.line)
            region_ids[rid] = rel
            naval = _scalar(node, "naval_terrain")
            members = _int_list(node, "provinces")
            if naval and naval not in NAVAL_TERRAINS:
                add("INFO", rel, f"naval_terrain '{naval}' is not one of the usual names; check it exists in common/terrain")
            land_flags = set()
            for p in members:
                if p not in defs:
                    add("ERROR", rel, f"strategic region {rid} lists unknown province {p}", node.line)
                    continue
                land_flags.add(defs[p]["land"])
                if p in region_of:
                    add("ERROR", rel, f"province {p} is in strategic regions {region_of[p]} and {rid}", node.line)
                region_of[p] = rid
            if naval and True in land_flags:   # Beyond Earth does this on purpose, so only a note
                add("INFO", rel, f"strategic region {rid} has naval_terrain but also contains land provinces; "
                    "check this is intended", node.line)
    for p in sorted(defs):
        if p not in region_of and p != 0:  # province 0 is the reserved 'unknown' entry
            add("ERROR", "map/strategicregions", f"province {p} is not in any strategic region; "
                "the game can crash on it")

    # ---- states -----------------------------------------------------------------------------
    # Tags can also be defined as blocks in common/countries (colours), with no tag file of their own.
    block_tags = set()
    countries_dir = root / "common/countries"
    for path in sorted(countries_dir.glob("*.txt")) if countries_dir.is_dir() else []:
        block_tags.update(COUNTRY_BLOCK_RE.findall(path.read_text(encoding="utf-8-sig", errors="replace")))
    tags = {}
    tag_dir = root / "common/country_tags"
    for path in sorted(tag_dir.glob("*.txt")) if tag_dir.is_dir() else []:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        rel = path.relative_to(root).as_posix()
        variables = {name: value for name, value in TAG_VAR_RE.findall(content)}
        for tag, quoted, word in TAG_LINE_RE.findall(content):
            target = quoted or variables.get(word)   # None when an alias is defined elsewhere
            tags[tag] = target
            if target and not (root / "common" / target).is_file() and tag not in block_tags:
                add("WARN", rel, f"country {tag} points to common/{target}, which is missing "
                    "(its colour and data must come from another common/countries file)")

    state_ids = {}
    state_owner = {}
    state_region = {}
    in_state = {}
    state_dir = root / "history/states"
    for path in sorted(state_dir.glob("*.txt")) if state_dir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        nodes, _ = parse(path.read_text(encoding="utf-8-sig"))
        for node in nodes:
            if node.key != "state" or not node.is_block:
                continue
            sid = _int_value(node, "id")
            if sid is None:
                add("ERROR", rel, "state has no numeric id", node.line)
                continue
            if sid in state_ids:
                add("ERROR", rel, f"state id {sid} is used twice (also in {state_ids[sid]})", node.line)
            state_ids[sid] = rel
            members = _int_list(node, "provinces")
            if not members:
                add("ERROR", rel, f"state {sid} has no provinces", node.line)
            regions_here = set()
            for p in members:
                if p not in defs:
                    add("ERROR", rel, f"state {sid} lists unknown province {p}", node.line)
                    continue
                if defs[p]["kind"] == "sea":   # lake provinces are allowed in states (Beyond Earth has 150)
                    add("ERROR", rel, f"state {sid} contains sea province {p}", node.line)
                if p in in_state:
                    add("ERROR", rel, f"province {p} is in states {in_state[p]} and {sid}", node.line)
                in_state[p] = sid
                regions_here.add(region_of.get(p))
            if len(regions_here) > 1:
                add("ERROR", rel, f"state {sid} spans more than one strategic region; all of its provinces must share one",
                    node.line)
            state_region[sid] = next(iter(regions_here)) if regions_here else None
            history = next((c for c in node.value if c.key == "history" and c.is_block), None)
            owner = _scalar(history, "owner") if history else None
            state_owner[sid] = owner
            if owner is None:
                add("ERROR", rel, f"state {sid} has no history owner", node.line)
            elif tags and owner not in tags:
                add("ERROR", rel, f"state {sid} is owned by {owner}, which is not in common/country_tags", node.line)
            name_key = _scalar(node, "name")
            if name_key and name_key not in st.loc:
                add("WARN", rel, f"no localisation for state name key '{name_key}'", node.line)
    for p in sorted(defs):
        if defs[p]["land"] and p != 0 and p not in in_state:
            add("WARN", "history/states", f"land province {p} is not in any state")

    # ---- countries and capitals ----------------------------------------------------------
    for path in sorted((root / "history/countries").glob("*.txt")) if (root / "history/countries").is_dir() else []:
        rel = path.relative_to(root).as_posix()
        match = re.match(r"^([A-Z0-9]{3})\b", path.name)
        if not match:
            continue
        tag = match.group(1)
        content = path.read_text(encoding="utf-8-sig")
        cap = re.search(r"^\s*capital\s*=\s*(\d+)", content, re.MULTILINE)
        if cap is None:
            add("INFO", rel, "no capital set; the country starts without a capital")
            continue
        sid = int(cap.group(1))
        if sid not in state_ids:
            add("ERROR", rel, f"capital = {sid} is not a state in this mod")
        elif state_owner.get(sid) != tag:
            add("ERROR", rel, f"capital state {sid} is owned by {state_owner.get(sid)}, not {tag}")
    if tags:
        for tag in sorted(tags):
            if not (root / "history/countries").is_dir() or not any(
                    p.name.startswith(tag + " ") for p in (root / "history/countries").glob("*.txt")):
                add("INFO", "common/country_tags", f"{tag} has no history file (no capital or politics set)")

    # ---- bookmarks ------------------------------------------------------------------------
    bm_dir = root / "common/bookmarks"
    for path in sorted(bm_dir.glob("*.txt")) if bm_dir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        nodes, _ = parse(path.read_text(encoding="utf-8-sig"))
        for top in nodes:
            if top.key != "bookmarks" or not top.is_block:
                continue
            for bm in top.value:
                if bm.key != "bookmark" or not bm.is_block:
                    continue
                default = _scalar(bm, "default_country")
                if default and tags and default not in tags:
                    add("ERROR", rel, f"default_country {default} is not in common/country_tags", bm.line)
                date = _scalar(bm, "date")
                if date is None:
                    add("ERROR", rel, "bookmark has no date", bm.line)
                elif not str(date).startswith("@") and not DATE_RE.match(str(date)):   # @name = a variable
                    add("ERROR", rel, f"date '{date}' must look like 1936.1.1 or 1936.1.1.12 "
                        "(year.month.day, then optional hour)", bm.line)
                for key in ("name", "desc", "picture"):
                    if _scalar(bm, key) is None:
                        add("WARN", rel, f"bookmark has no {key}", bm.line)
                for child in bm.value:
                    if child.is_block and child.key and re.match(r"^[A-Z0-9]{3}$", child.key):
                        if tags and child.key not in tags:
                            add("ERROR", rel, f"bookmark lists {child.key}, which is not in common/country_tags", child.line)
                        ideology = _scalar(child, "ideology")
                        if ideology and ideology not in IDEOLOGIES:
                            add("INFO", rel, f"ideology '{ideology}' is not one of the four base ideology groups; "
                                "check it is a valid ideology", child.line)

    # ---- supply, units, buildings, weather -------------------------------------------------
    for rel, index in (("map/supply_nodes.txt", 1), ("map/unitstacks.txt", 0), ("map/buildings.txt", 0)):
        body = text_of(rel)
        if not body:
            continue
        for lineno, raw in enumerate(body.splitlines(), 1):
            fields = raw.replace(";", " ").split()
            if not fields:
                continue
            try:
                p = int(fields[index])
            except (ValueError, IndexError):
                add("ERROR", rel, "line does not start with the expected numbers", lineno)
                continue
            if p not in defs:
                add("ERROR", rel, f"refers to province {p}, which is not in definition.csv", lineno)
            elif rel == "map/supply_nodes.txt" and defs[p]["kind"] == "sea":
                add("WARN", rel, f"supply node on sea province {p}", lineno)
    weather = text_of("map/weatherpositions.txt")
    if weather is not None:
        sizes = set()
        for lineno, raw in enumerate(weather.splitlines(), 1):
            if not raw.strip():
                continue
            parts = raw.split(";")
            if len(parts) != 5:
                add("ERROR", "map/weatherpositions.txt", "each line needs 5 fields: region;x;y;z;size", lineno)
                continue
            if not parts[0].strip().isdigit() or int(parts[0]) not in region_ids:
                add("ERROR", "map/weatherpositions.txt", f"unknown strategic region '{parts[0]}'", lineno)
            size = parts[4].strip()
            if size not in WEATHER_SIZES:
                add("WARN", "map/weatherpositions.txt", f"size '{size}' is not small or big "
                    "(Beyond Earth and the Nudger use big)", lineno)
            sizes.add(size)
        for want in WEATHER_SIZES:
            if want not in sizes:
                add("WARN", "map/weatherpositions.txt", f"no '{want}' entry; the wiki advises one small and one "
                    "big to avoid a crash, but Beyond Earth ships without small")

    # ---- descriptor: base-game folders must be replaced ------------------------------------
    descriptor = text_of("descriptor.mod") or ""
    if not re.search(r'replace_path\s*=\s*"map"', descriptor):
        add("WARN", "descriptor.mod", 'the custom map is mixed with base-game map files; add replace_path = "map" '
            "and replace_path = \"map/strategicregions\" (the builder does this)")


def _scalar(node, key):
    for c in node.value if node is not None and node.is_block else []:
        if c.key == key and not c.is_block:
            return c.value
    return None


def _int_value(node, key):
    value = _scalar(node, key)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _int_list(node, key):
    for c in node.value:
        if c.key == key and c.is_block:
            out = []
            for item in c.value:
                if item.key is None and not item.is_block:
                    try:
                        out.append(int(item.value))
                    except (TypeError, ValueError):
                        pass
            return out
    return []
