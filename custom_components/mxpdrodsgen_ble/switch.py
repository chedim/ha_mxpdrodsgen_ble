"""The Tuya BLE integration."""

from __future__ import annotations

from dataclasses import dataclass, field

import logging
from typing import Any, Callable

from homeassistant.components.switch import (
    SwitchEntityDescription,
    SwitchEntity,
    SwitchDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


TuyaBLESwitchGetter = (
    Callable[["TuyaBLESwitch", TuyaBLEProductInfo], bool | None] | None
)


TuyaBLESwitchIsAvailable = Callable[["TuyaBLESwitch", TuyaBLEProductInfo], bool] | None


TuyaBLESwitchSetter = Callable[["TuyaBLESwitch", TuyaBLEProductInfo, bool], None] | None


@dataclass
class TuyaBLESwitchMapping:
    """Model a DP, description and default values"""

    dp_id: int
    description: SwitchEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    bitmap_mask: bytes | None = None
    is_available: TuyaBLESwitchIsAvailable = None
    getter: TuyaBLESwitchGetter = None
    setter: TuyaBLESwitchSetter = None


def is_fingerbot_in_program_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 2
    return result


def is_fingerbot_in_switch_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 1
    return result


def is_water_valve_in_switch_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    result: bool = False
    if product.watervalve:
        result = True
    return result


def get_fingerbot_program_repeat_forever(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool | None:
    result: bool | None = None
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and isinstance(datapoint.value, bytes):
            repeat_count = int.from_bytes(datapoint.value[0:2], "big")
            result = repeat_count == 0xFFFF
    return result


def set_fingerbot_program_repeat_forever(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo, value: bool
) -> None:
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and isinstance(datapoint.value, bytes):
            new_value = (
                int.to_bytes(0xFFFF if value else 1, 2, "big") + datapoint.value[2:]
            )
            self._hass.create_task(datapoint.set_value(new_value))


def get_inverted_switch(self: TuyaBLESwitch, product: TuyaBLEProductInfo) -> bool:
    """Represent CBF02V2's reported false (pressed) state as on."""
    datapoint = self._device.datapoints[self._mapping.dp_id]
    return not bool(datapoint.value) if datapoint else False


def set_inverted_switch(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo, value: bool
) -> None:
    """Write the CBF02V2 actuator state with inverted polarity."""
    datapoint = self._device.datapoints.get_or_create(
        self._mapping.dp_id,
        TuyaBLEDataPointType.DT_BOOL,
        not value,
    )
    if datapoint:
        self._hass.create_task(datapoint.set_value(not value))


def set_16wgjvck_water_valve(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo, value: bool
) -> None:
    if value:
        # Read the set timer beforehand (DP 15 = use_time or DP 11 = countdown).
        dp_11_val = 60
        dp15 = self._device.datapoints[15]
        dp11 = self._device.datapoints[11]
        if dp15 and dp15.value:
            dp_11_val = int(dp15.value)
        elif dp11 and dp11.value:
            dp_11_val = int(dp11.value)
        if dp_11_val <= 0:
            dp_11_val = 60
        # Read the set valve opening (DP 2)
        dp_2_val = 100
        dp2 = self._device.datapoints[2]
        if dp2 and dp2.value is not None:
            dp_2_val = int(dp2.value)
        if dp_2_val <= 0:
            dp_2_val = 100

        # Create the data points in the cache IF they haven't already been sent by the device,
        # so that "set_multiple_values" doesn't simply ignore them.
        self._device.datapoints.get_or_create(1, TuyaBLEDataPointType.DT_BOOL, True)
        self._device.datapoints.get_or_create(
            2, TuyaBLEDataPointType.DT_VALUE, dp_2_val
        )
        self._device.datapoints.get_or_create(
            11, TuyaBLEDataPointType.DT_VALUE, dp_11_val
        )

        # Atomic Multi-Datapoint Payload for turning on
        dp_updates = {
            1: True,
            2: dp_2_val,
            11: dp_11_val,
        }
        self._hass.create_task(self._device.set_multiple_values(dp_updates))
    else:
        # Just turn off the switch
        self._device.datapoints.get_or_create(1, TuyaBLEDataPointType.DT_BOOL, False)
        self._hass.create_task(self._device.set_multiple_values({1: False}))


@dataclass
class TuyaBLEFingerbotSwitchMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="switch",
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_fingerbot_in_switch_mode


@dataclass
class TuyaBLEWaterValveSwitchMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="water_valve",
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_water_valve_in_switch_mode


@dataclass
class TuyaLockMotorStateMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="lock_motor_state",
        )
    )


@dataclass
class TuyaBLEWaterValveWeatherSwitchMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="weather_switch",
            icon="mdi:cloud-question",
        )
    )


