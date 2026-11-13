from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

DATA_MCP_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = DATA_MCP_ROOT.parent.parent


def resolve_data_path(value: str | Path) -> Path:
    """解析配置中的数据路径，兼容源码运行与容器安装两种布局。

    源码布局下 DATA_MCP_ROOT 指向 apps/data_mcp，"../../resources" 语义成立；
    容器内包安装在 site-packages，同一锚点会落到 .venv 下。先按传统锚点拼接，
    不存在时剥掉 ".." 前缀后逐级向上查找 resources 等数据目录。
    """
    raw = Path(str(value))
    if raw.is_absolute():
        return raw
    legacy = DATA_MCP_ROOT / raw
    if legacy.exists():
        return legacy
    suffix = Path(*(part for part in raw.parts if part not in ("..", ".")))
    for base in DATA_MCP_ROOT.parents:
        candidate = base / suffix
        if candidate.exists():
            return candidate
    return legacy


def _resolve_repository_path(value: str, default: Path) -> Path:
    path = Path(value) if value else default
    return path if path.is_absolute() else REPOSITORY_ROOT / path


CONFIG_PATH = _resolve_repository_path(
    os.getenv("DATA_MCP_CONFIG", ""),
    DATA_MCP_ROOT / "config.yaml",
)
VALID_ENVS = ("dev", "test", "uat", "prod")


def _select_environment_block(
    block: dict[str, Any],
    selected_env: str,
    config_path: str,
) -> dict[str, Any]:
    """兼容单环境部署配置和旧的 dev/uat/prod 多环境配置。"""
    environment_keys = set(VALID_ENVS).intersection(block)
    if not environment_keys:
        return dict(block)

    selected = block.get(selected_env) or {}
    if not isinstance(selected, dict):
        raise ValueError(f"配置 {config_path}.{selected_env} 必须是对象")
    return dict(selected)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"未找到配置文件: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误，应为 YAML 对象: {CONFIG_PATH}")
    return data


def resolve_env(env: str | None = None) -> str:
    requested = (env or "").strip().lower()
    if requested:
        if requested not in VALID_ENVS:
            raise ValueError(f"env 只能是 {', '.join(VALID_ENVS)}，收到: {env}")
        return requested

    current = str(load_config().get("current_env") or "dev").strip().lower()
    if current not in VALID_ENVS:
        raise ValueError(f"Data MCP 配置的 current_env 只能是 {', '.join(VALID_ENVS)}")
    return current


def _load_agent_env_config(section_name: str, env: str | None = None) -> dict[str, Any]:
    """读取智能体配置段 section_name.<env>，字段与项目画像保持一致。"""
    data = load_config()
    selected_env = resolve_env(env)
    section = data.get(section_name) or {}
    if not isinstance(section, dict):
        raise ValueError(f"Data MCP 配置中 {section_name} 必须是对象")

    has_environment_blocks = bool(set(VALID_ENVS).intersection(section))
    config = _select_environment_block(section, selected_env, section_name)

    host = str(config.get("host") or "").strip().rstrip("/")
    path = str(section.get("path") or "").strip()
    token = str(config.get("token") or "").strip()
    agent_id = str(config.get("agent_id") or "").strip()
    prefix = f"{section_name}.{selected_env}" if has_environment_blocks else section_name

    if not host:
        raise ValueError(f"请先在当前 Data MCP 配置的 {prefix}.host 中填写地址")
    if not path:
        raise ValueError(f"请先在当前 Data MCP 配置的 {section_name}.path 中填写接口路径")
    if not token:
        raise ValueError(f"请先在当前 Data MCP 配置的 {prefix}.token 中填写 token")
    if not agent_id:
        raise ValueError(f"请先在当前 Data MCP 配置的 {prefix}.agent_id 中填写 agent_id")

    timeout = config.get("timeout_seconds", 120)
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{prefix}.timeout_seconds 必须是数字") from exc

    return {
        "env": selected_env,
        "host": host,
        "path": path,
        "token": token,
        "agent_id": agent_id,
        "chat_id": config.get("chat_id"),
        "button_key": config.get("button_key"),
        "debug": bool(config.get("debug", False)),
        "timeout_seconds": timeout_seconds,
    }


