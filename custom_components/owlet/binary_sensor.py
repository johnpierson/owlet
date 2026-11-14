"""Support for Owlet binary sensors."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SLEEP_STATES
from .coordinator import OwletConfigEntry, OwletCoordinator
from .entity import OwletBaseEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OwletBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Represent the owlet binary sensor entity description."""

    available_during_charging: bool


SENSORS: tuple[OwletBinarySensorEntityDescription, ...] = (
    OwletBinarySensorEntityDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="high_heart_rate_alert",
        translation_key="high_hr_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="low_heart_rate_alert",
        translation_key="low_hr_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="high_oxygen_alert",
        translation_key="high_ox_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="low_oxygen_alert",
        translation_key="low_ox_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="critical_oxygen_alert",
        translation_key="crit_ox_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="low_battery_alert",
        translation_key="low_batt_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="critical_battery_alert",
        translation_key="crit_batt_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="lost_power_alert",
        translation_key="lost_pwr_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="sock_disconnected",
        translation_key="sock_discon_alrt",
        device_class=BinarySensorDeviceClass.SOUND,
        available_during_charging=True,
    ),
    OwletBinarySensorEntityDescription(
        key="sock_off",
        translation_key="sock_off",
        device_class=BinarySensorDeviceClass.POWER,
        available_during_charging=True,
    ),
)

AWAKE_DESCRIPTION = OwletBinarySensorEntityDescription(
    key="sleep_state",
    translation_key="awake",
    icon="mdi:sleep",
    available_during_charging=False,
)

STALE_DESCRIPTION = BinarySensorEntityDescription(
    key="vitals_stale",
    translation_key="vitals_stale",
    device_class=BinarySensorDeviceClass.PROBLEM,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OwletConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the owlet sensors from config entry."""
    sensors: list[BinarySensorEntity] = []

    for coordinator in config_entry.runtime_data.values():
        properties = coordinator.sock.properties
        sensors.extend(
            OwletBinarySensor(coordinator, sensor)
            for sensor in SENSORS
            if sensor.key in properties
        )

        if AWAKE_DESCRIPTION.key in properties:
            sensors.append(OwletAwakeSensor(coordinator, AWAKE_DESCRIPTION))
        if coordinator.vitals_updated_at is not None:
            sensors.append(OwletStaleSensor(coordinator))

    async_add_entities(sensors)


class OwletBinarySensor(OwletBaseEntity, BinarySensorEntity):
    """Representation of an Owlet binary sensor."""

    entity_description: OwletBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: OwletCoordinator,
        description: OwletBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._available_during_charging = description.available_during_charging
        self._requires_fresh_vitals = not description.available_during_charging

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        value = self.sock.properties.get(self.entity_description.key)
        return None if value is None else bool(value)


class OwletAwakeSensor(OwletBinarySensor):
    """Representation of an Owlet sleep sensor."""

    @property
    def is_on(self) -> bool | None:
        """Return true if awake, unknown if the sock has no sleep state."""
        state = self.sock.properties.get("sleep_state")
        if state not in SLEEP_STATES or SLEEP_STATES[state] == "unknown":
            return None
        return SLEEP_STATES[state] == "awake"


class OwletStaleSensor(OwletBaseEntity, BinarySensorEntity):
    """Problem sensor that turns on when the cloud stops receiving vitals."""

    entity_description = STALE_DESCRIPTION

    def __init__(self, coordinator: OwletCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, STALE_DESCRIPTION.key)

    @property
    def is_on(self) -> bool:
        """Return true if the readings stopped updating."""
        return self.coordinator.vitals_stale
