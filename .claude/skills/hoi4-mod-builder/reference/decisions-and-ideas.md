# Decisions, categories and ideas (national spirits)

## Decisions

Decisions are actions the player (or AI) takes from the decisions screen, usually for political power.
They sit inside **categories**, which group them on screen.

- Categories: `common/decisions/categories/*.txt`
- Decisions: `common/decisions/*.txt`, nested inside the category block of the same name.
- The file name does not matter; a category must exist before its decisions show.

```
# common/decisions/categories/por_homeland_affairs.txt
por_homeland_affairs = {
	allowed = {
		original_tag = POR
	}
	visible_when_empty = no
}

# common/decisions/por_homeland_affairs.txt
por_homeland_affairs = {
	por_declare_liberty_day = {
		cost = 25
		days_remove = 30
		fire_only_once = yes
		available = {
			has_war = no
		}
		complete_effect = {
			add_stability = 0.02
		}
		ai_will_do = {
			factor = 5
		}
	}
}
```

### The conditions

| Block | When it is checked | Effect |
|---|---|---|
| `allowed` | Once, at game start and on load | Decides whether the decision or category exists for this country. Use `original_tag = TAG` or a DLC check here. |
| `visible` | Every frame | Hidden unless true. Hidden decisions are not shown at all. |
| `available` | Every frame | Shown greyed out when false. Cannot be taken. |

Put conditions in the **narrowest** block that fits. Country and DLC checks go in `allowed`.

### Timer and effects

Taking a decision runs `complete_effect` at once and, if `days_remove` is set, starts a timer:

- `complete_effect`: runs **immediately** when the decision is taken (this is also when the timer starts).
- `days_remove = N`: the decision stays on screen as a timer for N days, then is removed. `-1` means the timer never removes it.
- `remove_effect`: runs **when the timer ends** (or when `remove_trigger` removes the decision early).
- `cancel_trigger` / `cancel_effect`: cancel the timer early; `cancel_effect` runs instead of `remove_effect`.
- `modifier = { }` applies while the timer runs.
- `days_re_enable = N`: cooldown before the decision can be taken again. By default it reappears the next day.
- `fire_only_once = yes`: the decision disappears for good after it is taken once.
- `cost = N`: political power. A `custom_cost_trigger` / `custom_cost_text` pair shows a custom cost, but
  **it costs nothing by itself**; subtract the resource in `complete_effect`.

### AI

- `ai_will_do = { factor = 10 }` (or `base = 10`) sets the AI's weight. **Without it the AI never takes the decision.**
- Use `modifier = { add = 10 has_war_with = ITA }` inside `ai_will_do` to make the AI interested only in some situations.

### Other arguments

- `icon`: the short name. The game adds `GFX_decision_` (decisions) or `GFX_decision_category_` (categories)
  itself, so `icon = my_icon` expects `GFX_decision_my_icon`.
- `priority`: higher shows closer to the top. Default is 1 for decisions.
- `visible_when_empty = yes` (categories): keep the category on screen when nothing in it is available.
- `picture = GFX_decision_category_picture` (categories): an image beside the category text. The category needs a description.
- `war_with_on_complete = TAG` / `war_with_on_remove = TAG`: warn the AI that this decision leads to war.

### Localisation

Decision name: key `<id>`. Description: key `<id>_desc`. Categories use the same pattern.

### Decisions in the spec

Use the `decisions` section of the spec (see spec-format.md). The builder writes both files and the loc keys.

## National spirits (ideas)

Ideas apply lasting modifiers to a country. National spirits are ideas in the `country` category.
Ideas live in `common/ideas/*.txt`.

```
ideas = {
	country = {
		por_lusitanian_spirit = {
			allowed = {
				original_tag = POR
			}
			modifier = {
				stability_factor = 0.05
				political_power_gain = 0.1
			}
			on_add = {
				add_political_power = 25
			}
		}
	}
}
```

### Parts of an idea

| Part | Meaning |
|---|---|
| `allowed` | Who may have it. Checked once, like decisions. |
| `picture` | Sprite short name. Default is `GFX_idea_<id>`. `picture = por_spirit` uses `GFX_idea_por_spirit`. |
| `modifier = { }` | Continuous modifiers, applied while the idea is held. Variables do not work here. Use dynamic modifiers for changing values. |
| `targeted_modifier = { tag = XXX ... }` | Modifiers aimed at another country. |
| `research_bonus = { <category> = 0.1 }` | Bonus to a technology category. |
| `equipment_bonus = { <archetype> = { ... } }` | Equipment bonuses. |
| `rule = { can_join_factions = no }` | Diplomatic rules. |
| `on_add = { }` / `on_remove = { }` | Effects when added or removed. |

Modifier names verified in community mods include `stability_factor`, `political_power_gain`,
`political_power_cost`. Use the wiki's "List of modifiers" page for others.

**Effects in `on_add` only run if the idea is added after the game has started.** If you add a spirit in
a country's history file, copy the effects into that file as well.

### Ideas in the spec

Use the `ideas` section (see spec-format.md). `category` defaults to `country`. The builder writes one
file, `common/ideas/<slug>_ideas.txt`, and the loc keys `<id>` and `<id>_desc`.

### Adding and removing spirits (effects)

```
add_ideas = por_lusitanian_spirit
remove_ideas = por_lusitanian_spirit
add_timed_idea = { idea = por_temporary_spirit days = 365 }
swap_ideas = {
	remove_idea = por_old_spirit
	add_idea = por_new_spirit
}
```

To start a country with a spirit, add it in `history/countries/<TAG> - <Name>.txt`.

### Other idea categories

Ideas are placed in categories. `country` is for national spirits. Other categories exist for army spirits,
laws, and hidden ideas. Look up the exact category keys on the wiki's "Idea modding" page (section "Other idea
categories") before using them. Use `country` unless you know you need another category.