def load_historical_valuation_config(env: str | None = None) -> dict[str, Any]:
    """加载历史成交可比估值智能体配置（historical_valuation.<env>）。"""
    return _load_agent_env_config("historical_valuation", env)


def load_project_profile_config(env: str | None = None) -> dict[str, Any]:
    """加载项目画像智能体配置（project_profile.<env>）。"""
    return _load_agent_env_config("project_profile", env)


def load_project_profile_qichacha_config(env: str | None = None) -> dict[str, Any]:
    """加载项目画像专用企查查配置（project_profile.qichacha.<env>）。"""
    data = load_config()
    selected_env = resolve_env(env)
    section = data.get("project_profile") or {}
    if not isinstance(section, dict):
        raise ValueError("Data MCP 配置中 project_profile 必须是对象")

    qichacha = section.get("qichacha") or {}
    if not isinstance(qichacha, dict):
        raise ValueError("Data MCP 配置中 project_profile.qichacha 必须是对象")

    config = _select_environment_block(
        qichacha,
        selected_env,
        "project_profile.qichacha",
    )

    return {
        "env": selected_env,
        "key": str(config.get("key") or "").strip(),
        "secret_key": str(config.get("secret_key") or "").strip(),
        "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
        "path": str(config.get("path") or "").strip(),
        "timeout_seconds": float(config.get("timeout_seconds") or 30),
    }


def load_project_profile_zhipu_config(env: str | None = None) -> dict[str, Any]:
    """加载项目画像专用智谱搜索配置（project_profile.zhipu.<env>）。"""
    data = load_config()
    selected_env = resolve_env(env)
    section = data.get("project_profile") or {}
    if not isinstance(section, dict):
        raise ValueError("Data MCP 配置中 project_profile 必须是对象")

    zhipu = section.get("zhipu") or {}
    if not isinstance(zhipu, dict):
        raise ValueError("Data MCP 配置中 project_profile.zhipu 必须是对象")

    config = _select_environment_block(
        zhipu,
        selected_env,
        "project_profile.zhipu",
    )

    templates = config.get("query_templates")
    query_templates: list[str] | None = None
    if isinstance(templates, list):
        query_templates = [str(item).strip() for item in templates if str(item).strip()]

    return {
        "env": selected_env,
        "api_key": str(config.get("api_key") or "").strip(),
        "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
        "path": str(config.get("path") or "").strip(),
        "search_engine": str(config.get("search_engine") or "search_pro").strip() or "search_pro",
        "count": int(config.get("count") or 10),
        "timeout_seconds": float(config.get("timeout_seconds") or 30),
        "query_templates": query_templates,
    }


def load_investor_network_config(env: str | None = None) -> dict[str, Any]:
    """加载网络投资人智能体配置（investor_network.<env>）。"""
    return _load_agent_env_config("investor_network", env)


