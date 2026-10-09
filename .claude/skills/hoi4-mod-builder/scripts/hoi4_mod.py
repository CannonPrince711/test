#!/usr/bin/env python3
"""
hoi4_mod.py - build and check Hearts of Iron IV mods.

Commands
  build    SPEC.json (--user-dir DIR | --out DIR) [--no-validate] [--preview PNG]
           Writes a complete mod from a JSON spec (see reference/spec-format.md),
           then validates the result. With --user-dir the mod is written to
           DIR/mod/<slug>/ and a launcher descriptor DIR/mod/<slug>.mod is added.
           A "world" object in the spec also writes a generated map, countries and
           a start bookmark (see reference/custom-worlds.md); --preview saves a PNG.
  validate MOD_DIR [--strict]
           Parses every script, .gfx and localisation file in a mod folder and
           reports syntax errors, broken references and common loading mistakes.
           A folder with map/definition.csv also gets the map and country checks.

Standard library only (Python 3.8+).
Exit codes: 0 = no errors; 1 = validation errors (or warnings with --strict);
            2 = bad spec or bad arguments.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # hoi4_world.py sits next to this file
import hoi4_world  # noqa: E402

MANIFEST_NAME = ".hoi4-builder-manifest.json"
DEFAULT_ICON = "GFX_goal_generic_construct_infrastructure"
DEFAULT_SUPPORTED_VERSION = "1.19.*"
EVENT_TYPES = ("country_event", "news_event", "state_event",
               "unit_leader_event", "operative_leader_event")
GENERATABLE_EVENT_TYPES = ("country_event", "news_event")
FOCUS_REF_KEYS = ("has_completed_focus", "complete_national_focus",
                  "unlock_national_focus", "uncomplete_national_focus")
COLOUR_FUNCTIONS = ("rgb", "hsv", "hsv360")

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NAMESPACE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")
EVENT_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*\.[0-9]+$")
TAG_RE = re.compile(r"^[A-Z0-9]{3}$")
FILTER_RE = re.compile(r"^FOCUS_FILTER_[A-Z0-9_]+$")
LOC_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
LOC_LINE_RE = re.compile(r'^\s*([A-Za-z0-9_.\-]+):(\d*)\s*"(.*)"\s*(#.*)?$')


# ============================================================================
# Clausewitz-style script tokenizer and parser (used by validate)
# ============================================================================

TOKEN_RE = re.compile(r"""
      (?P<nl>\n)
    | (?P<ws>[ \t\r\f\v]+)
    | (?P<comment>\#[^\n]*)
    | (?P<string>"[^"\n]*")
    | (?P<badstring>"[^\n]*)
    | (?P<op><=|>=|!=|==|=|<|>)
    | (?P<open>\{)
    | (?P<close>\})
    | (?P<word>[^\s{}=<>"\#]+)
""", re.VERBOSE)


class Node:
    """One entry of a script block: `key = value`, `key = { ... }`, `key > value` or a bare item."""
    __slots__ = ("key", "op", "value", "line")

    def __init__(self, key, op, value, line):
        self.key = key      # str, or None for bare items such as FOCUS_FILTER_POLITICAL
        self.op = op        # "=", a comparison operator, or None
        self.value = value  # str for scalars, list[Node] for blocks
        self.line = line

    @property
    def is_block(self):
        return isinstance(self.value, list)


def tokenize(text):
    tokens = []  # (kind, value, line)
    line = 1
    pos = 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:  # cannot happen: 'word' matches everything except whitespace and syntax
            tokens.append(("bad", text[pos], line))
            pos += 1
            continue
        pos = m.end()
        kind, val = m.lastgroup, m.group()
        if kind == "nl":
            line += 1
        elif kind in ("ws", "comment"):
            pass
        elif kind == "string":
            tokens.append(("str", val[1:-1], line))
        elif kind == "badstring":
            tokens.append(("badstr", val, line))
        elif kind == "op":
            tokens.append(("op", val, line))
        elif kind == "open":
            tokens.append(("{", "{", line))
        elif kind == "close":
            tokens.append(("}", "}", line))
        else:
            tokens.append(("word", val, line))
    return tokens


def parse_script(text):
    """Return (nodes, errors). errors is a list of (line, message)."""
    toks = tokenize(text)
    errors = []
    pos = 0

    def parse_block(open_line):
        nonlocal pos
        nodes = []
        while pos < len(toks):
            kind, val, line = toks[pos]
            if kind == "}":
                pos += 1
                if open_line is None:
                    errors.append((line, "unexpected '}' with no matching '{'"))
                    continue
                return nodes
            if kind == "{":
                pos += 1
                errors.append((line, "'{' without a key (expected 'key = {')"))
                nodes.append(Node(None, None, parse_block(line), line))
                continue
            if kind == "badstr":
                errors.append((line, 'unterminated string literal (missing closing ")'))
                pos += 1
                continue
            if kind in ("op", "bad"):
                errors.append((line, f"unexpected token '{val}'"))
                pos += 1
                continue
            # kind is 'word' or 'str'
            pos += 1
            nxt = toks[pos] if pos < len(toks) else None
            if nxt is None or nxt[0] not in ("op", "{"):
                nodes.append(Node(None, None, val, line))  # bare item
                continue
            if nxt[0] == "{":
                # `key { ... }` without '=' is not valid HOI4 script
                errors.append((line, f"'{val}' is followed by '{{' without '=' (write '{val} = {{')"))
                pos += 1
                nodes.append(Node(val, "=", parse_block(nxt[2]), line))
                continue
            op = nxt[1]
            pos += 1  # consume the operator
            value_tok = toks[pos] if pos < len(toks) else None
            if value_tok is None or value_tok[0] == "}":
                errors.append((line, f"'{val} {op}' has no value"))
                continue
            if value_tok[0] == "{":
                pos += 1
                nodes.append(Node(val, op, parse_block(value_tok[2]), line))
                continue
            if value_tok[0] == "op":
                errors.append((line, f"'{val} {op}' is followed by another operator '{value_tok[1]}'"))
                pos += 1
                continue
            pos += 1  # consume the value
            if value_tok[0] == "badstr":
                errors.append((value_tok[2], 'unterminated string literal (missing closing ")'))
            if (value_tok[0] == "word" and value_tok[1] in COLOUR_FUNCTIONS and pos < len(toks)
                    and toks[pos][0] == "{"):
                # colour literal such as `color = rgb { 255 216 82 }`
                open_line = toks[pos][2]
                pos += 1
                nodes.append(Node(val, op, parse_block(open_line), line))
                continue
            nodes.append(Node(val, op, value_tok[1], line))
        if open_line is not None:
            errors.append((open_line, "unclosed '{' - no matching '}' before end of file"))
        return nodes

    nodes = parse_block(None)
    return nodes, errors


def walk(nodes, depth=0):
    """Yield (node, depth) for every node, depth-first."""
    for n in nodes:
        yield n, depth
        if n.is_block:
            yield from walk(n.value, depth + 1)


def first(nodes, key):
    for n in nodes:
        if n.key == key:
            return n
    return None


def scalar(node):
    if node is None or node.is_block:
        return None
    return node.value


def blocks(nodes, key):
    return [n for n in nodes if n.key == key and n.is_block]


def to_int(text, default):
    try:
        return int(str(text))
    except (TypeError, ValueError):
        return default


# ============================================================================
# Spec handling (build)
# ============================================================================

TOP_KEYS = ("mod", "focus_trees", "events", "decisions", "ideas", "sprites", "localisation", "world")
WORLD_KEYS = ("seed", "width", "height", "land_ratio", "province_size", "state_size", "region_size",
              "sea_region_size", "max_continents", "countries", "start")
WORLD_COUNTRY_KEYS = ("tag", "name", "ideology", "color")
WORLD_START_KEYS = ("date", "name", "desc", "default_country")
WORLD_NAME_FORBIDDEN = '"\\/:*?<>|'


class SpecChecker:
    def __init__(self):
        self.errors = []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def unknown_keys(self, where, obj, allowed):
        for k in obj:
            if k not in allowed:
                hint = difflib.get_close_matches(k, list(allowed), n=1)
                extra = f" (did you mean '{hint[0]}'?)" if hint else ""
                self.err(where, f"unknown key '{k}'{extra}")

    def check_id(self, where, value, pattern=ID_RE, what="ID"):
        if not isinstance(value, str) or not pattern.match(value):
            self.err(where, f"{what} {value!r} is not valid (letters, digits and underscores; "
                            "must not start with a digit)")
            return False
        return True


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not s:
        s = "my_mod"
    if not s[0].isalpha():
        s = "mod_" + s
    return s


def as_list(value, chk, where):
    """Accept None, a string, or a list of strings (raw HOI4 script lines). Return a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    chk.err(where, "must be a string or a list of strings (raw HOI4 script lines)")
    return []


def opt_bool(chk, where, obj, key, default=False):
    v = obj.get(key, default)
    if not isinstance(v, bool):
        chk.err(f"{where}.{key}", "must be true or false")
        return default
    return v


def opt_str(chk, where, obj, key):
    v = obj.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        chk.err(f"{where}.{key}", "must be a non-empty string")
        return None
    if '"' in v and key in ("name", "desc", "title", "text"):
        chk.err(f"{where}.{key}", "must not contain double quotes (use ' or typographic quotes)")
        return None
    return v


def opt_number(chk, where, obj, key, default=None):
    v = obj.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        chk.err(f"{where}.{key}", "must be a number")
        return default
    return v


def normalise(spec, chk):
    """Check the spec and return a normalised model (None if the spec is unusable)."""
    if not isinstance(spec, dict):
        chk.err("spec", "top level must be a JSON object")
        return None
    chk.unknown_keys("spec", spec, TOP_KEYS)

    mod = spec.get("mod")
    if not isinstance(mod, dict):
        chk.err("mod", "required object is missing")
        return None
    chk.unknown_keys("mod", mod, ("name", "slug", "version", "supported_version", "tags", "picture"))
    name = mod.get("name")
    if not isinstance(name, str) or not name.strip():
        chk.err("mod.name", "required non-empty string")
        return None
    if '"' in name:
        chk.err("mod.name", "must not contain double quotes")
    slug = mod.get("slug") or slugify(name)
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        chk.err("mod.slug", "must match ^[a-z][a-z0-9_]*$ (lowercase ASCII; used for file names and the folder)")
    tags = mod.get("tags")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
        chk.err("mod.tags", "must be a list of strings")
        tags = None

    model = {
        "mod": {
            "name": name,
            "slug": slug,
            "version": str(mod.get("version", "1.0.0")),
            "supported_version": str(mod.get("supported_version", DEFAULT_SUPPORTED_VERSION)),
            "tags": tags,
            "picture": mod.get("picture"),
        },
        "trees": [], "events": [], "decision_cats": [], "idea_cats": [],
        "sprites": [], "loc_extra": {},
    }

    # ---- focus trees -------------------------------------------------------
    seen_tree_ids = set()
    for ti, t in enumerate(spec.get("focus_trees", []) or []):
        w = f"focus_trees[{ti}]"
        if not isinstance(t, dict):
            chk.err(w, "must be an object")
            continue
        chk.unknown_keys(w, t, ("id", "country", "default", "score", "focuses"))
        tid = t.get("id")
        if chk.check_id(f"{w}.id", tid, what="focus tree id"):
            if tid in seen_tree_ids:
                chk.err(f"{w}.id", f"duplicate focus tree id '{tid}'")
            seen_tree_ids.add(tid)
        tag = t.get("country")
        if not isinstance(tag, str) or not TAG_RE.match(tag):
            chk.err(f"{w}.country", "must be a 3-character country tag such as GER or TUR")
            tag = "XXX"
        focuses_in = t.get("focuses")
        if not isinstance(focuses_in, list) or not focuses_in:
            chk.err(f"{w}.focuses", "must be a non-empty list")
            focuses_in = []
        tree = {
            "id": tid, "country": tag,
            "default": opt_bool(chk, w, t, "default", False),
            "score": opt_number(chk, w, t, "score", 10),
            "focuses": [],
        }
        for fi, f in enumerate(focuses_in):
            tree["focuses"].append(normalise_focus(f"{w}.focuses[{fi}]", f, chk))
        ids_here = {f["id"] for f in tree["focuses"] if f["id"]}
        for fi, f in enumerate(tree["focuses"]):
            if f["relative_to"] and f["relative_to"] not in ids_here:
                chk.err(f"{w}.focuses[{fi}].relative_to",
                        f"'{f['relative_to']}' is not a focus in this same tree (relative positions must stay in one tree)")
        model["trees"].append(tree)

    # ---- events ------------------------------------------------------------
    for ni, nsb in enumerate(spec.get("events", []) or []):
        w = f"events[{ni}]"
        if not isinstance(nsb, dict):
            chk.err(w, "must be an object")
            continue
        chk.unknown_keys(w, nsb, ("namespace", "events"))
        ns = nsb.get("namespace")
        if not isinstance(ns, str) or not NAMESPACE_RE.match(ns):
            chk.err(f"{w}.namespace", "required; letters, digits and underscores (dots allowed), e.g. 'tur_events'")
            ns = "bad_namespace"
        block = {"namespace": ns, "events": []}
        for ei, ev in enumerate(nsb.get("events", []) or []):
            block["events"].append(normalise_event(f"{w}.events[{ei}]", ns, ev, chk))
        model["events"].append(block)

    # ---- decisions ---------------------------------------------------------
    for ci, cat in enumerate(spec.get("decisions", []) or []):
        w = f"decisions[{ci}]"
        if not isinstance(cat, dict):
            chk.err(w, "must be an object")
            continue
        chk.unknown_keys(w, cat, ("category", "name", "desc", "icon", "priority", "visible_when_empty",
                                  "allowed", "visible", "available", "items"))
        cid = cat.get("category")
        chk.check_id(f"{w}.category", cid, what="decision category id")
        prio = cat.get("priority")
        if prio is not None and (isinstance(prio, bool) or not isinstance(prio, int)):
            chk.err(f"{w}.priority", "must be an integer")
            prio = None
        dcat = {
            "id": cid, "name": opt_str(chk, w, cat, "name"), "desc": opt_str(chk, w, cat, "desc"),
            "icon": opt_str(chk, w, cat, "icon"), "priority": prio,
            "visible_when_empty": opt_bool(chk, w, cat, "visible_when_empty", False),
            "allowed": as_list(cat.get("allowed"), chk, f"{w}.allowed"),
            "visible": as_list(cat.get("visible"), chk, f"{w}.visible"),
            "available": as_list(cat.get("available"), chk, f"{w}.available"),
            "items": [],
        }
        items = cat.get("items")
        if not isinstance(items, list) or not items:
            chk.err(f"{w}.items", "must be a non-empty list of decisions")
            items = []
        for di, d in enumerate(items):
            dcat["items"].append(normalise_decision(f"{w}.items[{di}]", d, chk))
        model["decision_cats"].append(dcat)

    # ---- ideas -------------------------------------------------------------
    for ci, cat in enumerate(spec.get("ideas", []) or []):
        w = f"ideas[{ci}]"
        if not isinstance(cat, dict):
            chk.err(w, "must be an object")
            continue
        chk.unknown_keys(w, cat, ("category", "items"))
        icat = cat.get("category", "country")
        chk.check_id(f"{w}.category", icat, what="idea category")
        items = cat.get("items")
        if not isinstance(items, list) or not items:
            chk.err(f"{w}.items", "must be a non-empty list of ideas")
            items = []
        model["idea_cats"].append({
            "category": icat,
            "items": [normalise_idea(f"{w}.items[{ii}]", it, chk) for ii, it in enumerate(items)],
        })

    # ---- sprites -----------------------------------------------------------
    for si, s in enumerate(spec.get("sprites", []) or []):
        w = f"sprites[{si}]"
        if not isinstance(s, dict):
            chk.err(w, "must be an object")
            continue
        chk.unknown_keys(w, s, ("name", "texture", "kind"))
        sname = s.get("name")
        if not isinstance(sname, str) or not re.match(r"^GFX_[A-Za-z0-9_]+$", sname):
            chk.err(f"{w}.name", "must start with GFX_ and contain only letters, digits and underscores")
        tex = s.get("texture")
        if not isinstance(tex, str) or not tex or tex.startswith("/") or ".." in tex or "\\" in tex:
            chk.err(f"{w}.texture", "must be a relative path with forward slashes, e.g. gfx/interface/goals/my_icon.dds")
        elif not tex.lower().endswith((".dds", ".tga", ".png")):
            chk.err(f"{w}.texture", "must end with .dds (recommended), .tga or .png")
        kind = s.get("kind", "plain")
        if kind not in ("plain", "focus"):
            chk.err(f"{w}.kind", "must be 'plain' or 'focus' (focus adds the required _shine sprite)")
            kind = "plain"
        model["sprites"].append({"name": sname, "texture": tex, "kind": kind})

    # ---- extra localisation ------------------------------------------------
    extra = spec.get("localisation", {}) or {}
    if not isinstance(extra, dict):
        chk.err("localisation", "must be an object of key: text")
    else:
        for k, v in extra.items():
            if not LOC_KEY_RE.match(k) or not isinstance(v, str):
                chk.err(f"localisation.{k}", "keys must be plain identifiers and values must be strings")
                continue
            model["loc_extra"][k] = v

    # ---- duplicate IDs are fatal in HOI4, so refuse to write them ------------
    def unique(pairs, label):
        seen = {}
        for ident, where in pairs:
            if ident is None:
                continue
            if ident in seen:
                chk.err(where, f"duplicate {label} '{ident}' (already used at {seen[ident]})")
            else:
                seen[ident] = where

    unique([(t["id"], f"focus_trees[{i}]") for i, t in enumerate(model["trees"])], "focus tree id")
    unique([(f["id"], f"focus_trees[{i}]") for i, t in enumerate(model["trees"]) for f in t["focuses"]], "focus id")
    unique([(d["id"], f"decisions[{i}]") for i, c in enumerate(model["decision_cats"]) for d in c["items"]],
           "decision id")
    unique([(it["id"], f"ideas[{i}]") for i, c in enumerate(model["idea_cats"]) for it in c["items"]], "idea id")
    unique([(e["id"], f"events[{i}]") for i, b in enumerate(model["events"]) for e in b["events"]], "event id")
    unique([(s["name"], f"sprites[{i}]") for i, s in enumerate(model["sprites"])], "sprite name")

    # ---- tags (computed unless given) ----------------------------------------
    if model["mod"]["tags"] is None:
        auto = []
        if model["trees"]:
            auto.append("National Focuses")
        if model["events"]:
            auto.append("Events")
        model["mod"]["tags"] = auto or ["Gameplay"]

    # ---- custom world (map, countries, start bookmark) ------------------------
    if "world" in spec:
        model["world"] = normalise_world(spec["world"], model["mod"], chk)
    return model


def normalise_world(w, mod, chk):
    """Check the optional `world` object; return generator settings, or None if unusable."""
    where = "world"
    if not isinstance(w, dict):
        chk.err(where, "must be an object (see reference/custom-worlds.md)")
        return None
    chk.unknown_keys(where, w, WORLD_KEYS)

    def whole(key, default, lo, hi, multiple=1):
        v = w.get(key, default)
        if isinstance(v, bool) or not isinstance(v, int):
            chk.err(f"{where}.{key}", "must be a whole number")
            return default
        if not lo <= v <= hi:
            chk.err(f"{where}.{key}", f"must be between {lo} and {hi}")
            return default
        if v % multiple:
            chk.err(f"{where}.{key}", f"must be a multiple of {multiple} (HOI4 map files use 256-pixel steps)")
            return default
        return v

    def fraction(key, default, lo, hi):
        v = w.get(key, default)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            chk.err(f"{where}.{key}", f"must be a number between {lo} and {hi}")
            return default
        return float(v)

    seed = whole("seed", 1, 0, 2 ** 31 - 1)
    width = whole("width", 1024, 256, 4096, multiple=256)
    height = whole("height", 512, 256, 4096, multiple=256)
    if width * height > hoi4_world.GENERATOR_MAX_PIXELS:
        chk.err(where, "width x height must be at most 4194304 pixels (2048 x 2048)")
    settings = {
        "land_ratio": fraction("land_ratio", 0.35, 0.1, 0.8),
        "province_size": whole("province_size", 400, 20, 20000),
        "state_size": whole("state_size", 5, 1, 60),
        "region_size": whole("region_size", 12, 1, 200),
        "sea_region_size": whole("sea_region_size", 24, 1, 500),
        "max_continents": whole("max_continents", 6, 1, 12),
    }

    countries_in = w.get("countries")
    if not isinstance(countries_in, list) or not 1 <= len(countries_in) <= 40:
        chk.err(f"{where}.countries", "must be a list of 1 to 40 countries")
        countries_in = []
    countries = []
    seen_tags = set()
    for i, c in enumerate(countries_in):
        cw = f"{where}.countries[{i}]"
        if not isinstance(c, dict):
            chk.err(cw, "must be an object")
            continue
        chk.unknown_keys(cw, c, WORLD_COUNTRY_KEYS)
        tag = c.get("tag")
        if not isinstance(tag, str) or not TAG_RE.match(tag):
            chk.err(f"{cw}.tag", "must be 3 capital letters or digits, such as ZAL")
            tag = f"Z{i:02d}"[:3]
        elif tag in seen_tags:
            chk.err(f"{cw}.tag", f"duplicate country tag {tag}")
        seen_tags.add(tag)
        name = c.get("name")
        if not isinstance(name, str) or not name.strip() or any(ch in name for ch in WORLD_NAME_FORBIDDEN):
            chk.err(f"{cw}.name", "required; must not contain quotes, slashes or : * ? < > |")
            name = tag
        ideology = c.get("ideology", hoi4_world.IDEOLOGIES[i % len(hoi4_world.IDEOLOGIES)])
        if ideology not in hoi4_world.IDEOLOGIES:
            chk.err(f"{cw}.ideology", "must be democratic, fascism, communism or neutrality")
            ideology = "neutrality"
        color = c.get("color")
        if color is not None and not (isinstance(color, list) and len(color) == 3 and all(
                isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255 for v in color)):
            chk.err(f"{cw}.color", "must be [red, green, blue] with values 0-255")
            color = None
        countries.append({"tag": tag, "name": name, "ideology": ideology, "color": color})

    start_in = w.get("start", {})
    if not isinstance(start_in, dict):
        chk.err(f"{where}.start", "must be an object")
        start_in = {}
    chk.unknown_keys(f"{where}.start", start_in, WORLD_START_KEYS)
    date = start_in.get("date", hoi4_world.DEFAULT_START_DATE)
    match = hoi4_world.DATE_RE.match(date) if isinstance(date, str) else None
    if not match or not (2 <= int(match.group(1)) <= 9999 and 1 <= int(match.group(2)) <= 12
                         and 1 <= int(match.group(3)) <= 31 and 0 <= int(match.group(4) or 12) <= 23):   # the hour is optional; 12 is the usual start
        chk.err(f"{where}.start.date", "must look like 1936.1.1.12 or 1936.1.1 (year.month.day[.hour]; year 2 or later)")
        date = hoi4_world.DEFAULT_START_DATE
    start_name = opt_str(chk, f"{where}.start", start_in, "name") or mod["name"]
    start_desc = opt_str(chk, f"{where}.start", start_in, "desc") or f"{mod['name']}, as it stands at the start."
    default_country = start_in.get("default_country", countries[0]["tag"] if countries else None)
    if countries and default_country not in seen_tags:
        chk.err(f"{where}.start.default_country", f"{default_country!r} is not one of the countries listed")
        default_country = countries[0]["tag"]

    if chk.errors and any(e.startswith(where) for e in chk.errors):
        return None
    return dict(settings, seed=seed, width=width, height=height, countries=countries,
                start={"date": date, "name": start_name, "desc": start_desc,
                       "default_country": default_country},
                prefix=mod["slug"].upper(), slug=mod["slug"])


def normalise_focus(w, f, chk):
    if not isinstance(f, dict):
        chk.err(w, "must be an object")
        return {"id": None}
    chk.unknown_keys(w, f, ("id", "name", "desc", "icon", "cost", "x", "y", "relative_to",
                            "prerequisites", "mutually_exclusive", "search_filters",
                            "available", "ai_will_do", "completion_reward"))
    fid = f.get("id")
    chk.check_id(f"{w}.id", fid, what="focus id")
    prereqs = []
    raw_pre = f.get("prerequisites", []) or []
    if not isinstance(raw_pre, list):
        chk.err(f"{w}.prerequisites", "must be a list; a string is one required focus, a list of strings is an OR group")
        raw_pre = []
    for gi, group in enumerate(raw_pre):
        ids = [group] if isinstance(group, str) else group
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            chk.err(f"{w}.prerequisites[{gi}]", "must be a focus id or a non-empty list of focus ids")
            continue
        prereqs.append(list(ids))
    mutex = f.get("mutually_exclusive", []) or []
    if not isinstance(mutex, list) or not all(isinstance(m, str) for m in mutex):
        chk.err(f"{w}.mutually_exclusive", "must be a list of focus ids")
        mutex = []
    filters = f.get("search_filters", []) or []
    if not isinstance(filters, list) or not all(isinstance(s, str) and FILTER_RE.match(s) for s in filters):
        chk.err(f"{w}.search_filters", 'must be a list such as ["FOCUS_FILTER_POLITICAL"]')
        filters = []
    cost = opt_number(chk, w, f, "cost", 5)
    if cost is not None and cost <= 0:
        chk.err(f"{w}.cost", "must be greater than 0 (1 unit is about one week by default)")
    x = opt_number(chk, w, f, "x", 0)
    y = opt_number(chk, w, f, "y", 0)
    return {
        "id": fid,
        "name": opt_str(chk, w, f, "name"),
        "desc": opt_str(chk, w, f, "desc"),
        "icon": opt_str(chk, w, f, "icon") or DEFAULT_ICON,
        "cost": cost,
        "x": int(x or 0),
        "y": int(y or 0),
        "relative_to": opt_str(chk, w, f, "relative_to"),
        "prerequisites": prereqs,
        "mutually_exclusive": mutex,
        "search_filters": filters,
        "available": as_list(f.get("available"), chk, f"{w}.available"),
        "ai_will_do": as_list(f.get("ai_will_do"), chk, f"{w}.ai_will_do"),
        "completion_reward": as_list(f.get("completion_reward"), chk, f"{w}.completion_reward"),
    }


def normalise_event(w, ns, ev, chk):
    if not isinstance(ev, dict):
        chk.err(w, "must be an object")
        return {"id": None, "hidden": False, "options": []}
    chk.unknown_keys(w, ev, ("id", "type", "title", "desc", "picture", "major", "hidden",
                             "fire_only_once", "is_triggered_only", "trigger",
                             "mean_time_to_happen", "immediate", "options"))
    eid = ev.get("id")
    if not isinstance(eid, str) or not EVENT_ID_RE.match(eid):
        chk.err(f"{w}.id", "must look like '<namespace>.<number>', e.g. 'tur_events.1'")
    elif eid.rsplit(".", 1)[0] != ns:
        chk.err(f"{w}.id", f"must start with the block's namespace '{ns}.'")
    etype = ev.get("type", "country_event")
    if etype not in GENERATABLE_EVENT_TYPES:
        chk.err(f"{w}.type", f"must be one of {', '.join(GENERATABLE_EVENT_TYPES)}")
        etype = "country_event"
    hidden = opt_bool(chk, w, ev, "hidden", False)
    mtth = as_list(ev.get("mean_time_to_happen"), chk, f"{w}.mean_time_to_happen")
    raw_opts = ev.get("options", []) or []
    if not isinstance(raw_opts, list):
        chk.err(f"{w}.options", "must be a list")
        raw_opts = []
    if not hidden and not raw_opts:
        chk.err(f"{w}.options", "a visible event needs at least one option (the player must be able to close it)")
    if len(raw_opts) > 26:
        chk.err(f"{w}.options", "at most 26 options are supported")
    options = []
    for oi, o in enumerate(raw_opts):
        ow = f"{w}.options[{oi}]"
        if not isinstance(o, dict):
            chk.err(ow, "must be an object")
            continue
        chk.unknown_keys(ow, o, ("text", "trigger", "ai_chance", "effects"))
        text = opt_str(chk, ow, o, "text")
        if text is None:
            chk.err(f"{ow}.text", "option text is required")
        options.append({
            "text": text,
            "trigger": as_list(o.get("trigger"), chk, f"{ow}.trigger"),
            "ai_chance": as_list(o.get("ai_chance"), chk, f"{ow}.ai_chance"),
            "effects": as_list(o.get("effects"), chk, f"{ow}.effects"),
        })
    title = opt_str(chk, w, ev, "title")
    desc = opt_str(chk, w, ev, "desc")
    if not hidden and not (title or desc):
        chk.err(w, "a visible event needs a 'title' or a 'desc' (HOI4 requires one unless the event is hidden)")
    major = opt_bool(chk, w, ev, "major", False)
    if major and etype != "news_event":
        chk.err(f"{w}.major", "only news events can be major")
    return {
        "id": eid, "type": etype, "title": title, "desc": desc,
        "picture": opt_str(chk, w, ev, "picture"), "major": major, "hidden": hidden,
        "fire_only_once": opt_bool(chk, w, ev, "fire_only_once", False),
        "is_triggered_only": opt_bool(chk, w, ev, "is_triggered_only", not mtth),
        "trigger": as_list(ev.get("trigger"), chk, f"{w}.trigger"),
        "mean_time_to_happen": mtth,
        "immediate": as_list(ev.get("immediate"), chk, f"{w}.immediate"),
        "options": options,
    }


def normalise_decision(w, d, chk):
    if not isinstance(d, dict):
        chk.err(w, "must be an object")
        return {"id": None}
    chk.unknown_keys(w, d, ("id", "name", "desc", "icon", "cost", "fire_only_once", "days_remove",
                            "allowed", "visible", "available", "complete_effect",
                            "remove_effect", "ai_will_do"))
    did = d.get("id")
    chk.check_id(f"{w}.id", did, what="decision id")
    days = d.get("days_remove")
    if days is not None and (isinstance(days, bool) or not isinstance(days, int)):
        chk.err(f"{w}.days_remove", "must be an integer number of days")
        days = None
    return {
        "id": did, "name": opt_str(chk, w, d, "name"), "desc": opt_str(chk, w, d, "desc"),
        "icon": opt_str(chk, w, d, "icon"),
        "cost": opt_number(chk, w, d, "cost", None),
        "fire_only_once": opt_bool(chk, w, d, "fire_only_once", False),
        "days_remove": days,
        "allowed": as_list(d.get("allowed"), chk, f"{w}.allowed"),
        "visible": as_list(d.get("visible"), chk, f"{w}.visible"),
        "available": as_list(d.get("available"), chk, f"{w}.available"),
        "complete_effect": as_list(d.get("complete_effect"), chk, f"{w}.complete_effect"),
        "remove_effect": as_list(d.get("remove_effect"), chk, f"{w}.remove_effect"),
        "ai_will_do": as_list(d.get("ai_will_do"), chk, f"{w}.ai_will_do"),
    }


def normalise_idea(w, it, chk):
    if not isinstance(it, dict):
        chk.err(w, "must be an object")
        return {"id": None}
    chk.unknown_keys(w, it, ("id", "name", "desc", "picture", "allowed", "modifier"))
    iid = it.get("id")
    chk.check_id(f"{w}.id", iid, what="idea id")
    pic = opt_str(chk, w, it, "picture")
    if pic and pic.startswith("GFX_idea_"):
        pic = pic[len("GFX_idea_"):]  # the game adds the GFX_idea_ prefix itself
    return {
        "id": iid, "name": opt_str(chk, w, it, "name"), "desc": opt_str(chk, w, it, "desc"),
        "picture": pic,
        "allowed": as_list(it.get("allowed"), chk, f"{w}.allowed"),
        "modifier": as_list(it.get("modifier"), chk, f"{w}.modifier"),
    }


# ============================================================================
# Rendering (build)
# ============================================================================

def emit_raw(out, depth, items):
    """Append raw script lines re-indented with tabs by brace depth (input indentation is ignored)."""
    pad = "\t" * depth
    for item in items:
        level = 0
        for raw in item.strip("\n").splitlines():
            s = raw.strip()
            if not s:
                out.append("")
                continue
            closers = len(s) - len(s.lstrip("}"))
            out.append(pad + "\t" * max(level - closers, 0) + s)
            level = max(level + s.count("{") - s.count("}"), 0)


def emit_block(out, depth, key, items):
    if not items:
        return
    pad = "\t" * depth
    out.append(f"{pad}{key} = {{")
    emit_raw(out, depth + 1, items)
    out.append(f"{pad}}}")


def num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def focus_tree_script(tree):
    out = [
        "focus_tree = {",
        f"\tid = {tree['id']}",
        "\tcountry = {",
        "\t\tfactor = 0",
        "\t\tmodifier = {",
        f"\t\t\tadd = {num(tree['score'])}",
        f"\t\t\toriginal_tag = {tree['country']}",
        "\t\t}",
        "\t}",
        f"\tdefault = {'yes' if tree['default'] else 'no'}",
        "",
    ]
    for index, f in enumerate(tree["focuses"]):
        if index:
            out.append("")
        out.append("\tfocus = {")
        out.append(f"\t\tid = {f['id']}")
        out.append(f"\t\ticon = {f['icon']}")
        out.append(f"\t\tx = {f['x']}")
        out.append(f"\t\ty = {f['y']}")
        if f["relative_to"]:
            out.append(f"\t\trelative_position_id = {f['relative_to']}")
        out.append(f"\t\tcost = {num(f['cost'])}")
        if f["search_filters"]:
            out.append("\t\tsearch_filters = { " + " ".join(f["search_filters"]) + " }")
        for group in f["prerequisites"]:
            if len(group) == 1:
                out.append(f"\t\tprerequisite = {{ focus = {group[0]} }}")
            else:  # one prerequisite block with several focus entries means OR
                out.append("\t\tprerequisite = { " + " ".join(f"focus = {g}" for g in group) + " }")
        if f["mutually_exclusive"]:
            out.append("\t\tmutually_exclusive = { " + " ".join(f"focus = {m}" for m in f["mutually_exclusive"]) + " }")
        emit_block(out, 2, "available", f["available"])
        emit_block(out, 2, "ai_will_do", f["ai_will_do"])
        emit_block(out, 2, "completion_reward", f["completion_reward"])
        out.append("\t}")
    out.append("}")
    return "\n".join(out) + "\n"


def decision_category_script(cat):
    out = [f"{cat['id']} = {{"]
    emit_block(out, 1, "allowed", cat["allowed"])
    emit_block(out, 1, "visible", cat["visible"])
    emit_block(out, 1, "available", cat["available"])
    if cat["icon"]:
        out.append(f"\ticon = {cat['icon']}")
    if cat["priority"] is not None:
        out.append(f"\tpriority = {cat['priority']}")
    if cat["visible_when_empty"]:
        out.append("\tvisible_when_empty = yes")
    out.append("}")
    return "\n".join(out) + "\n"


def decisions_script(cat):
    out = [f"{cat['id']} = {{"]
    for index, d in enumerate(cat["items"]):
        if index:
            out.append("")
        out.append(f"\t{d['id']} = {{")
        if d["icon"]:
            out.append(f"\t\ticon = {d['icon']}")
        if d["cost"] is not None:
            out.append(f"\t\tcost = {num(d['cost'])}")
        if d["days_remove"] is not None:
            out.append(f"\t\tdays_remove = {d['days_remove']}")
        if d["fire_only_once"]:
            out.append("\t\tfire_only_once = yes")
        for key in ("allowed", "visible", "available"):
            emit_block(out, 2, key, d[key])
        emit_block(out, 2, "complete_effect", d["complete_effect"])
        emit_block(out, 2, "remove_effect", d["remove_effect"])
        emit_block(out, 2, "ai_will_do", d["ai_will_do"])
        out.append("\t}")
    out.append("}")
    return "\n".join(out) + "\n"


def ideas_script(idea_cats):
    out = ["ideas = {"]
    for cat in idea_cats:
        out.append(f"\t{cat['category']} = {{")
        for it in cat["items"]:
            out.append(f"\t\t{it['id']} = {{")
            if it["picture"]:
                out.append(f"\t\t\tpicture = {it['picture']}")
            emit_block(out, 3, "allowed", it["allowed"])
            emit_block(out, 3, "modifier", it["modifier"])
            out.append("\t\t}")
        out.append("\t}")
    out.append("}")
    return "\n".join(out) + "\n"


def event_script(ns, events):
    out = [f"add_namespace = {ns}"]
    for ev in events:
        out.append("")
        eid, etype, hidden = ev["id"], ev["type"], ev["hidden"]
        out.append(f"{etype} = {{")
        out.append(f"\tid = {eid}")
        if not hidden and ev["title"]:
            out.append(f"\ttitle = {eid}.t")
        if not hidden and ev["desc"]:
            out.append(f"\tdesc = {eid}.d")
        if ev["picture"]:
            out.append(f"\tpicture = {ev['picture']}")
        if etype == "news_event" and ev["major"]:
            out.append("\tmajor = yes")
        if hidden:
            out.append("\thidden = yes")
        if ev["fire_only_once"]:
            out.append("\tfire_only_once = yes")
        if ev["is_triggered_only"]:
            out.append("\tis_triggered_only = yes")
        emit_block(out, 1, "trigger", ev["trigger"])
        emit_block(out, 1, "mean_time_to_happen", ev["mean_time_to_happen"])
        emit_block(out, 1, "immediate", ev["immediate"])
        for i, opt in enumerate(ev["options"]):
            out.append("")
            out.append("\toption = {")
            out.append(f"\t\tname = {eid}.{chr(97 + i)}")
            emit_block(out, 2, "trigger", opt["trigger"])
            emit_block(out, 2, "ai_chance", opt["ai_chance"])
            emit_raw(out, 2, opt["effects"])
            out.append("\t}")
        out.append("}")
    return "\n".join(out) + "\n"


# Sprite animation template taken from the HOI4 modding wiki (focus shine effect).
SHINE_ANIMATION = """\
\t\tanimation = {{
\t\t\tanimationmaskfile = {tex}
\t\t\tanimationtexturefile = gfx/interface/goals/shine_overlay.dds
\t\t\tanimationrotation = {rot}
\t\t\tanimationlooping = no
\t\t\tanimationtime = 0.75
\t\t\tanimationdelay = 0
\t\t\tanimationblendmode = "add"
\t\t\tanimationtype = "scrolling"
\t\t\tanimationrotationoffset = {{ x = 0.0 y = 0.0 }}
\t\t\tanimationtexturescale = {{ x = 1.0 y = 1.0 }}
\t\t}}
"""


def gfx_script(sprites):
    out = ["spriteTypes = {"]
    for s in sprites:
        out.append("\tspriteType = {")
        out.append(f"\t\tname = {s['name']}")
        out.append(f"\t\ttexturefile = {s['texture']}")
        out.append("\t}")
        if s["kind"] == "focus":  # focus icons need a matching _shine sprite
            out.append("\tspriteType = {")
            out.append(f"\t\tname = {s['name']}_shine")
            out.append(f"\t\ttexturefile = {s['texture']}")
            out.append("\t\teffectFile = gfx/FX/buttonstate.lua")
            out.append(SHINE_ANIMATION.format(tex=s["texture"], rot="-90.0").rstrip("\n"))
            out.append(SHINE_ANIMATION.format(tex=s["texture"], rot="90.0").rstrip("\n"))
            out.append("\t\tlegacy_lazy_load = no")
            out.append("\t}")
    out.append("}")
    return "\n".join(out) + "\n"


def descriptor_text(mod, path=None, replace_paths=()):
    lines = [f'name="{mod["name"]}"']
    if path:
        lines.append(f'path="{path}"')
    if mod.get("picture"):
        lines.append(f'picture="{mod["picture"]}"')
    lines.append(f'version="{mod["version"]}"')
    if mod["tags"]:
        lines.append("tags={")
        lines.extend(f'\t"{t}"' for t in mod["tags"])
        lines.append("}")
    lines.append(f'supported_version="{mod["supported_version"]}"')
    # replace_path empties a base-game folder, so a custom world does not mix with the real map and countries
    lines.extend(f'replace_path="{p}"' for p in replace_paths)
    return "\n".join(lines) + "\n"


class LocTable:
    def __init__(self, chk):
        self.chk = chk
        self.entries = {}

    def add(self, key, text, where):
        if text is None:
            return
        if not LOC_KEY_RE.match(key):
            self.chk.err(where, f"localisation key '{key}' contains characters HOI4 does not allow")
            return
        value = " ".join(str(text).split()).replace('"', "'")
        if key in self.entries and self.entries[key] != value:
            self.chk.err(where, f"localisation key '{key}' is used twice with different text")
            return
        self.entries[key] = value

    def render(self):
        lines = ["l_english:"]
        lines += [f' {k}:0 "{v}"' for k, v in self.entries.items()]
        return ("\n".join(lines) + "\n").encode("utf-8-sig")  # UTF-8 *with* BOM


def render_mod(model, chk):
    """Return a dict mapping relative path -> file bytes for the whole mod."""
    mod = model["mod"]
    slug = mod["slug"]
    files = {}
    loc = LocTable(chk)

    for tree in model["trees"]:
        w = f"focus_trees[{tree['id']}]"
        for f in tree["focuses"]:
            loc.add(f["id"], f["name"], w)
            loc.add(f["id"] + "_desc", f["desc"], w)
        files[f"common/national_focus/{slug}_{tree['id']}.txt"] = focus_tree_script(tree).encode("utf-8")

    for cat in model["decision_cats"]:
        w = f"decisions[{cat['id']}]"
        loc.add(cat["id"], cat["name"], w)
        loc.add(cat["id"] + "_desc", cat["desc"], w)
        for d in cat["items"]:
            loc.add(d["id"], d["name"], w)
            loc.add(d["id"] + "_desc", d["desc"], w)
        files[f"common/decisions/categories/{slug}_{cat['id']}.txt"] = decision_category_script(cat).encode("utf-8")
        files[f"common/decisions/{slug}_{cat['id']}.txt"] = decisions_script(cat).encode("utf-8")

    if model["idea_cats"]:
        for cat in model["idea_cats"]:
            for it in cat["items"]:
                loc.add(it["id"], it["name"], f"ideas[{it['id']}]")
                loc.add(it["id"] + "_desc", it["desc"], f"ideas[{it['id']}]")
        files[f"common/ideas/{slug}_ideas.txt"] = ideas_script(model["idea_cats"]).encode("utf-8")

    for block in model["events"]:
        ns = block["namespace"]
        for ev in block["events"]:
            if ev["id"] is None:
                continue
            w = f"events[{ev['id']}]"
            if not ev["hidden"]:
                loc.add(ev["id"] + ".t", ev["title"], w)
                loc.add(ev["id"] + ".d", ev["desc"], w)
            for i, opt in enumerate(ev["options"]):
                loc.add(f"{ev['id']}.{chr(97 + i)}", opt["text"], w)
        files[f"events/{slug}_{ns.replace('.', '_')}.txt"] = event_script(ns, block["events"]).encode("utf-8")

    if model["sprites"]:
        files[f"interface/{slug}_sprites.gfx"] = gfx_script(model["sprites"]).encode("utf-8")

    for k, v in model["loc_extra"].items():
        loc.add(k, v, "localisation")

    replace_paths = ()
    if model.get("world"):
        try:
            world = hoi4_world.build_world(model["world"])
        except hoi4_world.WorldError as exc:
            chk.err("world", str(exc))
            return files
        world_files, world_loc, replace_paths = hoi4_world.world_files(world)
        files.update(world_files)
        for key, text in world_loc:
            loc.add(key, text, "world")
        model["world_obj"] = world
        model["replace_paths"] = replace_paths
    files[f"localisation/english/{slug}_l_english.yml"] = loc.render()

    files["descriptor.mod"] = descriptor_text(mod, replace_paths=replace_paths).encode("utf-8")
    return files


def write_mod_files(root, files):
    """Write the files, then delete files an earlier build wrote that this build no longer makes."""
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / MANIFEST_NAME
    previous = []
    if manifest.exists():
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8")).get("files", [])
        except (OSError, ValueError):
            previous = []
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    root_resolved = str(root.resolve())
    for rel in previous:
        if rel in files:
            continue
        target = root / rel
        if target.is_file() and str(target.resolve()).startswith(root_resolved):
            target.unlink()
    manifest.write_text(json.dumps({"generator": "hoi4_mod.py", "files": sorted(files)}, indent=2) + "\n",
                        encoding="utf-8")


def launcher_path(root, user_dir):
    try:
        return root.resolve().relative_to(user_dir.resolve()).as_posix()
    except ValueError:
        return root.resolve().as_posix()


def print_spec_errors(errors):
    print("[ERROR] the spec has problems, so nothing was written:")
    for e in errors:
        print(f"  - {e}")


def cmd_build(args):
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"[ERROR] cannot read spec {args.spec}: {exc}")
        return 2
    if not args.out and not args.user_dir:
        print("[ERROR] choose where the mod goes: --user-dir DIR (your HOI4 user folder) or --out DIR")
        return 2
    chk = SpecChecker()
    model = normalise(spec, chk)
    if model is None or chk.errors:
        print_spec_errors(chk.errors)
        return 2
    files = render_mod(model, chk)
    if chk.errors:
        print_spec_errors(chk.errors)
        return 2

    slug = model["mod"]["slug"]
    user_dir = Path(args.user_dir) if args.user_dir else None
    root = Path(args.out) if args.out else user_dir / "mod" / slug
    write_mod_files(root, files)
    print(f"Wrote {len(files)} files to {root}")
    for rel in sorted(files):
        print(f"  {rel}")
    world = model.get("world_obj")
    if world is not None:
        print(f"World: {world.summary()}")
    if args.preview:
        if world is None:
            print("[WARN] --preview needs a \"world\" in the spec; no picture was written")
        else:
            Path(args.preview).parent.mkdir(parents=True, exist_ok=True)
            Path(args.preview).write_bytes(hoi4_world.preview_png(world))
            print(f"Preview picture: {args.preview} (a rough picture of the map; not the game's view)")
    if user_dir is not None:
        launcher = user_dir / "mod" / f"{slug}.mod"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(descriptor_text(model["mod"], path=launcher_path(root, user_dir),
                                            replace_paths=model.get("replace_paths", ())), encoding="utf-8")
        print(f"Launcher descriptor: {launcher}")
    if args.no_validate:
        return 0
    print()
    rep = validate_mod(root)
    print_report(rep)
    return 1 if rep.count("ERROR") else 0


# ============================================================================
# Validation
# ============================================================================

class Report:
    def __init__(self):
        self.items = []  # (level, path, line, message)
        self.files = 0

    def add(self, level, path, line, msg):
        self.items.append((level, path, line or 0, msg))

    def count(self, level):
        return sum(1 for it in self.items if it[0] == level)


def print_report(rep):
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    for level, path, line, msg in sorted(rep.items, key=lambda it: (order[it[0]], it[1], it[2])):
        where = f"{path}:{line}" if line else path
        print(f"[{level:5}] {where}: {msg}")
    print(f"Checked {rep.files} files: {rep.count('ERROR')} error(s), "
          f"{rep.count('WARN')} warning(s), {rep.count('INFO')} note(s).")


class State:
    """Facts gathered from every file; cross-checked after all files are read."""

    def __init__(self):
        self.trees = []          # dict(id, file, line, default, has_score)
        self.focuses = []        # dict(id, tree, file, line, prereqs, mutex, x, y, rel, has_offset)
        self.focus_refs = []     # (focus id, file, line)
        self.cat_defs = {}       # decision category id -> [(file, line)]
        self.decisions = []      # dict(id, cat, file, line)
        self.ideas = []          # dict(id, file, line, picture)
        self.events = []         # dict(id, file, line, hidden, title, desc, options, picture)
        self.event_refs = []     # (event id, file, line)
        self.ns_issues = []      # (event id, namespace, file, line) - namespace not declared before use
        self.namespaces = set()  # every add_namespace seen anywhere in the mod
        self.sprites = {}        # sprite name -> [(file, line, texture)]
        self.loc = {}            # key -> [(file, line, value)]
        self.loc_needed = []     # (key, file, line, level, what)
        self.sprite_needed = []  # (sprite name, file, line, what)


def classify(rel):
    if rel == "descriptor.mod":
        return "descriptor"
    if rel.startswith("localisation/") and rel.endswith(".yml"):
        return "loc"
    if rel.startswith("interface/") and rel.endswith(".gfx"):
        return "gfx"
    if not rel.endswith(".txt"):
        return None
    if rel.startswith("common/national_focus/"):
        return "focus"
    if rel.startswith("common/decisions/categories/"):
        return "decision_categories"
    if rel.startswith("common/decisions/"):
        return "decisions"
    if rel.startswith("common/ideas/"):
        return "ideas"
    if rel.startswith("events/"):
        return "events"
    if rel.startswith(("common/", "history/", "map/")):
        return "script"
    return None


def read_utf8(path):
    """Return (text, has_bom) or (None, message)."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig"), raw.startswith(b"\xef\xbb\xbf")
    except UnicodeDecodeError as exc:
        return None, f"file is not valid UTF-8 (problem at byte {exc.start}); re-save it as UTF-8"


def loc_keys_of(node):
    """Keys used by a title/desc/name value: a plain key, or { text = key trigger = ... } blocks."""
    if node is None:
        return []
    if not node.is_block:
        return [node.value]
    return [c.value for c in node.value if c.key == "text" and not c.is_block]


def icon_names(node):
    if node is None:
        return []
    if not node.is_block:
        return [node.value]
    return [c.key for c in node.value if c.key]


LOC_FILE_RE = re.compile(r"_l_([a-z_]+)\.yml$")   # the language comes from the file name; the folder is free


def check_loc_file(rel, path, rep, st):
    if path.read_bytes()[:3] != b"\xef\xbb\xbf":
        rep.add("ERROR", rel, 1, "localisation file has no UTF-8 BOM - save it as 'UTF-8-BOM' or the game may ignore it")
    text, info = read_utf8(path)
    if text is None:
        rep.add("ERROR", rel, 1, info)
        return
    match = LOC_FILE_RE.search(path.name)
    if match is None:
        want = ("English localisation filenames must end with _l_english.yml" if "/english/" in rel
                else "localisation filenames must end with _l_<language>.yml")
        rep.add("ERROR", rel, 1, f"{want} (lowercase L); the game ignores files without a language name")
        language = None
    else:
        language = match.group(1)
    lines = text.splitlines()
    header_line = next((i for i, ln in enumerate(lines, 1) if ln.strip() and not ln.strip().startswith("#")), None)
    if header_line is None:
        rep.add("ERROR", rel, 1, "localisation file is empty; its first line must be 'l_<language>:'")
        return
    if language is not None:
        expected = f"l_{language}:"
        if lines[header_line - 1].split("#")[0].strip() != expected:
            rep.add("ERROR", rel, header_line,
                    f"first line must be '{expected}' (found '{lines[header_line - 1].strip()[:40]}')")
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#") or i == header_line:
            continue
        m = LOC_LINE_RE.match(line)
        if not m:
            rep.add("ERROR", rel, i, 'malformed localisation line (expected:  key:0 "text")')
            continue
        key, value = m.group(1), m.group(3)
        if re.search(r'(?<!\\)"', value):   # \" is fine; a bare quote ends the string early
            rep.add("WARN", rel, i, 'unescaped double quote inside the text; write \\" so the string does not end early')
        st.loc.setdefault(key, []).append((rel, i, value))


def collect_focus(rel, nodes, rep, st):
    def add_focus(node, tree_id):
        fid = scalar(first(node.value, "id"))
        if not fid:
            rep.add("ERROR", rel, node.line, "focus has no 'id'")
            return
        prereqs = []
        for p in blocks(node.value, "prerequisite"):
            ids = [c.value for c in p.value if c.key == "focus" and not c.is_block]
            if ids:
                prereqs.append(ids)
        mutex = []
        for m in blocks(node.value, "mutually_exclusive"):
            mutex += [c.value for c in m.value if c.key == "focus" and not c.is_block]
        cost = scalar(first(node.value, "cost"))
        if cost is not None:
            try:
                if float(cost) <= 0:
                    rep.add("WARN", rel, node.line, f"focus {fid} has cost {cost}; it must be greater than 0")
            except ValueError:
                rep.add("ERROR", rel, node.line, f"focus {fid} has a non-numeric cost '{cost}'")
        st.focuses.append({
            "id": fid, "tree": tree_id, "file": rel, "line": node.line,
            "prereqs": prereqs, "mutex": mutex,
            "x": to_int(scalar(first(node.value, "x")), 0), "y": to_int(scalar(first(node.value, "y")), 0),
            "rel": scalar(first(node.value, "relative_position_id")),
            "has_offset": first(node.value, "offset") is not None,
        })
        for icon in icon_names(first(node.value, "icon")):
            st.sprite_needed.append((icon, rel, node.line, f"icon of focus {fid}"))
            if icon.startswith("GFX_"):
                st.sprite_needed.append((icon + "_shine", rel, node.line, f"shine sprite of focus {fid}"))
        st.loc_needed.append((fid, rel, node.line, "WARN", f"name of focus {fid}"))
        st.loc_needed.append((fid + "_desc", rel, node.line, "INFO", f"description of focus {fid}"))

    for n in nodes:
        if not n.is_block:
            continue
        if n.key == "focus_tree":
            tid = scalar(first(n.value, "id"))
            has_score = any(first(c.value, "modifier") is not None for c in blocks(n.value, "country"))
            st.trees.append({"id": tid, "file": rel, "line": n.line,
                             "default": scalar(first(n.value, "default")) == "yes", "has_score": has_score})
            if not has_score:
                rep.add("WARN", rel, n.line,
                        f"focus tree {tid} has no country = {{ modifier = {{ ... }} }} score, so no country will load it")
            for f in blocks(n.value, "focus"):
                add_focus(f, tid)
        elif n.key in ("shared_focus", "joint_focus"):
            add_focus(n, None)


def collect_decisions(rel, nodes, st):
    for cat in nodes:
        if not (cat.key and cat.is_block):
            continue
        for d in cat.value:
            if d.key and d.is_block:
                st.decisions.append({"id": d.key, "cat": cat.key, "file": rel, "line": d.line})
                st.loc_needed.append((d.key, rel, d.line, "WARN", f"name of decision {d.key}"))
                st.loc_needed.append((d.key + "_desc", rel, d.line, "INFO", f"description of decision {d.key}"))


def collect_ideas(rel, nodes, st):
    for top in nodes:
        if top.key != "ideas" or not top.is_block:
            continue
        for cat in top.value:
            if not (cat.key and cat.is_block):
                continue
            for idea in cat.value:
                if idea.key and idea.is_block:
                    picture = scalar(first(idea.value, "picture"))
                    st.ideas.append({"id": idea.key, "file": rel, "line": idea.line, "picture": picture})
                    if picture:  # the game looks for GFX_idea_<picture>
                        st.sprite_needed.append((f"GFX_idea_{picture}", rel, idea.line, f"picture of idea {idea.key}"))
                    # name and desc default to the idea id, but an explicit key wins (Beyond Earth shares one name)
                    name_key = scalar(first(idea.value, "name")) or idea.key
                    desc_key = scalar(first(idea.value, "desc")) or idea.key + "_desc"
                    st.loc_needed.append((name_key, rel, idea.line, "WARN", f"name of idea {idea.key}"))
                    st.loc_needed.append((desc_key, rel, idea.line, "INFO", f"description of idea {idea.key}"))


def collect_events(rel, nodes, rep, st):
    declared_here = set()
    for n in nodes:
        if n.key == "add_namespace" and scalar(n):
            declared_here.add(scalar(n))
            st.namespaces.add(scalar(n))
            continue
        if n.key not in EVENT_TYPES or not n.is_block:
            continue
        eid = scalar(first(n.value, "id"))
        if not eid:
            rep.add("ERROR", rel, n.line, f"{n.key} has no 'id'")
            continue
        if not EVENT_ID_RE.match(eid):
            rep.add("ERROR", rel, n.line, f"event id '{eid}' must look like <namespace>.<integer>")
            continue
        ns = eid.rsplit(".", 1)[0]
        if ns not in declared_here:
            st.ns_issues.append((eid, ns, rel, n.line))
        hidden = scalar(first(n.value, "hidden")) == "yes"
        title = loc_keys_of(first(n.value, "title"))
        desc = loc_keys_of(first(n.value, "desc"))
        picture = scalar(first(n.value, "picture"))
        options = [{"name": loc_keys_of(first(o.value, "name")), "line": o.line} for o in blocks(n.value, "option")]
        st.events.append({"id": eid, "file": rel, "line": n.line, "hidden": hidden,
                          "title": title, "desc": desc, "options": options, "picture": picture})
        if not hidden and not (title or desc):
            rep.add("ERROR", rel, n.line, f"event {eid} has neither 'title' nor 'desc' (required unless hidden)")
        if not hidden and not options:
            rep.add("WARN", rel, n.line, f"event {eid} has no options; the player cannot close it")
        for key in title:
            st.loc_needed.append((key, rel, n.line, "WARN", f"title of event {eid}"))
        for key in desc:
            st.loc_needed.append((key, rel, n.line, "WARN", f"description of event {eid}"))
        for o in options:
            for key in o["name"]:
                st.loc_needed.append((key, rel, o["line"], "WARN", f"option text of event {eid}"))
        if picture and not picture.startswith("["):
            st.sprite_needed.append((picture, rel, n.line, f"picture of event {eid}"))


def collect_sprites(rel, nodes, st):
    for n, _depth in walk(nodes):
        if not n.is_block:
            continue
        name = scalar(first(n.value, "name"))
        tex = scalar(first(n.value, "texturefile"))
        if name and tex:
            st.sprites.setdefault(name, []).append((rel, n.line, tex))


def collect_refs(rel, nodes, st):
    """Event and focus references anywhere in a script file (definitions are skipped)."""
    for n, depth in walk(nodes):
        if n.key in EVENT_TYPES and depth > 0:
            target = scalar(first(n.value, "id")) if n.is_block else n.value
            if target:
                st.event_refs.append((target, rel, n.line))
        if n.key in FOCUS_REF_KEYS:
            if n.is_block:
                st.focus_refs += [(c.value, rel, n.line) for c in n.value if c.key == "focus" and not c.is_block]
            elif n.value:
                st.focus_refs.append((n.value, rel, n.line))


def check_focus_layout(st, rep):
    """Overlapping focuses and broken relative positions, tree by tree."""
    for tid in sorted({f["tree"] for f in st.focuses if f["tree"] is not None}):
        members = [f for f in st.focuses if f["tree"] == tid]
        by_id = {f["id"]: f for f in members}
        resolved = {}

        def position(fid, seen=()):
            if fid in resolved:
                return resolved[fid]
            f = by_id[fid]
            x, y = f["x"], f["y"]
            if f["rel"] and f["rel"] in by_id and f["rel"] not in seen:
                px, py = position(f["rel"], seen + (fid,))
                x, y = px + x, py + y
            elif f["rel"] and f["rel"] not in by_id:
                rep.add("WARN", f["file"], f["line"],
                        f"focus {fid} is positioned relative to {f['rel']}, which is not in the same tree")
            resolved[fid] = (x, y)
            return resolved[fid]

        cells = {}
        for f in members:
            if not f["has_offset"]:
                cells.setdefault(position(f["id"]), []).append(f)
        for cell, group in cells.items():
            if len(group) > 1:
                names = ", ".join(g["id"] for g in group)
                rep.add("WARN", group[0]["file"], group[0]["line"],
                        f"focuses {names} occupy the same grid position {cell}")


def validate_mod(root):
    root = Path(root)
    rep = Report()
    if not root.is_dir():
        rep.add("ERROR", str(root), 0, "mod folder does not exist")
        return rep
    st = State()

    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name == MANIFEST_NAME:
            continue
        rel = p.relative_to(root).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        files.append((rel, p))

    # ---- read and parse every file -------------------------------------------
    for rel, p in files:
        kind = classify(rel)
        if kind is None:
            continue
        rep.files += 1
        if kind == "loc":
            check_loc_file(rel, p, rep, st)
            continue
        text, info = read_utf8(p)
        if text is None:
            rep.add("ERROR", rel, 0, info)
            continue
        nodes, errors = parse_script(text)
        for line, msg in errors:
            rep.add("ERROR", rel, line, msg)
        if kind == "descriptor":
            if scalar(first(nodes, "name")) is None:
                rep.add("ERROR", rel, 1, "descriptor.mod has no name")
            if first(nodes, "supported_version") is None:
                rep.add("WARN", rel, 1, "no supported_version; the launcher cannot tell which game version this suits")
            if first(nodes, "path") is not None:
                rep.add("WARN", rel, 1, "'path' belongs only in the user-specific .mod file, not in descriptor.mod")
            pic = scalar(first(nodes, "picture"))
            if pic and not (root / pic).is_file():
                rep.add("WARN", rel, 1, f"picture '{pic}' not found in the mod folder")
            continue
        if kind == "gfx":
            collect_sprites(rel, nodes, st)
            continue
        if kind == "focus":
            collect_focus(rel, nodes, rep, st)
        elif kind == "decision_categories":
            for n in nodes:
                if n.key and n.is_block:
                    st.cat_defs.setdefault(n.key, []).append((rel, n.line))
        elif kind == "decisions":
            collect_decisions(rel, nodes, st)
        elif kind == "ideas":
            collect_ideas(rel, nodes, st)
        elif kind == "events":
            collect_events(rel, nodes, rep, st)
        collect_refs(rel, nodes, st)

    # ---- mod folder ----------------------------------------------------------
    if not (root / "descriptor.mod").is_file():
        rep.add("ERROR", str(root), 0, "descriptor.mod is missing; HOI4 will not recognise this folder as a mod")
    if root.parent.name == "mod":
        launcher = root.parent / f"{root.name}.mod"
        if not launcher.is_file():
            rep.add("WARN", str(root), 0,
                    f"no launcher descriptor at {launcher}; the mod will not appear in the HOI4 launcher")
    if any(ord(ch) > 127 for ch in str(root.resolve())):
        rep.add("WARN", str(root), 0, "the mod path contains non-ASCII characters; HOI4 cannot load mods from such paths")

    # ---- duplicates ----------------------------------------------------------
    def dupes(items, label):
        seen = {}
        for item_id, where, line in items:
            if item_id is None:
                continue
            if item_id in seen:
                rep.add("ERROR", where, line,
                        f"duplicate {label} '{item_id}' (first defined in {seen[item_id][0]}:{seen[item_id][1]})")
            else:
                seen[item_id] = (where, line)

    dupes([(t["id"], t["file"], t["line"]) for t in st.trees], "focus tree id")
    dupes([(f["id"], f["file"], f["line"]) for f in st.focuses], "focus id")
    dupes([(d["id"], d["file"], d["line"]) for d in st.decisions], "decision id")
    dupes([(i["id"], i["file"], i["line"]) for i in st.ideas], "idea id")
    dupes([(e["id"], e["file"], e["line"]) for e in st.events], "event id")
    for name, locs in st.sprites.items():
        if len(locs) > 1:
            rep.add("WARN", locs[-1][0], locs[-1][1], f"sprite {name} is defined more than once; only one definition is used")
    for cid, locs in st.cat_defs.items():
        if len(locs) > 1:
            rep.add("WARN", locs[-1][0], locs[-1][1], f"decision category {cid} is defined more than once")
    for key, entries in st.loc.items():
        if len(entries) > 1:
            first_file, first_line, _ = entries[0]
            other_file, other_line, _ = entries[-1]
            rep.add("WARN", other_file, other_line,
                    f"localisation key '{key}' is defined more than once (first at {first_file}:{first_line}); "
                    "only one value can be used, so keep a single definition")

    # ---- focus trees ---------------------------------------------------------
    defaults = [t for t in st.trees if t["default"]]
    if defaults:
        rep.add("WARN", defaults[0]["file"], defaults[0]["line"],
                "focus tree sets default = yes; the base game already has a default tree - only do this when replacing it")
    focus_by_id = {}
    for f in st.focuses:
        focus_by_id.setdefault(f["id"], f)
    for f in st.focuses:
        for group in f["prereqs"]:
            for target in group:
                t = focus_by_id.get(target)
                if t is None:
                    rep.add("WARN", f["file"], f["line"],
                            f"focus {f['id']} requires {target}, which this mod does not define (fine only for a base-game focus)")
                elif f["tree"] is not None and t["tree"] != f["tree"]:
                    rep.add("WARN", f["file"], f["line"],
                            f"focus {f['id']} requires {target}, which is in another focus tree; it may not draw a prerequisite line in the tree view")
        for target in f["mutex"]:
            if target not in focus_by_id:
                rep.add("WARN", f["file"], f["line"],
                        f"focus {f['id']} lists {target} as mutually exclusive, but this mod does not define it")
    for target, rel, line in st.focus_refs:
        if target not in focus_by_id:
            rep.add("WARN", rel, line,
                    f"focus {target} is referenced but this mod does not define it (fine only for a base-game focus)")
    check_focus_layout(st, rep)

    # ---- events --------------------------------------------------------------
    for eid, ns, rel, line in st.ns_issues:
        if ns in st.namespaces:
            rep.add("WARN", rel, line,
                    f"event {eid}: namespace '{ns}' is declared in another file; declare 'add_namespace = {ns}' in this file before the event")
        else:
            rep.add("ERROR", rel, line,
                    f"event {eid}: namespace '{ns}' is never declared; add 'add_namespace = {ns}' above the events "
                    "(without it the event ID is malformed and the event never fires)")
    defined_events = {e["id"] for e in st.events}
    for target, rel, line in st.event_refs:
        if target not in defined_events and not target.startswith("["):
            rep.add("WARN", rel, line,
                    f"event {target} is fired but this mod does not define it (fine only for a base-game event)")

    # ---- decisions and ideas -------------------------------------------------
    for d in st.decisions:
        if d["cat"] not in st.cat_defs:
            rep.add("WARN", d["file"], d["line"],
                    f"decision {d['id']} is in category '{d['cat']}', which this mod does not define in "
                    "common/decisions/categories (fine only for a base-game category)")
    for idea in st.ideas:
        if idea["picture"] is None and f"GFX_idea_{idea['id']}" not in st.sprites:
            rep.add("INFO", idea["file"], idea["line"],
                    f"idea {idea['id']} has no GFX_idea_{idea['id']} sprite, so the default icon is shown")

    # ---- sprites -------------------------------------------------------------
    for name, locs in st.sprites.items():
        for rel, line, tex in locs:
            if tex and not (root / tex).is_file():
                rep.add("WARN", rel, line,
                        f"texture '{tex}' for sprite {name} is not in the mod folder (fine only for base-game files)")
    reported = set()
    for name, rel, line, what in st.sprite_needed:
        if name in st.sprites or name in reported or name.startswith("["):
            continue
        reported.add(name)
        if what.startswith("shine sprite"):
            base = name[: -len("_shine")]
            if base in st.sprites:  # the icon belongs to this mod, so its shine sprite is required too
                rep.add("WARN", rel, line, f"{what}: {name} is not defined, so the icon will not shine")
            continue
        if what.startswith("icon of focus") and name.startswith("GFX_goal_"):
            continue  # base-game goal icon
        if what.startswith("picture of event") and name.startswith("GFX_report_event_"):
            continue  # base-game event picture
        rep.add("WARN", rel, line, f"{what}: sprite {name} is not defined in this mod (fine only for base-game sprites)")

    # ---- custom maps and worlds (any folder with map/definition.csv) ------------
    if (root / "map" / "definition.csv").is_file():
        hoi4_world.check_world(root, rep, st, parse_script)

    # ---- localisation coverage -----------------------------------------------
    reported = set()
    missing_desc = {}  # file -> count of descriptions without localisation (summarised as one note)
    for key, rel, line, level, what in st.loc_needed:
        if key in st.loc or key in reported or key.startswith("["):
            continue
        reported.add(key)
        if level == "INFO":
            missing_desc[rel] = missing_desc.get(rel, 0) + 1
            continue
        rep.add(level, rel, line, f"no localisation for {what} (key '{key}'); the raw key shows in game")
    for rel, count in sorted(missing_desc.items()):
        rep.add("INFO", rel, 0, f"{count} description(s) have no localisation; descriptions are optional, "
                                "but without them the raw key shows in the tooltip")
    return rep


# ============================================================================
# Command line
# ============================================================================

def cmd_validate(args):
    rep = validate_mod(args.mod_dir)
    print_report(rep)
    failed = rep.count("ERROR") or (args.strict and rep.count("WARN"))
    return 1 if failed else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        # Windows consoles may not show every character; a report must never crash on printing.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Build and check Hearts of Iron IV mods.")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="write a mod from a JSON spec, then validate it")
    b.add_argument("spec", help="path to the JSON spec")
    b.add_argument("--user-dir", help="HOI4 user folder: writes DIR/mod/<slug>/ and DIR/mod/<slug>.mod")
    b.add_argument("--out", help="write the mod folder here instead (no launcher file is written)")
    b.add_argument("--no-validate", action="store_true", help="skip the validation pass")
    b.add_argument("--preview", metavar="PNG", help="for a spec with a \"world\": also save a PNG picture of the map")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("validate", help="check an existing mod folder")
    v.add_argument("mod_dir", help="mod folder (the one that contains descriptor.mod)")
    v.add_argument("--strict", action="store_true", help="treat warnings as failures")
    v.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
