"""Diagnostics support for Owlet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_OWLET_EXPIRY, CONF_OWLET_REFRESH
from .coordinator import OwletConfigEntry

TO_REDACT = {CONF_API_TOKEN, CONF_OWLET_REFRESH, CONF_OWLET_EXPIRY, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OwletConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    socks = []
    for coordinator in entry.runtime_data.values():
        sock = coordinator.sock
        updated_at = coordinator.vitals_updated_at
        socks.append(
            {
                "model": sock.model,
                "oem_model": sock.oem_model,
                "sw_version": sock.sw_version,
                "version": sock.version,
                "revision": sock.revision,
                "connection_status": sock.connection_status,
                "last_update_success": coordinator.last_update_success,
                "vitals_updated_at": updated_at.isoformat() if updated_at else None,
                "vitals_stale": coordinator.vitals_stale,
                "properties": dict(sock.properties),
                "raw_property_names": sorted(sock.raw_properties),
            }
        )

    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "socks": socks,
    }
