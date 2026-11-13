"""北交互联主要财务指标采集。逻辑对齐低代码平台脚本，仅使用标准库。"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from data_mcp.shared.http.errors import ExternalServiceError

BASE = "https://otc.cbex.com"
CATEGORIES: dict[str, tuple[str, str, str, dict[str, str]]] = {
    "zz_gz": ("企业增资（国资）", "/page/zzkg/search/search_li", "/page/zzkg/search/index", {}),
    "zz_fgz": (
        "企业增资（非国资）",
        "/page/xmjs/prj/list_li",
        "/page/xmjs/prj/list_zzxm",
        {"pllx": "1,2", "jypl": "1C,2C", "ltype": "FGZ"},
    ),
    "cq_gz": ("产权转让（国资）", "/page/cgq/search/search_li", "/page/cgq/search/index", {}),
    "cq_fgz": (
        "产权转让（非国资）",
        "/page/xmjs/prj/list_li",
        "/page/xmjs/prj/list_cgq",
        {"pllx": "2", "jypl": "GQ", "ltype": "FGZ"},
    ),
}
FIELDS = {
    "资产总计": "total_assets",
    "资产合计": "total_assets",
    "资产总额": "total_assets",
    "总资产": "total_assets",
    "负债总计": "total_liabilities",
    "负债合计": "total_liabilities",
    "负债总额": "total_liabilities",
    "总负债": "total_liabilities",
    "所有者权益": "owners_equity",
    "所有者权益合计": "owners_equity",
    "股东权益": "owners_equity",
    "股东权益合计": "owners_equity",
    "净资产": "owners_equity",
    "营业收入": "revenue",
    "营业总收入": "revenue",
    "主营业务收入": "revenue",
    "净利润": "net_profit",
    "利润总额": "total_profit",
    "营业利润": "operating_profit",
}
CORE = ["total_assets", "total_liabilities", "owners_equity", "revenue", "net_profit"]
PUBLIC_VALUE_KEYS = (
    "total_assets",
    "total_liabilities",
    "owners_equity",
    "revenue",
    "net_profit",
    "total_profit",
    "operating_profit",
)
_DETAIL_PATH = re.compile(r"/(?:zzkg|cgq|xmjs/prj)/detail/\d+\.html")
_STOP = re.compile(
    r"^(?:增资行为|信息预披露决策|内部决策|资产评估情况|转让方名称|投资方资格|其他披露事项|交易条件|保证金设置|批准情况)"
)
_VOID_TAGS = {
    "br",
    "hr",
    "img",
    "input",
    "meta",
    "link",
    "wbr",
    "source",
    "area",
    "embed",
    "col",
    "param",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", unescape(str(value or ""))))


def field(value: Any) -> str | None:
    stripped = re.sub(r"[（(](?:单位:)?(?:万|亿)?元[)）]", "", clean(value))
    return FIELDS.get(stripped)


def period(value: Any) -> tuple[str, str] | None:
    text = clean(value)
    matched = re.search(r"(?<!\d)((?:19|20)\d{2})[-年/.](\d{1,2})(?:[-月/.](\d{1,2})日?)?", text)
    if matched:
        year, month, day = matched.groups()
        if 1 <= int(month) <= 12 and (day is None or 1 <= int(day) <= 31):
            suffix = "-" + day.zfill(2) if day else ""
            return ("latest", year + "-" + month.zfill(2) + suffix)
    matched = re.search(r"(?<!\d)((?:19|20)\d{2})(?:年度|年|$)", text)
    if matched and len(text) < 100:
        return ("annual", matched.group(1))
    return None


def number(raw: Any, default_unit: str | None) -> tuple[str | None, str | None]:
    text = clean(raw).replace(",", "").replace("−", "-").replace("人民币", "")
    unit = next((item for item in ("亿元", "万元", "元") if item in text), default_unit)
    text = re.sub(r"(亿元|万元|元)$", "", text)
    if re.fullmatch(r"\([\d.]+\)", text):
        text = "-" + text[1:-1]
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None, unit
    if unit not in ("元", "万元", "亿元"):
        return None, unit
    try:
        scaled = Decimal(text) * {"元": Decimal("0.0001"), "万元": Decimal(1), "亿元": Decimal(10000)}[unit]
        return format(scaled, "f"), unit
    except InvalidOperation:
        return None, unit


class Node:
    def __init__(self, tag: str = "", attrs: Any = (), parent: Node | None = None) -> None:
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children: list[Any] = []

    def text(self) -> str:
        return "".join(child.text() if isinstance(child, Node) else str(child) for child in self.children)

    def find(self, tag: str) -> Iterator[Node]:
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.find(tag)

    def ancestor(self, tag: str) -> Node | None:
        current = self.parent
        while current and current.tag != tag:
            current = current.parent
        return current


class DOM(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.cur = self.root
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID_TAGS:
            self.cur = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.cur.tag == tag:
            parent = self.cur.parent
            if parent is not None:
                self.cur = parent

    def handle_endtag(self, tag: str) -> None:
        current: Node | None = self.cur
        while current is not None and current.parent is not None:
            if current.tag == tag:
                self.cur = current.parent
                return
            current = current.parent

    def handle_data(self, data: str) -> None:
        self.cur.children.append(data)


def documents(source: str) -> Iterator[tuple[str, DOM]]:
    extras = re.findall(r"<textarea\b[^>]*>(.*?)</textarea>", source, re.I | re.S)
    base = re.sub(r"<textarea\b[^>]*>.*?</textarea>", "", source, flags=re.I | re.S)
    yield "page", DOM(base)
    for index, text in enumerate(extras):
        if "&lt;table" in text.lower():
            text = unescape(text)
        if "<table" in text.lower():
            yield "textarea_" + str(index), DOM(text)


def walk(node: Node) -> Iterator[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from walk(child)


def table_rows(table: Node) -> list[list[Node]]:
    cells = [cell for cell in table.find("td") if cell.ancestor("table") is table]
    cells += [cell for cell in table.find("th") if cell.ancestor("table") is table]
    order = {id(node): index for index, node in enumerate(walk(table))}
    cells.sort(key=lambda cell: order[id(cell)])
    rows: list[list[Node]] = []
    last: Any = object()
    for cell in cells:
        if any(True for _ in cell.find("table")):
            continue
        tr = cell.ancestor("tr")
        key: Node = tr if tr and tr.ancestor("table") is table else cell
        if key is not last:
            rows.append([])
            last = key
        rows[-1].append(cell)
    return rows


def _public_statement(record: dict[str, Any]) -> dict[str, Any]:
    raw_values = record.get("values")
    values = raw_values if isinstance(raw_values, dict) else {}
    return {
        "kind": record["kind"],
        "period": record["period"],
        "values": {key: values.get(key) for key in PUBLIC_VALUE_KEYS if key in values},
        "missing_core_fields": list(record.get("missing_core_fields") or []),
    }


def extract_financial_data(source: str) -> dict[str, Any]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    issues: list[str] = []
    disclosed_numbers: Counter[str] = Counter()
    consumed_numbers: Counter[str] = Counter()
    blocks = 0

    def record(period_key: tuple[str, str]) -> dict[str, Any]:
        if period_key not in records:
            records[period_key] = {
                "kind": period_key[0],
                "period": period_key[1],
                "unit": "万元",
                "values": {},
                "raw": {},
                "source_units": {},
            }
        return records[period_key]

    def put(period_key: tuple[str, str] | None, key: str, raw: str, unit: str | None) -> None:
        if number(raw, "万元")[0] is not None:
            consumed_numbers[clean(raw)] += 1
        if not period_key:
            issues.append("存在无法归属日期的财务值:" + key + ":" + raw)
            return
        row = record(period_key)
        value, source_unit = number(raw, unit)
        if key in row["raw"] and row["raw"][key] != raw:
            issues.append("同一期间指标冲突:" + period_key[1] + ":" + key)
            return
        row["raw"][key] = raw
        row["source_units"][key] = source_unit
        row["values"][key] = value
        if value is None and clean(raw) not in ("", "-", "--", "—", "/", "无", "不适用", "暂无", "N/A"):
            issues.append("数值或单位无法识别:" + period_key[1] + ":" + key + ":" + raw)

    for origin, doc in documents(source):
        for table_index, table in enumerate(doc.root.find("table")):
            rendered = [[clean(cell.text()) for cell in row] for row in table_rows(table)]
            starts = [
                index
                for index, row in enumerate(rendered)
                if any("主要财务指标" in cell and len(cell) < 60 for cell in row)
            ]
            for start in starts:
                blocks += 1
                section: list[list[str]] = []
                for index in range(start, len(rendered)):
                    row = rendered[index]
                    if index > start and (any(_STOP.search(cell) for cell in row[:1]) or index in starts):
                        break
                    section.append(row)
                evidence.append({"origin": origin, "table": table_index, "rows": section})
                for row in section:
                    if any(field(cell) for cell in row) or not any(period(cell) for cell in row):
                        for raw in row:
                            if number(raw, "万元")[0] is not None:
                                disclosed_numbers[clean(raw)] += 1
                    elif len(row) > 2:
                        for raw in row:
                            if not period(raw) and number(raw, "万元")[0] is not None:
                                disclosed_numbers[clean(raw)] += 1
                header = "".join(section[0]) if section else ""
                unit = next((item for item in ("亿元", "万元") if item in header), None)
                if unit is None and re.search(r"单位:元", header):
                    unit = "元"
                current: tuple[str, str] | None = None
                columns: dict[int, tuple[str, str]] = {}
                pending: tuple[list[tuple[int, str]], int] | None = None
                for row in section:
                    text = "|".join(row)
                    if "最近一期" in text:
                        current = ("latest", "最近一期（日期未披露）")
                        columns = {}
                        pending = None
                    periods = [(index, period(cell)) for index, cell in enumerate(row) if period(cell)]
                    keys = [(index, field(cell)) for index, cell in enumerate(row) if field(cell)]
                    if len(periods) >= 2 and not keys:
                        columns = {
                            index: parsed
                            for index, parsed in periods
                            if parsed is not None
                        }
                        current = None
                        pending = None
                        for _, parsed in periods:
                            if parsed is not None:
                                record(parsed)
                        continue
                    if len(periods) == 1 and not keys:
                        only = periods[0][1]
                        if only is not None:
                            current = only
                        columns = {}
                        if pending is None:
                            continue
                    if len(keys) == 1 and keys[0][0] == 0 and len(row) > 1:
                        metric = keys[0][1]
                        if metric is None:
                            continue
                        if columns:
                            for column, parsed in columns.items():
                                if column < len(row):
                                    put(parsed, metric, row[column], unit)
                                else:
                                    issues.append("年度列缺少单元格:" + parsed[1] + ":" + metric)
                        else:
                            put(current, metric, row[1], unit)
                        pending = None
                        continue
                    if len(keys) >= 2:
                        named = [(index, name) for index, name in keys if name]
                        pending = (named, len(row))
                        continue
                    if pending and not keys:
                        named, width = pending
                        if len(row) == width:
                            for column, metric in named:
                                put(current, metric, row[column], unit)
                            pending = None
                        elif periods:
                            pending = None
                if pending:
                    issues.append("财务表末尾存在无对应数值行的指标标题")
    unconsumed = disclosed_numbers - consumed_numbers
    if unconsumed:
        issues.append("财务区存在未映射数字单元格:" + json.dumps(dict(unconsumed), ensure_ascii=False))
    annual: list[dict[str, Any]] = []
    latest: list[dict[str, Any]] = []
    for statement in records.values():
        if not statement["raw"]:
            continue
        stored_values = statement["values"]
        value_map = stored_values if isinstance(stored_values, dict) else {}
        statement["missing_core_fields"] = [key for key in CORE if value_map.get(key) is None]
        (annual if statement["kind"] == "annual" else latest).append(statement)
    annual.sort(key=lambda item: item["period"])
    latest.sort(key=lambda item: item["period"])
    if any("近三年" in "".join(row) for block in evidence for row in block["rows"]) and len(annual) < 3:
        issues.append("页面使用近三年模板，但有效年度少于三年；检查原文是否留空")
    if not blocks:
        status = "not_disclosed_or_unsupported"
    elif not annual and not latest:
        status = "parse_failed_or_empty"
    elif issues:
        status = "needs_review"
    elif len(annual) < 2:
        status = "limited_disclosure"
    elif any(item["missing_core_fields"] for item in annual + latest):
        status = "limited_fields"
    else:
        status = "multi_year_extracted"
    return {
        "unit": "万元",
        "annual": [_public_statement(item) for item in annual],
        "latest": [_public_statement(item) for item in latest],
        "quality": {
            "status": status,
            "annual_count": len(annual),
            "latest_count": len(latest),
            "issues": list(dict.fromkeys(issues)),
            "financial_block_count": blocks,
        },
    }


def valid_url(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.netloc == "otc.cbex.com"
        and bool(_DETAIL_PATH.fullmatch(parts.path))
        and not parts.query
    )


class Client:
    def __init__(self, timeout: float = 15, budget: float = 90) -> None:
        self.timeout = timeout
        self.deadline = time.monotonic() + budget

    def fetch(self, url: str, data: dict[str, Any] | None = None, referer: str = BASE + "/index.html") -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ExternalServiceError("北交互联", "北交互联官网暂不可用", detail="达到本次任务总时间上限")
        body = urlencode(data).encode("utf-8") if data is not None else None
        request = Request(
            url,
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": referer,
                "Accept": "text/html,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        try:
            with urlopen(request, timeout=min(self.timeout, remaining)) as response:
                raw = response.read(8000001)
                if len(raw) > 8000000:
                    raise ValueError("响应超过8MB上限")
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ExternalServiceError("北交互联", "北交互联官网暂不可用", detail=type(exc).__name__) from exc
        lowered = text.lower()
        if "<html" not in lowered and "<li" not in lowered and "<div" not in lowered:
            raise ValueError("服务器未返回可识别HTML")
        return text


def disclosure_end_date(text: str) -> str:
    """Only read labelled disclosure deadlines/ranges, never unrelated dates."""
    date = r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})日?"
    label = r"(?:信息)?披露(?:起止日期|截止日期|结束日期|截止时间|结束时间|截止日|期满日期|期满日|截止|结束|期|日期)|挂牌截止日期"
    match = re.search(r"(?:" + label + r")[：:\s]*(" + date + r"(?:\s*(?:至|到|—|–|~|～|-)\s*" + date + r")?)", text)
    if not match:
        return ""
    dates = list(re.finditer(date, match.group(1)))
    year, month, day = dates[-1].groups()
    try:
        from datetime import date as calendar_date

        return calendar_date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ""


def candidate_deadline(anchor: Node) -> str:
    current = anchor.parent
    while current and current.tag not in {"body", "html", "root"}:
        # A project row may contain duplicate title links, but not another project.
        urls = {urljoin(BASE, str(a.attrs.get("href", ""))) for a in current.find("a")
                if valid_url(urljoin(BASE, str(a.attrs.get("href", ""))))}
        if len(urls) > 1:
            break
        value = disclosure_end_date(current.text())
        if value:
            return value
        current = current.parent
    return ""


def parse_candidates(source: str, category: str) -> list[dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for anchor in DOM(source).root.find("a"):
        url = urljoin(BASE, str(anchor.attrs.get("href", "")))
        name = re.sub(r"\s+", "", unescape(str(anchor.attrs.get("title") or anchor.text())))
        if valid_url(url) and len(name) > 4:
            results[url] = {
                "project_name": name,
                "detail_url": url,
                "category": category,
                "project_type": CATEGORIES[category][0],
                "disclosure_end_date": candidate_deadline(anchor),
            }
    return list(results.values())


def norm(name: str) -> str:
    return re.sub(r"(?:企业增资项目|增资项目|增资)$", "", clean(name))


def search(
    client: Client,
    name: str,
    categories: list[str],
    max_pages: int,
    log: list[dict[str, Any]],
    keyword: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    incomplete = False
    for category in categories:
        _, path, referer, defaults = CATEGORIES[category]
        seen: set[tuple[str, ...]] = set()
        for page in range(1, max_pages + 1):
            try:
                data = dict(
                    defaults,
                    keyWord=keyword if keyword is not None else re.sub(r"\s+", "", name),
                    pageNo=page,
                    pageSize=10,
                )
                html = client.fetch(BASE + path, data, BASE + referer)
                candidates = parse_candidates(html, category)
                urls = tuple(sorted(item["detail_url"] for item in candidates))
                log.append(
                    {
                        "category": category,
                        "page": page,
                        "keyword": data["keyWord"],
                        "candidate_count": len(candidates),
                    }
                )
                if not candidates:
                    if not re.search(
                        r"暂无|没有|无符合|无相关|_totalCount|totalCount|xmjs_list|cgqList|zzkgList",
                        html,
                    ):
                        incomplete = True
                        log.append({"category": category, "error": "列表结构未知或请求受限"})
                    break
                if urls in seen:
                    incomplete = True
                    log.append({"category": category, "error": "分页重复，未确认遍历完整"})
                    break
                seen.add(urls)
                for candidate in candidates:
                    left, right = norm(name), norm(str(candidate["project_name"]))
                    candidate["match_score"] = 100 if left == right else (90 if len(left) >= 4 and left in right else 0)
                    if candidate["match_score"]:
                        found[(category, str(candidate["detail_url"]))] = candidate
                if len(candidates) < 10:
                    break
                if page == max_pages:
                    incomplete = True
                    log.append({"category": category, "warning": "达到分页上限，可能还有候选"})
            except Exception as exc:
                incomplete = True
                log.append({"category": category, "page": page, "error": type(exc).__name__ + ": " + str(exc)})
                break
    return sorted(found.values(), key=lambda item: (-int(item["match_score"]), str(item["detail_url"]))), incomplete


def _empty_result(name: str, stage: str, message: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "message": message,
        "project_name": name,
        "matched_project_name": "",
        "detail_url": "",
        "project_type": "",
        "match_score": None,
        "quality_status": "",
        "unit": "万元",
        "annual": [],
        "latest": [],
        "candidates": [],
        "issues": [],
    }


def _public_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_name": str(item.get("project_name") or ""),
        "detail_url": str(item.get("detail_url") or ""),
        "project_type": str(item.get("project_type") or ""),
        "disclosure_end_date": str(item.get("disclosure_end_date") or ""),
        "match_score": int(item.get("match_score") or 0),
    }


def collect_listing_financials(
    project_name: str,
    *,
    detail_url: str = "",
    category: str = "all",
    client: Client | None = None,
    max_pages: int = 3,
) -> dict[str, Any]:
    name = str(project_name or "").strip()
    if not name:
        raise ValueError("缺少入参 project_name")
    selected_category = category or "all"
    if selected_category != "all" and selected_category not in CATEGORIES:
        raise ValueError("category 应为 all/zz_gz/zz_fgz/cq_gz/cq_fgz")
    pages = max(1, min(int(max_pages), 20))
    http = client or Client()
    direct = str(detail_url or "").strip()
    log: list[dict[str, Any]] = []
    selected: dict[str, Any]
    if direct:
        if not valid_url(direct):
            raise ValueError("detail_url 必须是官网HTTPS项目详情地址")
        source = http.fetch(direct)
        titles = [
            clean(node.text())
            for _, doc in documents(source)
            for tag in ("h1", "h2", "title")
            for node in doc.root.find(tag)
        ]
        if not any(norm(name) in title for title in titles):
            body = clean(DOM(source).root.text())
            if norm(name) not in body:
                raise ValueError("指定详情页未找到输入名称，请核对项目全称")
        selected = {
            "project_name": name,
            "detail_url": direct,
            "category": selected_category,
            "project_type": CATEGORIES[selected_category][0] if selected_category != "all" else "按指定详情页",
            "match_score": 100,
        }
    else:
        categories = list(CATEGORIES) if selected_category == "all" else [selected_category]
        candidates, incomplete = search(http, name, categories, pages, log)
        if not candidates and not incomplete:
            company = re.match(r".*?(?:股份有限公司|有限责任公司|有限公司|有限合伙[)）])", name)
            keyword = company.group(0) if company else re.sub(r"(?:增资项目|增资)$", "", name)
            if keyword != name:
                candidates, incomplete = search(http, name, categories, pages, log, keyword)
        if not candidates:
            stage = "search_incomplete" if incomplete else "not_found"
            message = "搜索未完成" if incomplete else "没有找到名称匹配的项目"
            return _empty_result(name, stage, message)
        best = [item for item in candidates if item["match_score"] == candidates[0]["match_score"]]
        if len(candidates) > 1 or incomplete:
            result = _empty_result(
                name,
                "selection_required",
                "存在多个同名或相似项目，或搜索未完成；请从候选中选定详情页后重试",
            )
            result["candidates"] = [_public_candidate(item) for item in candidates]
            return result
        selected = best[0]
        source = http.fetch(str(selected["detail_url"]))
    financial = extract_financial_data(source)
    quality_obj = financial.get("quality")
    quality = quality_obj if isinstance(quality_obj, dict) else {}
    issue_obj = quality.get("issues")
    raw_score = selected.get("match_score")
    return {
        "stage": "done",
        "message": "",
        "project_name": name,
        "matched_project_name": str(selected.get("project_name") or ""),
        "detail_url": str(selected.get("detail_url") or ""),
        "project_type": str(selected.get("project_type") or ""),
        "match_score": raw_score if isinstance(raw_score, int) else None,
        "quality_status": str(quality.get("status") or ""),
        "unit": "万元",
        "annual": financial.get("annual") or [],
        "latest": financial.get("latest") or [],
        "candidates": [],
        "issues": [str(part) for part in issue_obj] if isinstance(issue_obj, list) else [],
    }
