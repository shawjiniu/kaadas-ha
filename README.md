# 凯迪仕智能门锁 (Kaadas) Home Assistant 集成

基于凯迪仕微信小程序云端接口的 Home Assistant 集成（**当前为骨架版本**）。

## 功能

- **锁**：门锁状态（开锁 / 关锁），远程开锁暂未实现（需签名）
- **在线状态**：门锁 WiFi 在线 / 离线
- **电量 / WiFi 信号 / 固件版本 / 物模型版本 / 数据更新时间**
- 布防模式（binary_sensor）
- **云端 WebSocket 实时推送**：开关锁 / 上下线 / 门铃等事件即时刷新（替代定时轮询）
- **token 自动续期**：用 openId + 手机号自动重登录换新 token（见下文）
- **凭证失效自动重新认证（reauth）**：openId 失效时自动弹出重新认证表单

## 安装

1. 将 `custom_components/kaadas/` 复制到 Home Assistant 的 `config/custom_components/` 目录。
2. 重启 Home Assistant。
3. 在「设置 → 设备与服务 → 添加集成」中搜索「凯迪仕智能门锁」。

## 仪表盘卡片

集成自带一个 Lovelace 卡片 `kaadas-lock-card`，安装后**自动注册**（无需手动添加资源）。布局：

```
 [logo]   设备名称              [状态图标]
          设备型号               锁状态
             数据更新时间
 ┌────────────┐  ┌────────────┐
 │  电量显示   │  │ WiFi 信号  │
 └────────────┘  └────────────┘
 消息记录列表（时间  消息）
```

在仪表盘添加卡片时搜索「凯迪仕门锁卡片」，或直接写 YAML：

```yaml
type: custom:kaadas-lock-card
entity: lock.kaidas_xxx      # 必填：门锁实体
# 以下均可选（默认按设备自动发现）
name: 大门门锁
model: Q7 FVP
battery_entity: sensor.kaidas_xxx_battery
wifi_entity: sensor.kaidas_xxx_wifi_rssi
status_entity: sensor.kaidas_xxx_lock_status
records_entity: sensor.kaidas_xxx_last_operation_time
show_records: true
records_limit: 10
```

> 若未自动加载，可在「设置 → 仪表盘 → 资源」手动添加 URL `/kaadas/frontend/kaadas-lock-card.js`（JavaScript 模块）。

## 抓取凭证

集成只需填写 3 个值（不再需要手动抓取 token），凭证在微信本地存储中，可通过微信开发者工具 / 抓包获取：

- `openid`：存储键 `openid`（必填）
- `phone`：你的手机号，11 位（必填）
- `openIdToken`：存储键 `login_token`（必填，作为 `openIdToken` 请求头）

集成会自动调用 `/user/login` 登录并换取 token/uid，之后自动续期。

## 说明与已知限制

1. 服务端：HTTP `https://miniapp-cn.kaadas.com`；WebSocket `wss://miniws-cn.kaadas.com/ws/api/`
2. 响应 `code == 200` 为成功；`444/455/456/448` 表示登录过期。
3. 设备分「物模型」（`isThingModel=true`）与旧协议两类；旧协议设备直接从 `wifiList` 字段读取状态，物模型设备走 `/iot/device/properties/find`。
4. **远程开锁 / 上锁尚未实现**（远程开锁需要 `p_open_lock_uid` + `p_open_lock_sign` 签名）。
5. 物模型属性返回结构需实际抓包确认，`coordinator._find_key` 做了多结构兼容。

## 实时推送与更新机制

集成通过云端 WebSocket（`wss://miniws-cn.kaadas.com/ws/api/`，头 `Authorization: Bearer <token>`）订阅门锁事件，收到开关锁、上下线、门铃等推送时即时刷新状态，**不再定时轮询**（`iot_class` 为 `cloud_push`）。断线自动指数退避重连，重连后立即同步一次；`401` 时自动续期 token 后重连。

## 关于 token 自动续期

实测确认：`POST /user/login` 用已存的 openId + 手机号（+ `openIdToken` 头）即可**跳过微信 OAuth 直接重登录换新 token**。因此本集成实现的是真正的自动续期（与 xinaogas 的换票接口等价）：

- token 只在 `entry.data` 存一份，调度元数据在 `Store`
- 固定 7 天 TTL，提前 2 小时进入续期窗口
- 续期动作 = 用 openId + 手机号 + openIdToken 重登录 `/user/login`，成功后写回新 token/uid
- 数据请求遇到鉴权失败时**立即续期并重试一次**
- 网络错误指数退避重试；openId / openIdToken 本身失效（`448` 等）时才触发 reauth
- `asyncio.Lock` 防并发重复续期

> 注意：`openIdToken`（login_token）由微信 OAuth 签发，Home Assistant 无法自行刷新；一旦它失效，仍需用户重新抓取并触发 reauth。自动续期在此窗口内持续有效。

> 独立调试脚本见 `test_login.py`，可单独验证登录/续期是否正常。

## 参考

数据访问分析见仓库内 `Kaadas_门锁小程序数据访问分析.md`（位于上层工作目录）。
