import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent  # the skill folder
SCRIPT = SKILL / "scripts" / "hoi4_mod.py"
EXAMPLE = SKILL / "examples" / "spec.example.json"


def run(*args):
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def write(path, text, bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)


def minimal_spec(**overrides):
    spec = {
        "mod": {"name": "Test Mod"},
        "focus_trees": [{
            "id": "GER_test_tree", "country": "GER",
            "focuses": [
                {"id": "GER_a", "name": "Alpha", "x": 0, "y": 0},
                {"id": "GER_b", "name": "Beta", "x": 0, "y": 1, "prerequisites": ["GER_a"]},
            ],
        }],
    }
    spec.update(overrides)
    return spec


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hoi4test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spec_file(self, spec):
        p = self.tmp / "spec.json"
        p.write_text(json.dumps(spec), encoding="utf-8")
        return p

    # ---------------- positive paths ----------------
    def test_example_builds_clean(self):
        code, out = run("build", str(EXAMPLE), "--out", str(self.tmp / "m"))
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_example_files_and_bom(self):
        run("build", str(EXAMPLE), "--out", str(self.tmp / "m"))
        m = self.tmp / "m"
        expected = [
            "descriptor.mod",
            "common/national_focus/lusitanian_path_POR_lusitanian_path_focus.txt",
            "common/decisions/categories/lusitanian_path_por_homeland_affairs.txt",
            "common/decisions/lusitanian_path_por_homeland_affairs.txt",
            "common/ideas/lusitanian_path_ideas.txt",
            "events/lusitanian_path_por_events.txt",
            "localisation/english/lusitanian_path_l_english.yml",
        ]
        for rel in expected:
            self.assertTrue((m / rel).is_file(), rel)
        loc = (m / "localisation/english/lusitanian_path_l_english.yml").read_bytes()
        self.assertTrue(loc.startswith(b"\xef\xbb\xbfl_english:\n"))
        self.assertIn(b' POR_lusitanian_awakening:0 "Lusitanian Awakening"', loc)
        for rel in expected:
            text = (m / rel).read_bytes()
            self.assertNotIn(b"    ", text.replace(b"\t", b""), rel)  # tabs only: no runs of 4 spaces

    def test_launcher_descriptor_and_user_dir(self):
        user = self.tmp / "Hearts of Iron IV"
        code, out = run("build", str(EXAMPLE), "--user-dir", str(user))
        self.assertEqual(code, 0, out)
        launcher = user / "mod" / "lusitanian_path.mod"
        self.assertTrue(launcher.is_file())
        self.assertIn('path="mod/lusitanian_path"', launcher.read_text(encoding="utf-8"))
        self.assertTrue((user / "mod" / "lusitanian_path" / "descriptor.mod").is_file())

    def test_rebuild_is_idempotent_and_removes_stale_files(self):
        spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        out_dir = self.tmp / "m"
        run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        stale_candidate = out_dir / "common/national_focus/lusitanian_path_POR_lusitanian_path_focus.txt"
        self.assertTrue(stale_candidate.is_file())
        # remove the focus tree from the spec; the old file must disappear
        spec.pop("focus_trees")
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        self.assertEqual(code, 0, out)
        self.assertFalse(stale_candidate.exists())
        # build twice in a row gives identical output
        first = {p.relative_to(out_dir).as_posix(): p.read_bytes() for p in out_dir.rglob("*") if p.is_file()}
        run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        second = {p.relative_to(out_dir).as_posix(): p.read_bytes() for p in out_dir.rglob("*") if p.is_file()}
        self.assertEqual(first, second)

    def test_focus_icon_shine_and_sprites(self):
        spec = minimal_spec()
        spec["focus_trees"][0]["focuses"][0]["icon"] = "GFX_focus_por_custom"
        spec["sprites"] = [{"name": "GFX_focus_por_custom", "texture": "gfx/interface/goals/por_custom.dds", "kind": "focus"}]
        out_dir = self.tmp / "m"
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        gfx = (out_dir / "interface/test_mod_sprites.gfx").read_text(encoding="utf-8")
        self.assertIn("name = GFX_focus_por_custom\n", gfx)
        self.assertIn("name = GFX_focus_por_custom_shine", gfx)
        self.assertEqual(gfx.count("animation = {"), 2)
        # texture is missing in the mod folder -> a warning, not an error
        self.assertEqual(code, 0, out)
        self.assertIn("texture 'gfx/interface/goals/por_custom.dds'", out)
        # now create the texture and the warning goes away
        write(out_dir / "gfx/interface/goals/por_custom.dds", "placeholder")
        code, out = run("validate", str(out_dir))
        self.assertEqual(code, 0, out)
        self.assertNotIn("por_custom.dds", out)

    def test_multiline_raw_script_is_reindented(self):
        spec = minimal_spec()
        spec["focus_trees"][0]["focuses"][1]["completion_reward"] = [
            "hidden_effect = {\n        set_country_flag = x\n      }",
        ]
        out_dir = self.tmp / "m"
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        self.assertEqual(code, 0, out)
        text = (out_dir / "common/national_focus/test_mod_GER_test_tree.txt").read_text(encoding="utf-8")
        self.assertIn("\t\t\thidden_effect = {\n\t\t\t\tset_country_flag = x\n\t\t\t}\n", text)

    def test_or_and_prerequisites(self):
        spec = minimal_spec()
        spec["focus_trees"][0]["focuses"].append(
            {"id": "GER_c", "x": 1, "y": 2, "prerequisites": ["GER_a", ["GER_b", "GER_a"]]})
        out_dir = self.tmp / "m"
        run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        text = (out_dir / "common/national_focus/test_mod_GER_test_tree.txt").read_text(encoding="utf-8")
        self.assertIn("prerequisite = { focus = GER_a }", text)
        self.assertIn("prerequisite = { focus = GER_b focus = GER_a }", text)

    # ---------------- spec errors (exit 2, nothing written) ----------------
    def assert_spec_error(self, spec, needle):
        out_dir = self.tmp / "m"
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        self.assertEqual(code, 2, out)
        self.assertIn(needle, out)
        self.assertFalse(out_dir.exists(), "nothing must be written for a bad spec")

    def test_unknown_key_suggests_fix(self):
        spec = minimal_spec()
        spec["focus_tree"] = spec.pop("focus_trees")
        self.assert_spec_error(spec, "did you mean 'focus_trees'")

    def test_bad_country_tag(self):
        spec = minimal_spec()
        spec["focus_trees"][0]["country"] = "GERMANY"
        self.assert_spec_error(spec, "3-character country tag")

    def test_duplicate_focus_id_across_trees(self):
        spec = minimal_spec()
        spec["focus_trees"].append({"id": "GER_other", "country": "GER", "focuses": [{"id": "GER_a"}]})
        self.assert_spec_error(spec, "duplicate focus id 'GER_a'")

    def test_event_id_must_match_namespace(self):
        spec = minimal_spec(events=[{"namespace": "ger_ev", "events": [
            {"id": "other.1", "title": "T", "options": [{"text": "OK"}]}]}])
        self.assert_spec_error(spec, "must start with the block's namespace 'ger_ev.'")

    def test_visible_event_needs_option(self):
        spec = minimal_spec(events=[{"namespace": "ger_ev", "events": [
            {"id": "ger_ev.1", "title": "T", "desc": "D", "options": []}]}])
        self.assert_spec_error(spec, "needs at least one option")

    def test_visible_event_needs_title_or_desc(self):
        spec = minimal_spec(events=[{"namespace": "ger_ev", "events": [
            {"id": "ger_ev.1", "options": [{"text": "OK"}]}]}])
        self.assert_spec_error(spec, "needs a 'title' or a 'desc'")

    def test_quote_in_loc_text_is_rejected(self):
        spec = minimal_spec()
        spec["focus_trees"][0]["focuses"][0]["name"] = 'Say "hi"'
        self.assert_spec_error(spec, "must not contain double quotes")

    def test_missing_mod_name(self):
        spec = minimal_spec()
        spec["mod"] = {}
        self.assert_spec_error(spec, "mod.name")

    def test_bad_sprite_name(self):
        spec = minimal_spec(sprites=[{"name": "focus_icon", "texture": "gfx/a.dds"}])
        self.assert_spec_error(spec, "must start with GFX_")

    def test_loc_key_conflict(self):
        spec = minimal_spec(decisions=[{"category": "ger_cat", "items": [{"id": "GER_a", "name": "Different"}]}])
        spec["decisions"][0]["category"] = "ger_cat"
        out_dir = self.tmp / "m"
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        self.assertEqual(code, 2, out)
        self.assertIn("used twice with different text", out)

    def test_needs_destination(self):
        code, out = run("build", str(EXAMPLE))
        self.assertEqual(code, 2)
        self.assertIn("choose where the mod goes", out)


    def test_cross_tree_relative_position_rejected(self):
        spec = minimal_spec()
        spec["focus_trees"].append({"id": "GER_other", "country": "GER", "focuses": [{"id": "GER_c", "x": 3, "y": 3}]})
        spec["focus_trees"][0]["focuses"][1]["relative_to"] = "GER_c"
        self.assert_spec_error(spec, "must stay in one tree")

    def test_bad_values_are_all_reported_together(self):
        spec = minimal_spec()
        spec["focus_trees"][0]["focuses"][0]["cost"] = 0
        spec["events"] = [{"namespace": "ger_ev", "events": [
            {"id": "ger_ev.1", "title": "T", "options": [{"text": f"o{i}"} for i in range(27)]}]}]
        out_dir = self.tmp / "m"
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        self.assertEqual(code, 2, out)
        self.assertIn("must be greater than 0", out)
        self.assertIn("at most 26 options", out)
        self.assertFalse(out_dir.exists())

    def test_news_event_major_and_idea_picture_prefix(self):
        spec = minimal_spec(
            events=[{"namespace": "ger_news", "events": [
                {"id": "ger_news.1", "type": "news_event", "major": True, "title": "Headline",
                 "options": [{"text": "Read on"}]}]}],
            ideas=[{"items": [{"id": "ger_spirit", "name": "Spirit", "picture": "GFX_idea_ger_pic"}]}],
        )
        out_dir = self.tmp / "m"
        code, out = run("build", str(self.spec_file(spec)), "--out", str(out_dir))
        self.assertEqual(code, 0, out)
        news = (out_dir / "events/test_mod_ger_news.txt").read_text(encoding="utf-8")
        self.assertIn("news_event = {", news)
        self.assertIn("\tmajor = yes", news)
        ideas = (out_dir / "common/ideas/test_mod_ideas.txt").read_text(encoding="utf-8")
        self.assertIn("picture = ger_pic", ideas)
        self.assertNotIn("GFX_idea_GFX_idea", ideas)
        self.assertIn("sprite GFX_idea_ger_pic is not defined", out)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hoi4val_"))
        self.mod = self.tmp / "mod" / "testmod"
        run("build", str(EXAMPLE), "--out", str(self.mod))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def focus_file(self):
        return self.mod / "common/national_focus/lusitanian_path_POR_lusitanian_path_focus.txt"

    def loc_file(self):
        return self.mod / "localisation/english/lusitanian_path_l_english.yml"

    def event_file(self):
        return self.mod / "events/lusitanian_path_por_events.txt"

    def test_clean_example_validates(self):
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 0, out)

    def test_unclosed_brace_reports_line(self):
        text = self.focus_file().read_text(encoding="utf-8")
        self.focus_file().write_text(text.replace("\t}\n}\n", "\t}\n", 1), encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("unclosed '{'", out)

    def test_extra_closing_brace(self):
        self.focus_file().write_text(self.focus_file().read_text(encoding="utf-8") + "}\n", encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("unexpected '}'", out)

    def test_key_brace_without_equals(self):
        self.event_file().write_text(self.event_file().read_text(encoding="utf-8").replace(
            "immediate = {", "immediate {", 1), encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("without '='", out)

    def test_loc_without_bom(self):
        self.loc_file().write_bytes(self.loc_file().read_bytes()[3:])
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("no UTF-8 BOM", out)

    def test_loc_wrong_filename(self):
        new = self.loc_file().with_name("lusitanian_path_english.yml")
        self.loc_file().rename(new)
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("must end with _l_english.yml", out)

    def test_loc_bad_header_and_malformed_line(self):
        text = self.loc_file().read_text(encoding="utf-8-sig")
        text = text.replace("l_english:", "l_german:", 1) + ' bad line without quotes\n'
        write(self.loc_file(), text, bom=True)
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("first line must be 'l_english:'", out)
        self.assertIn("malformed localisation line", out)

    def test_duplicate_focus_id_in_other_file(self):
        extra = self.mod / "common/national_focus/zz_extra.txt"
        write(extra, "focus_tree = {\n\tid = X_tree\n\tcountry = {\n\t\tmodifier = {\n\t\t\tadd = 1\n\t\t}\n\t}\n"
                     "\tfocus = {\n\t\tid = POR_lusitanian_awakening\n\t\tx = 5\n\t\ty = 5\n\t}\n}\n")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate focus id 'POR_lusitanian_awakening'", out)

    def test_missing_prerequisite_is_warning(self):
        text = self.focus_file().read_text(encoding="utf-8").replace(
            "prerequisite = { focus = POR_lusitanian_awakening }", "prerequisite = { focus = POR_ghost }", 1)
        self.focus_file().write_text(text, encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 0, out)
        self.assertIn("requires POR_ghost, which this mod does not define", out)

    def test_prerequisite_in_other_tree(self):
        extra = self.mod / "common/national_focus/zz_other.txt"
        write(extra, "focus_tree = {\n\tid = OTHER_tree\n\tcountry = {\n\t\tmodifier = {\n\t\t\tadd = 1\n\t\t}\n\t}\n"
                     "\tfocus = {\n\t\tid = OTHER_root\n\t\tx = 9\n\t\ty = 9\n\t}\n}\n")
        text = self.focus_file().read_text(encoding="utf-8").replace(
            "prerequisite = { focus = POR_lusitanian_awakening }", "prerequisite = { focus = OTHER_root }", 1)
        self.focus_file().write_text(text, encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertIn("which is in another focus tree", out)

    def test_undeclared_namespace_is_error(self):
        text = self.event_file().read_text(encoding="utf-8").replace("add_namespace = por_events\n", "", 1)
        self.event_file().write_text(text, encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("namespace 'por_events' is never declared", out)

    def test_namespace_declared_in_other_file_is_warning(self):
        text = self.event_file().read_text(encoding="utf-8").replace("add_namespace = por_events\n", "", 1)
        self.event_file().write_text(text, encoding="utf-8")
        write(self.mod / "events/zz_ns.txt", "add_namespace = por_events\n")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 0, out)
        self.assertIn("declared in another file", out)

    def test_event_id_not_numeric(self):
        self.event_file().write_text(self.event_file().read_text(encoding="utf-8").replace(
            "por_events.2", "por_events.two", 1), encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("must look like <namespace>.<integer>", out)

    def test_missing_loc_is_warning(self):
        text = self.loc_file().read_text(encoding="utf-8-sig")
        text = "\n".join(l for l in text.splitlines() if not l.startswith(" POR_naval_bridge:0"))
        write(self.loc_file(), text + "\n", bom=True)
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 0, out)
        self.assertIn("no localisation for name of focus POR_naval_bridge", out)

    def test_missing_descriptor_is_error(self):
        (self.mod / "descriptor.mod").unlink()
        code, out = run("validate", str(self.mod))
        self.assertEqual(code, 1, out)
        self.assertIn("descriptor.mod is missing", out)

    def test_overlapping_focuses_warning(self):
        text = self.focus_file().read_text(encoding="utf-8").replace("\t\tx = 1\n\t\ty = 1\n", "\t\tx = -1\n\t\ty = 1\n", 1)
        self.focus_file().write_text(text, encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertIn("occupy the same grid position", out)

    def test_default_tree_warning(self):
        text = self.focus_file().read_text(encoding="utf-8").replace("default = no", "default = yes", 1)
        self.focus_file().write_text(text, encoding="utf-8")
        code, out = run("validate", str(self.mod))
        self.assertIn("sets default = yes", out)

    def test_missing_launcher_warning_inside_mod_dir(self):
        code, out = run("validate", str(self.mod))
        self.assertIn("no launcher descriptor", out)

    def test_strict_mode_fails_on_warning(self):
        text = self.focus_file().read_text(encoding="utf-8").replace("default = no", "default = yes", 1)
        self.focus_file().write_text(text, encoding="utf-8")
        code, _ = run("validate", str(self.mod), "--strict")
        self.assertEqual(code, 1)

    def test_non_ascii_path_warning(self):
        odd = self.tmp / "Documents_é" / "mod" / "x"
        run("build", str(EXAMPLE), "--out", str(odd))
        code, out = run("validate", str(odd))
        self.assertIn("non-ASCII", out)


class ParserTests(unittest.TestCase):
    """Exercise the script parser directly through the module."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPT.parent))
        import hoi4_mod
        cls.m = hoi4_mod

    def parse(self, text):
        return self.m.parse_script(text)

    def test_comments_strings_and_operators(self):
        nodes, errs = self.parse(
            "# header comment\n"
            "x = -5 # trailing\n"
            'name = "has # hash"\n'
            "trigger = { has_political_power > 50 date < 1936.2.11 }\n"
            "pair = { a >= 1 b <= 2 }\n")
        self.assertEqual(errs, [])
        self.assertEqual(nodes[0].value, "-5")
        self.assertEqual(nodes[1].value, "has # hash")
        trig = nodes[2].value
        self.assertEqual((trig[0].key, trig[0].op, trig[0].value), ("has_political_power", ">", "50"))
        self.assertEqual((trig[1].key, trig[1].op, trig[1].value), ("date", "<", "1936.2.11"))

    def test_bare_items_and_lists(self):
        nodes, errs = self.parse('tags = { "A" "B" }\nsearch_filters = { FOCUS_FILTER_POLITICAL }\n')
        self.assertEqual(errs, [])
        self.assertEqual([n.value for n in nodes[0].value], ["A", "B"])
        self.assertEqual(nodes[1].value[0].value, "FOCUS_FILTER_POLITICAL")

    def test_unterminated_string(self):
        _, errs = self.parse('name = "oops\nother = 1\n')
        self.assertTrue(any("unterminated string" in msg for _, msg in errs))

    def test_missing_value(self):
        _, errs = self.parse("x = \n")
        self.assertTrue(any("has no value" in msg for _, msg in errs))

    def test_colour_literals(self):
        nodes, errs = self.parse("GER = {\n\tcolor = rgb { 255 216 82 }\n\tcolor_ui = hsv360 { 1 2 3 }\n}\n")
        self.assertEqual(errs, [])
        self.assertEqual([n.key for n in nodes[0].value], ["color", "color_ui"])
        self.assertEqual([c.value for c in nodes[0].value[0].value], ["255", "216", "82"])

    def test_line_numbers(self):
        nodes, errs = self.parse("a = 1\nb = {\n  c = 2\n")
        self.assertEqual(errs[0][0], 2)  # unclosed block opened on line 2
        self.assertEqual(nodes[1].line, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
