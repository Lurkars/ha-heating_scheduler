"""Global behaviour switches for the Heating Scheduler, exposed as select entities.

These are plain entities (not stored in the schedule store) so their state is
restored by Home Assistant itself across restarts and they can be toggled from
any dashboard without touching the Heating Scheduler card.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    ENFORCEMENT_ENTITY_ID,
    ENFORCEMENT_FORCE,
    ENFORCEMENT_OPTIONS,
    NO_SCHEDULE_ACTION_ENTITY_ID,
    NO_SCHEDULE_OFF,
    NO_SCHEDULE_OPTIONS,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Heating Scheduler behaviour select entities."""
    async_add_entities(
        [
            _BehaviourSelect(
                entry,
                entity_id=NO_SCHEDULE_ACTION_ENTITY_ID,
                unique_id_suffix="no_schedule_action",
                translation_key="no_schedule_action",
                options=NO_SCHEDULE_OPTIONS,
                default=NO_SCHEDULE_OFF,
            ),
            _BehaviourSelect(
                entry,
                entity_id=ENFORCEMENT_ENTITY_ID,
                unique_id_suffix="enforcement",
                translation_key="enforcement",
                options=ENFORCEMENT_OPTIONS,
                default=ENFORCEMENT_FORCE,
            ),
        ]
    )


class _BehaviourSelect(SelectEntity, RestoreEntity):
    """A simple select entity whose state is restored across restarts."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        *,
        entity_id: str,
        unique_id_suffix: str,
        translation_key: str,
        options: list[str],
        default: str,
    ) -> None:
        self.entity_id = entity_id
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_translation_key = translation_key
        self._attr_options = options
        self._attr_current_option = default
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Heating Scheduler",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Restore the previous selection, if any."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            self._attr_current_option = last_state.state

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()
