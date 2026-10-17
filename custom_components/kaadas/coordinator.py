from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KaadasApiError, KaadasAuthError
from .const import (
    CONF_DEVICE_MODEL,
    CONF_ESN,
    CONF_IS_THING_MODEL,
    CONF_NICKNAME,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_MODE,
    CONF_WIFI_SN,
    DOMAIN,
    EVENT_ALARM,
    EVENT_DOORBELL,
    EVENT_OPERATION,
    LOCK_STATUS_LOCKED,
    LOCK_STATUS_UNLOCKED,
    MIN_POLLING_INTERVAL,
    DEFAULT_POLLING_MODE,
    POLLING_AUTO,
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
    RECORD_ALARM,
    RECORD_OPERATION,
    RECORD_POLL_INTERVAL_SECONDS,
    RECORD_VISIT,
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


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
    """数据协调器：WebSocket 实时推送 + 低频轮询兜底。

    每次刷新会拉取操作/访客/预警三类记录，并按记录 ``id`` 去重后，
    对新出现的记录在 HA 事件总线上触发 ``kaadas_*`` 事件。
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, token_manager: KaadasTokenManager
    ) -> None:
        self.entry = entry
        self.token_manager = token_manager
        self._seen_store = Store(hass, 1, f"{DOMAIN}_records_{entry.entry_id}")
        # 每类记录「已见的最新 id」水位线（Mongo ObjectId 十六进制，按时间单调）
        self._seen_ids: dict[str, str] = {
            RECORD_OPERATION: "",
            RECORD_VISIT: "",
            RECORD_ALARM: "",
        }
        self._seen_loaded = False

        # 轮询配置：自动模式下按配置间隔轮询；手动模式仅 WS 推送 + 手动刷新服务
        options = entry.options or {}
        polling_mode = str(options.get(CONF_POLLING_MODE) or DEFAULT_POLLING_MODE)
        polling_interval = _to_int(options.get(CONF_POLLING_INTERVAL))
        if polling_interval < MIN_POLLING_INTERVAL:
            polling_interval = RECORD_POLL_INTERVAL_SECONDS
        self._polling_mode = polling_mode
        self._polling_interval = polling_interval
        update_interval = (
            timedelta(seconds=polling_interval)
            if polling_mode == POLLING_AUTO
            else None
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
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

    @staticmethod
    def _format_ts(value: Any) -> str | None:
        """把秒/毫秒时间戳格式化为本地时间字符串。"""
        if value in (None, ""):
            return None
        try:
            ts = int(value)
            if ts < 10**12:  # 秒级时间戳转毫秒
                ts *= 1000
            dt = dt_util.as_local(
                dt_util.utc_from_timestamp(ts / 1000)
            )
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return str(value)

    def _device_fallback_data(self, device: dict[str, Any]) -> dict[str, Any]:
        """旧协议（isThingModel=0）设备：直接从 wifiList 字段取 lock_service 属性。"""
        screen = _nested(device, "screen")
        pir = _nested(device, "pir")
        set_pir = _nested(device, "setPir")
        open_status = (
            device.get("open_status")
            if device.get("open_status") is not None
            else device.get("openStatus")
        )
        lock_status = None
        if open_status is not None:
            # open_status: 1=关锁 / 2=开锁 -> lock_status: 2=关锁 / 1=开锁
            lock_status = {1: LOCK_STATUS_LOCKED, 2: LOCK_STATUS_UNLOCKED}.get(
                _to_int(open_status)
            )
        return {
            PROP_LOCK_STATUS: lock_status,
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

    async def _load_seen(self) -> None:
        """加载各类记录「已见最新 id」水位线（只读一次）。"""
        if self._seen_loaded:
            return
        try:
            saved = await self._seen_store.async_load() or {}
        except Exception:  # noqa: BLE001 - 读取失败不影响主流程
            saved = {}
        if isinstance(saved, dict):
            for category in (RECORD_OPERATION, RECORD_VISIT, RECORD_ALARM):
                self._seen_ids[category] = str(saved.get(category) or "")
        self._seen_loaded = True

    async def _save_seen(self) -> None:
        """持久化水位线。"""
        try:
            await self._seen_store.async_save(self._seen_ids)
        except Exception as err:  # noqa: BLE001 - 保存失败仅告警
            _LOGGER.warning("保存记录水位线失败：%s", err)

    async def _fetch_record_list(self, api: Any, wifi_sn: str, category: str) -> list[dict[str, Any]]:
        """拉取某一类记录首页（最新 10 条），失败返回空列表。"""
        records: list[dict[str, Any]] = []
        try:
            if category == RECORD_VISIT:
                result = await api.async_get_visit_records(wifi_sn)
            elif category == RECORD_ALARM:
                result = await api.async_get_alarm_records(wifi_sn)
            else:
                result = await api.async_get_operation_records(wifi_sn)
            if isinstance(result, dict):
                payload = result.get("data")
                if isinstance(payload, list):
                    records = [item for item in payload if isinstance(item, dict)]
        except (KaadasApiError, KaadasAuthError) as err:
            _LOGGER.warning("读取%s记录失败：%s", category, err)
        return records

    def _detect_new_records(self, category: str, records: list[dict[str, Any]]) -> None:
        """按 id 水位线检测新记录并触发事件；首轮只建基线不触发。"""
        if not records:
            return
        last_seen = self._seen_ids.get(category, "")
        ids = [str(record.get("id") or "") for record in records]
        current_max = max(ids) if ids else ""
        new_records: list[dict[str, Any]] = []
        if last_seen and current_max > last_seen:
            new_records = [
                record
                for record in records
                if str(record.get("id") or "") > last_seen
            ]
        if current_max > last_seen:
            self._seen_ids[category] = current_max
        # 从旧到新触发，保证事件顺序
        for record in reversed(new_records):
            self._fire_record_event(category, record)

    def _fire_record_event(self, category: str, record: dict[str, Any]) -> None:
        """在 HA 事件总线上触发一次记录事件。"""
        event_type = {
            RECORD_OPERATION: EVENT_OPERATION,
            RECORD_VISIT: EVENT_DOORBELL,
            RECORD_ALARM: EVENT_ALARM,
        }.get(category)
        if not event_type:
            return
        self.hass.bus.async_fire(
            event_type,
            {
                "wifi_sn": str(record.get("wifiSN") or ""),
                "time": record.get("time"),
                "text": str(record.get("textContent") or ""),
                "type": record.get("type"),
                "event_id": str(record.get("eventId") or ""),
                "thumb_url": str(record.get("thumbUrl") or ""),
                "pwd_type": record.get("pwdType"),
                "pwd_num": record.get("pwdNum"),
                "user_nickname": str(record.get("userNickname") or ""),
                "duress": bool(record.get("duress") or False),
            },
        )

    async def _fetch_records_and_stats(
        self, api: Any, wifi_sn: str, data: dict[str, Any]
    ) -> None:
        """读取操作/访客/预警记录与近 7 天统计（非致命，失败仅告警）。"""
        operation_records = await self._fetch_record_list(api, wifi_sn, RECORD_OPERATION)
        visit_records = await self._fetch_record_list(api, wifi_sn, RECORD_VISIT)
        alarm_records = await self._fetch_record_list(api, wifi_sn, RECORD_ALARM)

        # 去重检测并触发事件
        self._detect_new_records(RECORD_OPERATION, operation_records)
        self._detect_new_records(RECORD_VISIT, visit_records)
        self._detect_new_records(RECORD_ALARM, alarm_records)
        await self._save_seen()

        seven_day_stats: list[dict[str, Any]] = []
        try:
            stats = await api.async_get_seven_day_statistics(wifi_sn)
            if isinstance(stats, list):
                seven_day_stats = [item for item in stats if isinstance(item, dict)]
        except (KaadasApiError, KaadasAuthError) as err:
            _LOGGER.warning("读取近 7 天统计失败：%s", err)

        day_stats: dict[str, Any] = {}
        try:
            day = await api.async_get_day_statistics(wifi_sn)
            if isinstance(day, dict):
                day_stats = day
        except (KaadasApiError, KaadasAuthError) as err:
            _LOGGER.warning("读取当日统计失败：%s", err)

        open_count: dict[str, Any] = {}
        try:
            count = await api.async_get_open_count(wifi_sn)
            if isinstance(count, dict):
                open_count = count
        except (KaadasApiError, KaadasAuthError) as err:
            _LOGGER.warning("读取开锁次数失败：%s", err)

        data["operation_records"] = operation_records
        data["visit_records"] = visit_records
        data["alarm_records"] = alarm_records
        data["seven_day_stats"] = seven_day_stats
        data["day_stats"] = day_stats
        data["today_operation_count"] = day_stats.get("allCount")
        data["today_doorbell_count"] = day_stats.get("doorbellCount")
        data["open_count"] = open_count.get("openCount")
        data["open_count_compare_day"] = open_count.get("compareDay")
        data["seven_day_operation_count"] = sum(
            _to_int(item.get("operationCount")) for item in seven_day_stats
        )
        data["seven_day_doorbell_count"] = sum(
            _to_int(item.get("doorbellCount")) for item in seven_day_stats
        )
        data["seven_day_alarm_count"] = sum(
            _to_int(item.get("alarmCount")) for item in seven_day_stats
        )
        if operation_records:
            data["last_operation_time"] = self._format_ts(
                operation_records[0].get("time")
            )
        if visit_records:
            data["last_visit_time"] = self._format_ts(visit_records[0].get("time"))
        if alarm_records:
            data["last_alarm_time"] = self._format_ts(alarm_records[0].get("time"))

    async def _async_update_data(self) -> dict[str, Any]:
        await self._load_seen()
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

        api = await self.token_manager.async_get_api()

        if bool(device.get("isThingModel") or self.entry.data.get(CONF_IS_THING_MODEL)):
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

        await self._fetch_records_and_stats(api, wifi_sn, data)

        return data
