from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    LOCK_STATUS_ABNORMAL,
    LOCK_STATUS_LOCKED,
    LOCK_STATUS_UNLOCKED,
    PROP_LOCK_STATUS,
)
from .coordinator import KaadasCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KaadasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([KaadasLock(coordinator, entry)])


class KaadasLock(CoordinatorEntity[KaadasCoordinator], LockEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KaadasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lock"

    @property
    def is_locked(self) -> bool | None:
        """优先读物模型 p_lock_status，其次读设备列表 open_status。

        p_lock_status：1 开锁 / 2 关锁 / 3 异常
        open_status：1 关锁 / 2 开锁
        """
        data = self.coordinator.data or {}
        lock_status = data.get(PROP_LOCK_STATUS)
        if lock_status is not None:
            try:
                value = int(lock_status)
            except (TypeError, ValueError):
                value = -1
            if value == LOCK_STATUS_LOCKED:
                return True
            if value == LOCK_STATUS_UNLOCKED:
                return False
            if value == LOCK_STATUS_ABNORMAL:
                return None
        open_status = data.get("open_status")
        if open_status is not None:
            try:
                return int(open_status) == 1
            except (TypeError, ValueError):
                pass
        return None

    async def async_lock(self, **kwargs: Any) -> None:
        # TODO: 下发上锁指令（/iot/device/properties/set 或 /device/setLock）
        raise HomeAssistantError("凯迪仕门锁：远程上锁尚未实现")

    async def async_unlock(self, **kwargs: Any) -> None:
        # TODO: 远程开锁需要 p_open_lock_uid + p_open_lock_sign 签名，暂未实现
        raise HomeAssistantError("凯迪仕门锁：远程开锁尚未实现（需签名）")

    @property
    def device_info(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        device = data.get("device") or {}
        wifi_sn = str(device.get("wifiSN") or device.get("esn") or self.entry.entry_id)
        model = self.entry.data.get("device_model") or device.get("abbreviation") or "凯迪仕智能门锁"
        return {
            "identifiers": {(DOMAIN, wifi_sn)},
            "name": f"凯迪仕 {self.entry.data.get('nickname') or wifi_sn}",
            "manufacturer": "凯迪仕 Kaadas",
            "model": model,
        }
