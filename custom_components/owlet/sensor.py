"""Support for Owlet sensors."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import SLEEP_STATES
from .coordinator import OwletConfigEntry, OwletCoordinator
from .entity import OwletBaseEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OwletSensorEntityDescription(SensorEntityDescription):
    """Represent the owlet sensor entity description."""

    available_during_charging: bool


SENSORS: tuple[OwletSensorEntityDescription, ...] = (
    OwletSensorEntityDescription(
        key="battery_percentage",
        translation_key="batterypercent",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        available_during_charging=True,
    ),
    OwletSensorEntityDescription(
        key="oxygen_saturation",
        translation_key="o2saturation",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:leaf",
        available_during_charging=False,
    ),
    OwletSensorEntityDescription(
        key="heart_rate",
        translation_key="heartrate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        available_during_charging=False,
    ),
    OwletSensorEntityDescription(
        key="battery_minutes",
        translation_key="batterymin",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        available_during_charging=False,
    ),
    OwletSensorEntityDescription(
        key="signal_strength",
        translation_key="signalstrength",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        available_during_charging=True,
    ),
    OwletSensorEntityDescription(
        key="skin_temperature",
        translation_key="skintemp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        available_during_charging=False,
    ),
    OwletSensorEntityDescription(
        key="movement",
        translation_key="movement",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cursor-move",
        entity_registry_enabled_default=False,
        available_during_charging=False,
    ),
    OwletSensorEntityDescription(
        key="movement_bucket",
        translation_key="movementbucket",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:bucket-outline",
        entity_registry_enabled_default=False,
        available_during_charging=False,
    ),
)

SLEEP_STATE_DESCRIPTION = OwletSensorEntityDescription(
    key="sleep_state",
    translation_key="sleepstate",
    device_class=SensorDeviceClass.ENUM,
    options=list(SLEEP_STATES.values()),
    available_during_charging=False,
)

OXYGEN_AVERAGE_DESCRIPTION = OwletSensorEntityDescription(
    key="oxygen_10_av",
    translation_key="o2saturation10a",
    native_unit_of_measurement=PERCENTAGE,
    icon="mdi:leaf",
    available_during_charging=False,
    state_class=SensorStateClass.MEASUREMENT,
)

LAST_UPDATED_DESCRIPTION = SensorEntityDescription(
    key="last_updated",
    translation_key="lastupdated",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    # Changes on every poll, so it is opt-in to keep the recorder small.
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OwletConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the owlet sensors from config entry."""
    sensors: list[SensorEntity] = []

    for coordinator in config_entry.runtime_data.values():
        properties = coordinator.sock.properties
        sensors.extend(
            OwletSensor(coordinator, sensor)
            for sensor in SENSORS
            if sensor.key in properties
        )

        if SLEEP_STATE_DESCRIPTION.key in properties:
            sensors.append(OwletSleepSensor(coordinator, SLEEP_STATE_DESCRIPTION))
        if OXYGEN_AVERAGE_DESCRIPTION.key in properties:
            sensors.append(
                OwletOxygenAverageSensor(coordinator, OXYGEN_AVERAGE_DESCRIPTION)
            )
        if coordinator.vitals_updated_at is not None:
            sensors.append(OwletLastUpdatedSensor(coordinator))

    async_add_entities(sensors)


class OwletSensor(OwletBaseEntity, SensorEntity):
    """Representation of an Owlet sensor."""

    entity_description: OwletSensorEntityDescription

    def __init__(
        self,
        coordinator: OwletCoordinator,
        description: OwletSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._available_during_charging = description.available_during_charging
        # Live readings must not be shown once the cloud stops receiving them.
        self._requires_fresh_vitals = not description.available_during_charging

    @property
    def native_value(self) -> StateType:
        """Return sensor value."""
        value = self.sock.properties.get(self.entity_description.key)
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value


class OwletSleepSensor(OwletSensor):
    """Representation of an Owlet sleep sensor."""

    @property
    def native_value(self) -> StateType:
        """Return sensor value."""
        return SLEEP_STATES.get(self.sock.properties.get("sleep_state"))


class OwletOxygenAverageSensor(OwletSensor):
    """Representation of the Owlet 10 minute oxygen average sensor."""

    @property
    def native_value(self) -> StateType:
        """Return sensor value, the sock reports 255 until an average exists."""
        value = self.sock.properties.get("oxygen_10_av")
        if not isinstance(value, (int, float)) or not 0 <= value <= 100:
            return None
        return value


class OwletLastUpdatedSensor(OwletBaseEntity, SensorEntity):
    """Timestamp of the last vitals the Owlet cloud received from the sock."""

    entity_description = LAST_UPDATED_DESCRIPTION

    def __init__(self, coordinator: OwletCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, LAST_UPDATED_DESCRIPTION.key)

    @property
    def native_value(self) -> datetime | None:
        """Return sensor value."""
        return self.coordinator.vitals_updated_at
