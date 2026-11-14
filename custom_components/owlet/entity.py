"""Base class for Owlet entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import OwletCoordinator


class OwletBaseEntity(CoordinatorEntity[OwletCoordinator]):
    """Base class for Owlet Sock entities."""

    _attr_has_entity_name = True

    # Entities that only make sense while the sock is worn override these.
    _available_during_charging = True
    _requires_fresh_vitals = False

    def __init__(self, coordinator: OwletCoordinator, key: str) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self.sock = coordinator.sock
        self._key = key
        self._attr_unique_id = f"{self.sock.serial}-{key}"

        mac = format_mac(self.sock.mac) if self.sock.mac else ""
        connections = (
            {(CONNECTION_NETWORK_MAC, mac)}
            if len(mac) == 17 and mac.count(":") == 5
            else set()
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.sock.serial)},
            connections=connections,
            name=f"Owlet Sock {self.sock.serial}",
            suggested_area="Nursery",
            configuration_url="https://my.owletcare.com/",
            manufacturer=MANUFACTURER,
            model=self.sock.model or None,
            sw_version=self.sock.sw_version,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        properties = self.sock.properties
        if not self._available_during_charging and properties.get("charging"):
            return False
        if self._requires_fresh_vitals and self.coordinator.vitals_stale:
            return False
        return True
