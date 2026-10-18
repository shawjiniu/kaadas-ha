from __future__ import annotations

import logging
from collections import OrderedDict

from aiohttp import ClientTimeout
from aiohttp.web import Request, Response

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_CACHE_MAX = 64


class KaadasImageProxyView(HomeAssistantView):
    """按记录 id 精确代理凯迪仕抓拍图（服务端拉图，避免前端直连云端 URL）。"""

    url = "/api/kaadas/image_proxy/{entry_id}/{category}/{record_id}"
    name = "api:kaadas:image_proxy"
    # 图片通过 <img> 加载（无法带 Authorization 头），故不强制登录；
    # 安全性靠 URL 里的 entry_id(UUID) + record_id(ObjectId) 随机性 + 只查已拉取数据（防 SSRF）。
    requires_auth = False

    def __init__(self) -> None:
        self._cache: OrderedDict[str, tuple[str, bytes]] = OrderedDict()

    @staticmethod
    def _lookup_thumb_url(
        hass: HomeAssistant, entry_id: str, category: str, record_id: str
    ) -> str:
        """从协调器已拉取的数据里按记录 id 查 thumbUrl（不接受任意 URL，防 SSRF）。"""
        data = hass.data.get(DOMAIN, {}).get(entry_id, {})
        coordinator = data.get("coordinator")
        if coordinator is None:
            return ""
        records = (coordinator.data or {}).get(f"{category}_records") or []
        for record in records:
            if not isinstance(record, dict):
                continue
            if str(record.get("id") or "") == record_id:
                return str(record.get("thumbUrl") or "").strip()
        return ""

    async def get(
        self, request: Request, entry_id: str, category: str, record_id: str
    ) -> Response:
        if category not in ("visit", "alarm"):
            return Response(status=404, text="not found")

        hass = request.app["hass"]
        cache_key = f"{entry_id}:{category}:{record_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            content_type, body = cached
            return Response(body=body, content_type=content_type)

        thumb_url = self._lookup_thumb_url(hass, entry_id, category, record_id)
        if not thumb_url:
            return Response(status=404, text="not found")

        session = async_get_clientsession(hass)
        try:
            async with session.get(thumb_url, timeout=ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                body = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
        except Exception as err:  # noqa: BLE001 - 拉取失败返回 502
            _LOGGER.warning("代理抓拍图失败：%s", err)
            return Response(status=502, text="fetch failed")

        self._cache[cache_key] = (content_type, body)
        self._cache.move_to_end(cache_key)
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)

        return Response(body=body, content_type=content_type)
