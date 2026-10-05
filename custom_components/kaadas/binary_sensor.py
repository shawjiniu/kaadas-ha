from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    PROP_DEFENSE_MODE,
    PROP_DOUBLE_VERIFY_MODE,
    PROP_LOCKED_INSIDE_STATUS,
    PROP_SCREEN_ONOFF,
)
from .coordinator import KaadasCoordinator, device_info


@dataclass(frozen=True, kw_only=True)
class KaadasBinarySensorDescription(BinarySensorEntityDescription):
    key: str
    data_key: str


BINARY_SENSORS: tuple[KaadasBinarySensorDescription, ...] = (
    KaadasBinarySensorDescription(
        key="connectivity",
        data_key="connect_state",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:wifi",
    ),
    KaadasBinarySensorDescription(
        key="defense_mode",
        data_key=PROP_DEFENSE_MODE,
        translation_key="defense_mode",
        icon="mdi:shield-lock",
    ),
    KaadasBinarySensorDescription(
        key="locked_inside_status",
        data_key=PROP_LOCKED_INSIDE_STATUS,
        translation_key="locked_inside_status",
        icon="mdi:lock",
    ),
    KaadasBinarySensorDescription(
        key="double_verify_mode",
        data_key=PROP_DOUBLE_VERIFY_MODE,
        translation_key="double_verify_mode",
        icon="mdi:two-factor-authentication",
    ),
    KaadasBinarySensorDescription(
        key="screen_onoff",
        data_key=PROP_SCREEN_ONOFF,
        translation_key="screen_onoff",
        icon="mdi:monitor",
    ),
)


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"true", "1", "on", "yes", "开", "enabled"}:
        return True
    if text in {"false", "0", "off", "no", "关", "disabled"}:
        return False
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KaadasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        KaadasBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class KaadasBinarySensor(CoordinatorEntity[KaadasCoordinator], BinarySensorEntity):
    entity_description: KaadasBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KaadasCoordinator,
        entry: ConfigEntry,
        description: KaadasBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        key = self.entity_description.data_key
        if key == "connect_state":
            state = data.get(key)
            return state.lower() == "online" if isinstance(state, str) else None
        return _to_bool(data.get(key))

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> dict[str, Any]:
        return device_info(self.entry, self.coordinator.data or {})