def load_investor_match_config(env: str | None = None) -> dict[str, Any]:
    """加载投资人匹配配置：截断/权重 + 当前环境的 dmp/database/qichacha。"""
    data = load_config()
    selected_env = resolve_env(env)
    section = data.get("investor_match") or {}
    if not isinstance(section, dict):
        raise ValueError("Data MCP 配置中 investor_match 必须是对象")

    weight_ratio_raw = section.get("weight_ratio") or {
        "lbl_wgt": 1,
        "pref_wgt": 1,
        "smy_wgt": 1,
    }
    if not isinstance(weight_ratio_raw, dict):
        raise ValueError("investor_match.weight_ratio 必须是对象")

    def _env_block(name: str) -> dict[str, Any]:
        block = section.get(name) or {}
        if not isinstance(block, dict):
            raise ValueError(f"investor_match.{name} 必须是对象")
        return _select_environment_block(block, selected_env, f"investor_match.{name}")

    dmp = _env_block("dmp")
    mode = str(dmp.get("mode") or "real").strip().lower()
    if mode not in {"real", "mock"}:
        raise ValueError("INVALID_DMP_MODE")
    base_url = str(dmp.get("base_url") or "").strip().rstrip("/")
    if mode == "mock":
        if selected_env not in {"test", "uat"} or os.getenv("APP_ENV", selected_env) not in {
            "test",
            "uat",
        }:
            raise ValueError("DMP_MOCK_FORBIDDEN_IN_ENVIRONMENT")
        base_url = os.getenv("DMP_MOCK_BASE_URL", base_url).strip().rstrip("/")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "dmp-mock"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise ValueError("INVALID_DMP_MOCK_URL")
    elif selected_env == "prod" and (
        urlsplit(base_url).hostname in {"127.0.0.1", "localhost", "::1", "dmp-mock"}
        or _setting_text(dmp.get("app_key")).startswith("mock-dmp-")
    ):
        raise ValueError("DMP_MOCK_FORBIDDEN_IN_PRODUCTION")
    dmp_settings = {
        "mode": mode,
        "base_url": base_url,
        "path": str(dmp.get("path") or "").strip(),
        "method": str(dmp.get("method") or "POST").strip().upper() or "POST",
        # x_gw_token 为原始 API 平台 token；请求时再随机盐并 HMAC-SM3 加密
        "x_gw_appid": str(dmp.get("x_gw_appid") or "").strip(),
        "x_gw_org": str(dmp.get("x_gw_org") or "").strip(),
        "x_gw_token": "mock-dmp-gateway-token"
        if mode == "mock"
        else _setting_text(dmp.get("x_gw_token")),
        "x_gw_route": str(dmp.get("x_gw_route") or "").strip(),
        "app_key": "mock-dmp-app-key" if mode == "mock" else _setting_text(dmp.get("app_key")),
        "app_secret": "mock-dmp-app-secret"
        if mode == "mock"
        else _setting_text(dmp.get("app_secret")),
        "timeout_seconds": float(dmp.get("timeout_seconds") or 30),
    }
    for name in (
        "institution_offset",
        "institution_limit",
        "individual_offset",
        "individual_limit",
    ):
        page_value = _page_setting(dmp, name)
        if page_value is not None:
            dmp_settings[name] = page_value
    return {
        "env": selected_env,
        "internal_top_n": int(section.get("internal_top_n", 100)),
        "network_top_n": int(section.get("network_top_n", 10)),
        "weight_ratio": {
            "lbl_wgt": float(weight_ratio_raw.get("lbl_wgt", 1) or 0),
            "pref_wgt": float(weight_ratio_raw.get("pref_wgt", 1) or 0),
            "smy_wgt": float(weight_ratio_raw.get("smy_wgt", 1) or 0),
        },
        "dmp": dmp_settings,
        "database": _env_block("database"),
        "qichacha": _env_block("qichacha"),
    }


def load_http_retry_config() -> dict[str, Any]:
    """外部 HTTP 调用重试策略（超时/连接/429/5xx）。"""
    data = load_config()
    section = data.get("http_retry") or {}
    if not isinstance(section, dict):
        raise ValueError("Data MCP 配置中 http_retry 必须是对象")
    return {
        "max_retries": int(section.get("max_retries", 2)),
        "backoff_base_seconds": float(section.get("backoff_base_seconds", 0.5)),
        "backoff_max_seconds": float(section.get("backoff_max_seconds", 8.0)),
    }


def load_workbook_export_config() -> dict[str, Any]:
    """Export-only limits, read lazily; existing matching configuration is unchanged."""
    section = load_config().get("investor_match", {}).get("workbook_export", {})
    if not isinstance(section, dict):
        raise ValueError("INVALID_WORKBOOK_EXPORT_CONFIG")
    defaults = {
        "request_timeout_seconds": 30,
        "max_response_bytes": 67108864,
        "max_concurrent_exports": 1,
    }
    bounds = {
        "request_timeout_seconds": (1, 120),
        "max_response_bytes": (1024, 67108864),
        "max_concurrent_exports": (1, 1),
    }
    for key, default in defaults.items():
        value = section.get(key, default)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not bounds[key][0] <= value <= bounds[key][1]
        ):
            raise ValueError("INVALID_WORKBOOK_EXPORT_CONFIG")
        defaults[key] = int(value)
    return defaults


