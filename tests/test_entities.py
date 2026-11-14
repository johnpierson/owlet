"""Test Owlet sensors, binary sensors and the base station switch."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from . import (
    LATER,
    URL_DEVICES,
    FakeCloud,
    devices_payload,
    entity_id,
    mock_sock,
    properties_payload,
    requests_to,
    setup_entry,
    state_of,
    url_datapoint,
    url_properties,
)


async def _poll(hass: HomeAssistant, freezer, seconds: int = 6) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_sensors_asleep(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """Readings of a worn sock."""
    mock_sock(cloud, "update_properties_asleep.json")
    await setup_entry(hass)

    assert state_of(hass, "sensor", "battery_percentage") == "50.0"
    assert state_of(hass, "sensor", "battery_minutes") == "400.0"
    assert state_of(hass, "sensor", "heart_rate") == "97.0"
    assert state_of(hass, "sensor", "oxygen_saturation") == "99.0"
    assert state_of(hass, "sensor", "oxygen_10_av") == "97.0"
    assert state_of(hass, "sensor", "signal_strength") == "30.0"
    assert state_of(hass, "sensor", "skin_temperature") == "34"
    assert state_of(hass, "sensor", "sleep_state") == "light_sleep"

    assert state_of(hass, "binary_sensor", "sleep_state") == "off"
    assert state_of(hass, "binary_sensor", "charging") == "off"
    assert state_of(hass, "binary_sensor", "low_oxygen_alert") == "off"
    assert state_of(hass, "binary_sensor", "vitals_stale") == "off"
    assert state_of(hass, "switch", "base_station_on") == "on"

    # Noisy or rarely useful entities are opt-in.
    registry = er.async_get(hass)
    for key in ("movement", "movement_bucket", "last_updated"):
        assert registry.async_get(entity_id(hass, "sensor", key)).disabled


async def test_sensors_awake(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """Readings of an awake baby."""
    mock_sock(cloud, "update_properties_awake.json")
    await setup_entry(hass)

    assert state_of(hass, "sensor", "heart_rate") == "110.0"
    assert state_of(hass, "sensor", "sleep_state") == "awake"
    assert state_of(hass, "binary_sensor", "sleep_state") == "on"


async def test_sensors_charging(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """A sock on the charger has no vitals but still reports its battery."""
    mock_sock(cloud, "update_properties_charging.json")
    await setup_entry(hass)

    assert state_of(hass, "sensor", "battery_percentage") == "100.0"
    assert state_of(hass, "binary_sensor", "charging") == "on"
    for key in ("heart_rate", "oxygen_saturation", "oxygen_10_av", "sleep_state"):
        assert state_of(hass, "sensor", key) == STATE_UNAVAILABLE
    assert state_of(hass, "binary_sensor", "sleep_state") == STATE_UNAVAILABLE
    assert state_of(hass, "switch", "base_station_on") == STATE_UNAVAILABLE


async def test_sock_v2(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """A Smart Sock 2 sets up with the properties it has."""
    mock_sock(cloud, "update_properties_v2.json")
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert state_of(hass, "sensor", "heart_rate") not in (
        STATE_UNAVAILABLE,
        STATE_UNKNOWN,
    )
    # No shared vitals timestamp on a Sock 2, so no staleness entities.
    assert entity_id(hass, "binary_sensor", "vitals_stale") is None
    assert entity_id(hass, "sensor", "sleep_state") is None


async def test_frozen_vitals_become_unavailable(
    hass: HomeAssistant, cloud: FakeCloud, freezer
) -> None:
    """Readings the cloud stopped receiving are not shown as live values."""
    mock_sock(cloud, "update_properties_asleep.json")
    await setup_entry(hass)
    assert state_of(hass, "sensor", "heart_rate") == "97.0"

    # The cloud keeps answering with the same sample for 14 minutes.
    freezer.move_to(LATER)
    await _poll(hass, freezer)

    assert state_of(hass, "binary_sensor", "vitals_stale") == "on"
    for key in ("heart_rate", "oxygen_saturation", "skin_temperature", "sleep_state"):
        assert state_of(hass, "sensor", key) == STATE_UNAVAILABLE
    assert state_of(hass, "binary_sensor", "sleep_state") == STATE_UNAVAILABLE
    # Battery, alerts and the base station switch stay usable.
    assert state_of(hass, "sensor", "battery_percentage") == "50.0"
    assert state_of(hass, "binary_sensor", "low_oxygen_alert") == "off"
    assert state_of(hass, "switch", "base_station_on") == "on"


async def test_poll_failure_and_recovery(
    hass: HomeAssistant, cloud: FakeCloud, freezer
) -> None:
    """Entities go unavailable during an outage and recover afterwards."""
    cloud.get(URL_DEVICES, payload=devices_payload())
    cloud.post(url_datapoint("APP_ACTIVE"), status=201, payload={}, repeat=True)
    asleep = properties_payload("update_properties_asleep.json")
    cloud.get(url_properties(), payload=asleep)
    cloud.get(url_properties(), payload=asleep)
    cloud.get(url_properties(), status=502)
    cloud.get(url_properties(), payload=asleep, repeat=True)
    entry = await setup_entry(hass)
    assert state_of(hass, "sensor", "battery_percentage") == "50.0"

    await _poll(hass, freezer)
    assert state_of(hass, "sensor", "battery_percentage") == STATE_UNAVAILABLE
    assert entry.state is ConfigEntryState.LOADED

    await _poll(hass, freezer)
    assert state_of(hass, "sensor", "battery_percentage") == "50.0"


async def test_malformed_vitals_do_not_crash(
    hass: HomeAssistant, cloud: FakeCloud, freezer
) -> None:
    """Garbage in REAL_TIME_VITALS fails the poll instead of raising."""
    cloud.get(URL_DEVICES, payload=devices_payload())
    cloud.post(url_datapoint("APP_ACTIVE"), status=201, payload={}, repeat=True)
    asleep = properties_payload("update_properties_asleep.json")
    broken = [
        {"property": {**item["property"], "value": None}}
        if item["property"]["name"] == "REAL_TIME_VITALS"
        else item
        for item in asleep
    ]
    cloud.get(url_properties(), payload=asleep)
    cloud.get(url_properties(), payload=asleep)
    cloud.get(url_properties(), payload=broken, repeat=True)
    await setup_entry(hass)

    await _poll(hass, freezer)
    assert state_of(hass, "sensor", "heart_rate") == STATE_UNAVAILABLE


async def test_base_station_switch(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """The switch posts the base station command."""
    mock_sock(cloud, "update_properties_asleep.json")
    cloud.post(url_datapoint("BASE_STATION_ON_CMD"), status=201, payload={"ok": 1})
    await setup_entry(hass)
    switch = entity_id(hass, "switch", "base_station_on")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    assert requests_to(cloud, "POST", url_datapoint("BASE_STATION_ON_CMD")) == 1

    # The next command hits an unmocked URL, i.e. a connection failure.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": switch}, blocking=True
        )
