from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KaadasApiError, KaadasAuthError
from .const import (
    CONF_DEVICE_MODEL,
    CONF_ESN,
    CONF_IS_THING_MODEL,
    CONF_NICKNAME,
    CONF_WIFI_SN,
    DOMAIN,
    PROP_ALARM_TYPE,
    PROP_AUTO_CLOSE_LOCK_TIME,
    PROP_BATTERY_LEVEL,
    PROP_CLOSE_LOCK_MODE,
    PROP_DEFENSE_MODE,
    PROP_DOOR_DIRECTION,
    PROP_DOOR_LOCK_ACTION_TYPE,
    PROP_DOUBLE_VERIFY_MODE,
    PROP_FIRMWARE_VERSION,
    PROP_LANGUAGE,
    PROP_LINGER_DETECTION,
    PROP_LOCK_BODY_TYPE,
    PROP_LOCK_FORCE,
    PROP_LOCK_STATUS,
    PROP_LOCK_VOLUME,
    PROP_LOCKED_INSIDE_STATUS,
    PROP_MODEL_VERSION,
    PROP_SCREEN_ACTIVE_TIME,
    PROP_SCREEN_BACKLIGHT,
    PROP_SCREEN_ONOFF,
    PROP_WIFI_RSSI,
    SERVICE_BASIC,
    SERVICE_LOCK,
)
from .token_manager import KaadasTokenManager

_LOGGER = logging.getLogger(__name__)

# (service, property) 需要读取的物模型属性
_THING_PROPERTIES: list[tuple[str, str]] = [
    (SERVICE_BASIC, PROP_BATTERY_LEVEL),
    (SERVICE_BASIC, PROP_WIFI_RSSI),
    (SERVICE_BASIC, PROP_FIRMWARE_VERSION),
    (SERVICE_BASIC, PROP_MODEL_VERSION),
    (SERVICE_LOCK, PROP_LOCK_STATUS),
    (SERVICE_LOCK, PROP_DOOR_LOCK_ACTION_TYPE),
    (SERVICE_LOCK, PROP_ALARM_TYPE),
    (SERVICE_LOCK, PROP_LOCKED_INSIDE_STATUS),
    (SERVICE_LOCK, PROP_DEFENSE_MODE),
    (SERVICE_LOCK, PROP_DOUBLE_VERIFY_MODE),
    (SERVICE_LOCK, PROP_DOOR_DIRECTION),
    (SERVICE_LOCK, PROP_LOCK_FORCE),
    (SERVICE_LOCK, PROP_AUTO_CLOSE_LOCK_TIME),
    (SERVICE_LOCK, PROP_CLOSE_LOCK_MODE),
    (SERVICE_LOCK, PROP_LINGER_DETECTION),
    (SERVICE_LOCK, PROP_LOCK_VOLUME),
    (SERVICE_LOCK, PROP_LANGUAGE),
    (SERVICE_LOCK, PROP_LOCK_BODY_TYPE),
    (SERVICE_LOCK, PROP_SCREEN_ONOFF),
    (SERVICE_LOCK, PROP_SCREEN_BACKLIGHT),
    (SERVICE_LOCK, PROP_SCREEN_ACTIVE_TIME),
]


