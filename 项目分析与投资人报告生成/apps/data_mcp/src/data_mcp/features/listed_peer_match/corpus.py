from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from data_mcp.features.listed_peer_match.weights import FIELD_KEYS

# Excel 列名（取首行换行前的主标题）
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "security_code": ("证券代码",),
    "security_name": ("证券名称",),
    "company_name_cn": ("公司中文名称",),
    "pe_ttm": ("区间市盈率PE(TTM)平均值", "区间市盈率"),
    "pb_lf": ("区间市净率PB(LF)平均值", "区间市净率"),
    "ps_ttm": ("区间市销率PS(TTM)平均值", "区间市销率"),
    "revenue": ("营业收入",),
    "net_profit": ("净利润",),
    "industry": ("所在行业",),
    "track_tags": ("细分赛道",),
    "industry_chain_position": ("自身在产业链上下游位置",),
    "products_services": ("主要产品和服务",),
    "target_customers": ("目标客户",),
    "profit_model": ("盈利模式",),
}


@dataclass
class ListedCompany:
    security_code: str
    security_name: str
    company_name_cn: str = ""
    industry: str = ""
    track_tags_raw: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    valuation: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""

    @property
    def track_tags(self) -> list[str]:
        return split_tags(self.track_tags_raw)

    def profile_blob(self) -> str:
        parts = [
            self.fields.get("track_tags", ""),
            self.fields.get("industry_chain_position", ""),
            self.fields.get("products_services", ""),
            self.fields.get("target_customers", ""),
            self.fields.get("profit_model", ""),
        ]
        return "\n".join(p for p in parts if p.strip())

    def matching_profile(self) -> str:
        """业务事实用于重排与关键词证据；不让未经核实的赛道标签覆盖主营业务。"""
        fields = [
            ("所在行业", self.industry),
            ("主要产品和服务", self.fields.get("products_services", "")),
            ("目标客户", self.fields.get("target_customers", "")),
            ("盈利模式", self.fields.get("profit_model", "")),
            ("产业链角色", self.fields.get("industry_chain_position", "")),
        ]
        return "\n".join(f"{label}：{value.strip()}" for label, value in fields if value.strip())


def split_tags(raw: str) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    return [p.strip() for p in re.split(r"[、,，;/；|]+", str(raw)) if p.strip()]


def _header_title(cell_value: Any) -> str:
    text = str(cell_value or "").strip()
    if not text:
        return ""
    return text.split("\n", 1)[0].strip()


def _resolve_columns(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for idx, header in enumerate(headers):
            if any(header.startswith(alias) or alias in header for alias in aliases):
                mapping[key] = idx
                break
    required = ("security_code", "security_name", "track_tags", "industry_chain_position", "products_services")
    missing = [k for k in required if k not in mapping]
    if missing:
        raise ValueError(f"Excel 缺少必要列: {missing}；表头={headers}")
    return mapping


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


_EXCEL_SUFFIXES = {".xlsx", ".xls"}


def _company_dedupe_key(company: ListedCompany) -> str:
    code = (company.security_code or "").strip()
    if code:
        return f"code:{code}"
    name = (company.security_name or "").strip()
    if name:
        return f"name:{name}"
    return f"anon:{id(company)}"


def list_listed_excel_files(data_dir: Path | str, *, display_dir: str | None = None) -> list[Path]:
    """列出目录下一层 Excel（不递归子目录；忽略临时锁文件）。"""
    root = Path(data_dir)
    label = (display_dir or str(data_dir)).strip() or str(root)
    if not root.exists():
        raise ValueError(
            f"上市公司画像目录不存在: {label}。"
            "请在当前 Data MCP 配置的 listed_peer_match.data_dir 中配置有效目录。"
        )
    if not root.is_dir():
        raise ValueError(
            f"listed_peer_match.data_dir 必须是目录（不能是文件）: {label}。"
            "请将商业模式 Excel 放到该目录下，并确保路径指向目录本身。"
        )

    files = sorted(
        p
        for p in root.iterdir()
        if p.is_file()
        and p.suffix.lower() in _EXCEL_SUFFIXES
        and not p.name.startswith("~$")
    )
    if not files:
        raise ValueError(
            f"上市公司画像目录下没有 Excel 文件（*.xlsx/*.xls）: {label}。"
            "仅扫描该目录一层，不会读取子文件夹（例如 tag_data）。"
            "请将商业模式分析 Excel 直接放在该目录下。"
        )
    return files


def load_listed_corpus(path: Path | str) -> list[ListedCompany]:
    """从商业模式分析 Excel 加载有身份信息的上市公司行。"""
    xlsx_path = Path(path)
    if not xlsx_path.exists():
        raise ValueError(f"未找到上市公司画像数据文件: {xlsx_path.name}")

    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if not header_row:
            return []
        headers = [_header_title(c) for c in header_row]
        col = _resolve_columns(headers)

        companies: list[ListedCompany] = []
        for row in rows_iter:
            if row is None:
                continue

            def get(key: str, row_data: tuple[Any, ...] = row) -> Any:
                idx = col.get(key)
                if idx is None or idx >= len(row_data):
                    return None
                return row_data[idx]

            code = _cell_str(get("security_code"))
            name = _cell_str(get("security_name"))
            industry = _cell_str(get("industry"))
            track_raw = _cell_str(get("track_tags"))
            if not (code or name or industry or track_raw):
                continue

            fields = {
                "track_tags": track_raw,
                "industry_chain_position": _cell_str(get("industry_chain_position")),
                "products_services": _cell_str(get("products_services")),
                "target_customers": _cell_str(get("target_customers")),
                "profit_model": _cell_str(get("profit_model")),
            }
            # 至少有一个计分字段或赛道，才进入语料
            if not any(fields[k].strip() for k in FIELD_KEYS):
                continue

            companies.append(
                ListedCompany(
                    security_code=code,
                    security_name=name,
                    company_name_cn=_cell_str(get("company_name_cn")),
                    industry=industry,
                    track_tags_raw=track_raw,
                    fields=fields,
                    valuation={
                        "pe_ttm": _cell_number(get("pe_ttm")),
                        "pb_lf": _cell_number(get("pb_lf")),
                        "ps_ttm": _cell_number(get("ps_ttm")),
                        "revenue": _cell_number(get("revenue")),
                        "net_profit": _cell_number(get("net_profit")),
                    },
                    source_file=xlsx_path.name,
                )
            )
        return companies
    finally:
        wb.close()


def load_listed_corpus_dir(
    data_dir: Path | str,
    *,
    display_dir: str | None = None,
) -> tuple[list[ListedCompany], list[str]]:
    """扫描目录下一层 Excel，合并语料；同代码/同名后读覆盖。任一文件失败则整次报错。"""
    files = list_listed_excel_files(data_dir, display_dir=display_dir)
    source_files = [p.name for p in files]
    by_key: dict[str, ListedCompany] = {}

    for path in files:
        try:
            rows = load_listed_corpus(path)
        except ValueError as exc:
            raise ValueError(f"加载上市公司画像失败（文件: {path.name}）: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - surface parse/IO errors to MCP agent
            raise ValueError(
                f"加载上市公司画像失败（文件: {path.name}）: {exc}"
            ) from exc

        for company in rows:
            by_key[_company_dedupe_key(company)] = company

    companies = list(by_key.values())
    if not companies:
        raise ValueError(
            "上市公司画像语料为空（已读取: "
            + "、".join(source_files)
            + "）。请检查 Excel 是否包含有效公司行（证券代码/名称与商业模式字段）。"
        )
    return companies, source_files
