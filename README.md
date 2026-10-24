# Heating Scheduler

Custom Home Assistant integration + dashboard card for managing heating schedules for thermostats (`climate` entities).

## Features

- Create any number of schedules
- Select 1-n thermostats per schedule
- Weekdays (Mon-Sun) individually selectable
- From/to time, including overnight spans (e.g. 22:00-06:00)
- Mode per schedule: **Auto**, **Heat** (with target temperature), or **Off** (no temperature needed)
- Conditions per schedule using Home Assistant's own automation condition editor (state, numeric state, template, time, sun, zone, and/or/not, ...); **all** must be met for the schedule to apply
- Clear management GUI as a dashboard card: create, edit, duplicate (as a template), delete, enable/disable, reorder via arrows
- Schedule order = priority: if two active schedules overlap for the same thermostat, the one **lower in the list** automatically wins ("gets overwritten")
- Two behaviour switches as dedicated `select` entities (see below), changeable live at any time
- Fully localized UI: English and German, following Home Assistant's own language setting

## Installation

### Via HACS (custom repository)

1. Publish this directory as a Git repository on GitHub.
2. In Home Assistant: HACS → Integrations → menu (⋮) → Custom repositories → enter the repo URL, category "Integration".
3. Install "Heating Scheduler" and restart Home Assistant.

### Manual

Copy the `custom_components/heating_scheduler` folder into the `custom_components` directory of your Home Assistant configuration and restart Home Assistant.

### Setup

1. Settings → Devices & Services → Add integration → search for "Heating Scheduler" and add it (no further input needed).
2. Edit a dashboard → Add card → select "Heating Scheduler" (or as YAML: `type: custom:heating-scheduler-card`).
3. The card registers itself automatically as a plain Lovelace resource (no manual step needed). If that doesn't work for some reason on your setup (e.g. YAML-managed dashboards instead of storage mode), add it manually once: Settings → Dashboards → menu (⋮) → Resources → Add resource → URL `/heating_scheduler_files/heating-scheduler-card.js`, type "JavaScript Module".

> **Important:** the card is deliberately loaded *only* through the normal Lovelace resource (not additionally through a second, parallel mechanism). Two concurrent `import()` calls for the exact same module URL from two independent sources can, in some browsers, result in neither one actually registering the custom element (observed with Firefox) - identical network content, yet `customElements.get(...)` stays permanently `undefined`. If the card doesn't load for you despite the resource being registered correctly, check whether it's accidentally being loaded some other way too (e.g. a duplicate resource entry, or a dashboard that separately references it via YAML `resources:`).

## Usage

Create a schedule in the card via "+ New schedule":

- **Name** - freely chosen, for your own overview
- **Active** - fully enable/disable a schedule without deleting it
- **Thermostats** - one or more `climate` entities
- **Weekdays** - which days the schedule applies on
- **From/To** - time window; if "To" < "From" it automatically wraps past midnight
- **Mode** - Auto / Heat / Off; no temperature is set when "Off"
- **Target temperature** - only relevant for Heat/Auto mode
- **Conditions** - exactly the same conditions (and editor) as in automations, e.g. `input_boolean.kids_home` is on, outdoor temperature below 15 °C, someone is home, or any template; the schedule is only applied when **all** top-level conditions are met. To *exclude* a schedule (e.g. during holidays or with a window open), wrap the conditions in a **Not** condition. Weekdays and the time window stay separate fields on purpose.

Use **Duplicate** in a schedule's menu (⋮) to open a pre-filled copy in the editor; it's only created once you save it (and is appended at the end of the list, i.e. with the highest priority).

## How evaluation works

- Re-evaluated every minute, and immediately whenever an entity referenced by a condition or one of the two behaviour switches changes. Template conditions don't expose their entities, so they are only re-checked by the minute tick (up to ~1 min delay).
- A schedule with invalid conditions (e.g. referencing a removed integration) never applies; a warning is logged.
- For each thermostat, the list of schedules is walked from bottom to top; the **first** schedule found that way (i.e. the one lowest in the list) that currently matches time/weekday, is enabled, has its conditions met and none of its disable conditions on, wins and gets applied.
- If **no** schedule currently matches (e.g. a gap between two schedules, unmet conditions, or an active disable condition), `select.heating_scheduler_no_schedule_action` ("Heating Scheduler: Without an active schedule") takes over:
  - **Turn off** (default) - the thermostat is set to `off`.
  - **Do nothing** - the thermostat is left untouched; manual control is fully respected.
- Whenever a target is active (a schedule or the off-fallback), `select.heating_scheduler_enforcement` ("Heating Scheduler: Schedule enforcement") decides how it's handled:
  - **Force schedule** (default) - the target state is re-applied on every evaluation; a manual change gets overwritten again within a minute at most.
  - **Respect manual changes** - the target state is only applied once on a transition (a new schedule takes over, a new time window starts, the fallback kicks in or stops); after that you can manually override the thermostat without the schedule immediately fighting back, until the next transition.

Both switches appear automatically as entities after setup (device "Heating Scheduler" under Settings → Devices & Services) and can be added to any dashboard as a normal dropdown card.

## Data & storage

Schedules are stored in `.storage/heating_scheduler_schedules` inside the Home Assistant configuration (no YAML needed, no restart on changes). Schedules from older versions (plain condition entity lists) are migrated automatically on startup to equivalent `state` conditions ("is on").

## Developing & testing

**Fast iteration without HACS:** during development, HACS isn't worth the overhead - instead, symlink `custom_components/heating_scheduler` into the `custom_components` folder of your HA configuration:

```bash
ln -s /path/to/homeassistant-heating-scheduling/custom_components/heating_scheduler \
      /path/to/homeassistant-config/custom_components/heating_scheduler
```

- **Python changes** (`__init__.py`, `engine.py`, `select.py`, ...) only take effect after a **full restart** of Home Assistant - "reloading" the integration is *not* enough, since the Python module is already imported in memory.
- **Changes to `heating-scheduler-card.js`** don't need an HA restart, just a hard refresh in the browser (Ctrl+Shift+R). If the browser stubbornly caches an old version, bump `CARD_VERSION` in `const.py` (this only changes the `?v=` query parameter) and reload.

**Testing via HACS as your own repo:** yes, that works exactly as you'd expect:

1. Push this directory to a public GitHub repo.
2. Add it in HACS as a "Custom repository" (category "Integration") and install it.

**Update behaviour:** bumping `"version"` in `manifest.json` alone isn't enough for an automatic update. HACS defaults to tracking **GitHub Releases**:

1. Bump the version in `manifest.json` and commit/push.
2. Push a matching tag (e.g. `v0.2.0`) - `.github/workflows/release.yml` then automatically creates the GitHub release for you (it also fails the run if the tag doesn't match `manifest.json`'s version, to catch mismatches early).
3. HACS periodically checks for new releases in the background (and when you open HACS) and then shows an update - automatic downloading without confirmation only if you enable "Automatic updates" for the repository in HACS.
4. Even after a HACS update, Python changes still need a **Home Assistant restart** to load the new code (only the JS card takes effect right after a browser refresh).

Without a release/tag, HACS instead tracks the latest commit on the default branch (already prepared via `"zip_release": false` in `hacs.json`) - in that case, use the per-repository menu (⋮) → "Redownload" in HACS to force a specific state without a version bump.
