"""Support for Owlet switches."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyowletapi.exceptions import OwletError

from .coordinator import OwletConfigEntry, OwletCoordinator
from .entity import OwletBaseEntity

PARALLEL_UPDATES = 1

BASE_STATION_DESCRIPTION = SwitchEntityDescription(
    key="base_station_on",
    translation_key="base_on",
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OwletConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Owlet switch based on a config entry."""
    async_add_entities(
        OwletBaseStationSwitch(coordinator)
        for coordinator in config_entry.runtime_data.values()
        if BASE_STATION_DESCRIPTION.key in coordinator.sock.properties
    )


class OwletBaseStationSwitch(OwletBaseEntity, SwitchEntity):
    """Switch turning base station monitoring on or off."""

    entity_description = BASE_STATION_DESCRIPTION
    _available_during_charging = False

    def __init__(self, coordinator: OwletCoordinator) -> None:
        """Initialize owlet switch platform."""
        super().__init__(coordinator, BASE_STATION_DESCRIPTION.key)

    @property
    def is_on(self) -> bool | None:
        """Return if switch is on or off."""
        value = self.sock.properties.get(self.entity_description.key)
        return None if value is None else bool(value)

    async def _async_set(self, state: bool) -> None:
        """Send the command and refresh the state."""
        try:
            await self.sock.control_base_station(state)
        except (OwletError, ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Could not turn the Owlet base station {'on' if state else 'off'}: "
                f"{err}"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self._async_set(False)
