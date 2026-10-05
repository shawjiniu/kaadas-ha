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
    PROP_AUTO_CLOSE_LOCK_TIME,
    PROP_BATTERY_LEVEL,
    PROP_DOOR_DIRECTION,
    PROP_FIRMWARE_VERSION,
    PROP_LANGUAGE,
    PROP_LINGER_DETECTION,
    PROP_LOCK_BODY_TYPE,
    PROP_LOCK_FORCE,
    PROP_LOCK_STATUS,
    PROP_LOCK_VOLUME,
    PROP_MODEL_VERSION,
    PROP_SCREEN_ACTIVE_TIME,
    PROP_SCREEN_BACKLIGHT,
    PROP_WIFI_RSSI,
)
from .coordinator import KaadasCoordinator, device_info

DOOR_DIRECTION_MAP = {"1": "右开", "2": "左开"}
LOCK_FORCE_MAP = {"1": "更高", "2": "高", "3": "低"}
LANGUAGE_MAP = {"1": "中文", "2": "英文", "zh": "中文", "en": "英文"}
LOCK_STATUS_MAP = {"1": "开锁", "2": "关锁", "3": "异常"}


@dataclass(frozen=True, kw_only=True)
class KaadasSensorDescription(SensorEntityDescription):
    key: str
    data_key: str
    value_map: dict[str, str] | None = None


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
        key="lock_body_type",
        data_key=PROP_LOCK_BODY_TYPE,
        translation_key="lock_body_type",
        icon="mdi:door-closed-lock",
    ),
    KaadasSensorDescription(
        key="door_direction",
        data_key=PROP_DOOR_DIRECTION,
        translation_key="door_direction",
        value_map=DOOR_DIRECTION_MAP,
        icon="mdi:arrow-left-right",
    ),
    KaadasSensorDescription(
        key="lock_force",
        data_key=PROP_LOCK_FORCE,
        translation_key="lock_force",
        value_map=LOCK_FORCE_MAP,
        icon="mdi:gauge",
    ),
    KaadasSensorDescription(
        key="auto_close_lock_time",
        data_key=PROP_AUTO_CLOSE_LOCK_TIME,
        translation_key="auto_close_lock_time",
        native_unit_of_measurement="s",
        icon="mdi:timer-lock",
    ),
    KaadasSensorDescription(
        key="linger_detection",
        data_key=PROP_LINGER_DETECTION,
        translation_key="linger_detection",
        native_unit_of_measurement="s",
        icon="mdi:motion-sensor",
    ),
    KaadasSensorDescription(
        key="lock_volume",
        data_key=PROP_LOCK_VOLUME,
        translation_key="lock_volume",
        icon="mdi:volume-high",
    ),
    KaadasSensorDescription(
        key="language",
        data_key=PROP_LANGUAGE,
        translation_key="language",
        value_map=LANGUAGE_MAP,
        icon="mdi:translate",
    ),
    KaadasSensorDescription(
        key="screen_backlight",
        data_key=PROP_SCREEN_BACKLIGHT,
        translation_key="screen_backlight",
        icon="mdi:brightness-6",
    ),
    KaadasSensorDescription(
        key="screen_active_time",
        data_key=PROP_SCREEN_ACTIVE_TIME,
        translation_key="screen_active_time",
        native_unit_of_measurement="s",
        icon="mdi:clock-outline",
    ),
    KaadasSensorDescription(
        key="lock_status",
        data_key=PROP_LOCK_STATUS,
        translation_key="lock_status",
        value_map=LOCK_STATUS_MAP,
        icon="mdi:lock",
    ),
    KaadasSensorDescription(
        key="last_operation_time",
        data_key="last_operation_time",
        translation_key="last_operation_time",
        icon="mdi:history",
    ),
    KaadasSensorDescription(
        key="seven_day_operation_count",
        data_key="seven_day_operation_count",
        translation_key="seven_day_operation_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:door-open",
    ),
    KaadasSensorDescription(
        key="seven_day_doorbell_count",
        data_key="seven_day_doorbell_count",
        translation_key="seven_day_doorbell_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:bell-ring",
    ),
    KaadasSensorDescription(
        key="seven_day_alarm_count",
        data_key="seven_day_alarm_count",
        translation_key="seven_day_alarm_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert",
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
        if self.entity_description.value_map:
            return self.entity_description.value_map.get(str(value), value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "last_operation_time":
            return None
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {}
        records = data.get("operation_records")
        if records:
            attrs["操作记录"] = records[:20]
        stats = data.get("seven_day_stats")
        if stats:
            attrs["近7天统计"] = stats
        return attrs or None

    @property
    def device_info(self) -> dict[str, Any]:
        return device_info(self.entry, self.coordinator.data or {})
