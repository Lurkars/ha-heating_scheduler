"""Serve the Heating Scheduler Lovelace card and register it as a frontend module."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import CARD_PATH, CARD_URL

_LOGGER = logging.getLogger(__name__)

CARD_FILE = Path(__file__).parent / "frontend" / "heating-scheduler-card.js"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the card's JS file as a static path and register it as a resource.

    Deliberately uses *only* the normal Lovelace resource mechanism (not also
    `add_extra_js_url`) - loading the same URL through two independent
    mechanisms at once caused two concurrent `import()`s of the exact same
    module specifier, which in some browsers resulted in neither one ever
    actually defining the custom element. A single, standard resource
    registration is the same path every other Lovelace custom card uses.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_PATH, str(CARD_FILE), False)]
    )
    await _async_register_lovelace_resource(hass)


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Best-effort: register the card as a normal Lovelace resource.

    This mirrors what adding the resource by hand under Settings > Dashboards
    > Resources would do. Only applies when dashboards are storage-managed;
    in YAML mode this is a no-op and the resource has to be added manually
    (see README).

    Matches existing entries by CARD_PATH (regardless of the `?v=` query
    string, or whether it was entered as a relative or absolute URL), so a
    CARD_VERSION bump updates the existing resource in place and re-running
    setup never piles up duplicates.
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            return

        get_info = getattr(resources, "async_get_info", None)
        if get_info is not None:
            await get_info()

        matches = [
            item for item in resources.async_items() if CARD_PATH in item.get("url", "")
        ]

        if not matches:
            await resources.async_create_item({"res_type": "module", "url": CARD_URL})
            return

        keep, *duplicates = matches
        if keep["url"] != CARD_URL:
            await resources.async_update_item(
                keep["id"], {"res_type": "module", "url": CARD_URL}
            )
        for duplicate in duplicates:
            await resources.async_delete_item(duplicate["id"])
    except Exception:  # noqa: BLE001 - best effort, must never block setup
        _LOGGER.warning(
            "Could not auto-register the Lovelace resource for %s; "
            "add/update it manually under Settings > Dashboards > Resources if "
            "the card is missing or duplicated in the card picker.",
            CARD_URL,
            exc_info=True,
        )
