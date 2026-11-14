"""Test Owlet diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.owlet.diagnostics import async_get_config_entry_diagnostics

from . import EMAIL, FakeCloud, mock_sock, setup_entry


async def test_diagnostics_redact_account(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    """Diagnostics carry readings but no tokens or email."""
    mock_sock(cloud)
    entry = await setup_entry(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = str(diagnostics)

    assert "api_token" in diagnostics["entry"]["data"]
    assert "refresh_token" not in dumped
    assert EMAIL not in dumped
    assert diagnostics["socks"][0]["properties"]["heart_rate"] == 97.0
    assert diagnostics["socks"][0]["vitals_stale"] is False
