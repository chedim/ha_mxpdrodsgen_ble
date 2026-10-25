"""Local, cloud-free config flow for the MaxPeedingRods generator (BLE).

The device's UUID and local key are captured once (see the README) and entered
here by hand. They are stored in the config entry's options and served by
LocalTuyaBLEDeviceManager; nothing in this integration ever contacts the Tuya
cloud at runtime.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_CATEGORY,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_MODEL,
    CONF_PRODUCT_NAME,
    CONF_SEC_KEY,
    CONF_UUID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# This build targets exactly one product; these are not secret.
GEN_CATEGORY = "qt"
GEN_PRODUCT_ID = "jlblyn8z"
GEN_PRODUCT_NAME = "MXR4000 GT"
GEN_PRODUCT_MODEL = "MXR4000GT-BL"


class MxrGenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the MaxPeedingRods generator."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered over Bluetooth."""
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._discovered_address = discovery_info.address
        self._discovered_name = discovery_info.name or GEN_PRODUCT_NAME
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_credentials()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered BLE device, or type an address."""
        if user_input is not None:
            self._discovered_address = user_input[CONF_ADDRESS]
            return await self.async_step_credentials()

        current = self._async_current_ids()
        addresses: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, False):
            if format_mac(info.address) in current:
                continue
            addresses[info.address] = f"{info.name or 'BLE device'} ({info.address})"

        if not addresses:
            # Nothing discovered right now -- let them type the MAC in.
            schema = vol.Schema({vol.Required(CONF_ADDRESS): str})
        else:
            schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(addresses)})
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the local key / device id / uuid for the generator."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = self._discovered_address
            await self.async_set_unique_id(
                format_mac(address), raise_on_progress=False
            )
            self._abort_if_unique_id_configured()

            options = {
                CONF_UUID: user_input[CONF_UUID].strip(),
                CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY].strip(),
                CONF_DEVICE_ID: user_input[CONF_DEVICE_ID].strip(),
                CONF_CATEGORY: GEN_CATEGORY,
                CONF_PRODUCT_ID: GEN_PRODUCT_ID,
                CONF_DEVICE_NAME: user_input.get(CONF_DEVICE_NAME) or GEN_PRODUCT_NAME,
                CONF_PRODUCT_MODEL: GEN_PRODUCT_MODEL,
                CONF_PRODUCT_NAME: GEN_PRODUCT_NAME,
                "functions": [],
                "status_range": [],
            }
            sec_key = (user_input.get(CONF_SEC_KEY) or "").strip()
            if sec_key:
                options[CONF_SEC_KEY] = sec_key

            return self.async_create_entry(
                title=options[CONF_DEVICE_NAME],
                data={CONF_ADDRESS: address},
                options=options,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): str,
                vol.Required(CONF_LOCAL_KEY): str,
                vol.Required(CONF_UUID): str,
                vol.Optional(CONF_DEVICE_NAME, default=GEN_PRODUCT_NAME): str,
                vol.Optional(CONF_SEC_KEY): str,
            }
        )
        return self.async_show_form(
            step_id="credentials",
            data_schema=schema,
            errors=errors,
            description_placeholders={"address": self._discovered_address or ""},
        )
