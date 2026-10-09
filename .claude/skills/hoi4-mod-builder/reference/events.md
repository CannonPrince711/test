# Events

Events are pop-up windows (or news items) with a title, a description and options. Event files live in
`events/*.txt`. Source: the HOI4 wiki "Event modding" page and community event files.

## Minimal event file

```
add_namespace = por_events

country_event = {
	id = por_events.1
	title = por_events.1.t
	desc = por_events.1.d
	picture = GFX_report_event_generic_read_write

	is_triggered_only = yes
	fire_only_once = yes

	option = {
		name = por_events.1.a
		add_political_power = 25
	}
}
```

Rules that must hold, or the event silently does nothing:

- **`add_namespace = <namespace>` must come before any event that uses it**, outside any event block.
  The builder writes it at the top of every event file.
- The ID is `<namespace>.<integer>`. The number after the last dot must be an integer, because
  otherwise every event with a non-integer ID is treated as the same event.
- A namespace is declared with `add_namespace`. A namespace may contain dots, such as
  `add_namespace = por.naval`, which gives IDs like `por.naval.1`.

## Event types

| Type | What it is |
|---|---|
| `country_event` | Pop-up for one country. The usual choice. |
| `news_event` | News item. Use `major = yes` to show it to every country. A news event's pop-up can be turned off, but the country still gets it. |
| `state_event`, `unit_leader_event`, `operative_leader_event` | Scoped to a state or leader. Avoid unless you need the special window. |

## Localisation

- `title = <key>` and `desc = <key>` point at loc keys. Use `<id>.t` and `<id>.d` as the convention.
- Option names use the `name` key. Use `<id>.a`, `<id>.b`, ... for each option.
- Provide a title or a description for every visible event. Hidden events need neither.
- Conditional text: `title = { text = key_a trigger = { tag = POR } }` then `title = { text = key_b }`. The first
  block whose trigger holds is used.

## Pictures

`picture = GFX_my_picture` needs a sprite in `interface/*.gfx`, pointing to a texture in the mod. Base-game
pictures such as `GFX_report_event_generic_read_write` need no definition. The builder writes the sprite
only if you add it to `sprites`.

## When it fires

- **Triggered only**: `is_triggered_only = yes`. Fired by `country_event = <id>` from an effect, a focus,
  a decision or another event.
- **Automatic**: no `is_triggered_only`. The game checks `trigger` every 20 days. When the trigger holds, it
  checks `mean_time_to_happen` daily until the event fires. Example:

```
trigger = { tag = POR has_completed_focus = POR_naval_bridge }
mean_time_to_happen = { days = 60 }
```

- `fire_only_once = yes` makes the event fire a single time per country.
- `hidden = yes` runs `immediate` without showing a window. Use it for bookkeeping or delayed effects.
- `immediate = { ... }` runs effects when the event fires, before the options.

### Firing from an effect

```
country_event = { id = por_events.1 days = 5 }   # in five days
country_event = por_events.1                     # now
hidden_effect = { country_event = { id = por_events.2 days = 14 random = 7 } }
```

`hidden_effect` keeps the effect out of the tooltip.

## Options

```
option = {
	name = por_events.1.a
	trigger = { has_political_power > 50 }     # shown only if this holds
	ai_chance = { factor = 10 }                # how often the AI picks it
	add_political_power = -50
	set_country_flag = por_chose_assembly
}
```

- If the player does not choose, the **first** option is taken. Put the safest option first.
- An option whose `ai_chance` is `base = 0` is never picked by the AI.
- Keep 2–3 options. Each option should have a visible consequence.

## Patterns

- **Chain**: a focus completes (`completion_reward = { country_event = { id = por_events.1 } }`), the
  event asks a question, and an option fires the next event.
- **Flag memory**: set `set_country_flag` in one option and check `has_country_flag` in a later trigger.
- **Scheduled follow-up**: `country_event = { id = por_events.2 days = 30 }` inside an option.

## Common mistakes

- Missing `add_namespace` → the event ID is malformed and the event never appears. The validator flags this as an error.
- Two events with the same ID. Behaviour becomes unpredictable, so every event ID must be unique.
- Triggers that depend on exact dates. For example `date > 1936.2.11` followed by `date < 1936.2.13` can
  never be true if the check runs on other days. Use a flag or a hidden event instead.
- An event fired with a `days` delay for a country that does not exist yet waits until that country exists.
- A missing title or option name shows the raw key on screen (for example `por_events.1.a`). Add localisation.
