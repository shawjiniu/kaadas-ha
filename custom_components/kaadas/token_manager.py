from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import KaadasApi, KaadasApiError, KaadasAuthError
from .const import (
    CONF_OPENID,
    CONF_OPENID_TOKEN,
    CONF_PHONE,
    CONF_TOKEN,
    CONF_UID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Kaadas 接口不返回 token 有效期，沿用小程序 7 天重置（604800000ms）的常量。
TOKEN_TTL_MS = 7 * 24 * 3600 * 1000  # 7 天
TOKEN_RENEW_AHEAD_MS = 2 * 3600 * 1000  # 提前 2 小时续期
TOKEN_BACKOFF_BASE_MS = 5 * 60 * 1000  # 网络失败退避基数
TOKEN_BACKOFF_MAX_MS = 3600 * 1000  # 网络失败退避上限
TOKEN_MIN_SCHEDULE_DELAY_MS = 60 * 1000  # 最小调度间隔
TOKEN_INVALID_RETRY_MS = 24 * 3600 * 1000  # 凭证失效后停止常规调度


class KaadasTokenManager:
    """管理 token 的自动续期与重新认证。

    自动续期方式：用已存的 openId + 手机号重新调用 ``/user/login`` 换取新 token/uid
    （实测可跳过微信 OAuth）。token 只在 ``entry.data`` 存一份；本类用 ``Store``
    仅持久化调度元数据（生效时间 / 下次检查 / 退避计数 / token 指纹）。
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, 1, f"{DOMAIN}_token_{entry.entry_id}")
        self.data: dict[str, Any] = {}
        self._loaded = False
        self._unsub: Callable[[], None] | None = None
        self._renew_lock = asyncio.Lock()
        self._reauth_started = False

    async def async_load(self) -> None:
        if self._loaded:
            return
        self.data = await self.store.async_load() or {}
        self._loaded = True

    async def async_save(self) -> None:
        await self.store.async_save(self.data)

    def _token(self) -> str:
        return str(self.entry.data.get(CONF_TOKEN) or "").strip()

    def _uid(self) -> str:
        return str(self.entry.data.get(CONF_UID) or "").strip()

    def _openid(self) -> str:
        return str(self.entry.data.get(CONF_OPENID) or "").strip()

    def _phone(self) -> str:
        return str(self.entry.data.get(CONF_PHONE) or "").strip()

    def _open_id_token(self) -> str:
        return str(self.entry.data.get(CONF_OPENID_TOKEN) or "").strip()

    def _fingerprint(self) -> str:
        return hashlib.sha1(f"{self._token()}|{self._uid()}".encode()).hexdigest()

    async def async_get_api(self) -> KaadasApi:
        return KaadasApi(async_get_clientsession(self.hass), self._token(), self._uid())

    async def async_note_token_set(self) -> None:
        """登录 / 重新认证 / 选项更新后调用：记录生效时间并调度检查。"""
        await self.async_load()
        if not self._token():
            return
        now = self._now_ms()
        fingerprint = self._fingerprint()
        if self.data.get("token_fingerprint") != fingerprint:
            self.data["token_fingerprint"] = fingerprint
            self.data["token_save_time"] = now
            self.data["token_next_check"] = now + TOKEN_TTL_MS - TOKEN_RENEW_AHEAD_MS
            self.data["token_attempt"] = 0
        elif not self.data.get("token_next_check"):
            self.data["token_save_time"] = self.data.get("token_save_time") or now
            self.data["token_next_check"] = now + TOKEN_TTL_MS - TOKEN_RENEW_AHEAD_MS
        await self.async_save()
        self.async_schedule()

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """确保 token 有效并拉取设备列表；鉴权失败时自动续期并重试一次。"""
        await self.async_ensure_valid()
        try:
            api = await self.async_get_api()
            return await api.async_get_bind_devices()
        except KaadasAuthError:
            # 主动续期（重新登录）后重试一次
            try:
                await self._renew(force=True)
            except KaadasAuthError:
                await self.async_trigger_reauth()
                raise
            api = await self.async_get_api()
            return await api.async_get_bind_devices()

    async def async_renew_token(self) -> bool:
        """强制续期；成功（或仅网络错误）返回 True，凭证失效返回 False 并触发 reauth。"""
        try:
            await self._renew(force=True)
            return True
        except KaadasAuthError:
            await self.async_trigger_reauth()
            return False

    async def async_ensure_valid(self) -> None:
        """数据请求前调用：到期则续期。"""
        await self.async_load()
        now = self._now_ms()
        next_check = int(self.data.get("token_next_check") or 0)
        if not next_check or now >= next_check:
            await self._renew(force=False)

    def async_schedule(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        next_check = int(self.data.get("token_next_check") or 0)
        if not next_check:
            return
        now = self._now_ms()
        check_at = max(next_check, now + TOKEN_MIN_SCHEDULE_DELAY_MS)
        when = datetime.fromtimestamp(check_at / 1000, timezone.utc)
        self._unsub = async_track_point_in_utc_time(self.hass, self._async_token_check, when)

    def async_cancel(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _async_token_check(self, _now: datetime) -> None:
        self._unsub = None
        try:
            await self._renew(force=False)
        except KaadasAuthError:
            await self.async_trigger_reauth()
        self.async_schedule()

    async def _renew(self, force: bool = False) -> None:
        """自动续期：用 openId + 手机号重新登录换新 token。凭证失效抛 KaadasAuthError。"""
        async with self._renew_lock:
            await self.async_load()
            now = self._now_ms()
            save_time = int(self.data.get("token_save_time") or 0)
            if save_time and not force:
                remain = save_time + TOKEN_TTL_MS - now
                if remain > TOKEN_RENEW_AHEAD_MS:
                    # 未到续期窗口，只刷新调度账本
                    self.data["token_next_check"] = now + TOKEN_TTL_MS - TOKEN_RENEW_AHEAD_MS
                    await self.async_save()
                    return

            openid = self._openid()
            phone = self._phone()
            if not openid or not phone:
                # 缺自动续期凭证，退化为探活
                await self._probe_validity(now)
                return

            api = KaadasApi(async_get_clientsession(self.hass), "", self._uid())
            try:
                info = await api.async_login(openid, phone, self._open_id_token())
            except KaadasAuthError:
                self.data.update(
                    {
                        "token_last_check": now,
                        "token_next_check": now + TOKEN_INVALID_RETRY_MS,
                    }
                )
                await self.async_save()
                raise
            except KaadasApiError:
                attempt = int(self.data.get("token_attempt") or 0) + 1
                backoff = min(
                    TOKEN_BACKOFF_BASE_MS * (2 ** (attempt - 1)), TOKEN_BACKOFF_MAX_MS
                )
                self.data.update(
                    {
                        "token_attempt": attempt,
                        "token_last_check": now,
                        "token_next_check": now + backoff,
                    }
                )
                await self.async_save()
                return

            new_token = str(info.get("token") or "").strip()
            new_uid = str(info.get("uid") or self._uid() or "").strip()
            if not new_token:
                self.data.update(
                    {
                        "token_last_check": now,
                        "token_next_check": now + TOKEN_INVALID_RETRY_MS,
                    }
                )
                await self.async_save()
                raise KaadasAuthError("重新登录未返回 token")

            # 续期成功：更新 entry.data 与账本
            new_data = dict(self.entry.data)
            new_data[CONF_TOKEN] = new_token
            new_data[CONF_UID] = new_uid
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            self.data.update(
                {
                    "token_fingerprint": self._fingerprint(),
                    "token_save_time": now,
                    "token_next_check": now + TOKEN_TTL_MS - TOKEN_RENEW_AHEAD_MS,
                    "token_attempt": 0,
                    "token_last_check": now,
                }
            )
            await self.async_save()
            _LOGGER.info("凯迪仕 token 已自动续期")

    async def _probe_validity(self, now: int) -> None:
        """无 openId/phone 时的兜底：探活 token 是否仍有效。"""
        api = await self.async_get_api()
        try:
            await api.async_get_bind_devices()
        except KaadasAuthError:
            self.data.update(
                {
                    "token_last_check": now,
                    "token_next_check": now + TOKEN_INVALID_RETRY_MS,
                }
            )
            await self.async_save()
            raise
        except KaadasApiError:
            attempt = int(self.data.get("token_attempt") or 0) + 1
            backoff = min(
                TOKEN_BACKOFF_BASE_MS * (2 ** (attempt - 1)), TOKEN_BACKOFF_MAX_MS
            )
            self.data.update(
                {
                    "token_attempt": attempt,
                    "token_last_check": now,
                    "token_next_check": now + backoff,
                }
            )
            await self.async_save()
            return
        self.data.update(
            {
                "token_attempt": 0,
                "token_last_check": now,
                "token_next_check": now + TOKEN_TTL_MS - TOKEN_RENEW_AHEAD_MS,
            }
        )
        await self.async_save()

    async def async_trigger_reauth(self) -> None:
        """触发重新认证（去重，避免重复弹窗）。"""
        if self._reauth_started:
            return
        self._reauth_started = True
        _LOGGER.warning("凯迪仕凭证已失效（openId 过期），触发重新认证")
        self.hass.async_create_task(
            self.hass.config_entries.async_start_reauth(self.entry.entry_id)
        )

    def _now_ms(self) -> int:
        return int(dt_util.utcnow().timestamp() * 1000)
