from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KaadasAuthError
from .const import CONF_ESN, CONF_TOKEN, CONF_WIFI_SN, WS_URL
from .coordinator import KaadasCoordinator
from .token_manager import KaadasTokenManager

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 10  # 与小程序一致，每 10 秒发一次心跳
RECONNECT_BASE = 5
RECONNECT_MAX = 60


class KaadasWebSocket:
    """凯迪仕云端 WebSocket：实时推送替代定时轮询。"""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        token_manager: KaadasTokenManager,
        coordinator: KaadasCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.token_manager = token_manager
        self.coordinator = coordinator
        self._stop = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = self.hass.async_create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()

    def _wifi_sn(self) -> str:
        return str(
            self.entry.data.get(CONF_WIFI_SN) or self.entry.data.get(CONF_ESN) or ""
        ).strip()

    async def _run(self) -> None:
        backoff = RECONNECT_BASE
        while not self._stop:
            try:
                await self.token_manager.async_ensure_valid()
            except KaadasAuthError:
                await self.token_manager.async_trigger_reauth()
                await self._sleep(RECONNECT_MAX)
                backoff = RECONNECT_BASE
                continue

            token = str(self.entry.data.get(CONF_TOKEN) or "").strip()
            if not token:
                await self._sleep(RECONNECT_MAX)
                continue

            try:
                await self._listen(token)
                backoff = RECONNECT_BASE
            except KaadasAuthError:
                renewed = await self.token_manager.async_renew_token()
                backoff = RECONNECT_BASE if renewed else RECONNECT_MAX
            except asyncio.CancelledError:
                raise
            except aiohttp.ClientError as err:
                _LOGGER.warning("凯迪仕 WS 连接失败/断开：%s", err)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("凯迪仕 WS 异常：%s", err)

            if self._stop:
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX)

    async def _listen(self, token: str) -> None:
        session = async_get_clientsession(self.hass)
        headers = {
            "Authorization": f"Bearer {token}",
            "Ver": "1",
            "Timestamp": str(int(time.time() * 1000)),
        }
        async with session.ws_connect(WS_URL, headers=headers, heartbeat=None) as ws:
            hb_task = self.hass.async_create_task(self._heartbeat(ws))
            _LOGGER.info("凯迪仕 WS 已连接")
            try:
                # 连接/重连后立即同步一次，避免漏掉断线期间的事件
                await self.coordinator.async_request_refresh()
                async for msg in ws:
                    if self._stop:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
            finally:
                hb_task.cancel()
        _LOGGER.info("凯迪仕 WS 已断开")

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            while not self._stop:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await ws.send_str('{"msg":"发送心跳"}')
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass

    async def _handle_message(self, data: str) -> None:
        if "发送心跳" in data:
            return
        try:
            msg = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(msg, dict):
            return
        code = str(msg.get("code"))
        if code == "401":
            raise KaadasAuthError("WS 返回 401，token 失效")
        sn = str(msg.get("wifiSN") or msg.get("esn") or "")
        if sn and sn != self._wifi_sn():
            return
        _LOGGER.debug("凯迪仕 WS 推送：%s", msg)
        await self.coordinator.async_request_refresh()

    async def _sleep(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise
