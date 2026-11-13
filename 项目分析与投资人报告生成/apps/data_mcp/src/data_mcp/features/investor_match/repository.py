from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from data_mcp.features.investor_match.rules import compute_weight_score
from data_mcp.shared.settings import load_investor_match_config

ConnectFn = Callable[..., Any]


def _is_db_configured(cfg: dict[str, Any]) -> bool:
    return bool(str(cfg.get("host") or "").strip() and str(cfg.get("database") or "").strip())


def _json_safe(value: Any) -> Any:
    """把 MySQL/PyMySQL 常见非 JSON 类型转成可序列化值。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        sign = "-" if total < 0 else ""
        total = abs(total)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}"
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _connect_mysql(cfg: dict[str, Any]):
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("未安装 PyMySQL，无法连接 touziren 库（pip install PyMySQL）") from exc

    return pymysql.connect(
        host=str(cfg["host"]),
        port=int(cfg.get("port") or 3306),
        user=str(cfg.get("user") or ""),
        password=str(cfg.get("password") or ""),
        database=str(cfg["database"]),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


def query_touziren_investors(
    track_tags: list[str],
    env: str | None = None,
    *,
    weight_ratio: dict[str, float] | None = None,
    connect: ConnectFn | None = None,
) -> list[dict[str, Any]]:
    """按赛道标签匹配投资人权重表并关联信息全量表。"""
    full = load_investor_match_config(env)
    cfg = full["database"]
    ratio = weight_ratio or full.get("weight_ratio") or {"lbl_wgt": 1, "pref_wgt": 1, "smy_wgt": 1}

    tags = [str(t).strip() for t in track_tags if str(t).strip()]
    if not tags:
        raise ValueError("track_tags 不能为空")

    if not _is_db_configured(cfg):
        raise RuntimeError("touziren 数据库未配置 host/database")

    weight_table = str(cfg.get("weight_table") or "投资人权重")
    info_table = str(cfg.get("info_table") or "投资人信息全量")

    placeholders = ", ".join(["%s"] * len(tags))
    weight_sql = (
        f"SELECT usr_id, lbl_nm, lbl_wgt, pref_wgt, smy_wgt "
        f"FROM `{weight_table}` WHERE lbl_nm IN ({placeholders})"
    )

    connector = connect or _connect_mysql
    conn = connector(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(weight_sql, tags)
            weight_rows = list(cur.fetchall() or [])

            if not weight_rows:
                return []

            best: dict[Any, dict[str, Any]] = {}
            for row in weight_rows:
                uid = row.get("usr_id")
                score = compute_weight_score(
                    row.get("lbl_wgt"),
                    row.get("pref_wgt"),
                    row.get("smy_wgt"),
                    ratio,
                )
                prev = best.get(uid)
                if prev is None or score > float(prev.get("score") or 0):
                    best[uid] = {
                        "usr_id": uid,
                        "score": score,
                        "lbl_nm": row.get("lbl_nm"),
                        "lbl_wgt": row.get("lbl_wgt"),
                        "pref_wgt": row.get("pref_wgt"),
                        "smy_wgt": row.get("smy_wgt"),
                    }

            user_ids = list(best.keys())
            id_ph = ", ".join(["%s"] * len(user_ids))
            info_sql = f"SELECT * FROM `{info_table}` WHERE usr_id IN ({id_ph})"
            cur.execute(info_sql, user_ids)
            info_rows = list(cur.fetchall() or [])
    finally:
        try:
            conn.close()
        except Exception:
            pass

    info_by_id = {row.get("usr_id"): row for row in info_rows if isinstance(row, dict)}
    out: list[dict[str, Any]] = []
    for uid, scored in best.items():
        info = _json_safe(info_by_id.get(uid) or {})
        if not isinstance(info, dict):
            info = {}
        # usr_id 仅是内部标识。返回给 Agent 的候选名称必须可读、可用于
        # 股东过滤和跨来源去重，因此优先机构名，其次联系人/兼容名称。
        name = str(
            info.get("org_nm")
            or info.get("investor_name")
            or info.get("cust_nm")
            or info.get("usr_nm")
            or info.get("name")
            or ""
        ).strip()
        if not name:
            continue
        category = info.get("usr_cgy_cd_dsc")
        label = scored.get("lbl_nm")
        score = float(scored.get("score") or 0)
        raw = {
            **info,
            **{k: _json_safe(scored[k]) for k in ("lbl_nm", "lbl_wgt", "pref_wgt", "smy_wgt", "score")},
        }
        out.append(
            {
                "name": name,
                "score": score,
                "match_reason": f"库内标签匹配: {label}; 权重分 {score:.4f}",
                "raw": raw,
                "usr_cgy_cd_dsc": category,
            }
        )

    out.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return out