@dataclass
class TuyaBLEReversePositionsMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="reverse_positions",
            icon="mdi:arrow-up-down-bold",
            entity_category=EntityCategory.CONFIG,
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_fingerbot_in_switch_mode


def _parkside_rain_delay(self: TuyaBLESwitch) -> bytes | None:
    """Return the rain delay payload once the mower has reported it."""
    datapoint = self._device.datapoints[self._mapping.dp_id]
    value = datapoint.value if datapoint else None
    if isinstance(value, (bytes, bytearray)) and len(value) >= 2:
        return bytes(value)

    return None


def is_parkside_rain_delay_read(
    self: TuyaBLESwitch,
    product: TuyaBLEProductInfo,
) -> bool:
    """Report available once the payload is known.

    The switch and the delay share one payload, so neither may be written
    before the mower has reported the byte the other one owns.
    """
    return _parkside_rain_delay(self) is not None


def get_parkside_rain_delay(
    self: TuyaBLESwitch,
    product: TuyaBLEProductInfo,
) -> bool | None:
    """Read the switch from the first byte of the rain delay DP."""
    payload = _parkside_rain_delay(self)

    return bool(payload[0]) if payload else None


def set_parkside_rain_delay(
    self: TuyaBLESwitch,
    product: TuyaBLEProductInfo,
    value: bool,
) -> None:
    """Write the switch, keeping the delay held in the second byte."""
    payload = _parkside_rain_delay(self)
    if payload is None:
        return

    datapoint = self._device.datapoints.get_or_create(
        self._mapping.dp_id,
        TuyaBLEDataPointType.DT_RAW,
        b"",
    )
    self._hass.create_task(datapoint.set_value(bytes([int(value), payload[1]])))


@dataclass
class TuyaBLECategorySwitchMapping:
    """Models a dict of products and their mappings"""

    products: dict[str, list[TuyaBLESwitchMapping]] | None = None
    mapping: list[TuyaBLESwitchMapping] | None = None


mapping: dict[str, TuyaBLECategorySwitchMapping] = {
    "qt": TuyaBLECategorySwitchMapping(
        products={
            "jlblyn8z": [  # MXR4000 GT generator
                TuyaBLESwitchMapping(
                    dp_id=101,
                    description=SwitchEntityDescription(
                        key="generator",
                        icon="mdi:engine",
                    ),
                ),
                TuyaBLESwitchMapping(
                    dp_id=108,
                    description=SwitchEntityDescription(
                        key="eco_mode",
                        icon="mdi:leaf",
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLECategorySwitchMapping]:
    """Lookup mapping for a given device"""
    category = mapping.get(device.category)
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            return product_mapping
        if category.mapping is not None:
            return category.mapping

    return []


class TuyaBLESwitch(TuyaBLEEntity, SwitchEntity):
    """Representation of a Tuya BLE Switch."""

    platform = Platform.SWITCH

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESwitchMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""

        if self._mapping.getter:
            return self._mapping.getter(self, self._product)

        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            if (
                datapoint.type
                in [TuyaBLEDataPointType.DT_RAW, TuyaBLEDataPointType.DT_BITMAP]
                and self._mapping.bitmap_mask
            ):
                bitmap_value = bytes(datapoint.value)
                bitmap_mask = self._mapping.bitmap_mask
                for v, m in zip(bitmap_value, bitmap_mask, strict=True):
                    if (v & m) != 0:
                        return True
            else:
                return bool(datapoint.value)
        return False

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self._mapping.setter:
            return self._mapping.setter(self, self._product, True)

        new_value: bool | bytes
        if self._mapping.bitmap_mask:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BITMAP,
                self._mapping.bitmap_mask,
            )
            bitmap_mask = self._mapping.bitmap_mask
            bitmap_value = bytes(datapoint.value)
            new_value = bytes(
                v | m for (v, m) in zip(bitmap_value, bitmap_mask, strict=True)
            )
        else:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                True,
            )
            new_value = True
        if datapoint:
            self._hass.create_task(datapoint.set_value(new_value))

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self._mapping.setter:
            return self._mapping.setter(self, self._product, False)

        new_value: bool | bytes
        if self._mapping.bitmap_mask:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BITMAP,
                self._mapping.bitmap_mask,
            )
            bitmap_mask = self._mapping.bitmap_mask
            bitmap_value = bytes(datapoint.value)
            new_value = bytes(
                v & ~m for (v, m) in zip(bitmap_value, bitmap_mask, strict=True)
            )
        else:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                False,
            )
            new_value = False
        if datapoint:
            self._hass.create_task(datapoint.set_value(new_value))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLESwitch] = []
    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLESwitch(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
