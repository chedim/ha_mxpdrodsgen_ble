"""The Tuya BLE integration."""

from __future__ import annotations
from dataclasses import dataclass, field
import logging
from typing import Callable
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfRatio,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfFrequency,
    REVOLUTIONS_PER_MINUTE,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import (
    BATTERY_STATE_HIGH,
    BATTERY_STATE_LOW,
    BATTERY_STATE_NORMAL,
    BATTERY_CHARGED,
    BATTERY_CHARGING,
    BATTERY_NOT_CHARGING,
    CO2_LEVEL_ALARM,
    CO2_LEVEL_NORMAL,
    DOMAIN,
    PARKSIDE_MOWER_ERRORS,
    PARKSIDE_MOWER_STATUSES,
    PARKSIDE_MOWER_WARNINGS,
)
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)
SIGNAL_STRENGTH_DP_ID = -1
TuyaBLESensorIsAvailable = Callable[["TuyaBLESensor", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLESensorMapping:
    """Model a DP, description and default values"""

    dp_id: int
    description: SensorEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    getter: Callable[[TuyaBLESensor], None] | None = None
    coefficient: float = 1.0
    icons: list[str] | None = None
    is_available: TuyaBLESensorIsAvailable = None


@dataclass
class TuyaBLEBatteryMapping(TuyaBLESensorMapping):
    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="battery",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
        )
    )


@dataclass
class TuyaBLETemperatureMapping(TuyaBLESensorMapping):
    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        )
    )


def is_co2_alarm_enabled(self: TuyaBLESensor, product: TuyaBLEProductInfo) -> bool:
    """For a given sensor, read the datapoints and determine if co2 alarm is enabled"""
    result: bool = True
    datapoint = self._device.datapoints[13]
    if datapoint:
        result = bool(datapoint.value)
    return result


def battery_enum_getter(self: TuyaBLESensor) -> None:
    """For a given sensor, read the datapoints and determine battery info"""
    datapoint = self._device.datapoints[104]
    if datapoint:
        self._attr_native_value = datapoint.value * 20.0


def bstuokey_battery_getter(self: TuyaBLESensor) -> None:
    """Get battery percentage from string values for BSTUOKEY."""
    datapoint = self._device.datapoints[9]
    if datapoint and datapoint.value is not None:
        self._attr_native_value = {
            "high": 90,
            "medium": 60,
            "low": 30,
            "poweroff": 0,
        }.get(datapoint.value)


# The Parkside mower reports its logs, schedules and zones as raw datapoints.
# The layouts below follow the structures declared by the device model, with
# multi byte integers in network byte order.


def _parkside_entries(self: TuyaBLESensor, size: int) -> list[bytes]:
    """Split the mapped raw DP into its fixed size entries."""
    datapoint = self._device.datapoints[self._mapping.dp_id]
    value = datapoint.value if datapoint else None
    if not isinstance(value, (bytes, bytearray)):
        return []

    return [
        bytes(value[pos : pos + size]) for pos in range(0, len(value) - size + 1, size)
    ]


def _parkside_error_name(index: int) -> str:
    """Name an error by its index in the machine error bitmap."""
    if 0 <= index < len(PARKSIDE_MOWER_ERRORS):
        return PARKSIDE_MOWER_ERRORS[index]

    return str(index)


def _parkside_report(self: TuyaBLESensor, entries: list[dict], key: str) -> None:
    """Report the entry count and expose the entries as an attribute."""
    self._attr_native_value = len(entries)
    self._attr_extra_state_attributes = {key: entries}


def machine_error_log_getter(self: TuyaBLESensor) -> None:
    """Decode DP 111: 10 entries of a uint32 epoch and an error index."""
    entries = []
    for entry in _parkside_entries(self, 5):
        timestamp = int.from_bytes(entry[:4], "big")
        if timestamp == 0:
            continue
        entries.append(
            {
                "time": dt_util.utc_from_timestamp(timestamp).isoformat(),
                "error": _parkside_error_name(entry[4]),
            }
        )
    _parkside_report(self, entries, "errors")


def machine_work_log_getter(self: TuyaBLESensor) -> None:
    """Decode DP 112: 10 entries of a uint32 start, a duration and a mode."""
    modes = {1: "auto_mowing", 2: "spot_mowing"}
    entries = []
    for entry in _parkside_entries(self, 9):
        start = int.from_bytes(entry[:4], "big")
        if start == 0:
            continue
        entries.append(
            {
                "start": dt_util.utc_from_timestamp(start).isoformat(),
                "duration_seconds": int.from_bytes(entry[4:8], "big"),
                "mode": modes.get(entry[8], str(entry[8])),
            }
        )
    _parkside_report(self, entries, "sessions")


def machine_schedule_getter(self: TuyaBLESensor) -> None:
    """Decode DP 110: two slots of eight days, each a weekday and a period.

    Every field other than the weekday holds 0x88 when the slot is unused.
    """
    entries = []
    for entry in _parkside_entries(self, 5):
        weekday, start_hour, start_minute, end_hour, end_minute = entry
        if 0x88 in entry[1:]:
            continue
        entries.append(
            {
                "weekday": weekday,
                "start": f"{start_hour:02d}:{start_minute:02d}",
                "end": f"{end_hour:02d}:{end_minute:02d}",
            }
        )
    _parkside_report(self, entries, "slots")


