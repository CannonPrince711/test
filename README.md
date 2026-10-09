# test

## Claude skill: Hearts of Iron IV mod builder

[`.claude/skills/hoi4-mod-builder/`](.claude/skills/hoi4-mod-builder/SKILL.md) is a Claude skill for creating
and checking mods for Hearts of Iron IV. Claude uses it to write national focus trees, events, decisions,
national spirits, English localisation, sprite definitions and procedural custom worlds (a generated map with
countries and a start date) from a short JSON spec, then validates the result.

- **Use it in this repo:** Claude Code loads project skills from `.claude/skills/` automatically. Ask for a
  Hearts of Iron IV mod or focus tree.
- **Use it elsewhere:** copy `.claude/skills/hoi4-mod-builder/` into `~/.claude/skills/`, or zip the folder and
  add it through Claude's skill settings.

### Run the tool directly

```
python3 .claude/skills/hoi4-mod-builder/scripts/hoi4_mod.py build .claude/skills/hoi4-mod-builder/examples/spec.example.json --out ./lusitanian_path
python3 .claude/skills/hoi4-mod-builder/scripts/hoi4_mod.py validate ./lusitanian_path
python3 .claude/skills/hoi4-mod-builder/scripts/hoi4_mod.py build .claude/skills/hoi4-mod-builder/examples/world.example.json --out ./atlantic_frontier --preview ./atlantic_frontier.png
python3 -m unittest discover -s .claude/skills/hoi4-mod-builder/tests
```

The second build makes a custom world: a generated 1024 × 512 map with four countries and a start bookmark.
`--preview` writes a rough picture of the map. See `.claude/skills/hoi4-mod-builder/reference/custom-worlds.md`.

Python 3.8 or newer. No packages to install.

### Limits

The checks cover file structure, syntax, IDs, localisation encoding, references between files and the map rules
for custom worlds. They do not run the game, so balance and in-game behaviour still need a playtest with `-debug`
and the game's `error.log`. Custom worlds have not been loaded in the game.
