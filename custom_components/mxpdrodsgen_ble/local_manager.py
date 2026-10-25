"""Local (cloud-free) credentials manager for the generator.

The upstream Tuya BLE integration fetches a device's UUID / local key from the
Tuya IoT cloud. Here the credentials are captured once and stored in the config
entry's options, so this manager simply hands them back -- nothing ever calls
the cloud at runtime.
"""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_CATEGORY,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_MODEL,
    CONF_PRODUCT_NAME,
    CONF_PRODUCT_ID,
    CONF_SEC_KEY,
    CONF_UUID,
)
from homeassistant.const import CONF_DEVICE_ID

from .tuya_ble import AbstaractTuyaBLEDeviceManager, TuyaBLEDeviceCredentials


class LocalTuyaBLEDeviceManager(AbstaractTuyaBLEDeviceManager):
    """Serve device credentials straight from stored options."""

    def __init__(self, hass, data: dict[str, Any]) -> None:
        self._hass = hass
        self._data = data or {}

    async def get_device_credentials(
        self,
        address: str,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        d = self._data
        return self.check_and_create_device_credentials(
            d.get(CONF_UUID),
            d.get(CONF_LOCAL_KEY),
            d.get(CONF_DEVICE_ID),
            d.get(CONF_CATEGORY),
            d.get(CONF_PRODUCT_ID),
            d.get(CONF_DEVICE_NAME),
            d.get(CONF_PRODUCT_MODEL),
            d.get(CONF_PRODUCT_NAME),
            d.get("functions", []),
            d.get("status_range", []),
            d.get(CONF_SEC_KEY),
        )

    @property
    def data(self) -> dict[str, Any]:
        return self._data
