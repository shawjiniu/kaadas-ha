from __future__ import annotations

import logging

from aiohttp import ClientTimeout

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KaadasCoordinator, device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KaadasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            KaadasDoorbellCamera(coordinator, entry),
            KaadasAlarmCamera(coordinator, entry),
        ]
    )


class KaadasSnapshotCamera(CoordinatorEntity[KaadasCoordinator], Camera):
    """抓拍相机基类：显示最近一次记录（门铃 / 预警）的抓拍图。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KaadasCoordinator,
        entry: ConfigEntry,
        record_key: str,
        unique_id_suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.record_key = record_key
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._cache_url = ""
        self._cache_bytes: bytes | None = None

    @property
    def device_info(self) -> dict:
        return device_info(self.entry, self.coordinator.data or {})

    def _latest_thumb_url(self) -> str:
        data = self.coordinator.data or {}
        records = data.get(self.record_key) or []
        for record in records:
            url = str(record.get("thumbUrl") or "").strip()
            if url:
                return url
        return ""

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """返回最近一次抓拍图（带缓存，URL 变化时才重新拉取）。"""
        url = self._latest_thumb_url()
        if not url:
            return None
        if url == self._cache_url and self._cache_bytes is not None:
            return self._cache_bytes

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                self._cache_bytes = await resp.read()
                self._cache_url = url
        except Exception as err:  # noqa: BLE001 - 拉取失败回退到旧缓存
            _LOGGER.warning("获取抓拍图失败：%s", err)
        return self._cache_bytes


class KaadasDoorbellCamera(KaadasSnapshotCamera):
    """门铃抓拍相机。"""

    def __init__(self, coordinator: KaadasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "visit_records", "doorbell_camera", "门铃抓拍")


class KaadasAlarmCamera(KaadasSnapshotCamera):
    """预警抓拍相机。"""

    def __init__(self, coordinator: KaadasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alarm_records", "alarm_camera", "预警抓拍")
