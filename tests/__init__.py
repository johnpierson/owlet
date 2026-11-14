"""Tests for the Owlet integration."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from aiohttp import ClientConnectionError
from homeassistant.const import (
    CONF_API_TOKEN,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pyowletapi.const import REGION_INFO
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet.const import (
    CONF_OWLET_EXPIRY,
    CONF_OWLET_REFRESH,
    DOMAIN,
    POLLING_INTERVAL,
)

FIXTURES = Path(__file__).parent / "fixtures"
SERIAL = "SERIAL_NUMBER"
EMAIL = "sample@gmail.com"
# The V3 fixtures carry vitals stamped 2023-05-24T14:15:50Z.
NOW = "2023-05-24T14:16:00+00:00"
LATER = "2023-05-24T14:30:00+00:00"

BASE = REGION_INFO["europe"]["url_base"]
URL_DEVICES = f"{BASE}/devices.json"
URL_VERIFY = re.compile(r"^https://www\.googleapis\.com/identitytoolkit/.*$")
URL_REFRESH = re.compile(r"^https://securetoken\.googleapis\.com/v1/token.*$")
URL_MINI = REGION_INFO["europe"]["url_mini"]
URL_SIGNIN = REGION_INFO["europe"]["url_signin"]


class FakeResponse:
    """The parts of an aiohttp response the Owlet client uses."""

    def __init__(self, status: int, payload: Any) -> None:
        """Initialise the response."""
        self.status = status
        self.text = json.dumps(payload)
        self._payload = payload

    async def json(self) -> Any:
        """Return the JSON body."""
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        """Enter the request context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Leave the request context."""


class _FailedRequest:
    """Request context that fails to connect."""

    async def __aenter__(self) -> FakeResponse:
        raise ClientConnectionError("Connection refused by the fake Owlet cloud")

    async def __aexit__(self, *args: object) -> None:
        """Leave the request context."""


class FakeCloud:
    """Stand-in for the aiohttp session, answering with registered responses.

    Responses registered for the same URL are served in order; one registered
    with ``repeat=True`` is served forever. Unregistered URLs fail to connect.
    """

    def __init__(self) -> None:
        """Initialise the fake cloud."""
        self._routes: list[tuple[str, Any, int, Any, bool]] = []
        self.requests: list[tuple[str, str, Any]] = []

    def _add(self, method: str, url: Any, status: int, payload: Any, repeat: bool):
        self._routes.append((method, url, status, payload, repeat))

    def get(
        self, url: Any, status: int = 200, payload: Any = None, repeat: bool = False
    ) -> None:
        """Register a GET response."""
        self._add("GET", url, status, payload, repeat)

    def post(
        self, url: Any, status: int = 200, payload: Any = None, repeat: bool = False
    ) -> None:
        """Register a POST response."""
        self._add("POST", url, status, payload, repeat)

    def request(self, method: str, url: str, **kwargs: Any):
        """Mimic ClientSession.request."""
        self.requests.append((method, url, kwargs.get("json") or kwargs.get("data")))
        for index, (r_method, r_url, status, payload, repeat) in enumerate(
            self._routes
        ):
            if r_method != method:
                continue
            if not (
                r_url.match(url) if isinstance(r_url, re.Pattern) else r_url == url
            ):
                continue
            if not repeat:
                del self._routes[index]
            return FakeResponse(status, payload)
        return _FailedRequest()


def url_properties(dsn: str = SERIAL) -> str:
    """Return the properties URL of a device."""
    return f"{BASE}/dsns/{dsn}/properties.json"


def url_datapoint(prop: str, dsn: str = SERIAL) -> str:
    """Return the datapoint URL of a device property."""
    return f"{BASE}/dsns/{dsn}/properties/{prop}/datapoints.json"


def load_json(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def devices_payload(*extra_dsns: str) -> list[dict[str, Any]]:
    """Return a /devices.json payload with the fixture sock plus extra devices."""
    devices = list(load_json("get_devices.json")["response"])
    for dsn in extra_dsns:
        devices.append({"device": {**devices[0]["device"], "dsn": dsn}})
    return devices


def properties_payload(fixture: str) -> list[dict[str, Any]]:
    """Return a properties.json payload in the shape the Owlet API uses."""
    return [{"property": prop} for prop in load_json(fixture)["response"].values()]


def mock_sock(
    cloud: FakeCloud,
    fixture: str = "update_properties_asleep.json",
    devices: list[dict[str, Any]] | None = None,
) -> None:
    """Register a working account with one sock."""
    cloud.get(URL_DEVICES, payload=devices or devices_payload(), repeat=True)
    cloud.post(url_datapoint("APP_ACTIVE"), status=201, payload={}, repeat=True)
    cloud.get(url_properties(), payload=properties_payload(fixture), repeat=True)


def mock_sign_in(cloud: FakeCloud, repeat: bool = False) -> None:
    """Register a working token refresh chain."""
    cloud.post(
        URL_REFRESH,
        payload={"refresh_token": "new_refresh_token", "id_token": "id_token"},
        repeat=repeat,
    )
    cloud.get(URL_MINI, payload={"mini_token": "mini_token"}, repeat=repeat)
    cloud.post(
        URL_SIGNIN,
        payload={"access_token": "new_api_token", "expires_in": 86400},
        repeat=repeat,
    )


def requests_to(cloud: FakeCloud, method: str, url: str) -> int:
    """Count the requests made to a URL."""
    return sum(
        1
        for called_method, called_url, _ in cloud.requests
        if called_method == method and called_url == url
    )


def create_entry(
    hass: HomeAssistant, *, expired: bool = False, version: int = 2
) -> MockConfigEntry:
    """Create the config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        title=EMAIL,
        unique_id=f"europe_{EMAIL}" if version == 2 else EMAIL,
        data={
            CONF_REGION: "europe",
            CONF_USERNAME: EMAIL,
            CONF_API_TOKEN: "api_token",
            CONF_OWLET_EXPIRY: time.time() + (-10 if expired else 3600),
            CONF_OWLET_REFRESH: "refresh_token",
        },
        options={CONF_SCAN_INTERVAL: POLLING_INTERVAL},
    )
    entry.add_to_hass(hass)
    return entry


async def setup_entry(hass: HomeAssistant, **kwargs: Any) -> MockConfigEntry:
    """Create and set up the config entry."""
    entry = create_entry(hass, **kwargs)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str | None:
    """Return the entity id for a sock property."""
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SERIAL}-{key}")


def state_of(hass: HomeAssistant, platform: str, key: str) -> str | None:
    """Return the state for a sock property."""
    eid = entity_id(hass, platform, key)
    assert eid is not None, f"{platform} {key} was not created"
    state = hass.states.get(eid)
    assert state is not None, f"{eid} has no state"
    return state.state
