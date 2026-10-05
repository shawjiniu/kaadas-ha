from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KaadasApi, KaadasApiError, KaadasAuthError
from .const import (
    CONF_DEVICE_MODEL,
    CONF_ESN,
    CONF_IS_THING_MODEL,
    CONF_NICKNAME,
    CONF_OPENID,
    CONF_OPENID_TOKEN,
    CONF_PHONE,
    CONF_TOKEN,
    CONF_UID,
    CONF_WIFI_SN,
    DOMAIN,
)

CONF_DEVICE_CHOICE = "device_choice"


def _device_value(device: dict[str, Any]) -> str:
    return str(device.get("wifiSN") or device.get("esn") or "")


def _device_label(device: dict[str, Any]) -> str:
    sn = _device_value(device)
    nickname = str(
        device.get("lockNickname") or device.get("nickname") or device.get("deviceName") or ""
    )
    model = str(
        device.get("abbreviation")
        or device.get("model")
        or device.get("productName")
        or ""
    )
    parts = [f"门锁 {sn}"]
    if nickname:
        parts.append(nickname)
    if model:
        parts.append(model)
    return " / ".join(parts)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_OPENID, default=defaults.get(CONF_OPENID, "")): str,
            vol.Required(CONF_PHONE, default=defaults.get(CONF_PHONE, "")): str,
            vol.Required(CONF_OPENID_TOKEN, default=defaults.get(CONF_OPENID_TOKEN, "")): str,
        }
    )


def _reauth_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_OPENID, default=defaults.get(CONF_OPENID, "")): str,
            vol.Required(CONF_PHONE, default=defaults.get(CONF_PHONE, "")): str,
            vol.Required(CONF_OPENID_TOKEN, default=defaults.get(CONF_OPENID_TOKEN, "")): str,
        }
    )


def _device_schema(devices: list[dict[str, Any]]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DEVICE_CHOICE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": _device_value(device), "label": _device_label(device)}
                        for device in devices
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=False,
                )
            )
        }
    )


def _select_device(devices: list[dict[str, Any]], value: str) -> dict[str, Any] | None:
    for device in devices:
        if _device_value(device) == value:
            return device
    return None


def _device_entry_data(
    device: dict[str, Any],
    token: str,
    uid: str,
    openid: str,
    phone: str,
    open_id_token: str,
) -> dict[str, Any]:
    return {
        CONF_TOKEN: token,
        CONF_UID: uid,
        CONF_OPENID: openid,
        CONF_PHONE: phone,
        CONF_OPENID_TOKEN: open_id_token,
        CONF_WIFI_SN: str(device.get("wifiSN") or device.get("esn") or ""),
        CONF_ESN: str(device.get("esn") or device.get("wifiSN") or ""),
        CONF_DEVICE_MODEL: str(device.get("abbreviation") or device.get("model") or ""),
        CONF_NICKNAME: str(
            device.get("lockNickname") or device.get("nickname") or device.get("deviceName") or ""
        ),
        CONF_IS_THING_MODEL: bool(device.get("isThingModel")),
    }


async def _login_and_fetch_devices(
    hass: HomeAssistant, openid: str, phone: str, open_id_token: str
) -> tuple[str, str, list[dict[str, Any]]]:
    """用 openId + 手机号登录，返回 (token, uid, devices)。"""
    api = KaadasApi(async_get_clientsession(hass), "", "")
    info = await api.async_login(openid, phone, open_id_token)
    token = str(info.get("token") or "").strip()
    uid = str(info.get("uid") or "").strip()
    if not token:
        raise KaadasAuthError("登录未返回 token")

    api2 = KaadasApi(async_get_clientsession(hass), token, uid)
    devices = await api2.async_get_bind_devices()
    if not devices:
        raise KaadasApiError("未找到绑定的门锁设备")
    return token, uid, devices


class KaadasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []
        self._pending: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            openid = str(user_input.get(CONF_OPENID) or "").strip()
            phone = str(user_input.get(CONF_PHONE) or "").strip()
            open_id_token = str(user_input.get(CONF_OPENID_TOKEN) or "").strip()
            try:
                token, uid, devices = await _login_and_fetch_devices(
                    self.hass, openid, phone, open_id_token
                )
            except KaadasAuthError:
                errors["base"] = "auth"
            except KaadasApiError:
                errors["base"] = "cannot_connect"
            else:
                self._devices = devices
                self._pending = {
                    CONF_TOKEN: token,
                    CONF_UID: uid,
                    CONF_OPENID: openid,
                    CONF_PHONE: phone,
                    CONF_OPENID_TOKEN: open_id_token,
                }
                return await self.async_step_select_device()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    async def async_step_select_device(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if not self._devices:
            return await self.async_step_user()

        if user_input is not None:
            device = _select_device(
                self._devices, str(user_input.get(CONF_DEVICE_CHOICE) or "")
            )
            if device is None:
                errors[CONF_DEVICE_CHOICE] = "invalid_device"
            else:
                return await self._create_entry(device)

        return self.async_show_form(
            step_id="select_device",
            data_schema=_device_schema(self._devices),
            errors=errors,
            description_placeholders={"count": str(len(self._devices))},
        )

    async def _create_entry(self, device: dict[str, Any]):
        data = _device_entry_data(
            device,
            self._pending.get(CONF_TOKEN, ""),
            self._pending.get(CONF_UID, ""),
            self._pending.get(CONF_OPENID, ""),
            self._pending.get(CONF_PHONE, ""),
            self._pending.get(CONF_OPENID_TOKEN, ""),
        )
        await self.async_set_unique_id(
            data.get(CONF_WIFI_SN) or data.get(CONF_ESN) or ""
        )
        self._abort_if_unique_id_configured(updates=data)
        nickname = data.get(CONF_NICKNAME) or data.get(CONF_WIFI_SN) or "门锁"
        title = f"凯迪仕 {nickname}"
        return self.async_create_entry(title=title, data=data)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        """openId 失效后的重新认证：重新填写 openId / 手机号并更新条目。"""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        if user_input is not None:
            openid = str(user_input.get(CONF_OPENID) or "").strip()
            phone = str(user_input.get(CONF_PHONE) or "").strip()
            open_id_token = str(user_input.get(CONF_OPENID_TOKEN) or "").strip()
            try:
                token, uid, devices = await _login_and_fetch_devices(
                    self.hass, openid, phone, open_id_token
                )
            except KaadasAuthError:
                errors["base"] = "auth"
            except KaadasApiError:
                errors["base"] = "cannot_connect"
            else:
                wifi_sn = str(
                    entry.data.get(CONF_WIFI_SN) or entry.data.get(CONF_ESN) or ""
                )
                device = _select_device(devices, wifi_sn) or devices[0]
                data = _device_entry_data(device, token, uid, openid, phone, open_id_token)
                return self.async_create_entry(title=entry.title, data=data)

        return self.async_show_form(
            step_id="reauth",
            data_schema=_reauth_schema(
                {
                    CONF_OPENID: entry.data.get(CONF_OPENID, ""),
                    CONF_PHONE: entry.data.get(CONF_PHONE, ""),
                    CONF_OPENID_TOKEN: entry.data.get(CONF_OPENID_TOKEN, ""),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return KaadasOptionsFlow(config_entry)


class KaadasOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._devices: list[dict[str, Any]] = []
        self._pending: dict[str, Any] = {}

    def _current(self) -> dict[str, Any]:
        return {
            CONF_OPENID: self._entry.data.get(CONF_OPENID, ""),
            CONF_PHONE: self._entry.data.get(CONF_PHONE, ""),
            CONF_OPENID_TOKEN: self._entry.data.get(CONF_OPENID_TOKEN, ""),
        }

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            openid = str(user_input.get(CONF_OPENID) or "").strip()
            phone = str(user_input.get(CONF_PHONE) or "").strip()
            open_id_token = str(user_input.get(CONF_OPENID_TOKEN) or "").strip()
            try:
                token, uid, devices = await _login_and_fetch_devices(
                    self.hass, openid, phone, open_id_token
                )
            except KaadasAuthError:
                errors["base"] = "auth"
            except KaadasApiError:
                errors["base"] = "cannot_connect"
            else:
                self._devices = devices
                self._pending = {
                    CONF_TOKEN: token,
                    CONF_UID: uid,
                    CONF_OPENID: openid,
                    CONF_PHONE: phone,
                    CONF_OPENID_TOKEN: open_id_token,
                }
                return await self.async_step_select_device()

        return self.async_show_form(
            step_id="init",
            data_schema=_user_schema(self._current()),
            errors=errors,
        )

    async def async_step_select_device(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if not self._devices:
            return await self.async_step_init()

        if user_input is not None:
            device = _select_device(
                self._devices, str(user_input.get(CONF_DEVICE_CHOICE) or "")
            )
            if device is None:
                errors[CONF_DEVICE_CHOICE] = "invalid_device"
            else:
                data = _device_entry_data(
                    device,
                    self._pending.get(CONF_TOKEN, ""),
                    self._pending.get(CONF_UID, ""),
                    self._pending.get(CONF_OPENID, ""),
                    self._pending.get(CONF_PHONE, ""),
                    self._pending.get(CONF_OPENID_TOKEN, ""),
                )
                # 凭证/设备标识必须写进 entry.data（集成只读 entry.data），
                # OptionsFlow 的 async_create_entry 会写进 entry.options，故改用 update_entry。
                self.hass.config_entries.async_update_entry(self._entry, data=data)
                await self.hass.config_entries.async_reload(self._entry.entry_id)
                return self.async_abort(reason="updated")

        return self.async_show_form(
            step_id="select_device",
            data_schema=_device_schema(self._devices),
            errors=errors,
            description_placeholders={"count": str(len(self._devices))},
        )
