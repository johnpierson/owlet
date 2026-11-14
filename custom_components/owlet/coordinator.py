"""Owlet integration coordinator class."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pyowletapi.exceptions import OwletAuthenticationError, OwletError
from pyowletapi.sock import Sock

from .const import DOMAIN, STALE_AFTER, UPDATE_TIMEOUT

if TYPE_CHECKING:
    from .api import OwletClient

_LOGGER = logging.getLogger(__name__)

type OwletConfigEntry = ConfigEntry[dict[str, OwletCoordinator]]

TOKEN_KEYS = ("api_token", "expiry", "refresh")


@callback
def async_persist_tokens(
    hass: HomeAssistant, entry: ConfigEntry, client: OwletClient
) -> None:
    """Store refreshed API tokens so they survive a restart."""
    tokens = {
        key: value
        for key, value in client.tokens.items()
        if key in TOKEN_KEYS and value is not None
    }
    if any(entry.data.get(key) != value for key, value in tokens.items()):
        hass.config_entries.async_update_entry(entry, data={**entry.data, **tokens})


class OwletCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator polling a single sock."""

    config_entry: OwletConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OwletConfigEntry,
        sock: Sock,
        interval: int,
    ) -> None:
        """Initialise a custom coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {sock.serial}",
            update_interval=timedelta(seconds=interval),
        )
        self.sock = sock

    @property
    def vitals_updated_at(self) -> datetime | None:
        """Return when the cloud last received vitals (Smart Sock 3 only)."""
        raw = self.sock.raw_properties.get("REAL_TIME_VITALS")
        if not isinstance(raw, dict):
            return None
        value = raw.get("data_updated_at")
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        return dt_util.as_utc(parsed)

    @property
    def vitals_stale(self) -> bool:
        """Return True if the readings stopped updating in the Owlet cloud."""
        updated_at = self.vitals_updated_at
        if updated_at is None:
            return False
        return (dt_util.utcnow() - updated_at).total_seconds() > STALE_AFTER

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the data from the device."""
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT):
                await self.sock.update_properties()
        except OwletAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                "Owlet authentication expired, please sign in again"
            ) from err
        except (OwletError, ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching Owlet data: {err}") from err
        except (KeyError, TypeError, ValueError) as err:
            raise UpdateFailed(
                f"Unexpected data from Owlet ({type(err).__name__}: {err})"
            ) from err

        async_persist_tokens(self.hass, self.config_entry, self.sock.api)
        return dict(self.sock.properties)
