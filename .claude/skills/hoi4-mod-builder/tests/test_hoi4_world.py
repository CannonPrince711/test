"""Tests for custom worlds: the generated map, regions, states, countries and bookmark, plus the
validator checks that cover them. Run from the repository root with:

    python3 -m unittest discover -s .claude/skills/hoi4-mod-builder/tests
"""
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "hoi4_mod.py"
WORLD_EXAMPLE = SKILL / "examples" / "world.example.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# terrain.bmp palette index for each terrain, from the base game's common/terrain/00_terrain.txt
TERRAIN_INDEX = {"plains": 0, "forest": 1, "hills": 2, "desert": 3, "mountain": 6, "marsh": 9,
                 "lakes": 14, "urban": 13, "jungle": 21, "ocean": 15, "unknown": 0}


def run(*args):
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def world_spec(**world):
    """A 512x256 world with three countries (builds in about a second). Keyword args override the world."""
    body = {
        "seed": 7, "width": 512, "height": 256,
        "province_size": 120, "state_size": 5, "region_size": 12, "sea_region_size": 20,
        "max_continents": 5,
        "countries": [
            {"tag": "ZAL", "name": "Zalvoria", "ideology": "democratic", "color": [70, 130, 200]},
            {"tag": "KRV", "name": "Kravia", "ideology": "fascism"},
            {"tag": "ORN", "name": "Ornland", "ideology": "communism"},
        ],
        "start": {"date": "1936.1.1.12", "name": "Smoke World, 1936", "desc": "Test start.",
                  "default_country": "ZAL"},
    }
    body.update(world)
    return {"mod": {"name": "Smoke World", "slug": "smoke_world", "version": "1.0.0"}, "world": body}


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def text(path):
    return path.read_text(encoding="utf-8-sig")


def definitions(root):
    """province id -> rgb, kind (land/sea/lake), terrain and continent, from map/definition.csv."""
    out = {}
    for line in text(root / "map/definition.csv").splitlines():
        if line.strip():
            parts = line.split(";")
            out[int(parts[0])] = {"rgb": tuple(int(v) for v in parts[1:4]), "kind": parts[4],
                                  "terrain": parts[6], "continent": int(parts[7])}
    return out


def province_lists(body):
    """Every provinces = { ... } block in a region or state file, as lists of province ids."""
    return [[int(v) for v in re.findall(r"\d+", block)]
            for block in re.findall(r"provinces = \{([^}]*)\}", body)]


def count_listings(root, folder):
    """How many times each province id is listed across the region or state files of one folder."""
    counts = Counter()
    for path in sorted((root / folder).glob("*.txt")):
        for block in province_lists(text(path)):
            counts.update(block)
    return counts


def region_of(root):
    """province id -> strategic region id (the last listing wins; the exactly-one test catches repeats)."""
    out = {}
    for path in sorted((root / "map/strategicregions").glob("*.txt")):
        body = text(path)
        rid = int(re.search(r"\bid = (\d+)", body).group(1))
        for block in province_lists(body):
            for pid in block:
                out[pid] = rid
    return out


def states(root):
    out = []
    for path in sorted((root / "history/states").glob("*.txt")):
        body = text(path)
        out.append({
            "id": int(re.search(r"\bid = (\d+)", body).group(1)),
            "owner": re.search(r"owner = (\w+)", body).group(1),
            "provinces": [p for block in province_lists(body) for p in block],
            "vp": int(re.search(r"victory_points = \{ (\d+) \d+ \}", body).group(1)),
            "path": path,
        })
    return out


def continent_names(root):
    return re.search(r"continents = \{([^}]*)\}", text(root / "map/continent.txt")).group(1).split()


