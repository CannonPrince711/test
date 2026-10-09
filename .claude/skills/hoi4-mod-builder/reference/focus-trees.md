# National focus trees

A focus tree is a set of national focuses that one country works through, with prerequisites and
rewards. Trees live in `common/national_focus/*.txt`. A file can hold several trees, and the file
name is irrelevant. Source: the HOI4 wiki "National focus modding" page, checked against community mods.

## Tree structure

```
focus_tree = {
	id = POR_lusitanian_path_focus
	country = {
		factor = 0
		modifier = {
			add = 10
			original_tag = POR
		}
	}
	default = no

	focus = { ... }
	focus = { ... }
}
```

- `id` must be unique in the game.
- `country` scores the tree for a country. The game picks the tree with the highest score when the game
  starts. `original_tag` also covers civil-war breakaways, which is why the builder uses it.
  Without a `country` block with a `modifier`, nothing ever loads the tree.
- `default = yes` marks the fallback tree. Exactly one default tree should exist in the game, and the base
  game already has one, so new mods leave `default = no`.
- Scores are fixed when the game starts. A tree change needs a restart (or a `load_focus_tree` effect).

## Focus fields

| Field | Meaning |
|---|---|
| `id` | Unique focus ID. Name and description loc keys are `id` and `id_desc`. |
| `icon` | Sprite name. Focus icons need a `GFX_x` sprite and a `GFX_x_shine` sprite (see hoi4-mod-rules.md). |
| `x`, `y` | Grid position. One unit is 96 px across and 130 px down. |
| `relative_position_id` | Position `x`/`y` as offsets from another focus in the same tree. Moving the parent moves the whole branch. |
| `offset = { x y trigger = { } }` | Shift the focus when a condition is true when the tree loads. |
| `cost` | Days in units of 7: `cost = 1` is about a week, so `cost = 10` is about ten weeks. Decimals round down. |
| `prerequisite = { focus = A }` | Lists focuses that must be finished first. |
| `mutually_exclusive = { focus = B }` | Locks this focus out once `B` is done. Both directions show the arrow. |
| `available = { }` | Extra conditions. Triggers in this block are AND, and they are listed in the focus tooltip. |
| `bypass = { }` | Conditions under which the focus is skipped (marked complete). |
| `allow_branch = { }` | Whether the focus is visible at all (checked when the tree loads). |
| `ai_will_do = { base = 10 }` | How keen the AI is on this focus. Higher = picked sooner. |
| `search_filters = { FOCUS_FILTER_POLITICAL }` | Category tags used by the search box. |
| `completion_reward = { }` | Effects when the focus completes. |
| `select_effect`, `bypass_effect`, `cancel` | Less common. See the wiki. |

### Prerequisites: AND and OR

```
prerequisite = { focus = A }              # needs A
prerequisite = { focus = A focus = B }    # needs A OR B (one block with several focus entries)
prerequisite = { focus = C }              # ...and C (a second block is an AND)
```

Each block must be satisfied. Keep prerequisites in the same tree: a prerequisite in another tree is allowed
but may not draw a line in the tree view. Put a prerequisite above the focus that requires it, or the lines render wrongly. Anything
more complex (A or (B and C)) needs `available = { has_completed_focus = ... }` plus a custom
tooltip.

### Search filters (verified)

`FOCUS_FILTER_POLITICAL`, `FOCUS_FILTER_RESEARCH`, `FOCUS_FILTER_INDUSTRY`, `FOCUS_FILTER_STABILITY`,
`FOCUS_FILTER_WAR_SUPPORT`, `FOCUS_FILTER_MANPOWER`, `FOCUS_FILTER_ANNEXATION`, `FOCUS_FILTER_HISTORICAL`,
`FOCUS_FILTER_INTERNATIONAL_TRADE`, `FOCUS_FILTER_ARMY_XP`, `FOCUS_FILTER_NAVY_XP`, `FOCUS_FILTER_AIR_XP`,
`FOCUS_FILTER_POLITICAL_CHARACTER`, `FOCUS_FILTER_MILITARY_CHARACTER`. Several can go in one block.

## Layout that reads well

- Lay out one branch per column. Keep sibling branches two or more units apart, so lines don't cross.
- Use `relative_position_id` on focuses that have prerequisites (the wiki recommends it), so a branch moves as one piece.
- A country has one active tree at a time. Switch trees mid-game with `load_focus_tree`; `keep_completed = yes` keeps shared progress. Use `shared_focus` for focuses that appear in several trees.
- Keep each tree readable: roughly 20–40 focuses is a comfortable size for a player to scan.
- Put the tree's root at `x = 0`, `y = 0`. Branches spread out to negative and positive `x`.
- Every focus needs a unique `(x, y)` in its tree unless `offset` is used. The validator warns on overlaps.
- Mutually exclusive choices sit side by side (for example `x = -1` and `x = 1`), so the player sees the fork.
- Let each branch end in a strong capstone (more political power, a flag that unlocks events).

## Rewards and balance

- Rewards are effects: `add_political_power = 50`, `add_stability = 0.02`, `add_war_support = 0.05`,
  `add_manpower = 10000`, `add_ideas`, `set_country_flag`, `country_event = { id = ... }`.
- Stability and war support are fractions: `0.02` = 2%.
- Give a branch 2–4 small rewards (political power, a spirit, a flag) and one bigger one at the end.
- Use flags (`set_country_flag`) to remember choices, and `has_country_flag` / `has_completed_focus` to branch later.
- A focus is **not yet complete** while its own `completion_reward` runs. A `has_completed_focus` check for
  that same focus returns false during the reward. Use a flag or a hidden event with no delay instead.

## Icons

- Use vanilla goal icons (no sprite needed): `GFX_goal_generic_construct_infrastructure`,
  `GFX_goal_generic_dangerous_deal`, `GFX_goal_generic_allies_build_infantry`. Others are in the base game.
- Custom icons: give the focus `icon: "GFX_focus_<name>"` and add a sprite with `kind: "focus"` in the spec.
  The texture must exist in the mod (DDS recommended). Match the size of existing focus icons in the base game.

## Writing focus names and descriptions

- Name: 1–4 words, title case. Description: one or two sentences in the in-game voice.
- Use the user's language for the names and descriptions, unless the mod is for a different language.
- Keep historical accuracy when the user asks for it. Mark invented events as alternate history in the mod tags.

## Shared focuses (advanced)

`shared_focus = { id = ... }` defines a focus once and pulls it into several trees with `shared_focus = ID` in
each tree. A shared focus is not a duplicate. Avoid two different definitions of the same ID. Referencing a shared
focus that does not exist crashes the game when the main menu loads.
