"""Evaluate heating schedules and apply them to climate entities.

Priority model: schedules are evaluated in list order, and the *last* schedule
in the list that currently matches (weekday, time window, conditions met,
enabled) wins for a given climate entity. This gives a simple "last one
overwrites" behaviour without needing an explicit priority field - reordering
schedules in the UI is how you change precedence.

Two global behaviours are controlled by select entities (see select.py) so
they can be changed live from any dashboard:

- "Ohne aktiven Plan" (no_schedule_action): if no schedule currently matches a
  managed entity, either force it to "off" (default) or leave it untouched.
- "Plandurchsetzung" (enforcement): "Plan erzwingen" (default) re-applies the
  active target every evaluation, overriding manual changes within minutes.
  "Manuelle Änderung respektieren" only applies a target when it actually
  changes (a different schedule/fallback takes over), so a manual change made
  while a schedule is active is left alone until the next transition.

Conditions use the exact same format and evaluation as automation conditions
(state, numeric_state, template, time, sun, and/or/not, ...), via Home
Assistant's own condition helpers.

Re-evaluation happens every minute and whenever any entity referenced by a
schedule's conditions - or either behaviour select - changes state, so e.g.
"Kinder zuhause" turning off mid-window takes effect immediately instead of
waiting for the next scheduled boundary. Template conditions don't expose
their entities, so they are only picked up by the minute tick.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from datetime import datetime, time as dt_time
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import condition, config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)

from .const import (
    ENFORCEMENT_ENTITY_ID,
    ENFORCEMENT_FORCE,
    ENFORCEMENT_RESPECT_MANUAL,
    NO_SCHEDULE_ACTION_ENTITY_ID,
    NO_SCHEDULE_OFF,
    SIGNAL_STATUS_UPDATED,
)
from .store import ScheduleStore

_LOGGER = logging.getLogger(__name__)

_FALLBACK_OFF_SOURCE = "__fallback_off__"


async def async_validate_conditions(
    hass: HomeAssistant, raw_conditions: list[dict[str, Any]]
) -> list[Any]:
    """Validate automation-style conditions, the same way automations do.

    Raises vol.Invalid or HomeAssistantError if a condition is invalid. The
    raw input is left untouched, so it can be stored as entered.
    """
    conditions = cv.CONDITIONS_SCHEMA(copy.deepcopy(raw_conditions))
    return await condition.async_validate_conditions_config(hass, conditions)


def _never_met(variables: Any = None) -> bool:
    return False


def _parse_time(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def _in_window(now: dt_time, start: dt_time, end: dt_time) -> bool:
    """Return whether `now` falls in [start, end), handling overnight spans."""
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _matching_weekday(now: datetime, start: dt_time, end: dt_time) -> int:
    """Return the weekday (0=Mon) the currently active window belongs to.

    For an overnight window (e.g. 22:00-06:00), the hours after midnight still
    belong to the weekday the window started on.
    """
    if start <= end or now.time() >= start:
        return now.weekday()
    return (now.weekday() - 1) % 7


class SchedulerEngine:
    """Evaluate heating schedules and drive climate entities."""

    def __init__(self, hass: HomeAssistant, store: ScheduleStore) -> None:
        self.hass = hass
        self.store = store
        self._unsub_time = None
        self._unsub_state = None
        self._last_commanded: dict[str, tuple[str, str, float | None]] = {}
        self._checkers: dict[str, Callable[..., bool]] = {}
        self._condition_entities: set[str] = set()
        # Schedule id -> whether its conditions are currently met.
        self.conditions_status: dict[str, bool] = {}

    async def async_start(self) -> None:
        """Start periodic evaluation and condition-entity tracking."""
        self._unsub_time = async_track_time_change(
            self.hass, self._handle_time_tick, second=0
        )
        await self._async_build_checkers()
        self._resubscribe_conditions()
        await self.async_evaluate()

    @callback
    def async_stop(self) -> None:
        """Stop all listeners."""
        if self._unsub_time:
            self._unsub_time()
            self._unsub_time = None
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    async def async_reload(self) -> None:
        """Call after schedules were changed via the frontend."""
        await self._async_build_checkers()
        self._resubscribe_conditions()
        await self.async_evaluate()

    async def _async_build_checkers(self) -> None:
        """Compile every schedule's conditions into a checker function."""
        checkers: dict[str, Callable[..., bool]] = {}
        entities: set[str] = set()

        for schedule in self.store.schedules:
            raw_conditions = schedule.get("conditions", [])
            if not raw_conditions:
                continue
            name = f"Heating schedule '{schedule['name']}'"
            try:
                validated = await async_validate_conditions(self.hass, raw_conditions)
                checker = await condition.async_conditions_from_config(
                    self.hass, validated, _LOGGER, name
                )
            except (vol.Invalid, HomeAssistantError) as err:
                # Never let a broken schedule apply - treat it as "not met".
                _LOGGER.warning("Invalid conditions in %s: %s", name, err)
                checker = _never_met
            else:
                for config in validated:
                    entities |= condition.async_extract_entities(config)
            checkers[schedule["id"]] = checker

        self._checkers = checkers
        self._condition_entities = entities

    def _check_conditions(self, schedule: dict[str, Any]) -> bool:
        checker = self._checkers.get(schedule["id"])
        if checker is None:
            # Not compiled (yet) - only safe to treat as met without conditions.
            return not schedule.get("conditions")
        try:
            return checker(None)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Error evaluating conditions of %s: %s", schedule["name"], err
            )
            return False

    def _resubscribe_conditions(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

        condition_entities = sorted(
            self._condition_entities
            | {NO_SCHEDULE_ACTION_ENTITY_ID, ENFORCEMENT_ENTITY_ID}
        )
        self._unsub_state = async_track_state_change_event(
            self.hass, condition_entities, self._handle_condition_change
        )

    @callback
    def _handle_time_tick(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_evaluate(now))

    @callback
    def _handle_condition_change(self, event) -> None:
        self.hass.async_create_task(self.async_evaluate())

    async def async_evaluate(self, now: datetime | None = None) -> None:
        """Re-evaluate every scheduled climate entity and apply the winner."""
        now = now or datetime.now()
        current_time = now.time()

        # Evaluate each schedule's conditions once per run, not per entity.
        status = {
            schedule["id"]: self._check_conditions(schedule)
            for schedule in self.store.schedules
        }
        if status != self.conditions_status:
            self.conditions_status = status
            async_dispatcher_send(self.hass, SIGNAL_STATUS_UPDATED, status)

        entities = sorted(
            {
                entity_id
                for schedule in self.store.schedules
                for entity_id in schedule.get("entities", [])
            }
        )

        for entity_id in entities:
            winner = self._find_winner(entity_id, now, current_time, status)
            target = self._resolve_target(winner)
            if target is not None:
                await self._maybe_apply(entity_id, target)

    def _find_winner(
        self,
        entity_id: str,
        now: datetime,
        current_time: dt_time,
        status: dict[str, bool],
    ) -> dict[str, Any] | None:
        for schedule in reversed(self.store.schedules):
            if not schedule.get("enabled", True):
                continue
            if entity_id not in schedule.get("entities", []):
                continue

            start = _parse_time(schedule["time_from"])
            end = _parse_time(schedule["time_to"])
            if not _in_window(current_time, start, end):
                continue

            weekday = _matching_weekday(now, start, end)
            if weekday not in schedule.get("weekdays", []):
                continue

            if not status.get(schedule["id"], False):
                continue

            return schedule
        return None

    def _resolve_target(
        self, winner: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Turn a winning schedule (or the lack of one) into a concrete target."""
        if winner is not None:
            return {
                "source": winner["id"],
                "mode": winner["mode"],
                "temperature": winner.get("temperature"),
            }

        no_schedule_state = self.hass.states.get(NO_SCHEDULE_ACTION_ENTITY_ID)
        no_schedule_action = (
            no_schedule_state.state if no_schedule_state else NO_SCHEDULE_OFF
        )
        if no_schedule_action == NO_SCHEDULE_OFF:
            return {"source": _FALLBACK_OFF_SOURCE, "mode": "off", "temperature": None}
        return None

    def _enforcement(self) -> str:
        state = self.hass.states.get(ENFORCEMENT_ENTITY_ID)
        return state.state if state else ENFORCEMENT_FORCE

    async def _maybe_apply(self, entity_id: str, target: dict[str, Any]) -> None:
        desired_key = (target["source"], target["mode"], target["temperature"])

        if self._enforcement() == ENFORCEMENT_RESPECT_MANUAL:
            if self._last_commanded.get(entity_id) == desired_key:
                # Same schedule/fallback as last time we actively commanded -
                # any drift since then is a manual change we intentionally
                # leave alone until the target itself changes.
                return

        await self._apply(entity_id, target)
        self._last_commanded[entity_id] = desired_key

    async def _apply(self, entity_id: str, target: dict[str, Any]) -> None:
        mode = target["mode"]
        temperature = target.get("temperature")

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.debug("Skipping unknown entity %s", entity_id)
            return

        if state.state != mode:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": mode},
                blocking=True,
            )

        if mode != "off" and temperature is not None:
            current_temp = state.attributes.get("temperature")
            if current_temp != temperature:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": temperature},
                    blocking=True,
                )