def bitmap_rows(path, bpp):
    """(width, height, rows) for an uncompressed bitmap; rows[0] is the first row in the file."""
    data = path.read_bytes()
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    assert struct.unpack_from("<H", data, 28)[0] == bpp, path
    height = abs(height)
    stride = (width * bpp // 8 + 3) // 4 * 4
    rows = [data[offset + r * stride: offset + r * stride + width * bpp // 8] for r in range(height)]
    return width, height, rows


def add_province(path, pid):
    """Put a province id into the first provinces block of a state or region file."""
    body = text(path)
    new = re.sub(r"(provinces = \{\n\t\t)", lambda m: m.group(1) + f"{pid} ", body, count=1)
    assert new != body, path
    path.write_text(new, encoding="utf-8")


def set_provinces(path, ids):
    """Replace the province list of a state or region file with ids."""
    body = text(path)
    new = re.sub(r"provinces = \{[^}]*\}", lambda m: "provinces = {\n\t\t" + " ".join(map(str, ids)) + "\n\t}",
                 body, count=1)
    assert new != body, path
    path.write_text(new, encoding="utf-8")


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class WorldFixture(unittest.TestCase):
    """Builds one small world per test class. Tests that damage the world work on a copy."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hoi4world_"))
        cls.spec = cls.tmp / "spec.json"
        write(cls.spec, json.dumps(world_spec()))
        cls.base = cls.tmp / "base"
        code, log = run("build", str(cls.spec), "--out", str(cls.base),
                        "--preview", str(cls.tmp / "preview.png"))
        if code != 0:
            raise RuntimeError(log)
        cls.build_log = log
        cls.defs = definitions(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        root = Path(tempfile.mkdtemp(prefix="hoi4copy_"))
        self.addCleanup(shutil.rmtree, root, True)
        dest = root / "mod"
        shutil.copytree(self.base, dest)
        return dest


class WorldBuildTests(WorldFixture):
    def test_build_validates_with_no_errors(self):
        self.assertIn("0 error(s)", self.build_log)
        code, out = run("validate", str(self.base))
        self.assertEqual(code, 0, out)

    def test_preview_png_is_written(self):
        self.assertEqual((self.tmp / "preview.png").read_bytes()[:8], PNG_SIGNATURE)

    def test_every_province_is_in_exactly_one_strategic_region(self):
        counts = count_listings(self.base, "map/strategicregions")
        for pid in self.defs:
            if pid:  # province 0 is the reserved black entry
                self.assertEqual(counts[pid], 1, f"province {pid}")

    def test_every_land_province_is_in_exactly_one_state_and_sea_in_none(self):
        counts = count_listings(self.base, "history/states")
        for pid, d in self.defs.items():
            if pid == 0:
                continue
            if d["kind"] == "land":
                self.assertEqual(counts[pid], 1, f"land province {pid}")
            else:
                self.assertEqual(counts[pid], 0, f"sea province {pid}")

    def test_each_state_lies_in_one_strategic_region(self):
        region = region_of(self.base)
        for s in states(self.base):
            self.assertEqual(len({region[p] for p in s["provinces"]}), 1, f"state {s['id']}")

    def test_victory_point_is_a_province_of_its_state(self):
        for s in states(self.base):
            self.assertIn(s["vp"], s["provinces"], f"state {s['id']}")

    def test_continents_are_one_to_k_on_land_and_zero_at_sea(self):
        k = len(continent_names(self.base))
        used = set()
        for pid, d in self.defs.items():
            if pid == 0:
                continue
            if d["kind"] == "land":
                self.assertTrue(1 <= d["continent"] <= k, f"province {pid} has continent {d['continent']}")
                used.add(d["continent"])
            else:
                self.assertEqual(d["continent"], 0, f"sea province {pid}")
        self.assertEqual(used, set(range(1, k + 1)))

    def test_continent_names_have_localisation(self):
        loc = text(next((self.base / "localisation/english").glob("*.yml")))
        names = continent_names(self.base)
        self.assertTrue(names)
        for name in names:
            self.assertIn(f" {name}:0 ", loc)

    def test_province_colours_are_unique(self):
        colours = Counter(d["rgb"] for d in self.defs.values())
        self.assertEqual([c for c, n in colours.items() if n > 1], [])

    def test_land_uses_several_terrains(self):
        terrains = {d["terrain"] for d in self.defs.values() if d["kind"] == "land"}
        self.assertGreaterEqual(len(terrains), 4, terrains)

    def test_terrain_bitmap_matches_each_province_terrain(self):
        w, h, prov = bitmap_rows(self.base / "map/provinces.bmp", 24)
        w2, h2, ter = bitmap_rows(self.base / "map/terrain.bmp", 8)
        self.assertEqual((w, h), (w2, h2))
        by_rgb = {d["rgb"]: d for d in self.defs.values()}
        bad, checked = [], 0
        for r in range(h):
            for x in range(w):
                b, g, rr = prov[r][3 * x: 3 * x + 3]
                d = by_rgb.get((rr, g, b))
                if d is None:
                    continue
                checked += 1
                if ter[r][x] != TERRAIN_INDEX[d["terrain"]]:
                    bad.append((x, r))
        self.assertGreater(checked, 0)
        self.assertEqual(bad[:5], [])

    def test_bookmark_lists_only_defined_countries(self):
        tags = set(re.findall(r'^([A-Z0-9]{3}) = "countries/', text(next((self.base / "common/country_tags").glob("*.txt"))), re.M))
        bookmark = text(next((self.base / "common/bookmarks").glob("*.txt")))
        listed = set(re.findall(r"^\t\t([A-Z0-9]{3}) = \{", bookmark, re.M))
        default = re.search(r"default_country = (\w+)", bookmark).group(1)
        self.assertEqual(tags, {"ZAL", "KRV", "ORN"})
        self.assertLessEqual(listed, tags)
        self.assertIn(default, tags)
        for tag in tags:
            self.assertTrue((self.base / f"common/countries/{tag}.txt").is_file(), tag)
            self.assertTrue(list((self.base / "history/countries").glob(f"{tag} - *.txt")), tag)

    def test_every_region_has_small_and_big_weather(self):
        sizes = {}
        for line in text(self.base / "map/weatherpositions.txt").splitlines():
            if line.strip():
                rid, _x, _y, _z, size = line.split(";")
                sizes.setdefault(int(rid), set()).add(size)
        self.assertEqual(set(sizes), set(region_of(self.base).values()))
        for rid, found in sizes.items():
            self.assertEqual(found, {"small", "big"}, f"region {rid}")

    def test_default_map_refers_only_to_files_that_exist(self):
        live = [line for line in text(self.base / "map/default.map").splitlines()
                if not line.lstrip().startswith("#")]  # the climate line is commented out, as in the base game
        for value in re.findall(r'=\s*"([^"]+)"', "\n".join(live)):
            if value.endswith((".csv", ".bmp", ".txt")):
                self.assertTrue((self.base / "map" / value).is_file(), value)

    def test_same_seed_gives_identical_files(self):
        other = self.tmp / "again"
        code, out = run("build", str(self.spec), "--out", str(other))
        self.assertEqual(code, 0, out)
        self.assertEqual(hashes(self.base), hashes(other))

    def test_different_seed_gives_a_different_map(self):
        spec = self.tmp / "seed8.json"
        write(spec, json.dumps(world_spec(seed=8)))
        other = self.tmp / "seed8"
        code, out = run("build", str(spec), "--out", str(other))
        self.assertEqual(code, 0, out)
        self.assertNotEqual(hashes(self.base)["map/definition.csv"], hashes(other)["map/definition.csv"])


class WorldSpecTests(unittest.TestCase):
    CASES = [
        ("width not a multiple of 256", lambda w: w.update(width=300), "must be a multiple of 256"),
        ("no countries", lambda w: w.update(countries=[]), "must be a list of 1 to 40 countries"),
        ("default country not listed", lambda w: w["start"].update(default_country="QQQ"),
         "is not one of the countries listed"),
        ("slash in a country name", lambda w: w["countries"][0].update(name="Zal/via"),
         "must not contain quotes, slashes"),
        ("map too large", lambda w: w.update(width=4096, height=4096), "must be at most 4194304 pixels"),
        ("date with dashes", lambda w: w["start"].update(date="1936-01-01"),
         "must look like 1936.1.1.12 or 1936.1.1"),
        ("misspelt key", lambda w: w.update(widht=512), "did you mean 'width'"),
        ("lower-case tag", lambda w: w["countries"][0].update(tag="zal"), "must be 3 capital letters or digits"),
    ]

    def test_bad_world_specs_are_refused_and_write_nothing(self):
        for name, change, message in self.CASES:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                spec = world_spec()
                change(spec["world"])
                path = Path(tmp) / "spec.json"
                write(path, json.dumps(spec))
                out_dir = Path(tmp) / "out"
                code, out = run("build", str(path), "--out", str(out_dir))
                self.assertEqual(code, 2, out)
                self.assertIn(message, out)
                self.assertFalse(out_dir.exists())


class ExampleWorldTests(unittest.TestCase):
    def test_example_world_builds_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "mod"
            code, log = run("build", str(WORLD_EXAMPLE), "--out", str(out))
            self.assertEqual(code, 0, log)
            self.assertIn("0 error(s)", log)


class WorldValidateTests(WorldFixture):
    def test_province_in_two_states_is_an_error(self):
        mod = self.copy()
        first, second = states(mod)[0], states(mod)[1]
        pid = first["provinces"][0]
        add_province(second["path"], pid)
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn(f"province {pid} is in states", out)

    def test_province_outside_every_region_is_an_error(self):
        mod = self.copy()
        pid = next(iter(region_of(mod)))
        (mod / f"map/strategicregions/{region_of(mod)[pid]}.txt").unlink()
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn(f"province {pid} is not in any strategic region", out)

    def test_duplicate_province_colour_is_an_error(self):
        mod = self.copy()
        path = mod / "map/definition.csv"
        lines = text(path).splitlines()
        first, second = lines[1].split(";"), lines[2].split(";")
        second[1:4] = first[1:4]
        lines[2] = ";".join(second)
        write(path, "\n".join(lines) + "\n")
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn("is used by provinces", out)

    def test_capital_in_another_countrys_state_is_an_error(self):
        mod = self.copy()
        other = next(s for s in states(mod) if s["owner"] != "ZAL")
        history = next((mod / "history/countries").glob("ZAL - *.txt"))
        write(history, re.sub(r"capital = \d+", f"capital = {other['id']}", text(history)))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn(f"capital state {other['id']} is owned by {other['owner']}, not ZAL", out)

    def test_bookmark_default_country_must_be_defined(self):
        mod = self.copy()
        bookmark = next((mod / "common/bookmarks").glob("*.txt"))
        write(bookmark, text(bookmark).replace("default_country = ZAL", "default_country = QQQ"))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn("default_country QQQ is not in common/country_tags", out)

    def test_pixel_colour_that_no_province_defines_is_an_error(self):
        mod = self.copy()
        self.assertNotIn((253, 254, 255), {d["rgb"] for d in self.defs.values()})
        path = mod / "map/provinces.bmp"
        data = bytearray(path.read_bytes())
        data[60:63] = bytes((255, 254, 253))  # BGR bytes of pixel 2: colour (253, 254, 255)
        path.write_bytes(bytes(data))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn("pixel(s) use a colour that no province defines", out)

    def test_map_width_must_be_a_multiple_of_256(self):
        mod = self.copy()
        path = mod / "map/provinces.bmp"
        data = bytearray(path.read_bytes())
        struct.pack_into("<i", data, 18, 500)
        path.write_bytes(bytes(data))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn("width and height must both be multiples of 256", out)

    def test_state_owner_must_be_a_country_tag(self):
        mod = self.copy()
        s = states(mod)[0]
        write(s["path"], text(s["path"]).replace(f"owner = {s['owner']}", "owner = QQQ", 1))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn("is owned by QQQ, which is not in common/country_tags", out)

    def test_bookmark_listing_an_unknown_country_is_an_error(self):
        mod = self.copy()
        bookmark = next((mod / "common/bookmarks").glob("*.txt"))
        write(bookmark, re.sub(r"^(\t+)KRV = \{", r"\1QRX = {", text(bookmark), count=1, flags=re.M))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn("bookmark lists QRX, which is not in common/country_tags", out)

    def test_state_spanning_two_regions_is_an_error(self):
        mod = self.copy()
        region = region_of(mod)
        all_states = states(mod)
        first = all_states[0]
        donor = next(s for s in all_states if len(s["provinces"]) > 1
                     and region[s["provinces"][0]] != region[first["provinces"][0]])
        pid = next(p for p in donor["provinces"] if p != donor["vp"])
        set_provinces(donor["path"], [p for p in donor["provinces"] if p != pid])
        set_provinces(first["path"], first["provinces"] + [pid])
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn(f"state {first['id']} spans more than one strategic region", out)

    def test_land_province_outside_every_state_is_a_warning(self):
        mod = self.copy()
        s = next(s for s in states(mod) if len(s["provinces"]) > 1)
        pid = next(p for p in s["provinces"] if p != s["vp"])
        set_provinces(s["path"], [p for p in s["provinces"] if p != pid])
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertIn(f"land province {pid} is not in any state", out)

    def test_sea_province_in_a_state_is_an_error(self):
        mod = self.copy()
        sea = next(pid for pid, d in definitions(mod).items() if d["kind"] == "sea")
        s = states(mod)[0]
        add_province(s["path"], sea)
        code, out = run("validate", str(mod))
        self.assertEqual(code, 1, out)
        self.assertIn(f"state {s['id']} contains sea province {sea}", out)

    def test_lake_province_in_a_state_is_allowed(self):
        mod = self.copy()
        pid = states(mod)[0]["provinces"][0]
        path = mod / "map/definition.csv"
        lines = text(path).splitlines()
        for i, line in enumerate(lines):
            parts = line.split(";")
            if parts[0] == str(pid):
                parts[4], parts[6] = "lake", "lakes"
                lines[i] = ";".join(parts)
        write(path, "\n".join(lines) + "\n")
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertNotIn("contains sea province", out)

    def test_region_without_a_big_weather_entry_is_a_warning(self):
        mod = self.copy()
        path = mod / "map/weatherpositions.txt"
        write(path, "\n".join(line for line in text(path).splitlines() if not line.endswith(";big")) + "\n")
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertIn("no 'big' entry", out)

    def test_weather_size_other_than_small_or_big_is_a_warning(self):
        mod = self.copy()
        path = mod / "map/weatherpositions.txt"
        write(path, text(path).replace(";big", ";large", 1))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertIn("size 'large' is not small or big", out)

    def test_smaller_tree_map_is_only_a_note(self):
        mod = self.copy()
        path = mod / "map/trees.bmp"
        data = bytearray(path.read_bytes())
        struct.pack_into("<ii", data, 18, 256, 128)
        path.write_bytes(bytes(data))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertIn("differs from provinces.bmp", out)

    def test_tag_defined_through_an_alias_is_accepted(self):
        mod = self.copy()
        tags_file = next((mod / "common/country_tags").glob("*.txt"))
        write(tags_file, text(tags_file).replace('ZAL = "countries/ZAL.txt"',
                                                 '@ZV = "countries/ZAL.txt"\nZAL = @ZV', 1))
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertNotIn("not in common/country_tags", out)
        self.assertNotIn("country ZAL points to", out)
        # The alias must resolve: with its file gone, the warning names the file it points to.
        (mod / "common/countries/ZAL.txt").unlink()
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertIn("country ZAL points to common/countries/ZAL.txt, which is missing", out)

    def test_tag_defined_as_a_block_needs_no_file(self):
        mod = self.copy()
        (mod / "common/countries/KRV.txt").unlink()
        write(mod / "common/countries/colors.txt", "KRV = {\n\tcolor = { 180 60 60 }\n}\n")
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertNotIn("country KRV points to", out)

    def test_tag_with_no_file_and_no_block_is_a_warning(self):
        mod = self.copy()
        (mod / "common/countries/ORN.txt").unlink()
        code, out = run("validate", str(mod))
        self.assertEqual(code, 0, out)
        self.assertIn("country ORN points to common/countries/ORN.txt, which is missing", out)

    def test_bookmark_date_forms_are_checked(self):
        for name, new_date, accepted in (("variable", "@start_date_default", True),
                                         ("without an hour", "1936.1.1", True),
                                         ("with dashes", "1936-01-01", False)):
            with self.subTest(name):
                mod = self.copy()
                bookmark = next((mod / "common/bookmarks").glob("*.txt"))
                body = text(bookmark).replace("date = 1936.1.1.12", f"date = {new_date}", 1)
                if new_date.startswith("@"):
                    body = f"{new_date} = 1936.1.1.12\n" + body
                write(bookmark, body)
                code, out = run("validate", str(mod))
                if accepted:
                    self.assertEqual(code, 0, out)
                    self.assertNotIn("must look like", out)
                else:
                    self.assertEqual(code, 1, out)
                    self.assertIn("must look like", out)


if __name__ == "__main__":
    unittest.main()
