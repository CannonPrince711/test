# Scripting cheat sheet

Triggers check conditions. Effects change things. Both go inside blocks like `trigger = { }`,
`available = { }`, `completion_reward = { }`, `immediate = { }`, `complete_effect = { }`.

Every name below appears in published HOI4 wiki pages or in real community mods. Check the wiki
(hoi4.paradoxwikis.com) for anything not listed, and for changes after the latest patch.

## Syntax

```
key = value                    # assignment, value can be a word, number or yes/no
key = { ... }                  # block
key > value                    # comparison in triggers: >  <  >=  <=  (tokens with no '=' are fine)
NOT = { ... }                  # negation
OR = { ... }                   # any inside are true
AND = { ... }                  # all inside are true (default for a plain trigger block)
# a comment runs to the end of the line
```

Scopes: `ROOT` is the country whose effect or focus runs; `FROM` is the sender (for events);
`THIS` is the current scope; `PREV` is the scope one level up the chain. Country tags work as scopes too:
`GER = { country_event = ... }`. States use their number: `802 = { is_core_of = ROOT }`.

## Triggers (verified)

| Trigger | Example | Notes |
|---|---|---|
| `tag` / `original_tag` | `original_tag = POR` | `original_tag` survives civil wars and collaborators. |
| `has_government` | `has_government = democratic` | Ideology group names: democratic, fascism, communism, neutrality. |
| `has_war` | `has_war = yes` | |
| `has_war_with` | `has_war_with = ITA` | |
| `has_political_power` | `has_political_power > 100` | Compare with `>` and `<`. |
| `stability` / `war_support` | `stability > 0.1` | 0–1 scale. |
| `has_country_flag` | `has_country_flag = por_done` | |
| `has_completed_focus` | `has_completed_focus = POR_naval_bridge` | |
| `has_idea` | `has_idea = por_spirit` | |
| `has_dlc` | `has_dlc = "Gotterdammerung"` | Quote names with spaces, e.g. `"Poland: United and Ready"`. |
| `date` | `date > 1936.2.11` | Use ranges carefully; exact-day checks may never match. |
| `num_of_civilian_factories` | `num_of_civilian_factories > 10` | Also `num_of_military_factories`. |
| `is_ai` | `is_ai = no` | |
| `check_variable` | `check_variable = { my_var > 3 }` | Variables from `set_variable`. |
| `always` | `always = yes` | Handy placeholder. |
| `is_core_of`, `is_fully_controlled_by`, `is_owned_by` | `802 = { is_fully_controlled_by = ROOT }` | State checks. |
| `compliance`, `resistance` | `802 = { compliance > 30 }` | State values. |

## Effects (verified)

| Effect | Example | Notes |
|---|---|---|
| `add_political_power` | `add_political_power = 50` | Negative values subtract. |
| `add_stability` | `add_stability = 0.02` | 0–1 scale. |
| `add_war_support` | `add_war_support = -0.05` | 0–1 scale. |
| `add_manpower` | `add_manpower = 10000` | |
| `add_popularity` | `add_popularity = { ideology = democratic popularity = 0.1 }` | Ideology group, then fraction. |
| `set_country_flag` / `clr_country_flag` | `set_country_flag = por_done` | Flags remember choices. |
| `add_ideas` / `remove_ideas` | `add_ideas = por_spirit` | National spirits and laws. |
| `add_timed_idea` | `add_timed_idea = { idea = X days = 365 }` | Expires after the set days. |
| `country_event` / `news_event` | `country_event = { id = por_events.1 days = 5 }` | `id` plus optional `days`, `random`. |
| `hidden_effect` | `hidden_effect = { ... }` | Runs without a tooltip line. |
| `custom_effect_tooltip` | `custom_effect_tooltip = por_tooltip_key` | Shows a loc line instead of the raw effects. |
| `complete_national_focus` / `unlock_national_focus` | `complete_national_focus = POR_x` | Complete or skip a focus. |
| `load_focus_tree` | `load_focus_tree = { tree = X keep_completed = yes }` | Switch the active tree. |
| `random_owned_controlled_state` | `random_owned_controlled_state = { save_event_target_as = s }` | Picks a state; `save_event_target_as` keeps it for the event. |
| `add_state_core` / `remove_state_claim` | `add_state_core = 802` | State ownership claims. |
| `transfer_state_to` | `transfer_state_to = ROOT` | Used in state events and decisions. |
| `log` | `log = "debug [?my_var]"` | Writes to the log, handy when debugging. |
| `set_variable` | `set_variable = { my_var = 5 }` | Named variables; read them with `check_variable`. |

## Logic blocks

```
if = {
	limit = { has_country_flag = por_done }
	add_stability = 0.01
}
```

## Patterns from real mods

```
# Decision that needs a neighbour at war, state-based check
available = {
	802 = {
		is_fully_controlled_by = ROOT
		compliance > 30
	}
}

# Hidden event fired after a delay, no window
hidden_effect = {
	country_event = { id = por_events.2 days = 30 }
}

# One-time reward guarded by a flag
if = {
	limit = { NOT = { has_country_flag = por_reward_given } }
	set_country_flag = por_reward_given
	add_political_power = 100
}
```

## Balance rules of thumb

- Political power: 25–75 for small rewards, 100–150 for branch capstones.
- Stability and war support: 0.01–0.05 per step. Larger values need a reason.
- A decision's `cost` is political power; keep it at 25–100 unless the decision is a major commitment.
- Don't stack many large rewards on one focus; spread them across a branch.
