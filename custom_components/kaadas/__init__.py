from __future__ import annotations

import logging
from pathlib import Path
import shutil

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import KaadasCoordinator
from .token_manager import KaadasTokenManager
from .websocket import KaadasWebSocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LOCK,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

FRONTEND_URL = "/kaadas/frontend"
BRAND_URL = "/kaadas/brand"
CARD_JS = "kaadas-lock-card.js"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_frontend(hass)

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


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """把随集成打包的 Lovelace 卡片注册为额外前端资源。"""
    flag = f"{DOMAIN}_frontend_registered"
    if hass.data.get(flag):
        return

    base = Path(__file__).parent

    # 1) 注册静态路径（卡片 JS + 品牌图标）
    try:
        await _async_register_static_paths(hass, base)
    except Exception as err:  # noqa: BLE001 - 静态路径失败不阻塞后续
        _LOGGER.error("凯迪仕静态路径注册失败：%s", err)

    # 2) 自动同步卡片到 config/www/，供 /local/ 资源使用（手机 App 需走 /local/）
    card_src = base / "frontend" / CARD_JS
    www_dir = Path(hass.config.path("www"))
    www_dst = www_dir / CARD_JS
    try:
        synced = await hass.async_add_executor_job(
            _sync_card_file, www_dir, card_src, www_dst
        )
        if synced:
            _LOGGER.info("凯迪仕卡片已同步到 /local/%s", CARD_JS)
    except Exception as err:  # noqa: BLE001 - 同步失败不影响浏览器端
        _LOGGER.error("同步凯迪仕卡片到 config/www 失败：%s", err)

    # 3) 注入额外 JS 模块（浏览器端）
    try:
        from homeassistant.components import frontend

        frontend.add_extra_js_url(hass, f"{FRONTEND_URL}/{CARD_JS}")
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("凯迪仕卡片资源注入失败：%s", err)
        return

    hass.data[flag] = True
    _LOGGER.info(
        "凯迪仕门锁卡片已注册：%s/%s（若未生效请硬刷新浏览器）", FRONTEND_URL, CARD_JS
    )


def _sync_card_file(www_dir: Path, src: Path, dst: Path) -> bool:
    """把卡片 JS 同步到 config/www，返回是否有变化（供 executor 调用）。"""
    www_dir.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.read_bytes() == src.read_bytes():
        return False
    shutil.copyfile(src, dst)
    return True


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
