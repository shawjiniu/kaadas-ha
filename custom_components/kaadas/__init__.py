from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SERVICE_REFRESH
from .coordinator import KaadasCoordinator
from .token_manager import KaadasTokenManager
from .websocket import KaadasWebSocket

_LOGGER = logging.getLogger(__name__)

REFRESH_SCHEMA = vol.Schema({vol.Optional("entry_id"): str})

PLATFORMS: list[Platform] = [
    Platform.LOCK,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.CAMERA,
]

FRONTEND_URL = "/kaadas/frontend"
BRAND_URL = "/kaadas/brand"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """注册前端静态路径与手动刷新服务。"""
    # 前端静态路径（卡片 JS + 品牌图标）：在 async_setup 阶段注册（与
    # chinese_calendar 一致），保证手机 App 通过 /kaadas/frontend/ 也能加载卡片。
    try:
        await _async_register_static_paths(hass, Path(__file__).parent)
    except Exception as err:  # noqa: BLE001 - 静态路径失败不阻塞其它功能
        _LOGGER.error("凯迪仕静态路径注册失败：%s", err)

    async def _refresh(call) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            entries = [hass.config_entries.async_get_entry(entry_id)]
        else:
            entries = list(hass.config_entries.async_entries(DOMAIN))
        for entry in entries:
            if not entry or entry.domain != DOMAIN:
                continue
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if data and data.get("coordinator"):
                await data["coordinator"].async_request_refresh()
                _LOGGER.info("凯迪仕 %s 手动刷新", entry.entry_id)

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _refresh, schema=REFRESH_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    token_manager = KaadasTokenManager(hass, entry)
    await token_manager.async_load()
    await token_manager.async_note_token_set()

    coordinator = KaadasCoordinator(hass, entry, token_manager)
    await coordinator.async_config_entry_first_refresh()

    websocket = KaadasWebSocket(hass, entry, token_manager, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "token_manager": token_manager,
        "websocket": websocket,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    websocket.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            await data["websocket"].stop()
            data["token_manager"].async_cancel()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_static_paths(hass: HomeAssistant, base: Path) -> None:
    """注册静态路径，兼容新版（async_register_static_paths）与旧版 HA。"""
    try:
        from homeassistant.components.http import StaticPathConfig
    except ImportError:
        StaticPathConfig = None  # type: ignore[assignment]

    if StaticPathConfig is not None:
        try:
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(FRONTEND_URL, str(base / "frontend"), False),
                    StaticPathConfig(BRAND_URL, str(base / "brand"), True),
                ]
            )
            return
        except AttributeError:
            pass  # 旧版 HA，回退到 register_static_path
        except TypeError as err:
            _LOGGER.warning(
                "async_register_static_paths 调用失败，回退旧接口：%s", err
            )

    # 旧版接口
    hass.http.register_static_path(
        FRONTEND_URL, str(base / "frontend"), cache_headers=False
    )
    hass.http.register_static_path(
        BRAND_URL, str(base / "brand"), cache_headers=True
    )
