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

from .const import DOMAIN, PROP_DEFENSE_MODE
from .coordinator import KaadasCoordinator, device_info


@dataclass(frozen=True, kw_only=True)
class KaadasBinarySensorDescription(BinarySensorEntityDescription):
    key: str


BINARY_SENSORS: tuple[KaadasBinarySensorDescription, ...] = (
    KaadasBinarySensorDescription(
        key="connectivity",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:wifi",
    ),
    KaadasBinarySensorDescription(
        key="defense_mode",
        translation_key="defense_mode",
        icon="mdi:shield-lock",
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
    if text in {"true", "1", "on", "yes", "开"}:
        return True
    if text in {"false", "0", "off", "no", "关"}:
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
        if self.entity_description.key == "connectivity":
            state = data.get("connect_state")
            if isinstance(state, str):
                return state.lower() == "online"
            return None
        if self.entity_description.key == "defense_mode":
            return _to_bool(data.get(PROP_DEFENSE_MODE))
        return None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> dict[str, Any]:
        return device_info(self.entry, self.coordinator.data or {})
