"""Test Owlet setup, authentication and device discovery."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.owlet.const import CONF_OWLET_REFRESH, DOMAIN

from . import (
    EMAIL,
    SERIAL,
    URL_DEVICES,
    URL_MINI,
    URL_REFRESH,
    URL_SIGNIN,
    FakeCloud,
    create_entry,
    devices_payload,
    mock_sign_in,
    mock_sock,
    properties_payload,
    requests_to,
    setup_entry,
    url_datapoint,
    url_properties,
)


def _reauth_started(hass: HomeAssistant) -> bool:
    return any(
        flow["context"]["source"] == SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    )


async def test_setup_and_unload(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """A valid token sets up the sock without any sign-in request."""
    mock_sock(cloud)
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, SERIAL)}
    assert device.manufacturer == "Owlet Baby Care"
    assert device.model == "AY001MTL1"
    # The fixture MAC is not a MAC address, so it must not be registered.
    assert device.connections == set()

    entities = er.async_entries_for_device(
        er.async_get(hass), device.id, include_disabled_entities=True
    )
    # 9 binary + awake + stale, 8 sensors + sleep + average + last update, switch
    assert len(entities) == 23

    # Discovery reads the sock once, the first refresh reads it again, and
    # neither is preceded by a token validation probe.
    assert requests_to(cloud, "GET", URL_DEVICES) == 1
    assert requests_to(cloud, "GET", url_properties()) == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_migrate_v1_unique_id(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """Version 1 entries get the region added to their unique id."""
    mock_sock(cloud)
    entry = await setup_entry(hass, version=1)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.unique_id == f"europe_{EMAIL}"


async def test_expired_token_is_refreshed_and_stored(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """An expired token is refreshed once and the new tokens are persisted."""
    mock_sign_in(cloud)
    mock_sock(cloud)
    entry = await setup_entry(hass, expired=True)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_API_TOKEN] == "new_api_token"
    assert entry.data[CONF_OWLET_REFRESH] == "new_refresh_token"
    assert requests_to(cloud, "POST", URL_SIGNIN) == 1


async def test_rejected_refresh_token_starts_reauth(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """A refresh token Owlet no longer accepts asks the user to sign in."""
    cloud.post(URL_REFRESH, status=400, payload={"error": {"message": "INVALID"}})
    entry = await setup_entry(hass, expired=True)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert _reauth_started(hass)


async def test_sign_in_outage_is_retried_not_reauth(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """A server error while refreshing must not demand the password again."""
    cloud.post(
        URL_REFRESH,
        payload={"refresh_token": "new_refresh_token", "id_token": "id_token"},
    )
    cloud.get(URL_MINI, status=503, payload={})
    entry = await setup_entry(hass, expired=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not _reauth_started(hass)


async def test_cloud_error_is_retried(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """An Owlet outage leaves the entry retrying."""
    cloud.get(URL_DEVICES, status=500, repeat=True)
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_revoked_token_is_refreshed_and_request_retried(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """A 401 on a token that looked valid triggers one refresh and a retry."""
    cloud.get(URL_DEVICES, status=401)
    mock_sign_in(cloud)
    mock_sock(cloud)
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_API_TOKEN] == "new_api_token"
    assert requests_to(cloud, "GET", URL_DEVICES) == 2


async def test_unreadable_device_does_not_break_the_sock(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """A camera or other device that cannot be probed is skipped."""
    cloud.post(url_datapoint("APP_ACTIVE", "CAMERA"), status=404, repeat=True)
    cloud.get(url_properties("CAMERA"), status=404, repeat=True)
    mock_sock(cloud, devices=devices_payload("CAMERA"))
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert list(entry.runtime_data) == [SERIAL]


async def test_non_sock_device_only(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """An account without a supported sock fails with a clear error."""
    cloud.get(URL_DEVICES, payload=devices_payload(), repeat=True)
    cloud.post(url_datapoint("APP_ACTIVE"), status=201, payload={}, repeat=True)
    cloud.get(
        url_properties(),
        payload=[{"property": {"name": "SOMETHING_ELSE", "value": 1}}],
        repeat=True,
    )
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not _reauth_started(hass)


async def test_activation_failure_still_reads_properties(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """Failing to set APP_ACTIVE does not hide readings that are available."""
    cloud.get(URL_DEVICES, payload=devices_payload(), repeat=True)
    cloud.post(url_datapoint("APP_ACTIVE"), status=500, repeat=True)
    cloud.get(
        url_properties(),
        payload=properties_payload("update_properties_asleep.json"),
        repeat=True,
    )
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED


async def test_no_stored_token_starts_reauth(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """An entry without usable tokens asks the user to sign in."""
    entry = create_entry(hass)
    hass.config_entries.async_update_entry(
        entry, data={"region": "europe", "username": EMAIL}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert _reauth_started(hass)
