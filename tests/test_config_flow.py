"""Test the Owlet config, reauth and options flows."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.owlet.const import CONF_OWLET_REFRESH, DOMAIN

from . import (
    EMAIL,
    URL_DEVICES,
    URL_VERIFY,
    FakeCloud,
    create_entry,
    mock_sign_in,
    mock_sock,
    setup_entry,
)

USER_INPUT = {"region": "europe", "username": EMAIL, "password": "sample"}


def _mock_password(cloud: FakeCloud) -> None:
    cloud.post(URL_VERIFY, payload={"refreshToken": "refresh_token"})


async def _submit(hass: HomeAssistant, user_input: dict[str, str]):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


async def test_user_flow(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """Signing in creates an entry that then loads from the stored tokens."""
    _mock_password(cloud)
    mock_sign_in(cloud)
    mock_sock(cloud)

    result = await _submit(hass, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"]["region"] == "europe"
    assert result["data"]["username"] == EMAIL
    assert result["data"][CONF_API_TOKEN] == "new_api_token"
    assert result["data"][CONF_OWLET_REFRESH] == "new_refresh_token"
    assert "password" not in result["data"]
    assert result["result"].unique_id == f"europe_{EMAIL}"
    assert result["result"].state is ConfigEntryState.LOADED


async def test_user_flow_invalid_credentials(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """Wrong credentials show an error and can be corrected."""
    cloud.post(
        URL_VERIFY,
        status=400,
        payload={"error": {"message": "INVALID_LOGIN_CREDENTIALS"}},
    )
    result = await _submit(hass, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_credentials"}

    _mock_password(cloud)
    mock_sign_in(cloud)
    mock_sock(cloud)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_too_many_attempts(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """A throttled sign-in is reported as such."""
    cloud.post(
        URL_VERIFY,
        status=400,
        payload={"error": {"message": "TOO_MANY_ATTEMPTS_TRY_LATER : blocked"}},
    )
    result = await _submit(hass, USER_INPUT)

    assert result["errors"] == {"base": "auth_failed"}


async def test_user_flow_cannot_connect(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """An unreachable cloud is reported as a connection problem."""
    _mock_password(cloud)
    mock_sign_in(cloud)
    cloud.get(URL_DEVICES, status=500)
    result = await _submit(hass, USER_INPUT)

    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_devices(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """An account without socks is reported."""
    _mock_password(cloud)
    mock_sign_in(cloud)
    cloud.get(URL_DEVICES, payload=[])
    result = await _submit(hass, USER_INPUT)

    assert result["errors"] == {"base": "no_devices"}


async def test_user_flow_duplicate(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """The same account in the same region cannot be added twice."""
    create_entry(hass)
    result = await _submit(hass, {**USER_INPUT, "username": EMAIL.upper()})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_same_email_other_region(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """The same email in the other region is a different account."""
    create_entry(hass)
    cloud.post(
        URL_VERIFY,
        status=400,
        payload={"error": {"message": "INVALID_LOGIN_CREDENTIALS"}},
    )
    result = await _submit(hass, {**USER_INPUT, "region": "world"})

    # Not aborted as a duplicate: the flow went on to try the sign-in.
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_credentials"}


async def test_reauth_flow(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """Reauth stores new tokens and reloads the entry."""
    entry = create_entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    cloud.post(
        URL_VERIFY,
        status=400,
        payload={"error": {"message": "INVALID_LOGIN_CREDENTIALS"}},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_credentials"}

    _mock_password(cloud)
    mock_sign_in(cloud)
    mock_sock(cloud)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "right"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_TOKEN] == "new_api_token"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_flow_applies_interval(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """Changing the polling interval takes effect without a restart."""
    mock_sock(cloud)
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 30}
    assert entry.state is ConfigEntryState.LOADED
    for coordinator in entry.runtime_data.values():
        assert coordinator.update_interval == timedelta(seconds=30)