def machine_zones_getter(self: TuyaBLESensor) -> None:
    """Decode DP 113: five zones of a uint32 passage length and a share."""
    entries = []
    for entry in _parkside_entries(self, 5):
        length = int.from_bytes(entry[:4], "big")
        if length == 0:
            continue
        entries.append(
            {
                "passage_length_m": length,
                "area_share_percent": entry[4],
            }
        )
    _parkside_report(self, entries, "zones")


@dataclass
class TuyaBLECategorySensorMapping:
    """Models a dict of products and their mappings"""

    products: dict[str, list[TuyaBLESensorMapping]] | None = None
    mapping: list[TuyaBLESensorMapping] | None = None


@dataclass
class TuyaBLEWorkStateMapping(TuyaBLESensorMapping):
    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="work_state",
            device_class=SensorDeviceClass.ENUM,
            options=[
                "auto",
                "manual",
                "idle",
            ],
        )
    )


@dataclass
class TuyaBLEAlarmLockStateMapping(TuyaBLESensorMapping):
    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="alarm_lock",
            device_class=SensorDeviceClass.ENUM,
            options=[
                "wrong_finger",
                "wrong_password",
                "wrong_card",
                "wrong_face",
                "tongue_bad",
                "too_hot",
                "unclosed_time",
                "tongue_not_out",
                "pry",
                "key_in",
                "low_battery",
                "power_off",
                "shock",
            ],
        )
    )


mapping: dict[str, TuyaBLECategorySensorMapping] = {
    "qt": TuyaBLECategorySensorMapping(
        products={
            "jlblyn8z": [  # MXR4000 GT generator
                TuyaBLESensorMapping(
                    dp_id=104,
                    description=SensorEntityDescription(
                        key="power",
                        device_class=SensorDeviceClass.POWER,
                        native_unit_of_measurement=UnitOfPower.WATT,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=102,
                    description=SensorEntityDescription(
                        key="fuel_level",
                        icon="mdi:fuel",
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=110,
                    description=SensorEntityDescription(
                        key="voltage",
                        device_class=SensorDeviceClass.VOLTAGE,
                        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=111,
                    description=SensorEntityDescription(
                        key="frequency",
                        device_class=SensorDeviceClass.FREQUENCY,
                        native_unit_of_measurement=UnitOfFrequency.HERTZ,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=112,
                    force_add=False,
                    description=SensorEntityDescription(
                        key="engine_speed",
                        icon="mdi:engine",
                        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=103,
                    description=SensorEntityDescription(
                        key="run_time",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=105,
                    description=SensorEntityDescription(
                        key="total_run_time",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        state_class=SensorStateClass.TOTAL_INCREASING,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLEBatteryMapping(dp_id=115, force_add=False),
                TuyaBLESensorMapping(
                    dp_id=106,
                    description=SensorEntityDescription(
                        key="online_state",
                        device_class=SensorDeviceClass.ENUM,
                        options=["offline", "online", "protected"],
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=107,
                    description=SensorEntityDescription(
                        key="fault",
                        icon="mdi:alert-circle-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=116,
                    force_add=False,
                    description=SensorEntityDescription(
                        key="charging_capacity",
                        icon="mdi:battery-charging",
                        state_class=SensorStateClass.MEASUREMENT,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=114,
                    description=SensorEntityDescription(
                        key="generator_sn",
                        icon="mdi:identifier",
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
            ],
        },
    ),
}


def rssi_getter(sensor: TuyaBLESensor) -> None:
    sensor._attr_native_value = sensor._device.rssi


rssi_mapping = TuyaBLESensorMapping(
    dp_id=SIGNAL_STRENGTH_DP_ID,
    description=SensorEntityDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    getter=rssi_getter,
)


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLESensorMapping]:
    category = mapping.get(device.category)
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            return product_mapping
        if category.mapping is not None:
            return category.mapping

    return []


class TuyaBLESensor(TuyaBLEEntity, SensorEntity):
    """Representation of a Tuya BLE sensor."""

    platform = Platform.SENSOR

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESensorMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._mapping.getter is not None:
            self._mapping.getter(self)
        else:
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if datapoint:
                if datapoint.type == TuyaBLEDataPointType.DT_ENUM:
                    if self.entity_description.options is not None:
                        if datapoint.value >= 0 and datapoint.value < len(
                            self.entity_description.options
                        ):
                            self._attr_native_value = self.entity_description.options[
                                datapoint.value
                            ]
                        else:
                            self._attr_native_value = datapoint.value
                    if self._mapping.icons is not None:
                        if datapoint.value >= 0 and datapoint.value < len(
                            self._mapping.icons
                        ):
                            self._attr_icon = self._mapping.icons[datapoint.value]
                elif datapoint.type == TuyaBLEDataPointType.DT_VALUE:
                    self._attr_native_value = (
                        datapoint.value / self._mapping.coefficient
                    )
                else:
                    self._attr_native_value = datapoint.value
        self.async_write_ha_state()

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
    entities: list[TuyaBLESensor] = [
        TuyaBLESensor(
            hass,
            data.coordinator,
            data.device,
            data.product,
            rssi_mapping,
        )
    ]
    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLESensor(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
