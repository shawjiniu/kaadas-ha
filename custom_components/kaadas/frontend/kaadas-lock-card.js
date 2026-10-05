/**
 * 凯迪仕智能门锁 Lovelace 卡片
 *
 * 布局：
 *   [logo] 设备名称 / 设备型号            （标题栏，缩小）
 *   ┌───────────────┐ ┌───────────────┐
 *   │   锁状态       │ │   电量(横向条) │
 *   └───────────────┘ └───────────────┘
 *   [布防模式][逗留检测][反锁/隐私][在线状态]   （可配置隐藏）
 *   消息记录（滚动，可见 5 条，内容更多）       （可配置隐藏）
 *   数据更新时间（最底端）
 */

const CARD_VERSION = "0.1.0";
const BRAND_LOGO = "/kaadas/brand/icon.png";

const LOG = (...args) => console.log("%c[kaadas-lock-card]", "color:#3F8CFF", ...args);

/* ---------------------------------- 工具 ---------------------------------- */

const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

function toBool(v) {
  if (v === true || v === 1 || v === "1" || v === "on" || v === "open" || v === "开启") return true;
  if (v === false || v === 0 || v === "0" || v === "off" || v === "close" || v === "关闭") return false;
  return null;
}

function fmtTime(value) {
  if (value === undefined || value === null || value === "") return "—";
  let ts = Number(value);
  if (!Number.isFinite(ts)) return String(value);
  if (ts < 1e12) ts *= 1000;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(value);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/* ------------------------------- 记录字段枚举 ------------------------------ */

const PWD_TYPE = {
  0: "密码", 1: "密码", 2: "指纹", 3: "卡片", 4: "人脸",
  5: "时效密码", 6: "周期密码", 12: "掌静脉", 19: "门磁",
};
const OPERATE_TYPE = {
  1: "开锁成功", 2: "门已上锁", 3: "密码", 4: "密码", 5: "修改管理员密码",
  6: "自动模式", 7: "手动模式", 8: "常用模式切换", 9: "安全模式切换",
  10: "反锁模式", 11: "布防模式", 12: "修改密码昵称", 13: "添加分享用户",
  14: "删除分享用户", 15: "修改管理", 16: "添加管理员", 17: "开启节能模式",
  18: "关闭节能模式", 19: "门锁已恢复出厂设置", 20: "室内反锁已开启",
  21: "室内反锁已关闭",
};

function getField(record, ...names) {
  for (const n of names) {
    if (record && record[n] !== undefined && record[n] !== null && record[n] !== "") {
      return record[n];
    }
  }
  return undefined;
}

function formatPwdNum(pwdNum) {
  const map = {
    100: "使用机械方式开锁成功", 101: "远程开锁成功", 102: "室内open键开锁成功",
    103: "APP开锁成功", 104: "BLE自动开锁成功", 106: "室内感应把手开锁成功",
    250: "使用一次性密码开锁成功", 252: "使用一次性密码开锁", 253: "访客密码开锁成功",
    254: "管理员开锁成功", 255: "管理员开锁成功",
  };
  if (map[pwdNum] !== undefined) return map[pwdNum];
  const n = Number(pwdNum);
  if (Number.isFinite(n) && n > 0) return "编号" + String(n).padStart(2, "0");
  return "";
}

function recordMessage(record) {
  if (!record || typeof record !== "object") return String(record ?? "—");
  const operator = String(getField(record, "userNickname", "userName", "name", "user") ?? "").trim();
  const type = Number(getField(record, "type"));
  const pwdType = Number(getField(record, "pwdType", "keyType", "functionId"));
  const pwdDetailType = Number(getField(record, "pwdDetailType"));
  const pwdNum = getField(record, "pwdNum", "keyNum", "keyId", "pwdId");
  const pwdNickname = String(getField(record, "pwdNickname", "keyName", "pwdName") ?? "").trim();

  const pwdTypeText = Number.isFinite(pwdType) && PWD_TYPE[pwdType] ? PWD_TYPE[pwdType] : "";
  const pwdDetailText = Number.isFinite(pwdDetailType) && PWD_TYPE[pwdDetailType] ? PWD_TYPE[pwdDetailType] : "";
  const pwdNumText = formatPwdNum(pwdNum);
  const isNumberedKey = pwdNumText.startsWith("编号");

  let content = "";
  if (type === 1) {
    if (pwdDetailText) {
      content = `使用${pwdDetailText}开锁成功`;
    } else if (isNumberedKey && Number(pwdNum) === 0 && (pwdType === 1 || pwdType === 2)) {
      content = `使用管理员${pwdTypeText}开锁成功`;
    } else if (isNumberedKey && pwdTypeText) {
      content = `使用${pwdTypeText}${pwdNickname || pwdNumText}开锁成功`;
    } else if (pwdNumText) {
      content = pwdNumText;
    } else if (pwdTypeText) {
      content = `使用${pwdTypeText}开锁成功`;
    } else {
      content = "开锁成功";
    }
  } else if (type === 2) {
    content = "门已上锁";
  } else if (type === 3) {
    content = `添加${pwdNickname || `“${pwdTypeText}${pwdNumText}”`}`;
  } else if (type === 4) {
    content = `删除${pwdNickname || pwdNumText}的${pwdTypeText}`;
  } else if (Number.isFinite(type) && OPERATE_TYPE[type]) {
    content = OPERATE_TYPE[type];
  } else {
    const keys = Object.keys(record).filter((k) => k !== "id" && k !== "time");
    content = keys.slice(0, 4).map((k) => `${k}=${record[k]}`).join("  ") || "—";
  }
  return operator ? `${operator} ${content}` : content;
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
    this._config = {
      show_chips: true,
      show_records: true,
      show_update_time: true,
      records_limit: 20,
      ...config,
    };
    this._rendered = false;
  }

  set hass(hass) {
    this._hass = hass;
    const sig = this._signature();
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  _signature() {
    const r = this._resolve();
    const ids = [
      this._config.entity,
      r.byKey.lock_status,
      r.byKey.battery,
      r.byKey.last_update_time,
      r.byKey.last_operation_time,
      r.byKey.defense_mode,
      r.byKey.linger_detection,
      r.byKey.locked_inside_status,
      r.byKey.connectivity,
    ];
    return ids
      .map((id) => {
        const s = id ? this._hass?.states?.[id] : undefined;
        return s ? `${s.state}|${s.last_updated}` : "-";
      })
      .join("~");
  }

  _resolve() {
    const hass = this._hass;
    const cfg = this._config;
    const out = { byKey: {}, device: null, lockEntity: null, name: cfg.name, model: cfg.model };
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
    if (cfg.records_entity) out.byKey.last_operation_time = cfg.records_entity;
    if (cfg.defense_entity) out.byKey.defense_mode = cfg.defense_entity;
    if (cfg.linger_entity) out.byKey.linger_detection = cfg.linger_entity;
    if (cfg.inside_entity) out.byKey.locked_inside_status = cfg.inside_entity;
    if (cfg.connectivity_entity) out.byKey.connectivity = cfg.connectivity_entity;

    out.name = out.name || out.device?.name_by_user || out.device?.name || "凯迪仕智能门锁";
    out.model = out.model || out.device?.model || "";
    return out;
  }

  _state(entityId) {
    return entityId ? this._hass?.states?.[entityId] : undefined;
  }

  _render() {
    if (!this._hass) return;
    const r = this._resolve();
    const cfg = this._config;

    const lockState = this._state(r.lockEntity);
    const statusState = this._state(r.byKey.lock_status);
    const batteryState = this._state(r.byKey.battery);
    const updateState = this._state(r.byKey.last_update_time);
    const recordsState = this._state(r.byKey.last_operation_time);
    const defenseState = this._state(r.byKey.defense_mode);
    const lingerState = this._state(r.byKey.linger_detection);
    const insideState = this._state(r.byKey.locked_inside_status);
    const connState = this._state(r.byKey.connectivity);

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
    const batteryPct = battery === null ? 0 : Math.max(0, Math.min(100, battery));

    const defenseOn = toBool(defenseState?.state);
    const insideOn = toBool(insideState?.state);
    const online = connState?.state === "on";
    const linger = num(lingerState?.state);
    const lingerText = linger === null ? "—" : linger === 0 ? "关闭" : linger + "秒";
    const chips = [
      { label: "布防模式", icon: "mdi:shield-lock", on: defenseOn === true, text: defenseOn === null ? "—" : defenseOn ? "开" : "关" },
      { label: "逗留检测", icon: "mdi:motion-sensor", on: linger !== null && linger > 0, text: lingerText },
      { label: "反锁/隐私", icon: "mdi:lock", on: insideOn === true, text: insideOn === null ? "—" : insideOn ? "开" : "关" },
      { label: "在线状态", icon: "mdi:wifi", on: online, text: online ? "在线" : "离线" },
    ];

    const updateTime = updateState?.state && updateState.state !== "unknown" ? updateState.state : "—";
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
          </div>

          <div class="stats">
            <div class="stat lock-stat">
              <div class="lock-ring" style="color:${lockColor}">
                <ha-icon icon="${lockIcon}"></ha-icon>
              </div>
              <div class="stat-body">
                <div class="stat-label">锁状态</div>
                <div class="stat-value">${this._esc(lockText)}</div>
              </div>
            </div>
            <div class="stat battery-stat">
              <div class="stat-head">
                <span class="stat-label">电量</span>
                <span class="stat-value">${battery === null ? "—" : battery + "%"}</span>
              </div>
              <div class="progress">
                <div class="progress-fill" style="width:${batteryPct}%"></div>
              </div>
            </div>
          </div>

          ${
            cfg.show_chips
              ? `<div class="chips">
                   ${chips
                     .map(
                       (it) => `
                       <div class="chip ${it.on ? "on" : ""}">
                         <ha-icon icon="${it.icon}"></ha-icon>
                         <div class="chip-body">
                           <span class="chip-label">${it.label}</span>
                           <span class="chip-value">${this._esc(it.text)}</span>
                         </div>
                       </div>`
                     )
                     .join("")}
                 </div>`
              : ""
          }

          ${
            cfg.show_records
              ? `<div class="records">
                   <div class="records-title">消息记录</div>
                   <div class="records-list">
                     ${
                       records.length
                         ? records
                             .slice(0, cfg.records_limit)
                             .map(
                               (rec) => `
                         <div class="record">
                           <span class="record-time">${this._esc(fmtTime(rec?.time))}</span>
                           <span class="record-msg">${this._esc(recordMessage(rec))}</span>
                         </div>`
                             )
                             .join("")
                         : `<div class="records-empty">暂无记录</div>`
                     }
                   </div>
                 </div>`
              : ""
          }

          ${
            cfg.show_update_time !== false
              ? `<div class="updated">数据更新时间：${this._esc(updateTime)}</div>`
              : ""
          }
        </div>
      </ha-card>
    `;

    if (!this._rendered) {
      this.shadowRoot.innerHTML = `<style>${KaadasLockCard.styles}</style>${html}`;
      this._rendered = true;
    } else {
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
      .wrap { padding: 14px; display: flex; flex-direction: column; gap: 12px; }

      /* 标题栏（缩小） */
      .header { display: flex; align-items: center; gap: 10px; }
      .logo {
        width: 40px; height: 40px; border-radius: 50%; flex: 0 0 auto;
        display: flex; align-items: center; justify-content: center;
        background: var(--secondary-background-color, #f2f4f7);
      }
      .logo img { width: 28px; height: 28px; object-fit: contain; }
      .logo.logo-fallback::after {
        content: "\\f023"; font-family: "Material Design Icons";
        font-size: 20px; color: #3F8CFF;
      }
      .title { flex: 1 1 auto; min-width: 0; }
      .name {
        font-size: 1rem; font-weight: 600; color: var(--primary-text-color);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .model {
        font-size: 0.78rem; color: var(--secondary-text-color); margin-top: 1px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }

      /* 锁状态 + 电量（高度约为原来的 2/3） */
      .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .stat {
        display: flex; align-items: center; gap: 12px; padding: 12px;
        border-radius: 12px; background: var(--secondary-background-color, #f2f4f7);
        min-height: 62px;
      }
      .lock-ring {
        width: 44px; height: 44px; border-radius: 50%; flex: 0 0 auto;
        display: flex; align-items: center; justify-content: center;
        border: 2px solid currentColor;
      }
      .lock-ring ha-icon { --mdc-icon-size: 24px; }
      .stat-body { min-width: 0; }
      .stat-label { font-size: 0.78rem; color: var(--secondary-text-color); }
      .stat-value {
        font-size: 1.1rem; font-weight: 600; color: var(--primary-text-color);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .battery-stat { flex-direction: column; align-items: stretch; justify-content: center; gap: 8px; }
      .stat-head { display: flex; align-items: baseline; justify-content: space-between; }
      .progress {
        height: 10px; border-radius: 5px; overflow: hidden;
        background: var(--divider-color, #e0e0e0);
      }
      .progress-fill {
        height: 100%; border-radius: 5px; background: #3F8CFF;
        transition: width 0.5s ease;
      }

      /* 四个状态项 */
      .chips { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
      .chip {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 4px; padding: 8px 4px; border-radius: 10px;
        background: var(--secondary-background-color, #f2f4f7); text-align: center;
      }
      .chip ha-icon { --mdc-icon-size: 22px; color: var(--secondary-text-color); }
      .chip.on ha-icon { color: #3F8CFF; }
      .chip-body { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
      .chip-label { font-size: 0.72rem; color: var(--secondary-text-color); white-space: nowrap; }
      .chip-value { font-size: 0.85rem; font-weight: 600; color: var(--primary-text-color); white-space: nowrap; }

      /* 消息记录：滚动，可见约 5 条，内容更多 */
      .records { display: flex; flex-direction: column; gap: 6px; }
      .records-title { font-size: 0.85rem; font-weight: 600; color: var(--primary-text-color); }
      .records-list { display: flex; flex-direction: column; max-height: 150px; overflow-y: auto; }
      .record {
        display: flex; gap: 10px; padding: 6px 0; font-size: 0.82rem;
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
      .records-empty { font-size: 0.82rem; color: var(--secondary-text-color); padding: 6px 0; }

      /* 数据更新时间：最底端 */
      .updated {
        text-align: center; font-size: 0.76rem; color: var(--secondary-text-color);
        border-top: 1px solid var(--divider-color, #e0e0e0); padding-top: 8px;
      }

      @media (max-width: 380px) {
        .chips { grid-template-columns: repeat(2, 1fr); }
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
          <ha-formfield label="显示布防/逗留栏">
            <ha-switch id="show_chips"></ha-switch>
          </ha-formfield>
          <ha-formfield label="显示消息记录">
            <ha-switch id="show_records"></ha-switch>
          </ha-formfield>
          <ha-formfield label="显示数据更新时间">
            <ha-switch id="show_update_time"></ha-switch>
          </ha-formfield>
        </div>`;
      this._built = true;
      const fire = () => {
        const entity = this.querySelector("#entity").value;
        const name = this.querySelector("#name").value;
        const model = this.querySelector("#model").value;
        const show_chips = this.querySelector("#show_chips").checked;
        const show_records = this.querySelector("#show_records").checked;
        const show_update_time = this.querySelector("#show_update_time").checked;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { ...this._config, entity, name, model, show_chips, show_records, show_update_time } },
            bubbles: true,
            composed: true,
          })
        );
      };
      this.querySelector("#entity").addEventListener("value-changed", fire);
      this.querySelector("#name").addEventListener("change", fire);
      this.querySelector("#model").addEventListener("change", fire);
      this.querySelector("#show_chips").addEventListener("change", fire);
      this.querySelector("#show_records").addEventListener("change", fire);
      this.querySelector("#show_update_time").addEventListener("change", fire);
    }
    const e = this.querySelector("#entity");
    e.hass = this._hass;
    e.value = this._config?.entity || "";
    this.querySelector("#name").value = this._config?.name || "";
    this.querySelector("#model").value = this._config?.model || "";
    this.querySelector("#show_chips").checked = this._config?.show_chips !== false;
    this.querySelector("#show_records").checked = this._config?.show_records !== false;
    this.querySelector("#show_update_time").checked = this._config?.show_update_time !== false;
  }
}

customElements.define("kaadas-lock-card-editor", KaadasLockCardEditor);

/* ------------------------------- 注册到卡片库 ------------------------------ */

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "kaadas-lock-card")) {
  window.customCards.push({
    type: "kaadas-lock-card",
    name: "凯迪仕门锁卡片",
    description: "凯迪仕智能门锁状态卡片（设备名/型号、锁状态、电量、消息记录）",
    preview: true,
    documentationURL: "https://github.com/custom-components/kaadas",
  });
}

LOG(`v${CARD_VERSION} 已加载`);
