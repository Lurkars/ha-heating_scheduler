"""The Heating Scheduler integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .engine import SchedulerEngine
from .frontend import async_register_frontend
from .store import ScheduleStore
from .websocket_api import async_register as async_register_websocket_api

PLATFORMS: list[str] = ["select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Scheduler from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    store = ScheduleStore(hass)
    await store.async_load()

    engine = SchedulerEngine(hass, store)

    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["engine"] = engine

    if not hass.data[DOMAIN].get("ws_registered"):
        async_register_websocket_api(hass)
        hass.data[DOMAIN]["ws_registered"] = True

    await async_register_frontend(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await engine.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data.get(DOMAIN)
    if data and "engine" in data:
        data["engine"].async_stop()
    hass.data.pop(DOMAIN, None)
    return unloaded
