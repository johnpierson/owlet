"""Config flow for Owlet Smart Sock integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyowletapi.exceptions import (
    OwletAuthenticationError,
    OwletCredentialsError,
    OwletDevicesError,
    OwletError,
)

from .api import OwletClient
from .const import (
    DOMAIN,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    POLLING_INTERVAL,
    SETUP_TIMEOUT,
    SUPPORTED_VERSIONS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REGION): vol.In(["europe", "world"]),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class OwletConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Owlet Smart Sock."""

    VERSION = 2

    async def _async_sign_in(
        self, region: str, username: str, password: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Sign in and check a sock exists, return (tokens, errors)."""
        errors: dict[str, str] = {}
        client = OwletClient(
            region=region,
            user=username,
            password=password,
            session=async_get_clientsession(self.hass),
        )
        try:
            async with asyncio.timeout(SETUP_TIMEOUT):
                await client.authenticate()
                await client.get_devices(SUPPORTED_VERSIONS)
        except OwletDevicesError:
            errors["base"] = "no_devices"
        except OwletCredentialsError:
            errors["base"] = "invalid_credentials"
        except OwletAuthenticationError as err:
            _LOGGER.warning("Owlet sign-in was rejected: %s", err)
            errors["base"] = "auth_failed"
        except (OwletError, ClientError, TimeoutError) as err:
            _LOGGER.warning("Could not reach Owlet: %s", err)
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        return dict(client.tokens), errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(
                f"{user_input[CONF_REGION]}_{username.lower()}"
            )
            self._abort_if_unique_id_configured()

            tokens, errors = await self._async_sign_in(
                user_input[CONF_REGION], username, user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_REGION: user_input[CONF_REGION],
                        CONF_USERNAME: username,
                        **tokens,
                    },
                    options={CONF_SCAN_INTERVAL: POLLING_INTERVAL},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {
                    key: value
                    for key, value in (user_input or {}).items()
                    if key != CONF_PASSWORD
                },
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            tokens, errors = await self._async_sign_in(
                reauth_entry.data[CONF_REGION],
                reauth_entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            # A missing sock is not a reason to refuse working credentials.
            if not errors or errors == {"base": "no_devices"}:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=tokens
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )


class OptionsFlowHandler(OptionsFlow):
    """Handle a options flow for owlet."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, POLLING_INTERVAL
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_POLLING_INTERVAL, max=MAX_POLLING_INTERVAL),
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
