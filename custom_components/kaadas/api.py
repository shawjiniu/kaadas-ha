from __future__ import annotations

from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import BASE_URL, USER_AGENT


class KaadasApiError(Exception):
    """凯迪仕接口返回错误。"""


class KaadasAuthError(KaadasApiError):
    """登录/凭证已失效（code 444/455/456/448 等）。"""


class KaadasApi:
    """凯迪仕小程序云端接口客户端。

    凭证来自小程序本地存储：
      - token -> app_user_token（请求头 ``token``）
      - uid   -> app_user_uid
    """

    def __init__(self, session: ClientSession, token: str, uid: str) -> None:
        self._session = session
        self.token = token.strip()
        self.uid = uid.strip()

    def _headers(self, include_token: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "reqSource": "miniProgram",
            "lang": "zh_CN",
            "clientOSVersion": "iOS 18.5",
        }
        if include_token:
            headers["token"] = self.token
        return headers

    def _check(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise KaadasApiError("接口返回格式异常")
        code = str(payload.get("code"))
        if code == "200":
            return
        message = str(payload.get("msg") or payload.get("message") or "接口返回失败")
        if code in {"444", "455", "456", "448", "401", "403"}:
            raise KaadasAuthError(message)
        raise KaadasApiError(f"{message}（code={code}）")

    async def _request(
        self,
        method: str,
        url: str,
        data: Any = None,
        headers: dict[str, str] | None = None,
        include_token: bool = True,
    ) -> Any:
        """发送请求并返回响应包里的 ``data`` 字段。"""
        h = self._headers(include_token=include_token)
        if headers:
            h.update(headers)
        try:
            if method == "get":
                async with self._session.get(url, params=data, headers=h, timeout=ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
            else:
                async with self._session.post(url, json=data, headers=h, timeout=ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
        except ClientError as err:
            raise KaadasApiError(str(err)) from err
        except ValueError as err:
            raise KaadasApiError("接口返回无法解析") from err

        self._check(payload)
        if isinstance(payload, dict):
            return payload.get("data")
        return None

    async def async_login(
        self, openid: str, phone: str, open_id_token: str = ""
    ) -> dict[str, Any]:
        """用 openId + 手机号登录，换取 token/uid（可跳过微信 OAuth，用于自动续期）。"""
        tel = phone.strip()
        if tel and not tel.startswith("86"):
            tel = "86" + tel
        headers: dict[str, str] = {
            "terminalName": "iPhone",
            "terminalModel": "iPhone",
        }
        if open_id_token.strip():
            headers["openIdToken"] = open_id_token.strip()
        data = await self._request(
            "post",
            f"{BASE_URL}/user/login",
            {"tel": tel, "openId": openid.strip()},
            headers=headers,
            include_token=False,
        )
        return data if isinstance(data, dict) else {}

    async def async_get_bind_devices(self) -> list[dict[str, Any]]:
        """获取账号下所有绑定设备（把 productInfoList 合并进 wifiList）。"""
        data = await self._request(
            "post",
            f"{BASE_URL}/wifi/user/getAllBindDevice",
            {"uid": self.uid},
            headers={"ver": "20230412"},
        )
        data = data or {}
        wifi_list = data.get("wifiList") or []
        product_list = data.get("productInfoList") or []
        product_by_esn = {
            str(item.get("esn") or ""): item
            for item in product_list
            if isinstance(item, dict)
        }
        result: list[dict[str, Any]] = []
        for device in wifi_list:
            if not isinstance(device, dict):
                continue
            merged = dict(device)
            esn = str(device.get("wifiSN") or device.get("esn") or "")
            product = product_by_esn.get(esn)
            if product:
                for key, value in product.items():
                    if value not in (None, "", [], {}):
                        merged.setdefault(key, value)
            result.append(merged)
        return result

    def _thing_body(self, did: str, properties: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "msgId": uuid4().hex,
            "source": f"wx:{self.uid}",
            "did": did,
            "body": {"properties": properties},
        }

    async def async_get_properties(self, did: str, properties: list[dict[str, Any]]) -> Any:
        """读取物模型属性。properties 形如 ``[{"name": "p_lock_status", "service": "lock_service"}]``。"""
        return await self._request(
            "post",
            f"{BASE_URL}/iot/device/properties/find",
            self._thing_body(did, properties),
        )

    async def async_set_properties(self, did: str, properties: list[dict[str, Any]]) -> Any:
        """下发物模型属性。properties 需额外带 ``value``。"""
        return await self._request(
            "post",
            f"{BASE_URL}/iot/device/properties/set",
            self._thing_body(did, properties),
        )

    async def async_get_operation_records(
        self, wifi_sn: str, page: int = 1, max_id: str = ""
    ) -> Any:
        """分页获取操作记录（开锁/上锁等）。"""
        return await self._request(
            "post",
            f"{BASE_URL}/record/operation/list",
            {"wifiSN": wifi_sn, "page": page, "maxId": max_id},
            headers={"ver": "1"},
        )

    async def async_get_seven_day_statistics(self, wifi_sn: str) -> Any:
        """近 7 天开锁/门铃/报警统计。"""
        return await self._request(
            "post",
            f"{BASE_URL}/wifi/statistics/sevenDays",
            {"uid": self.uid, "wifiSN": wifi_sn},
        )
