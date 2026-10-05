from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    PROP_BATTERY_LEVEL,
    PROP_FIRMWARE_VERSION,
    PROP_MODEL_VERSION,
    PROP_WIFI_RSSI,
)
from .coordinator import KaadasCoordinator, device_info


@dataclass(frozen=True, kw_only=True)
class KaadasSensorDescription(SensorEntityDescription):
    key: str
    data_key: str


SENSORS: tuple[KaadasSensorDescription, ...] = (
    KaadasSensorDescription(
        key="battery",
        data_key=PROP_BATTERY_LEVEL,
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    KaadasSensorDescription(
        key="wifi_rssi",
        data_key=PROP_WIFI_RSSI,
        translation_key="wifi_rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wifi",
    ),
    KaadasSensorDescription(
        key="firmware_version",
        data_key=PROP_FIRMWARE_VERSION,
        translation_key="firmware_version",
        icon="mdi:chip",
    ),
    KaadasSensorDescription(
        key="model_version",
        data_key=PROP_MODEL_VERSION,
        translation_key="model_version",
        icon="mdi:information-outline",
    ),
    KaadasSensorDescription(
        key="last_update_time",
        data_key="last_update_time",
        translation_key="last_update_time",
        icon="mdi:update",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KaadasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        KaadasSensor(coordinator, entry, description) for description in SENSORS
    )


class KaadasSensor(CoordinatorEntity[KaadasCoordinator], SensorEntity):
    entity_description: KaadasSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KaadasCoordinator,
        entry: ConfigEntry,
        description: KaadasSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        value = data.get(self.entity_description.data_key)
        if value in (None, ""):
            return None
        return value

    @property
    def device_info(self) -> dict[str, Any]:
        return device_info(self.entry, self.coordinator.data or {})
