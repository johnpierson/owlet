"""The Owlet Smart Sock integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_TOKEN,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyowletapi.exceptions import (
    OwletAuthenticationError,
    OwletCredentialsError,
    OwletDevicesError,
    OwletError,
)
from pyowletapi.sock import Sock

from .api import OwletClient
from .const import (
    CONF_OWLET_EXPIRY,
    CONF_OWLET_REFRESH,
    MIN_POLLING_INTERVAL,
    POLLING_INTERVAL,
    SETUP_TIMEOUT,
    SUPPORTED_VERSIONS,
)
from .coordinator import OwletConfigEntry, OwletCoordinator, async_persist_tokens

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

_LOGGER = logging.getLogger(__name__)


def _scan_interval(entry: ConfigEntry) -> int:
    """Return the configured polling interval in seconds."""
    try:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL) or POLLING_INTERVAL)
    except (TypeError, ValueError):
        interval = POLLING_INTERVAL
    return max(interval, MIN_POLLING_INTERVAL)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 2:
        return False

    if entry.version == 1:
        # Version 2 adds the region to the unique id, so the same email can be
        # used for accounts in both Owlet regions.
        region = entry.data.get(CONF_REGION, "world")
        username = str(entry.data.get(CONF_USERNAME) or entry.unique_id or "").lower()
        hass.config_entries.async_update_entry(
            entry, unique_id=f"{region}_{username}", version=2
        )
        _LOGGER.debug("Migrated Owlet config entry to version 2")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: OwletConfigEntry) -> bool:
    """Set up Owlet Smart Sock from a config entry."""
    client = OwletClient(
        region=entry.data[CONF_REGION],
        token=entry.data.get(CONF_API_TOKEN),
        expiry=entry.data.get(CONF_OWLET_EXPIRY),
        refresh=entry.data.get(CONF_OWLET_REFRESH),
        session=async_get_clientsession(hass),
    )

    try:
        async with asyncio.timeout(SETUP_TIMEOUT):
            await client.authenticate()
            devices = await client.get_devices(SUPPORTED_VERSIONS)
    except (OwletAuthenticationError, OwletCredentialsError) as err:
        raise ConfigEntryAuthFailed(
            "Owlet credentials are no longer valid, please sign in again"
        ) from err
    except OwletDevicesError as err:
        raise ConfigEntryError(
            "No supported Owlet socks were found on this account"
        ) from err
    except (OwletError, ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(f"Error connecting to Owlet: {err}") from err

    async_persist_tokens(hass, entry, client)

    interval = _scan_interval(entry)
    coordinators = {
        device["device"]["dsn"]: OwletCoordinator(
            hass, entry, Sock(client, device["device"]), interval
        )
        for device in devices["response"]
    }

    await asyncio.gather(
        *(
            coordinator.async_config_entry_first_refresh()
            for coordinator in coordinators.values()
        )
    )

    entry.runtime_data = coordinators
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: OwletConfigEntry) -> None:
    """Apply a changed polling interval.

    The listener also fires whenever refreshed tokens are stored, so this must
    not reload the entry.
    """
    interval = timedelta(seconds=_scan_interval(entry))
    for coordinator in entry.runtime_data.values():
        if coordinator.update_interval != interval:
            coordinator.update_interval = interval
            await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: OwletConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
