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
    """服务端代理凯迪仕抓拍图。

    前端把记录里的 thumbUrl 作为 ``url`` 查询参数传入；服务端只在
    「协调器已拉取的记录里存在该 thumbUrl」时才去拉图并返回，避免 SSRF。
    """

    url = "/api/kaadas/image_proxy"
    name = "api:kaadas:image_proxy"
    # 图片通过 <img> 加载（无法带 Authorization 头），故不强制登录；
    # 安全性靠「只允许已存在于记录数据里的 thumbUrl」白名单 + URL 随机性。
    requires_auth = False

    def __init__(self) -> None:
        self._cache: OrderedDict[str, tuple[str, bytes]] = OrderedDict()

    @staticmethod
    def _known_thumb_urls(hass: HomeAssistant) -> set[str]:
        """收集当前所有条目里已知的抓拍图 thumbUrl。"""
        known: set[str] = set()
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            coordinator = entry_data.get("coordinator")
            if coordinator is None:
                continue
            data = coordinator.data or {}
            for category in ("visit", "alarm"):
                for record in data.get(f"{category}_records") or []:
                    if not isinstance(record, dict):
                        continue
                    url = str(record.get("thumbUrl") or "").strip()
                    if url:
                        known.add(url)
        return known

    async def get(self, request: Request) -> Response:
        thumb_url = request.query.get("url", "").strip()
        if not thumb_url:
            return Response(status=400, text="missing url")

        hass = request.app["hass"]
        if thumb_url not in self._known_thumb_urls(hass):
            return Response(status=404, text="not found")

        cached = self._cache.get(thumb_url)
        if cached is not None:
            self._cache.move_to_end(thumb_url)
            content_type, body = cached
            return Response(body=body, content_type=content_type)

        session = async_get_clientsession(hass)
        try:
            async with session.get(thumb_url, timeout=ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                body = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
        except Exception as err:  # noqa: BLE001 - 拉取失败返回 502
            _LOGGER.warning("代理抓拍图失败：%s", err)
            return Response(status=502, text="fetch failed")

        self._cache[thumb_url] = (content_type, body)
        self._cache.move_to_end(thumb_url)
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)

        return Response(body=body, content_type=content_type)
