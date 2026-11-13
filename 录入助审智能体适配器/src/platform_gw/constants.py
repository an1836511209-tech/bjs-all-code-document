"""平台响应头与业务码常量（提供方侧）"""

# 平台生成（提供方不得伪造）
HEADER_GW_INSTANCE = "x-gw-instance"
HEADER_GW_RETURN_CODE = "x-gw-return-code"
HEADER_GW_RETURN_MSG = "x-gw-return-msg"

# 提供方生成
HEADER_GW_BIZ_CODE = "x-gw-biz-code"
HEADER_GW_BIZ_MSG = "x-gw-biz-msg"

# 消费方请求头（平台侧校验，提供方仅可观测，不据此赋权）
HEADER_GW_APPID = "x-gw-appid"
HEADER_GW_ORG = "x-gw-org"
HEADER_GW_TOKEN = "x-gw-token"
HEADER_GW_SALT_KEY = "x-gw-salt-key"
HEADER_GW_ROUTE = "x-gw-route"

# 提供方可选鉴权头（本项目约定，非平台标准请求头）
HEADER_PROVIDER_API_KEY = "X-Provider-Api-Key"

# 规范已指定
BIZ_CODE_SUCCESS = "PS-001"
BIZ_CODE_PAYLOAD_TOO_LARGE = "PI-001"
BIZ_MSG_PAYLOAD_TOO_LARGE_ZH = "查询结果大于10M，请缩小查询区间或范围再执行查询"
BIZ_MSG_PAYLOAD_TOO_LARGE_ASCII = (
    "Query result exceeds 10M; narrow the query range and retry"
)

PLATFORM_GENERATED_HEADERS = frozenset(
    {
        HEADER_GW_INSTANCE,
        HEADER_GW_RETURN_CODE,
        HEADER_GW_RETURN_MSG,
    }
)
