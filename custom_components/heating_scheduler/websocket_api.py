"""WebSocket API used by the Heating Scheduler Lovelace card."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, MODES, SIGNAL_STATUS_UPDATED
from .engine import async_validate_conditions

SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("name"): str,
        vol.Optional("enabled", default=True): bool,
        vol.Required("entities"): [str],
        vol.Required("weekdays"): [vol.All(int, vol.Range(min=0, max=6))],
        vol.Required("time_from"): str,
        vol.Required("time_to"): str,
        vol.Required("mode"): vol.In(MODES),
        vol.Optional("temperature", default=None): vol.Any(None, vol.Coerce(float)),
        # Takes precedence over "temperature" when set (e.g. an input_number).
        vol.Optional("temperature_entity", default=None): vol.Any(None, str),
        # Automation-style condition configs; validated separately with
        # Home Assistant's own condition helpers in ws_save_schedule.
        vol.Optional("conditions", default=[]): [dict],
    },
    extra=vol.REMOVE_EXTRA,
)


def async_register(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    websocket_api.async_register_command(hass, ws_list_schedules)
    websocket_api.async_register_command(hass, ws_save_schedule)
    websocket_api.async_register_command(hass, ws_delete_schedule)
    websocket_api.async_register_command(hass, ws_reorder_schedules)
    websocket_api.async_register_command(hass, ws_subscribe_status)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list"})
@websocket_api.async_response
async def ws_list_schedules(hass, connection, msg):
    """Return all configured schedules, in priority order."""
    store = hass.data[DOMAIN]["store"]
    connection.send_result(msg["id"], {"schedules": store.schedules})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save",
        vol.Required("schedule"): dict,
    }
)
@websocket_api.async_response
async def ws_save_schedule(hass, connection, msg):
    """Create or update a schedule."""
    try:
        schedule = SCHEDULE_SCHEMA(msg["schedule"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_schedule", str(err))
        return

    try:
        await async_validate_conditions(hass, schedule["conditions"])
    except (vol.Invalid, HomeAssistantError) as err:
        connection.send_error(msg["id"], "invalid_conditions", str(err))
        return

    store = hass.data[DOMAIN]["store"]
    saved = await store.async_upsert(schedule)
    await hass.data[DOMAIN]["engine"].async_reload()
    connection.send_result(msg["id"], {"schedule": saved})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/delete",
        vol.Required("schedule_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_schedule(hass, connection, msg):
    """Delete a schedule."""
    store = hass.data[DOMAIN]["store"]
    await store.async_delete(msg["schedule_id"])
    await hass.data[DOMAIN]["engine"].async_reload()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reorder",
        vol.Required("order"): [str],
    }
)
@websocket_api.async_response
async def ws_reorder_schedules(hass, connection, msg):
    """Reorder schedules. Order in the list doubles as priority."""
    store = hass.data[DOMAIN]["store"]
    await store.async_reorder(msg["order"])
    await hass.data[DOMAIN]["engine"].async_reload()
    connection.send_result(msg["id"], {"schedules": store.schedules})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe_status"})
@callback
def ws_subscribe_status(hass, connection, msg):
    """Push each schedule's live state (time window, conditions, winners).

    Conditions can be arbitrary (templates, sun, numeric_state, ...) and the
    time window depends on Home Assistant's time zone, so the card can't
    evaluate them itself - the engine's result is pushed instead, once right
    away and then whenever it changes.
    """

    @callback
    def forward(status):
        connection.send_message(
            websocket_api.event_message(msg["id"], {"status": status})
        )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_STATUS_UPDATED, forward
    )
    connection.send_result(msg["id"])
    forward(hass.data[DOMAIN]["engine"].status)
