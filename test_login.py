#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凯迪仕 token 自动续期可行性实测脚本。

结论验证：凯迪仕小程序没有「用旧 token 换新 token」的换票接口，凭证链底部是
微信 OAuth。本脚本实测：**用已存的 openId + 手机号直接调用 /user/login**，
能否跳过微信 OAuth 重新登录换取新 token。若可行，则 HA 集成可据此实现真正的
token 自动续期；若返回 448（openId 失效），则必须重新走微信 OAuth，无法自动续期。

用法：
    python test_login.py --openid <openid> --phone <手机号> [--open-id-token <login_token>] \
        [--token <当前token>] [--uid <当前uid>] [--env release]

所需凭证来自小程序本地存储（微信开发者工具 / 抓包）：
    openid        -> 存储键 openid
    openIdToken   -> 存储键 login_token（可选，作为 openIdToken 请求头）
    phone         -> 你的手机号（11 位，不加国家码）
    token / uid   -> 存储键 app_user_token / app_user_uid（可选，用于对比新旧 token）
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE_URLS = {
    "release": "https://miniapp-cn.kaadas.com",
    "test": "https://iot-test.juziwulian.com",
}
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 MicroMessenger MiniProgram"
)


def request(
    base: str,
    method: str,
    path: str,
    data: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, object]:
    url = base + path
    h = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "reqSource": "miniProgram",
        "lang": "zh_CN",
        "clientOSVersion": "iOS 18.5",
    }
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(payload)
            except json.JSONDecodeError:
                return resp.status, {"_raw": payload}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", "replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"_raw": raw}
    except urllib.error.URLError as err:
        return 0, {"_error": str(err.reason)}


def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if phone.startswith("86") and len(phone) == 13:
        return phone
    return "86" + phone


def print_json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="凯迪仕 token 续期可行性实测")
    parser.add_argument("--openid", required=True, help="小程序存储键 openid")
    parser.add_argument("--phone", required=True, help="手机号（11 位，不加国家码）")
    parser.add_argument("--open-id-token", default="", help="小程序存储键 login_token（可选）")
    parser.add_argument("--token", default="", help="当前 app_user_token（可选，用于对比）")
    parser.add_argument("--uid", default="", help="当前 app_user_uid（可选，用于验证）")
    parser.add_argument("--env", default="release", choices=list(BASE_URLS))
    args = parser.parse_args()

    base = BASE_URLS[args.env]
    tel = normalize_phone(args.phone)
    open_id_token = args.open_id_token.strip()

    login_headers: dict = {
        "terminalName": "iPhone",
        "terminalModel": "iPhone",
    }
    if open_id_token:
        login_headers["openIdToken"] = open_id_token

    print("=" * 64)
    print(f"环境: {args.env} ({base})")
    print(f"手机号: {args.phone} -> tel={tel}")
    print(f"openId: {args.openid}")
    print(f"openIdToken 头: {'有' if open_id_token else '无'}")
    print("=" * 64)

    print("\n[测试 1] POST /user/login 用已存 openId 重新登录")
    status, resp = request(
        base,
        "POST",
        "/user/login",
        data={"tel": tel, "openId": args.openid},
        headers=login_headers,
    )
    print(f"HTTP {status}")
    print_json(resp)

    if not isinstance(resp, dict):
        print("\n结果: 响应不是 JSON，无法判断。")
        return 2

    code = str(resp.get("code"))
    data = resp.get("data") or {}
    new_token = str(data.get("token") or "").strip()
    new_uid = str(data.get("uid") or args.uid or "").strip()

    if code == "200" and new_token:
        print("\n✅ 重新登录成功，拿到新 token —— 说明可跳过微信 OAuth 自动续期！")
        if args.token and new_token != args.token:
            print(f"   🔄 token 已更新（旧:{args.token[:16]}… 新:{new_token[:16]}…）")
        elif args.token:
            print("   ⚠️ 新旧 token 相同（服务端可能复用会话）")
        print(f"   uid: {new_uid or '(未返回)'}")

        print("\n[测试 2] POST /wifi/user/getAllBindDevice 用新 token 验证有效性")
        verify_uid = new_uid or args.uid
        status2, resp2 = request(
            base,
            "POST",
            "/wifi/user/getAllBindDevice",
            data={"uid": verify_uid},
            headers={"token": new_token, "ver": "20230412"},
        )
        print(f"HTTP {status2}")
        print_json(resp2)
        if isinstance(resp2, dict) and str(resp2.get("code")) == "200":
            wifi = (resp2.get("data") or {}).get("wifiList") or []
            print(f"\n✅ 新 token 有效，账号下绑定 {len(wifi)} 个门锁")
            for dev in wifi:
                if isinstance(dev, dict):
                    print(
                        f"   - {dev.get('wifiSN') or dev.get('esn')} "
                        f"{dev.get('nickname') or dev.get('deviceName') or ''} "
                        f"isThingModel={dev.get('isThingModel')}"
                    )
            return 0
        print("\n⚠️ 新 token 拉设备列表失败，请核对 uid")
        return 1

    if code == "448":
        print("\n❌ code=448：openId 已失效，必须重新走微信 OAuth，HA 无法自动续期。")
        return 3

    print(f"\n❌ 登录失败：{resp.get('msg') or resp.get('message') or resp}")
    return 4


if __name__ == "__main__":
    sys.exit(main())
