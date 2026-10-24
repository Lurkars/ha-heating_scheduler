"""Persistent storage for heating schedules."""
from __future__ import annotations

import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


def _state_on(entity_id: str) -> dict[str, Any]:
    return {"condition": "state", "entity_id": entity_id, "state": "on"}


def _migrate_schedule_v1(schedule: dict[str, Any]) -> None:
    """Convert v1 entity-list conditions into automation-style conditions.

    v1 stored `conditions` (all must be on) and `disable_conditions` (none may
    be on) as plain entity id lists. v2 stores a single list of Home Assistant
    condition configs, so "none may be on" becomes one `not` condition.
    """
    conditions = [_state_on(entity_id) for entity_id in schedule.get("conditions", [])]
    disable_conditions = schedule.pop("disable_conditions", [])
    if disable_conditions:
        conditions.append(
            {
                "condition": "not",
                "conditions": [_state_on(entity_id) for entity_id in disable_conditions],
            }
        )
    schedule["conditions"] = conditions


class _ScheduleStorage(Store):
    """Store with migrations between schedule storage versions."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict
    ) -> dict:
        if old_major_version < 2:
            for schedule in old_data.get("schedules", []):
                _migrate_schedule_v1(schedule)
        return old_data


class ScheduleStore:
    """Load, persist and mutate the list of heating schedules."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = _ScheduleStorage(hass, STORAGE_VERSION, STORAGE_KEY)
        self.schedules: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load schedules from disk."""
        data = await self._store.async_load()
        self.schedules = (data or {}).get("schedules", [])

    async def async_save(self) -> None:
        """Persist the current schedules to disk."""
        await self._store.async_save({"schedules": self.schedules})

    def get(self, schedule_id: str) -> dict[str, Any] | None:
        """Return a schedule by id, if it exists."""
        return next((s for s in self.schedules if s["id"] == schedule_id), None)

    async def async_upsert(self, schedule: dict[str, Any]) -> dict[str, Any]:
        """Create a new schedule or update an existing one, keeping list order."""
        schedule_id = schedule.get("id")
        existing = self.get(schedule_id) if schedule_id else None

        if existing is None:
            schedule["id"] = schedule_id or uuid.uuid4().hex
            self.schedules.append(schedule)
        else:
            self.schedules[self.schedules.index(existing)] = schedule

        await self.async_save()
        return schedule

    async def async_delete(self, schedule_id: str) -> None:
        """Remove a schedule by id."""
        self.schedules = [s for s in self.schedules if s["id"] != schedule_id]
        await self.async_save()

    async def async_reorder(self, ordered_ids: list[str]) -> None:
        """Reorder schedules. List order doubles as priority (last wins)."""
        lookup = {s["id"]: s for s in self.schedules}
        reordered = [lookup[i] for i in ordered_ids if i in lookup]
        # Keep any schedules not mentioned (defensive) at the end, unchanged order.
        missing = [s for s in self.schedules if s["id"] not in ordered_ids]
        self.schedules = reordered + missing
        await self.async_save()
