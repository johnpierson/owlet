"""Constants for the Owlet Smart Sock integration."""

DOMAIN = "owlet"

CONF_OWLET_EXPIRY = "expiry"
CONF_OWLET_REFRESH = "refresh"

SUPPORTED_VERSIONS = [2, 3]
POLLING_INTERVAL = 5
MIN_POLLING_INTERVAL = 5
MAX_POLLING_INTERVAL = 3600

# Seconds allowed for a single HTTP request / a whole poll / the initial setup.
REQUEST_TIMEOUT = 20
UPDATE_TIMEOUT = 45
SETUP_TIMEOUT = 90

# A Smart Sock 3 pushes REAL_TIME_VITALS every few seconds. If the cloud copy is
# older than this the readings are frozen, so they are reported as unavailable
# rather than shown as if they were live.
STALE_AFTER = 300

MANUFACTURER = "Owlet Baby Care"
SLEEP_STATES = {0: "unknown", 1: "awake", 8: "light_sleep", 15: "deep_sleep"}
