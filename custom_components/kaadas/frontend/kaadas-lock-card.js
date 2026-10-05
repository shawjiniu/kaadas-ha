/**
 * 凯迪仕智能门锁 Lovelace 卡片
 *
 * 布局（参考设计图）：
 *   [logo]   设备名称              [状态图标]
 *            设备型号               锁状态
 *               数据更新时间
 *   ┌────────────┐  ┌────────────┐
 *   │  电量显示   │  │ WiFi信号   │
 *   └────────────┘  └────────────┘
 *   消息记录列表
 *   时间  消息
 */

const CARD_VERSION = "0.1.0";
const BRAND_LOGO = "/kaadas/brand/icon.png";

const LOG = (...args) => console.log("%c[kaadas-lock-card]", "color:#3F8CFF", ...args);

/* ---------------------------------- 工具 ---------------------------------- */

const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

function fmtTime(value) {
  if (value === undefined || value === null || value === "") return "—";
  let ts = Number(value);
  if (!Number.isFinite(ts)) return String(value);
  if (ts < 1e12) ts *= 1000; // 秒 -> 毫秒
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(value);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function batteryIcon(level) {
  if (level === null) return "mdi:battery-unknown";
  if (level >= 95) return "mdi:battery";
  if (level >= 80) return "mdi:battery-80";
  if (level >= 60) return "mdi:battery-60";
  if (level >= 40) return "mdi:battery-40";
  if (level >= 20) return "mdi:battery-20";
  return "mdi:battery-alert";
}

function wifiIcon(rssi) {
  if (rssi === null) return "mdi:wifi-off";
  if (rssi >= -60) return "mdi:wifi-strength-4";
  if (rssi >= -70) return "mdi:wifi-strength-3";
  if (rssi >= -80) return "mdi:wifi-strength-2";
  return "mdi:wifi-strength-1";
}

/** 从一条操作记录里尽力提取一句可读描述 */
function recordMessage(record) {
  if (!record || typeof record !== "object") return String(record ?? "");
  const candidates = [
    record.message,
    record.msg,
    record.eventName,
    record.operationName,
    record.typeName,
    record.openTypeName,
    record.unlockTypeName,
    record.userName,
    record.name,
    record.type,
    record.openType,
  ];
  for (const c of candidates) {
    if (c !== undefined && c !== null && String(c).trim() !== "") return String(c).trim();
  }
  const keys = Object.keys(record).filter((k) => k !== "id" && k !== "time");
  if (keys.length) {
    return keys
      .slice(0, 4)
      .map((k) => `${k}=${record[k]}`)
      .join("  ");
  }
  return "—";
}

/* --------------------------------- 卡片本体 -------------------------------- */

class KaadasLockCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._rendered = false;
  }

  static getStubConfig(hass) {
    let entity = "";
    if (hass?.entities) {
      for (const [eid, e] of Object.entries(hass.entities)) {
        if (eid.startsWith("lock.") && e.platform === "kaadas") {
          entity = eid;
          break;
        }
      }
    }
    return { entity };
  }

  static getConfigElement() {
    return document.createElement("kaadas-lock-card-editor");
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("请指定 entity（凯迪仕门锁实体，例如 lock.kaidas_xxx）");
    }
    this._config = { show_records: true, records_limit: 10, ...config };
    this._rendered = false;
  }

  set hass(hass) {
    this._hass = hass;
    const sig = this._signature();
    if (sig === this._sig) return; // 相关状态未变，跳过重绘
    this._sig = sig;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  /** 只关心这几个实体的状态/属性变化 */
  _signature() {
    const r = this._resolve();
    const ids = [
      this._config.entity,
      r.byKey.lock_status,
      r.byKey.battery,
      r.byKey.wifi_rssi,
      r.byKey.last_update_time,
      r.byKey.last_operation_time,
    ];
    return ids
      .map((id) => {
        const s = id ? this._hass?.states?.[id] : undefined;
        return s ? `${s.state}|${s.last_updated}` : "-";
      })
      .join("~");
  }

  /* ------------------------------ 数据解析 ------------------------------ */

  _resolve() {
    const hass = this._hass;
    const cfg = this._config;
    const out = {
      byKey: {},
      device: null,
      lockEntity: null,
      name: cfg.name,
      model: cfg.model,
    };
    if (!hass) return out;

    const entityId = cfg.entity;
    const reg = hass.entities?.[entityId];
    const deviceId = reg?.device_id;
    if (deviceId) out.device = hass.devices?.[deviceId] || null;

    if (hass.entities) {
      for (const [eid, e] of Object.entries(hass.entities)) {
        if (deviceId && e.device_id !== deviceId) continue;
        if (e.translation_key) out.byKey[e.translation_key] = eid;
        if (eid.startsWith("lock.") && (!out.lockEntity || eid === entityId)) {
          out.lockEntity = eid;
        }
      }
    }
    if (entityId.startsWith("lock.")) out.lockEntity = entityId;

    out.lockEntity = cfg.lock_entity || out.lockEntity;
    if (cfg.status_entity) out.byKey.lock_status = cfg.status_entity;
    if (cfg.battery_entity) out.byKey.battery = cfg.battery_entity;
    if (cfg.wifi_entity) out.byKey.wifi_rssi = cfg.wifi_entity;
    if (cfg.records_entity) out.byKey.last_operation_time = cfg.records_entity;

    out.name = out.name || out.device?.name_by_user || out.device?.name || "凯迪仕智能门锁";
    out.model = out.model || out.device?.model || "";
    return out;
  }

  _state(entityId) {
    return entityId ? this._hass?.states?.[entityId] : undefined;
  }

  /* -------------------------------- 渲染 -------------------------------- */

  _render() {
    if (!this._hass) return;
    const r = this._resolve();
    const hass = this._hass;

    const lockState = this._state(r.lockEntity);
    const statusState = this._state(r.byKey.lock_status);
    const batteryState = this._state(r.byKey.battery);
    const wifiState = this._state(r.byKey.wifi_rssi);
    const updateState = this._state(r.byKey.last_update_time);
    const recordsState = this._state(r.byKey.last_operation_time);

    const unlocked = lockState?.state === "unlocked";
    const lockText =
      statusState?.state && statusState.state !== "unknown"
        ? statusState.state
        : lockState?.state === "locked"
          ? "关锁"
          : lockState?.state === "unlocked"
            ? "开锁"
            : lockState?.state === "unavailable"
              ? "不可用"
              : "未知";
    const lockIcon = unlocked ? "mdi:lock-open-variant" : "mdi:lock";
    const lockColor = unlocked ? "var(--warning-color, #ffa726)" : "var(--success-color, #4caf50)";

    const battery = num(batteryState?.state);
    const rssi = num(wifiState?.state);

    const updateTime = updateState?.state && updateState.state !== "unknown"
      ? updateState.state
      : "—";

    const records = Array.isArray(recordsState?.attributes?.["操作记录"])
      ? recordsState.attributes["操作记录"]
      : [];

    const html = `
      <ha-card>
        <div class="wrap">
          <div class="header">
            <div class="logo">
              <img src="${BRAND_LOGO}" alt="Kaadas" onerror="this.style.display='none'; this.parentNode.classList.add('logo-fallback')" />
            </div>
            <div class="title">
              <div class="name">${this._esc(r.name)}</div>
              <div class="model">${this._esc(r.model || "—")}</div>
            </div>
            <div class="status">
              <div class="status-icon" style="color:${lockColor}">
                <ha-icon icon="${lockIcon}"></ha-icon>
              </div>
              <div class="status-text">${this._esc(lockText)}</div>
            </div>
          </div>

          <div class="updated">数据更新：${this._esc(updateTime)}</div>

          <div class="stats">
            <div class="stat">
              <ha-icon icon="${batteryIcon(battery)}"></ha-icon>
              <div class="stat-body">
                <div class="stat-label">电量</div>
                <div class="stat-value">${battery === null ? "—" : battery + " %"}</div>
              </div>
            </div>
            <div class="stat">
              <ha-icon icon="${wifiIcon(rssi)}"></ha-icon>
              <div class="stat-body">
                <div class="stat-label">WiFi 信号</div>
                <div class="stat-value">${rssi === null ? "—" : rssi + " dBm"}</div>
              </div>
            </div>
          </div>

          ${
            this._config.show_records
              ? `<div class="records">
                   <div class="records-title">消息记录</div>
                   ${
                     records.length
                       ? `<div class="records-list">${records
                           .slice(0, this._config.records_limit)
                           .map(
                             (rec) => `
                         <div class="record">
                           <span class="record-time">${this._esc(fmtTime(rec?.time))}</span>
                           <span class="record-msg">${this._esc(recordMessage(rec))}</span>
                         </div>`
                           )
                           .join("")}</div>`
                       : `<div class="records-empty">暂无记录</div>`
                   }
                 </div>`
              : ""
          }
        </div>
      </ha-card>
    `;

    if (!this._rendered) {
      this.shadowRoot.innerHTML = `<style>${KaadasLockCard.styles}</style>${html}`;
      this._rendered = true;
    } else {
      // 仅更新内容，避免整卡重绘造成闪烁
      const card = this.shadowRoot.querySelector("ha-card");
      if (card) card.outerHTML = html.trim();
      else this.shadowRoot.innerHTML = `<style>${KaadasLockCard.styles}</style>${html}`;
    }
  }

  _esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  static get styles() {
    return `
      :host { display: block; }
      ha-card { overflow: hidden; }
      .wrap { padding: 16px; display: flex; flex-direction: column; gap: 12px; }

      .header { display: flex; align-items: center; gap: 14px; }
      .logo {
        width: 58px; height: 58px; border-radius: 50%; flex: 0 0 auto;
        display: flex; align-items: center; justify-content: center;
        background: var(--secondary-background-color, #f2f4f7);
      }
      .logo img { width: 40px; height: 40px; object-fit: contain; }
      .logo.logo-fallback::after {
        content: "\\f023"; font-family: "Material Design Icons";
        font-size: 26px; color: #3F8CFF;
      }
      .title { flex: 1 1 auto; min-width: 0; }
      .name {
        font-size: 1.15rem; font-weight: 600; color: var(--primary-text-color);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .model {
        font-size: 0.85rem; color: var(--secondary-text-color); margin-top: 2px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }

      .status { display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 0 0 auto; }
      .status-icon {
        width: 46px; height: 46px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        border: 2px solid currentColor;
      }
      .status-icon ha-icon { --mdc-icon-size: 24px; }
      .status-text { font-size: 0.82rem; color: var(--secondary-text-color); }

      .updated {
        text-align: center; font-size: 0.8rem; color: var(--secondary-text-color);
        border-bottom: 1px solid var(--divider-color, #e0e0e0); padding-bottom: 10px;
      }

      .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .stat {
        display: flex; align-items: center; gap: 10px; padding: 12px;
        border-radius: 12px; background: var(--secondary-background-color, #f2f4f7);
      }
      .stat ha-icon { color: #3F8CFF; --mdc-icon-size: 26px; flex: 0 0 auto; }
      .stat-body { min-width: 0; }
      .stat-label { font-size: 0.78rem; color: var(--secondary-text-color); }
      .stat-value {
        font-size: 1.05rem; font-weight: 600; color: var(--primary-text-color);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }

      .records { display: flex; flex-direction: column; gap: 6px; }
      .records-title {
        font-size: 0.85rem; font-weight: 600; color: var(--primary-text-color);
      }
      .records-list { display: flex; flex-direction: column; }
      .record {
        display: flex; gap: 10px; padding: 7px 0; font-size: 0.82rem;
        border-bottom: 1px dashed var(--divider-color, #e0e0e0);
      }
      .record:last-child { border-bottom: none; }
      .record-time {
        flex: 0 0 auto; color: var(--secondary-text-color);
        font-variant-numeric: tabular-nums;
      }
      .record-msg {
        flex: 1 1 auto; color: var(--primary-text-color);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }
      .records-empty {
        font-size: 0.82rem; color: var(--secondary-text-color); padding: 6px 0;
      }

      @media (max-width: 380px) {
        .stats { grid-template-columns: 1fr; }
      }
    `;
  }
}

