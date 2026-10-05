from __future__ import annotations

DOMAIN = "kaadas"

# 配置项
CONF_TOKEN = "token"
CONF_UID = "uid"
CONF_OPENID = "openid"
CONF_PHONE = "phone"
CONF_OPENID_TOKEN = "open_id_token"
CONF_WIFI_SN = "wifi_sn"
CONF_ESN = "esn"
CONF_DEVICE_MODEL = "device_model"
CONF_NICKNAME = "nickname"
CONF_IS_THING_MODEL = "is_thing_model"

# 服务端
BASE_URL = "https://miniapp-cn.kaadas.com"
WS_URL = "wss://miniws-cn.kaadas.com/ws/api/"
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 MicroMessenger MiniProgram"
)

# 物模型服务
SERVICE_BASIC = "basic_service"
SERVICE_LOCK = "lock_service"

# 物模型属性标识
PROP_BATTERY_LEVEL = "p_battery_level"
PROP_WIFI_RSSI = "p_wifi_rssi"
PROP_FIRMWARE_VERSION = "p_firmware_version"
PROP_MODEL_VERSION = "p_model_version"
PROP_LOCK_STATUS = "p_lock_status"
PROP_DEFENSE_MODE = "p_defense_mode"
PROP_LOCKED_INSIDE_STATUS = "p_locked_inside_status"
PROP_DOOR_LOCK_ACTION_TYPE = "p_door_lock_action_type"
PROP_ALARM_TYPE = "p_alarm_type"
PROP_DOOR_DIRECTION = "p_door_direction"
PROP_LOCK_FORCE = "p_lock_force"
PROP_AUTO_CLOSE_LOCK_TIME = "p_auto_close_lock_time"
PROP_CLOSE_LOCK_MODE = "p_close_lock_mode"
PROP_LINGER_DETECTION = "p_linger_detection"
PROP_LOCK_VOLUME = "p_lock_volume"
PROP_LANGUAGE = "p_language"
PROP_LOCK_BODY_TYPE = "p_lock_body_type"
PROP_DOUBLE_VERIFY_MODE = "p_double_verify_mode"
PROP_SCREEN_ONOFF = "p_screen_onoff"
PROP_SCREEN_BACKLIGHT = "p_screen_backlight"
PROP_SCREEN_ACTIVE_TIME = "p_screen_active_time"

# 锁状态枚举（p_lock_status）
LOCK_STATUS_UNLOCKED = 1
LOCK_STATUS_LOCKED = 2
LOCK_STATUS_ABNORMAL = 3