def _find_key(obj: Any, key: str) -> Any:
    """递归查找第一个 key 匹配的值（兼容多种物模型返回结构）。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def _nested(device: dict[str, Any], key: str) -> dict[str, Any]:
    value = device.get(key)
    return value if isinstance(value, dict) else {}


def device_info(entry: ConfigEntry, data: dict[str, Any]) -> dict[str, Any]:
    """生成统一的设备信息，供各实体平台挂到同一个设备下。"""
    device = data.get("device") or {}
    wifi_sn = str(device.get("wifiSN") or device.get("esn") or entry.entry_id)
    nickname = str(entry.data.get(CONF_NICKNAME) or wifi_sn)
    model = str(
        entry.data.get(CONF_DEVICE_MODEL)
        or device.get("abbreviation")
        or device.get("lockModel")
        or "凯迪仕智能门锁"
    )
    return {
        "identifiers": {(DOMAIN, wifi_sn)},
        "name": f"凯迪仕 {nickname}",
        "manufacturer": "凯迪仕 Kaadas",
        "model": model,
    }


class KaadasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """数据协调器：由 WebSocket 实时推送驱动刷新，不自动轮询。"""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, token_manager: KaadasTokenManager
    ) -> None:
        self.entry = entry
        self.token_manager = token_manager
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            always_update=True,
        )

    def _wifi_sn(self) -> str:
        return str(
            self.entry.data.get(CONF_WIFI_SN) or self.entry.data.get(CONF_ESN) or ""
        ).strip()

    @staticmethod
    def _find_device(devices: list[dict[str, Any]], wifi_sn: str) -> dict[str, Any] | None:
        for device in devices:
            if str(device.get("wifiSN") or device.get("esn") or "") == wifi_sn:
                return device
        return None

    def _device_fallback_data(self, device: dict[str, Any]) -> dict[str, Any]:
        """旧协议（isThingModel=0）设备：直接从 wifiList 字段取 lock_service 属性。"""
        screen = _nested(device, "screen")
        pir = _nested(device, "pir")
        set_pir = _nested(device, "setPir")
        return {
            PROP_LOCKED_INSIDE_STATUS: device.get("operatingMode"),
            PROP_DEFENSE_MODE: device.get("defences"),
            PROP_DOOR_DIRECTION: device.get("openDirection"),
            PROP_LOCK_FORCE: device.get("openForce"),
            PROP_AUTO_CLOSE_LOCK_TIME: device.get("autoRelockTime"),
            PROP_CLOSE_LOCK_MODE: device.get("closeLockMode")
            or device.get("lockMode"),
            PROP_LINGER_DETECTION: pir.get("stayTime")
            if pir.get("stayTime") is not None
            else set_pir.get("stay_time"),
            PROP_LOCK_VOLUME: device.get("volume"),
            PROP_LANGUAGE: device.get("language"),
            PROP_LOCK_BODY_TYPE: device.get("lockType")
            if device.get("lockType") is not None
            else device.get("lockModel"),
            PROP_DOUBLE_VERIFY_MODE: device.get("doubleVerify")
            if device.get("doubleVerify") is not None
            else device.get("doubleVerification"),
            PROP_SCREEN_ONOFF: device.get("screenLightSwitch")
            if device.get("screenLightSwitch") is not None
            else screen.get("enabled"),
            PROP_SCREEN_BACKLIGHT: device.get("screenLightLevel")
            if device.get("screenLightLevel") is not None
            else screen.get("brightness"),
            PROP_SCREEN_ACTIVE_TIME: device.get("screenLightTime")
            if device.get("screenLightTime") is not None
            else screen.get("duration"),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            devices = await self.token_manager.async_get_devices()
        except KaadasAuthError as err:
            # reauth 已在 token_manager 内触发
            _LOGGER.error("凯迪仕认证失败：%s", err)
            raise UpdateFailed(f"登录已过期，请重新认证：{err}") from err
        except KaadasApiError as err:
            _LOGGER.error("凯迪仕接口错误：%s", err)
            raise UpdateFailed(str(err)) from err

        wifi_sn = self._wifi_sn()
        device = self._find_device(devices, wifi_sn)
        if device is None:
            raise UpdateFailed("账号下未找到该门锁设备")

        data: dict[str, Any] = {
            "device": device,
            "wifi_sn": wifi_sn,
            "connect_state": device.get("connectState"),
            "open_status": (
                device.get("open_status")
                if device.get("open_status") is not None
                else device.get("openStatus")
            ),
            "power": device.get("power"),
            "last_update_time": dt_util.now().strftime("%Y-%m-%d %H:%M:%S"),
            # 旧协议设备：直接从设备字段取（供传感器回退）
            PROP_BATTERY_LEVEL: device.get("power"),
            PROP_WIFI_RSSI: (
                device.get("rssi")
                if device.get("rssi") is not None
                else device.get("RSSI")
            ),
            PROP_FIRMWARE_VERSION: device.get("wifiVersion") or device.get("wifiVer"),
            PROP_MODEL_VERSION: device.get("lockModel") or device.get("deviceModel"),
        }
        data.update(self._device_fallback_data(device))

        if bool(device.get("isThingModel") or self.entry.data.get(CONF_IS_THING_MODEL)):
            api = await self.token_manager.async_get_api()
            try:
                properties = await api.async_get_properties(
                    wifi_sn,
                    [
                        {"name": name, "service": service}
                        for service, name in _THING_PROPERTIES
                    ],
                )
            except KaadasAuthError:
                await self.token_manager.async_trigger_reauth()
                properties = None
            except KaadasApiError as err:
                _LOGGER.warning("读取物模型属性失败：%s", err)
                properties = None
            data["properties"] = properties
            for _service, name in _THING_PROPERTIES:
                value = _find_key(properties, name)
                if value is not None:
                    data[name] = value

        return data