customElements.define("kaadas-lock-card", KaadasLockCard);

/* ------------------------------ 可视化编辑器 ------------------------------ */

class KaadasLockCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    if (!this._built) {
      this.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:12px;padding:8px 0">
          <ha-entity-picker id="entity" label="门锁实体 (lock.*)" allow-custom-entity></ha-entity-picker>
          <ha-textfield id="name" label="设备名称（可选）"></ha-textfield>
          <ha-textfield id="model" label="设备型号（可选）"></ha-textfield>
        </div>`;
      this._built = true;
      const fire = () => {
        const entity = this.querySelector("#entity").value;
        const name = this.querySelector("#name").value;
        const model = this.querySelector("#model").value;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { ...this._config, entity, name, model } },
            bubbles: true,
            composed: true,
          })
        );
      };
      this.querySelector("#entity").addEventListener("value-changed", fire);
      this.querySelector("#name").addEventListener("change", fire);
      this.querySelector("#model").addEventListener("change", fire);
    }
    const e = this.querySelector("#entity");
    e.hass = this._hass;
    e.value = this._config?.entity || "";
    this.querySelector("#name").value = this._config?.name || "";
    this.querySelector("#model").value = this._config?.model || "";
  }
}

customElements.define("kaadas-lock-card-editor", KaadasLockCardEditor);

/* ------------------------------- 注册到卡片库 ------------------------------ */

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "kaadas-lock-card")) {
  window.customCards.push({
    type: "kaadas-lock-card",
    name: "凯迪仕门锁卡片",
    description: "凯迪仕智能门锁状态卡片（设备名/型号、锁状态、电量、WiFi、消息记录）",
    preview: true,
    documentationURL: "https://github.com/custom-components/kaadas",
  });
}

LOG(`v${CARD_VERSION} 已加载`);
