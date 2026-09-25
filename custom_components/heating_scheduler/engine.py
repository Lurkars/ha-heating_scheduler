"""Evaluate heating schedules and apply them to climate entities.

Priority model: schedules are evaluated in list order, and the *last* schedule
in the list that currently matches (weekday, time window, all conditions true,
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

Re-evaluation happens every minute and whenever any condition entity used by a
schedule - or either behaviour select - changes state, so a boolean flipping
mid-window (e.g. "Kinder zuhause" turning off) takes effect immediately
instead of waiting for the next scheduled boundary.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time
from typing import Any

from homeassistant.core import HomeAssistant, callback
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
)
from .store import ScheduleStore

_LOGGER = logging.getLogger(__name__)

_CONDITION_TRUE_STATES = ("on",)
_FALLBACK_OFF_SOURCE = "__fallback_off__"


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

    async def async_start(self) -> None:
        """Start periodic evaluation and condition-entity tracking."""
        self._unsub_time = async_track_time_change(
            self.hass, self._handle_time_tick, second=0
        )
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
        self._resubscribe_conditions()
        await self.async_evaluate()

    def _resubscribe_conditions(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

        condition_entities = sorted(
            {
                entity_id
                for schedule in self.store.schedules
                for entity_id in schedule.get("conditions", [])
            }
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

        entities = sorted(
            {
                entity_id
                for schedule in self.store.schedules
                for entity_id in schedule.get("entities", [])
            }
        )

        for entity_id in entities:
            winner = self._find_winner(entity_id, now, current_time)
            target = self._resolve_target(winner)
            if target is not None:
                await self._maybe_apply(entity_id, target)

    def _find_winner(
        self, entity_id: str, now: datetime, current_time: dt_time
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

            if not self._conditions_met(schedule.get("conditions", [])):
                continue

            return schedule
        return None

    def _conditions_met(self, condition_entities: list[str]) -> bool:
        for entity_id in condition_entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state not in _CONDITION_TRUE_STATES:
                return False
        return True

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