def _page_setting(block: dict[str, Any], name: str) -> int | None:
    """读取 DMP 分页整数。缺省或非法时返回 None，由调用方使用代码默认值。"""
    if name not in block or block[name] is None or block[name] == "":
        return None
    try:
        return int(block[name])
    except (TypeError, ValueError):
        return None


def _setting_text(value: Any) -> str:
    """读取配置字符串。`{env: NAME}` 从进程环境变量取值，缺省为空串。"""
    if isinstance(value, dict):
        env_name = value.get("env")
        if isinstance(env_name, str) and set(value) <= {"env"}:
            return os.getenv(env_name.strip(), "").strip()
        return ""
    return str(value or "").strip()


def load_track_labels_config(env: str | None = None) -> dict[str, Any]:
    """加载赛道标签查询配置：API 平台 + 重试 + 本地兜底 + HiAgent。"""
    data = load_config()
    selected_env = resolve_env(env)
    section = data.get("track_labels") or {}
    if not isinstance(section, dict):
        raise ValueError("Data MCP 配置中 track_labels 必须是对象")

    def _env_block(name: str) -> dict[str, Any]:
        block = section.get(name) or {}
        if not isinstance(block, dict):
            raise ValueError(f"track_labels.{name} 必须是对象")
        return _select_environment_block(block, selected_env, f"track_labels.{name}")

    retry_raw = section.get("retry") or {}
    if not isinstance(retry_raw, dict):
        raise ValueError("track_labels.retry 必须是对象")
    fallback_raw = section.get("fallback") or {}
    if not isinstance(fallback_raw, dict):
        raise ValueError("track_labels.fallback 必须是对象")

    api = _env_block("api")
    hiagent = _env_block("hiagent")
    hiagent_group = section.get("hiagent") or {}
    if not isinstance(hiagent_group, dict):
        raise ValueError("track_labels.hiagent 必须是对象")
    taxonomy_path = str(fallback_raw.get("taxonomy_path") or "").strip()
    if not taxonomy_path:
        raise ValueError("track_labels.fallback.taxonomy_path 不能为空")

    return {
        "env": selected_env,
        "api": {
            "base_url": str(api.get("base_url") or "").strip().rstrip("/"),
            "path": str(api.get("path") or "").strip(),
            "method": str(api.get("method") or "POST").strip().upper() or "POST",
            "secret_key": _setting_text(api.get("secret_key")),
            "source": str(api.get("source") or "2").strip() or "2",
            # x_gw_token 为原始 API 平台 token；请求时再随机盐并 HMAC-SM3 加密
            "x_gw_appid": str(api.get("x_gw_appid") or "").strip(),
            "x_gw_org": str(api.get("x_gw_org") or "").strip(),
            "x_gw_token": _setting_text(api.get("x_gw_token")),
            "x_gw_route": str(api.get("x_gw_route") or "").strip(),
            "timeout_seconds": float(api.get("timeout_seconds") or 90),
        },
        "retry": {
            "max_attempts": int(retry_raw.get("max_attempts") or 2),
            "interval_seconds": float(retry_raw.get("interval_seconds") or 20),
        },
        "fallback": {
            "taxonomy_path": taxonomy_path,
        },
        "hiagent": {
            "host": str(hiagent.get("host") or "").strip().rstrip("/"),
            "path": str(hiagent_group.get("path") or "").strip(),
            "token": str(hiagent.get("token") or "").strip(),
            "agent_id": str(hiagent.get("agent_id") or "").strip(),
            "chat_id": hiagent.get("chat_id"),
            "button_key": hiagent.get("button_key"),
            "debug": bool(hiagent.get("debug", False)),
            "timeout_seconds": float(hiagent.get("timeout_seconds") or 120),
        },
    }


