"""Hardened Owlet cloud client.

``pyowletapi`` is no longer maintained. This subclass keeps using it for the
sign-in flow and property decoding, and replaces the parts that misbehave:

* every request was preceded by an extra ``GET /devices.json`` "is my token
  still valid" probe, doubling the load on the Owlet cloud;
* requests had no timeout, so one hung connection stalled polling;
* one device that cannot be probed (for example an Owlet Cam) made the whole
  account fail to set up;
* temporary server errors during a token refresh were reported as bad
  credentials, forcing a needless re-authentication.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout
from pyowletapi.api import OwletAPI
from pyowletapi.exceptions import (
    OwletAuthenticationError,
    OwletConnectionError,
    OwletDevicesError,
)

from .const import REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# pyowletapi raises OwletAuthenticationError for these server-side failures even
# though the stored credentials are fine.
_TRANSIENT_AUTH_ERRORS = (
    "Generic ayla mini error",
    "Generic ayla endpoint error",
    "Ayla 404 error",
)


class OwletClient(OwletAPI):
    """OwletAPI with timeouts, lazy token validation and tolerant discovery."""

    async def refresh_authentication(self):
        """Refresh the API token, separating outages from rejected credentials."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT * 2):
                return await super().refresh_authentication()
        except OwletAuthenticationError as err:
            if str(err).startswith(_TRANSIENT_AUTH_ERRORS):
                raise OwletConnectionError(
                    f"Owlet sign-in service unavailable: {err}"
                ) from err
            raise
        except (ClientError, TimeoutError, KeyError, ValueError) as err:
            raise OwletConnectionError(
                f"Owlet sign-in service unavailable: {type(err).__name__}"
            ) from err

    async def validate_authentication(self):
        """Refresh the token only when it is missing or expired."""
        return await self.authenticate()

    async def _request(
        self, method: str, url: str, data: dict[str, Any] | None = None
    ) -> Any:
        """Call the Owlet API, re-authenticating once if the token is rejected."""
        for attempt in (1, 2):
            await self.authenticate()
            try:
                async with self.session.request(
                    method,
                    self._api_url + url,
                    headers=self.headers,
                    json=data,
                    timeout=ClientTimeout(total=REQUEST_TIMEOUT),
                ) as response:
                    if response.status == 401 and attempt == 1:
                        # Token revoked or expired early: force a refresh.
                        self._auth_token = None
                        continue
                    if response.status == 401:
                        raise OwletAuthenticationError(
                            "Owlet rejected a freshly issued API token"
                        )
                    if response.status not in (200, 201):
                        raise OwletConnectionError(
                            f"Owlet API returned HTTP {response.status} "
                            f"for {method} {url}"
                        )
                    return await response.json()
            except (ClientError, TimeoutError, ValueError) as err:
                raise OwletConnectionError(
                    f"Error talking to the Owlet API: {type(err).__name__}"
                ) from err
        raise OwletConnectionError("Error talking to the Owlet API")

    async def get_properties(self, device: str) -> dict[str, Any]:
        """Return the raw properties of a device.

        The base station only streams vitals while ``APP_ACTIVE`` is set, so it
        is set on every poll, but a failure to set it must not prevent reading
        the properties that are available.
        """
        try:
            await self.activate(device)
        except OwletConnectionError as err:
            _LOGGER.debug("Could not set APP_ACTIVE: %s", err)

        api_response = await self._request("GET", f"/dsns/{device}/properties.json")
        if not isinstance(api_response, list):
            raise OwletConnectionError("Unexpected properties response from Owlet")

        return {
            "response": {
                item["property"]["name"]: item["property"]
                for item in api_response
                if isinstance(item, dict) and "name" in item.get("property", {})
            }
        }

    async def get_devices(self, versions: list[int] | None = None) -> dict[str, Any]:
        """Return the supported socks on the account.

        Each device is probed separately; devices that are not socks, or that
        cannot be read, are skipped instead of failing the whole account.
        """
        versions = versions or [3, 2]
        api_response = await self._request("GET", "/devices.json")
        if not isinstance(api_response, list):
            raise OwletConnectionError("Unexpected devices response from Owlet")

        candidates = [
            item
            for item in api_response
            if isinstance(item, dict) and item.get("device", {}).get("dsn")
        ]
        results = await asyncio.gather(
            *(self._sock_version(item["device"]["dsn"]) for item in candidates),
            return_exceptions=True,
        )

        socks = []
        probe_failed = False
        for item, result in zip(candidates, results, strict=True):
            if isinstance(result, OwletAuthenticationError):
                raise result
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                probe_failed = True
                _LOGGER.debug(
                    "Skipping an Owlet device that could not be read: %s", result
                )
                continue
            if result in versions:
                socks.append(item)

        if not socks:
            if probe_failed:
                raise OwletConnectionError("Could not read any Owlet device")
            raise OwletDevicesError("No supported Owlet socks found")

        return {"response": socks}

    async def _sock_version(self, dsn: str) -> int:
        """Return the Smart Sock generation of a device, 0 if it is not a sock."""
        properties = (await self.get_properties(dsn))["response"]
        if "REAL_TIME_VITALS" in properties:
            return 3
        if "CHARGE_STATUS" in properties:
            return 2
        return 0
