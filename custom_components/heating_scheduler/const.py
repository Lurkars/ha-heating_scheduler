"""Constants for the Heating Scheduler integration."""

DOMAIN = "heating_scheduler"

STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}_schedules"

MODES = ["auto", "heat", "off"]

# 0 = Monday ... 6 = Sunday, matching datetime.weekday()
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Dispatcher signal fired by the engine whenever the per-schedule
# "conditions met" status changes; forwarded to the card via websocket.
SIGNAL_STATUS_UPDATED = f"{DOMAIN}_status_updated"

# CARD_PATH is fixed; bump CARD_VERSION whenever heating-scheduler-card.js
# changes so a hard browser refresh reliably picks up the new file during
# development, rather than an old cached copy.
CARD_PATH = "/heating_scheduler_files/heating-scheduler-card.js"
CARD_VERSION = "14"
CARD_URL = f"{CARD_PATH}?v={CARD_VERSION}"

# Options for the "no schedule active" behaviour select entity. These are
# stable internal values (state + option keys) - the displayed label is
# translated via strings.json/translations (entity.select.*.state.*), not by
# changing these values.
NO_SCHEDULE_OFF = "off"
NO_SCHEDULE_NOTHING = "nothing"
NO_SCHEDULE_OPTIONS = [NO_SCHEDULE_OFF, NO_SCHEDULE_NOTHING]
NO_SCHEDULE_ACTION_ENTITY_ID = "select.heating_scheduler_no_schedule_action"

# Options for the enforcement select entity. Same note on translation applies.
ENFORCEMENT_FORCE = "force"
ENFORCEMENT_RESPECT_MANUAL = "respect_manual"
ENFORCEMENT_OPTIONS = [ENFORCEMENT_FORCE, ENFORCEMENT_RESPECT_MANUAL]
ENFORCEMENT_ENTITY_ID = "select.heating_scheduler_enforcement"