def load_listed_peer_match_config(env: str | None = None) -> dict[str, Any]:
    """加载上市公司可比匹配配置并校验权重约束。

    embedding / rerank 按环境读取：listed_peer_match.{embedding|rerank}.<env>
    """
    from data_mcp.features.listed_peer_match.weights import (
        DEFAULT_FIELD_WEIGHTS,
        validate_field_weights,
    )

    data = load_config()
    selected_env = resolve_env(env)
    section = data.get("listed_peer_match") or {}
    if not isinstance(section, dict):
        raise ValueError("Data MCP 配置中 listed_peer_match 必须是对象")

    constraints_raw = section.get("constraints") or {}
    if not isinstance(constraints_raw, dict):
        raise ValueError("listed_peer_match.constraints 必须是对象")

    require_sum = float(constraints_raw.get("require_sum_approx", 1.0))
    sum_tol = float(constraints_raw.get("sum_tolerance", 0.001))
    chain_min_raw = constraints_raw.get("require_chain_plus_products_min", 0.75)
    chain_min = None if chain_min_raw is None else float(chain_min_raw)

    weights_raw = section.get("field_weights") or DEFAULT_FIELD_WEIGHTS
    weights = validate_field_weights(
        weights_raw,
        require_sum_approx=require_sum,
        sum_tolerance=sum_tol,
        require_chain_plus_products_min=chain_min,
    )

    def _env_block(name: str) -> dict[str, Any]:
        block = section.get(name) or {}
        if not isinstance(block, dict):
            raise ValueError(f"listed_peer_match.{name} 必须是对象")
        return _select_environment_block(block, selected_env, f"listed_peer_match.{name}")

    embedding = _env_block("embedding")
    rerank = _env_block("rerank")

    thresholds = section.get("score_threshold") or {}
    if not isinstance(thresholds, dict):
        raise ValueError("listed_peer_match.score_threshold 必须是对象")

    data_dir = str(section.get("data_dir") or "").strip()
    if not data_dir:
        raise ValueError(
            "listed_peer_match.data_dir 不能为空。"
            "请配置存放上市公司商业模式 Excel 的目录（仅扫描该目录一层，不含子文件夹）。"
        )

    raw_index_dir = str(section.get("index_dir") or "").strip()
    if raw_index_dir:
        index_path = resolve_data_path(raw_index_dir)
    else:
        index_path = REPOSITORY_ROOT / ".runtime" / "data_mcp" / "listed_peer_index"

    return {
        "env": selected_env,
        "data_dir": data_dir,
        "index_dir": str(index_path),
        "field_weights": weights,
        "constraints": {
            "require_sum_approx": require_sum,
            "sum_tolerance": sum_tol,
            "require_chain_plus_products_min": chain_min,
        },
        "top_k_recall": int(section.get("top_k_recall", 80)),
        "top_n_return": int(section.get("top_n_return", 10)),
        "enable_rerank": bool(section.get("enable_rerank", False)),
        "score_threshold": {
            "high": float(thresholds.get("high", 0.72)),
            "medium": float(thresholds.get("medium", 0.55)),
        },
        "embedding": {
            "backend": str(embedding.get("backend") or "http").strip().lower(),
            "url": str(embedding.get("url") or "").strip(),
            "api_key": str(embedding.get("api_key") or "").strip(),
            "model": str(embedding.get("model") or "").strip(),
            "timeout_seconds": float(embedding.get("timeout_seconds", 60)),
            "batch_size": int(embedding.get("batch_size") or 32),
        },
        "rerank": {
            "url": str(rerank.get("url") or "").strip(),
            "api_key": str(rerank.get("api_key") or "").strip(),
            "model": str(rerank.get("model") or "").strip(),
            "timeout_seconds": float(rerank.get("timeout_seconds", 60)),
        },
    }
