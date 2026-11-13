"""
PDF 文本层补全

针对 Paddle OCR-VL 表格行丢失等问题：用 PyMuPDF 提取 PDF 内置文本层，
逐页对比 OCR 与文本层，在 OCR 明确缺失且可同源验证的行注入 md_content 与 Anchor 片段。

保守策略：仅注入能在同页文本层定位 bbox、且 OCR 归一化文本中确未出现的逻辑行；
宁肯不补，也不向模型灌入可能错误的文本。

标的基本情况：当 OCR 未解析出任一资产二级分类（房屋、土地、机械设备等）的详细信息时，
从文本层选取信息量最大的二级分类，按「标的基本信息-{分类}{详情}」格式补全。

页码与 Paddle OCR 分页（0-based page_num / ``---`` 分隔）保持一致，仅对 OCR 已解析页补全。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore


# 页码标记（与 Paddle md_content 中常见格式一致）
_PAGE_MARKER_PATTERNS = [
    re.compile(r"第\s*(\d+)\s*页\s*共\s*\d+\s*页", re.IGNORECASE),
    re.compile(r"第\s*(\d+)\s*页", re.IGNORECASE),
]

# Paddle parse_file 合并各页 md_content 时使用的分隔符（与 paddle/client.py 一致）
PADDLE_MD_PAGE_SEPARATOR = "\n\n---\n\n"


class MdPageJoinMode(str, Enum):
    """md_content 分页/合并方式"""

    MARKERS = "markers"  # 文内「第 N 页」标记
    SEPARATOR = "separator"  # --- 分隔
    SINGLE = "single"  # 单页或未识别


@dataclass(frozen=True)
class MdPageSplitResult:
    sections: Dict[int, str]
    join_mode: MdPageJoinMode

_SUPPLEMENT_START = "<!-- TEXT_LAYER_SUPPLEMENT_START -->"
_SUPPLEMENT_END = "<!-- TEXT_LAYER_SUPPLEMENT_END -->"


@dataclass(frozen=True)
class FieldSupplementRule:
    """单条补全规则：OCR 侧检测关键字 + 文本层侧关键字"""

    name: str
    ocr_keywords: Tuple[str, ...]
    text_layer_keywords: Tuple[str, ...]


@dataclass(frozen=True)
class TextLayerSupplementSegment:
    """
    单条文本层补全片段（供 Anchor 溯源 / Paddle 高亮）

    bbox 为 144 DPI 像素坐标，与 Paddle layout_block 及 PaddlePDFHighlighter 一致。
    """

    text: str
    page_idx: int
    bbox: List[float]
    segment_type: str = "text_layer_supplement"


# 信息披露申请书常见易丢失字段（可按业务扩展）
DEFAULT_FIELD_RULES: Tuple[FieldSupplementRule, ...] = (
    FieldSupplementRule(
        name="核准或备案机构",
        ocr_keywords=("核准或备案机构", "核准（备案）机构"),
        text_layer_keywords=("核准或备案机构", "核准（备案）机构"),
    ),
    FieldSupplementRule(
        name="评估机构",
        ocr_keywords=("评估机构",),
        text_layer_keywords=("评估机构",),
    ),
    FieldSupplementRule(
        name="评估基准日",
        ocr_keywords=("评估基准日",),
        text_layer_keywords=("评估基准日",),
    ),
    FieldSupplementRule(
        name="账面价值",
        ocr_keywords=("账面价值",),
        text_layer_keywords=("账面价值",),
    ),
    FieldSupplementRule(
        name="资产评估值",
        ocr_keywords=("资产评估值", "评估价值"),
        text_layer_keywords=("资产评估值", "评估价值"),
    ),
)


@dataclass(frozen=True)
class AssetSubCategoryRule:
    """标的基本情况下的二级资产分类"""

    name: str
    header_matchers: Tuple[str, ...]
    detail_field_labels: Tuple[str, ...]


# 二级分类（匹配顺序：更长/更具体的在前）
ASSET_SUB_CATEGORY_RULES: Tuple[AssetSubCategoryRule, ...] = (
    AssetSubCategoryRule(
        name="交通运输工具（飞行器类）",
        header_matchers=("交通运输工具（飞行器类）", "交通运输工具飞行器", "飞行器"),
        detail_field_labels=(
            "号牌号码",
            "型号",
            "所在地",
            "国籍",
            "购置日期",
            "登记日期",
            "使用年限",
            "颜色",
            "飞行里程数",
            "数量",
            "配置情况",
            "是否有抵押",
        ),
    ),
    AssetSubCategoryRule(
        name="交通运输工具",
        header_matchers=("交通运输工具", "交通运"),
        detail_field_labels=(
            "号牌号码",
            "型号",
            "所在地",
            "购置日期",
            "登记日期",
            "使用年限",
            "颜色",
            "行驶公里数",
            "数量",
            "是否有抵押",
        ),
    ),
    AssetSubCategoryRule(
        name="机械设备",
        header_matchers=("机械设备", "机械"),
        detail_field_labels=(
            "名称",
            "所在地",
            "规格型号",
            "计量单位",
            "数量",
            "成新率",
            "是否有抵押",
        ),
    ),
    AssetSubCategoryRule(
        name="在建工程",
        header_matchers=("在建工程", "在建"),
        detail_field_labels=("坐落位置", "描述", "是否有抵押"),
    ),
    AssetSubCategoryRule(
        name="房屋",
        header_matchers=("房屋",),
        detail_field_labels=(
            "坐落位置",
            "房产证号",
            "不动产权证号",
            "建筑面积",
            "目前用途",
            "附属设施",
            "使用年限",
            "已用年限",
            "是否为住宅",
            "是否有抵押",
        ),
    ),
    AssetSubCategoryRule(
        name="土地",
        header_matchers=("土地",),
        detail_field_labels=(
            "坐落位置",
            "土地证号",
            "不动产权证号",
            "土地面积",
            "用途",
            "类型",
            "使用年限",
            "已用年限",
            "是否有抵押",
        ),
    ),
    AssetSubCategoryRule(
        name="存货",
        header_matchers=("存货",),
        detail_field_labels=(
            "名称",
            "计量单位",
            "所在地",
            "规格型号",
            "数量",
            "是否有抵押",
        ),
    ),
    AssetSubCategoryRule(
        name="债权",
        header_matchers=("债权",),
        detail_field_labels=(
            "名称",
            "账面价值",
            "本金",
            "孳息",
            "基准日",
            "其他费用",
            "债务人相关信息",
            "是否有质押",
        ),
    ),
    AssetSubCategoryRule(
        name="其他",
        header_matchers=("其他",),
        detail_field_labels=(
            "名称",
            "计量单位",
            "所在地",
            "型号",
            "数量",
            "资产描述",
            "是否有抵押",
        ),
    ),
)

_ASSET_SECTION_START_MARKERS = ("标的基本情况", "标的基本")
_ASSET_SECTION_END_MARKERS = ("资产评估情况", "资产评估")
_CHECKBOX_LINE_RE = re.compile(r"^[□☑☐\s是否]+$")
_UNIT_ONLY_RE = re.compile(
    r"^(平方米|万元|万公里|%|批|台|套|辆|件|个|吨|千克|kg|m²|m2|/|\-+|—+)$",
    re.IGNORECASE,
)
# 信息量判定：至少达到该得分才视为「有详细信息」
_ASSET_DETAIL_MIN_SCORE = 12


def extract_page_texts(pdf_bytes: bytes) -> Dict[int, str]:
    """
    按页提取 PDF 文本层（0-based 页码 -> 文本）

    Args:
        pdf_bytes: PDF 文件二进制内容

    Returns:
        页索引到文本的映射；无文本页可能为空字符串
    """
    if not pdf_bytes:
        return {}
    if fitz is None:
        logger.warning("PyMuPDF 未安装，无法提取 PDF 文本层")
        return {}

    result: Dict[int, str] = {}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for i in range(doc.page_count):
                result[i] = doc[i].get_text("text") or ""
        finally:
            doc.close()
    except Exception as e:
        logger.error(f"PDF 文本层提取失败: {e}", exc_info=True)
        return {}
    return result


def _normalize_for_match(text: str) -> str:
    """
    匹配用归一化：去掉所有空白（OCR 常插入空格/换行，如「评 估 机 构」）
    """
    if not text:
        return ""
    return re.sub(r"\s+", "", text)


def _contains_any(text: str, keywords: Tuple[str, ...]) -> bool:
    """关键字是否出现在文本中（忽略空白差异）"""
    if not text:
        return False
    normalized = _normalize_for_match(text)
    for kw in keywords:
        if not kw:
            continue
        if _normalize_for_match(kw) in normalized:
            return True
    return False


# 所有字段标签（用于判断「下一行是否是另一个字段」）
_ALL_FIELD_LABEL_KEYWORDS: Tuple[str, ...] = tuple(
    dict.fromkeys(
        kw for rule in DEFAULT_FIELD_RULES for kw in rule.text_layer_keywords
    )
)

# 已知标签（字段 + 资产分类 + 详情字段，用于文本层拆行合并）
_ALL_KNOWN_LABEL_KEYWORDS: Tuple[str, ...] = tuple(
    dict.fromkeys(
        list(_ALL_FIELD_LABEL_KEYWORDS)
        + [label for rule in ASSET_SUB_CATEGORY_RULES for label in rule.detail_field_labels]
        + [matcher for rule in ASSET_SUB_CATEGORY_RULES for matcher in rule.header_matchers]
    )
)

# 不作为独立补全行注入的章节标题
_SECTION_HEADER_ONLY_KEYWORDS: Tuple[str, ...] = (
    "标的基本情况",
    "标的基本",
    "资产评估情况",
    "资产评估",
    "信息披露申请书",
)

_SUPPLEMENT_BLOCK_RE = re.compile(
    r"<!--\s*TEXT_LAYER_SUPPLEMENT_START\s*-->.*?<!--\s*TEXT_LAYER_SUPPLEMENT_END\s*-->",
    re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# 行尾勾选框等噪声
_CHECKBOX_SUFFIX_RE = re.compile(r"\s*[□☑☐]\s*.*$")


def _normalize_field_line(line: str) -> str:
    """合并空白并去掉行尾勾选框选项"""
    line = _CHECKBOX_SUFFIX_RE.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


def _value_after_keyword(line: str, keyword: str) -> str:
    """关键字之后的有效取值部分"""
    idx = line.find(keyword)
    if idx < 0:
        return ""
    rest = line[idx + len(keyword) :].strip()
    rest = _CHECKBOX_SUFFIX_RE.sub("", rest).strip()
    return rest


def _is_pure_label_line(line: str, keyword: str) -> bool:
    """
    判断是否为「仅字段名、取值在下一行」的文本层行。

    PDF 文本层常见：
        评估机构
        北京德平达盛资产评估有限责任公司
    """
    stripped = line.strip()
    if stripped == keyword:
        return True
    rest = _value_after_keyword(line, keyword)
    if not rest:
        return True
    if len(rest) <= 2:
        return True
    if re.match(r"^[A-Za-z\.\u6838准备案□☑☐\s]+$", rest):
        return True
    return False


def _line_starts_other_field_label(line: str, current_keyword: str) -> bool:
    """下一行是否是另一个表单字段标签"""
    stripped = line.strip()
    for kw in _ALL_KNOWN_LABEL_KEYWORDS:
        if kw == current_keyword:
            continue
        if stripped == kw or stripped.startswith(kw):
            return True
    return False


def _extract_field_lines_from_page(text: str, rule: FieldSupplementRule) -> List[str]:
    """
    从单页文本层提取「字段名 + 取值」完整行，供 LLM 按封面字段同样方式理解。

    示例输出：
        评估机构 北京德平达盛资产评估有限责任公司
        核准或备案机构 北京市首都公路发展集团有限公司
    """
    lines = [ln.strip() for ln in text.splitlines()]
    results: List[str] = []
    consumed: Set[int] = set()

    i = 0
    while i < len(lines):
        if i in consumed:
            i += 1
            continue

        line = lines[i]
        if not line:
            i += 1
            continue

        matched_kw: Optional[str] = None
        for kw in rule.text_layer_keywords:
            if kw in line:
                matched_kw = kw
                break
        if not matched_kw:
            i += 1
            continue

        entry: Optional[str] = None

        if _is_pure_label_line(line, matched_kw):
            # 字段名与取值分行：合并后续 1～2 行
            parts = [matched_kw]
            j = i + 1
            while j < len(lines) and j <= i + 2:
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if _line_starts_other_field_label(nxt, matched_kw):
                    break
                if any(kw in nxt for kw in rule.text_layer_keywords if nxt != matched_kw):
                    break
                parts.append(nxt)
                consumed.add(j)
                j += 1
            entry = _normalize_field_line(" ".join(parts))
            i = max(i + 1, j)
        else:
            entry = _normalize_field_line(line)
            i += 1

        if entry and _value_after_keyword(entry, matched_kw):
            results.append(entry)

    return results


def _dedupe_preserve_order(lines: List[str]) -> List[str]:
    seen: Set[str] = set()
    unique: List[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


def _collapse_text(text: str) -> str:
    """去除空白便于匹配 PDF 文本层拆行"""
    return re.sub(r"\s+", "", text)


def _is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _CHECKBOX_LINE_RE.match(stripped):
        return True
    if stripped in ("是", "否", "有", "无"):
        return True
    if _CHECKBOX_SUFFIX_RE.search(stripped) and len(stripped) <= 6:
        return True
    if _UNIT_ONLY_RE.match(stripped):
        return True
    if re.match(r"^第\s*\d+\s*页", stripped):
        return True
    if stripped.startswith("版本："):
        return True
    return False


def _is_value_line(line: str, labels: Tuple[str, ...]) -> bool:
    stripped = _normalize_field_line(line)
    if _is_noise_line(stripped):
        return False
    collapsed = _collapse_text(stripped)
    for label in labels:
        if collapsed == _collapse_text(label):
            return False
        if collapsed.startswith(_collapse_text(label)) and len(collapsed) <= len(_collapse_text(label)) + 2:
            return False
    for rule in ASSET_SUB_CATEGORY_RULES:
        for matcher in rule.header_matchers:
            if collapsed == _collapse_text(matcher):
                return False
    return len(stripped) >= 1


def _match_asset_subcategory_at(lines: List[str], index: int) -> Optional[str]:
    """根据当前行及后续拆行匹配二级分类名（长匹配优先）"""
    cluster = "".join(lines[j].strip() for j in range(index, min(index + 6, len(lines))))
    collapsed = _collapse_text(cluster)

    if "交通运输工具" in collapsed and "飞行器" in collapsed:
        return "交通运输工具（飞行器类）"
    if collapsed.startswith("交通运输工具") or collapsed.startswith("交通运"):
        return "交通运输工具"
    if collapsed.startswith("机械设备") or (
        collapsed.startswith("机械") and "设备" in collapsed[:8]
    ):
        return "机械设备"
    if collapsed.startswith("在建工程") or (
        collapsed.startswith("在建") and "工程" in collapsed[:8]
    ):
        return "在建工程"
    if collapsed.startswith("房屋"):
        return "房屋"
    if collapsed.startswith("土地"):
        return "土地"
    if collapsed.startswith("存货"):
        return "存货"
    if collapsed.startswith("债权"):
        return "债权"
    if collapsed.startswith("其他"):
        return "其他"
    return None


def _slice_asset_basic_region(text: str) -> str:
    """截取「标的基本情况」至「资产评估」之间的文本层片段"""
    if not text:
        return ""
    collapsed = text
    start = -1
    for marker in _ASSET_SECTION_START_MARKERS:
        idx = collapsed.find(marker)
        if idx >= 0:
            start = idx
            break
    if start < 0:
        return ""
    region = collapsed[start:]
    end = len(region)
    for marker in _ASSET_SECTION_END_MARKERS:
        idx = region.find(marker)
        if idx > 0:
            end = min(end, idx)
    return region[:end]


def _split_asset_subcategory_sections(text: str) -> Dict[str, str]:
    """将标的基本情况区域按二级分类切分为 name -> 原始片段文本"""
    region = _slice_asset_basic_region(text)
    if not region:
        return {}

    lines = [ln.strip() for ln in region.splitlines()]
    sections: Dict[str, List[str]] = {}
    current_name: Optional[str] = None
    i = 0
    while i < len(lines):
        name = _match_asset_subcategory_at(lines, i)
        if name:
            current_name = name
            if current_name not in sections:
                sections[current_name] = []
            i += 1
            continue
        if current_name:
            line = lines[i]
            if line and not _is_noise_line(line):
                if re.match(r"^第\s*\d+\s*页", line) or line.startswith("版本："):
                    i += 1
                    continue
                if "===== PAGE" in line:
                    i += 1
                    continue
                sections[current_name].append(line)
        i += 1

    return {name: "\n".join(chunk) for name, chunk in sections.items() if chunk}


def _get_subcategory_rule(name: str) -> Optional[AssetSubCategoryRule]:
    for rule in ASSET_SUB_CATEGORY_RULES:
        if rule.name == name:
            return rule
    return None


def _match_detail_label_at(
    lines: List[str], index: int, labels: Tuple[str, ...]
) -> Optional[Tuple[str, int, str]]:
    """
    匹配字段标签（支持拆行，如「名」+「称」→ 名称）。

    Returns:
        (标签名, 标签占用行数, 同行残余取值)
    """
    for join_len in (1, 2, 3, 4):
        if index + join_len > len(lines):
            continue
        cluster = "".join(lines[index + k].strip() for k in range(join_len))
        collapsed = _collapse_text(cluster)
        for label in labels:
            label_c = _collapse_text(label)
            if collapsed == label_c:
                return label, join_len, ""
            if collapsed.startswith(label_c):
                remainder = collapsed[len(label_c) :].strip()
                if remainder and not _is_noise_line(remainder):
                    return label, join_len, remainder
    return None


def _extract_label_value_pairs(
    section_text: str, labels: Tuple[str, ...]
) -> List[Tuple[str, str]]:
    """从分类片段中提取「字段标签 -> 取值」对（兼容 PDF 拆行）"""
    lines = [ln.strip() for ln in section_text.splitlines() if ln.strip()]
    pairs: List[Tuple[str, str]] = []
    all_labels = labels
    i = 0
    while i < len(lines):
        if _is_noise_line(lines[i]):
            i += 1
            continue

        matched = _match_detail_label_at(lines, i, all_labels)
        if not matched:
            i += 1
            continue

        label, consumed, inline_value = matched
        if inline_value:
            pairs.append((label, inline_value))
            i += consumed
            continue

        values: List[str] = []
        j = i + consumed
        while j < len(lines) and j <= i + consumed + 4:
            nxt = lines[j].strip()
            if not nxt or _is_noise_line(nxt):
                j += 1
                continue
            if _match_detail_label_at(lines, j, all_labels):
                break
            if _match_asset_subcategory_at(lines, j):
                break
            values.append(_normalize_field_line(nxt))
            j += 1
        if values:
            pairs.append((label, " ".join(values)))
        i = max(i + consumed, j)

    return pairs


def _score_asset_section(section_text: str, rule: AssetSubCategoryRule) -> int:
    """估算二级分类片段的信息量（仅计「字段标签 + 有效取值」对）"""
    pairs = _extract_label_value_pairs(section_text, rule.detail_field_labels)
    score = 0
    for label, value in pairs:
        if not label:
            continue
        val = value.strip()
        if not val or val in ("/", "-", "—") or _UNIT_ONLY_RE.match(val):
            continue
        score += 4 + len(val)
    return score


def _format_asset_category_details(section_text: str, rule: AssetSubCategoryRule) -> str:
    """格式化为「字段：值」拼接的详情文本"""
    pairs = _extract_label_value_pairs(section_text, rule.detail_field_labels)
    parts: List[str] = []
    for label, value in pairs:
        val = value.strip()
        if not val or val in ("/", "-", "—") or _UNIT_ONLY_RE.match(val):
            continue
        if label:
            parts.append(f"{label}：{val}")
        else:
            parts.append(val)
    return "".join(parts)


def _ocr_has_any_asset_subcategory_details(ocr_text: str) -> bool:
    """OCR 是否已解析出至少一个二级分类的详细信息（忽略 OCR 空格差异）"""
    sections = _split_asset_subcategory_sections(ocr_text)
    for name, body in sections.items():
        rule = _get_subcategory_rule(name)
        if not rule:
            continue
        if _score_asset_section(body, rule) >= _ASSET_DETAIL_MIN_SCORE:
            return True
    return False


def _build_asset_basic_supplement_line(native_text: str) -> Optional[str]:
    """
    从文本层选取信息量最大的二级分类，生成补全行。

    格式：标的基本信息-{二级分类}{详情}
    """
    sections = _split_asset_subcategory_sections(native_text)
    if not sections:
        return None

    best_name: Optional[str] = None
    best_score = 0
    best_body = ""

    for name, body in sections.items():
        rule = _get_subcategory_rule(name)
        if not rule:
            continue
        score = _score_asset_section(body, rule)
        if score > best_score:
            best_score = score
            best_name = name
            best_body = body

    if not best_name or best_score < _ASSET_DETAIL_MIN_SCORE:
        return None

    rule = _get_subcategory_rule(best_name)
    if not rule:
        return None

    details = _format_asset_category_details(best_body, rule)
    if not details:
        return None

    line = f"标的基本信息-{best_name}{details}"
    logger.info(
        f"标的基本情况文本层补全 | 二级分类: {best_name} | 信息量得分: {best_score} | "
        f"详情长度: {len(details)}"
    )
    return line


def _compute_asset_basic_supplement(
    ocr_full_text: str,
    native_full_text: str,
) -> Optional[str]:
    """当 OCR 无任何二级分类详情时，从文本层补全信息量最大的一类"""
    if _ocr_has_any_asset_subcategory_details(ocr_full_text):
        return None
    return _build_asset_basic_supplement_line(native_full_text)


def _find_asset_basic_injection_page(text_layer_pages: Dict[int, str]) -> int:
    """定位注入页：优先含「标的基本」的页，否则取最小页码"""
    for page_idx in sorted(text_layer_pages.keys()):
        page_text = text_layer_pages[page_idx]
        if any(marker in page_text for marker in _ASSET_SECTION_START_MARKERS):
            return page_idx
    return min(text_layer_pages.keys()) if text_layer_pages else 0


def _merge_supplement_block(existing: str, extra_line: str) -> str:
    """将标的基本情况补全行并入已有补全块"""
    if not extra_line:
        return existing
    if not existing:
        return "\n".join(
            [_SUPPLEMENT_START, "【PDF文本层补全】", extra_line, _SUPPLEMENT_END]
        )
    if extra_line in existing:
        return existing
    if _SUPPLEMENT_END in existing:
        return existing.replace(
            _SUPPLEMENT_END, f"{extra_line}\n{_SUPPLEMENT_END}", 1
        )
    return f"{existing}\n{extra_line}"


def _split_md_by_page_markers(md_content: str) -> Dict[int, str]:
    """按文内「第 N 页」标记切分（0-based page_idx）"""
    markers: List[Tuple[int, int, int]] = []
    for pattern in _PAGE_MARKER_PATTERNS:
        for match in pattern.finditer(md_content):
            page_num = int(match.group(1))
            page_idx = max(0, page_num - 1)
            markers.append((match.start(), page_num, page_idx))

    if not markers:
        return {}

    markers.sort(key=lambda x: x[0])
    deduped: List[Tuple[int, int, int]] = []
    last_pos = -1
    for start, page_num, page_idx in markers:
        if start == last_pos:
            continue
        deduped.append((start, page_num, page_idx))
        last_pos = start

    sections: Dict[int, str] = {}
    if deduped[0][0] > 0:
        sections[0] = md_content[: deduped[0][0]]

    for i, (start, _page_num, page_idx) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(md_content)
        chunk = md_content[start:end]
        if page_idx in sections:
            sections[page_idx] += "\n" + chunk
        else:
            sections[page_idx] = chunk
    return sections


def split_md_content_by_page(
    md_content: str,
    expected_page_count: Optional[int] = None,
) -> MdPageSplitResult:
    """
    将 OCR md_content 按页切分，页码与 PyMuPDF / Paddle page_num 对齐（0-based）。

    优先级：
    1. 文内「第 N 页」标记（且能切出多页）
    2. Paddle 默认页间分隔符 ``\\n\\n---\\n\\n``
    3. 整篇作为第 0 页
    """
    if not md_content:
        return MdPageSplitResult({}, MdPageJoinMode.SINGLE)

    # Paddle 合并 md 时使用 ---，优先按分隔符分页，避免文内「第4页」等字样干扰
    if PADDLE_MD_PAGE_SEPARATOR in md_content:
        parts = md_content.split(PADDLE_MD_PAGE_SEPARATOR)
        sections = {i: part for i, part in enumerate(parts)}
        if len(sections) > 1:
            if expected_page_count and len(sections) != expected_page_count:
                logger.warning(
                    f"md_content 按 '---' 切分得到 {len(sections)} 页，"
                    f"与 PDF 页数 {expected_page_count} 不一致，仍以切分结果为准"
                )
            logger.debug(
                f"md_content 按 Paddle 分隔符分页 | 页数: {len(sections)} | "
                f"expected: {expected_page_count}"
            )
            return MdPageSplitResult(sections, MdPageJoinMode.SEPARATOR)

    marker_sections = _split_md_by_page_markers(md_content)
    if len(marker_sections) > 1:
        return MdPageSplitResult(marker_sections, MdPageJoinMode.MARKERS)

    if marker_sections:
        return MdPageSplitResult(marker_sections, MdPageJoinMode.MARKERS)

    return MdPageSplitResult({0: md_content}, MdPageJoinMode.SINGLE)


def split_md_content_by_page_legacy(md_content: str) -> Dict[int, str]:
    """兼容旧调用：仅返回 sections 字典"""
    return split_md_content_by_page(md_content).sections


def _align_page_sections(
    sections: Dict[int, str],
    expected_page_count: Optional[int],
    supplement_pages: Optional[Set[int]] = None,
) -> Dict[int, str]:
    """
    将分页结果对齐到 PDF 总页数（0..N-1），避免补全落在「无 OCR 分段」的页时被迫叠到文末。
    """
    max_idx = max(sections.keys()) if sections else -1
    if supplement_pages:
        max_idx = max(max_idx, max(supplement_pages))
    if expected_page_count:
        max_idx = max(max_idx, expected_page_count - 1)
    if max_idx < 0:
        return dict(sections)
    aligned: Dict[int, str] = {}
    for i in range(max_idx + 1):
        aligned[i] = sections.get(i, "")
    return aligned


def _merge_md_page_sections(
    ocr_sections: Dict[int, str],
    page_supplements: Dict[int, str],
    join_mode: MdPageJoinMode,
    expected_page_count: Optional[int] = None,
) -> str:
    """按页合并 OCR 片段与补全块，保持与切分时一致的分页结构"""
    ocr_sections = _align_page_sections(
        ocr_sections,
        expected_page_count,
        supplement_pages=set(page_supplements.keys()),
    )
    all_indices = sorted(set(ocr_sections.keys()) | set(page_supplements.keys()))
    if not all_indices:
        return ""

    page_chunks: List[str] = []
    for page_idx in all_indices:
        body = (ocr_sections.get(page_idx) or "").rstrip()
        supplement = page_supplements.get(page_idx)
        if supplement:
            body = f"{body}\n\n{supplement}" if body else supplement
        if body:
            page_chunks.append(body)

    if join_mode == MdPageJoinMode.SEPARATOR:
        return PADDLE_MD_PAGE_SEPARATOR.join(page_chunks)
    return "\n\n".join(page_chunks)


def _strip_html_for_diff(text: str) -> str:
    """将 OCR Markdown 转为可对比的纯文本（去掉 HTML、补全块等）"""
    if not text:
        return ""
    text = _SUPPLEMENT_BLOCK_RE.sub("", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("|", " ")
    return text


def _ocr_page_indices_for_supplement(
    ocr_page_sections: Dict[int, str],
    expected_page_count: Optional[int] = None,
) -> List[int]:
    """
    仅对 Paddle OCR 已分页的页码做补全，与 parse_result 页索引一致（0-based）。
    """
    indices = sorted(ocr_page_sections.keys())
    if expected_page_count is not None and expected_page_count > 0:
        indices = [i for i in indices if 0 <= i < expected_page_count]
    return indices


def _is_section_header_only(line: str) -> bool:
    collapsed = _collapse_text(line)
    if not collapsed:
        return True
    for header in _SECTION_HEADER_ONLY_KEYWORDS:
        if collapsed == _collapse_text(header):
            return True
    for rule in ASSET_SUB_CATEGORY_RULES:
        for matcher in rule.header_matchers:
            if collapsed == _collapse_text(matcher):
                return True
    return False


def _has_substantial_cjk_or_digit(text: str) -> bool:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    digits = len(re.findall(r"\d", text))
    return cjk >= 2 or (cjk >= 1 and digits >= 1)


def _is_meaningful_supplement_line(line: str, min_line_chars: int) -> bool:
    """保守判定：是否值得作为补全候选行"""
    normalized = _normalize_field_line(line)
    if _is_noise_line(normalized):
        return False
    if _is_section_header_only(normalized):
        return False
    collapsed = _collapse_text(normalized)
    if len(collapsed) < min_line_chars:
        return False
    if not _has_substantial_cjk_or_digit(normalized):
        return False
    if collapsed in ("/", "-", "—"):
        return False
    return True


def _extract_value_part(line: str) -> str:
    """提取逻辑行中的取值部分（标签后的内容）"""
    normalized = _normalize_field_line(line)
    for sep in ("：", ":", " "):
        if sep in normalized:
            parts = normalized.split(sep, 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    for kw in sorted(_ALL_KNOWN_LABEL_KEYWORDS, key=len, reverse=True):
        if kw in normalized:
            rest = _value_after_keyword(normalized, kw)
            if rest:
                return rest
    return normalized


def _line_present_in_ocr(line: str, ocr_text: str) -> bool:
    """
    保守判断：OCR 是否已包含该逻辑行（归一化子串 + 取值部分双重校验）。
    """
    ocr_norm = _normalize_for_match(_strip_html_for_diff(ocr_text))
    line_norm = _normalize_for_match(line)
    if not line_norm:
        return True
    if line_norm in ocr_norm:
        return True

    value_part = _extract_value_part(line)
    value_norm = _normalize_for_match(value_part)
    if value_norm and len(value_norm) >= 4 and value_norm in ocr_norm:
        return True

    # 较长文本：取值前 8 字已在 OCR 中则视为已覆盖
    if len(value_norm) >= 8 and value_norm[:8] in ocr_norm:
        return True

    return False


def _extract_logical_lines_from_native_page(native_text: str) -> List[str]:
    """
    从单页文本层提取逻辑行（合并标签/取值拆行），供与 OCR 对比。
    """
    lines = [ln.strip() for ln in native_text.splitlines()]
    results: List[str] = []
    consumed: Set[int] = set()

    i = 0
    while i < len(lines):
        if i in consumed:
            i += 1
            continue

        line = lines[i]
        if not line or _is_noise_line(line):
            i += 1
            continue

        matched_kw: Optional[str] = None
        for kw in sorted(_ALL_KNOWN_LABEL_KEYWORDS, key=len, reverse=True):
            if kw in line:
                matched_kw = kw
                break

        if matched_kw:
            entry: Optional[str] = None
            if _is_pure_label_line(line, matched_kw):
                parts = [matched_kw]
                j = i + 1
                while j < len(lines) and j <= i + 2:
                    nxt = lines[j].strip()
                    if not nxt:
                        j += 1
                        continue
                    if _line_starts_other_field_label(nxt, matched_kw):
                        break
                    if any(
                        kw in nxt
                        for kw in _ALL_KNOWN_LABEL_KEYWORDS
                        if nxt != matched_kw and kw != matched_kw
                    ):
                        break
                    parts.append(nxt)
                    consumed.add(j)
                    j += 1
                entry = _normalize_field_line(" ".join(parts))
                i = max(i + 1, j)
            else:
                entry = _normalize_field_line(line)
                i += 1

            if entry and _value_after_keyword(entry, matched_kw):
                results.append(entry)
            continue

        normalized = _normalize_field_line(line)
        if _is_meaningful_supplement_line(normalized, min_line_chars=6):
            results.append(normalized)
        i += 1

    return results


def _is_page_alignment_trusted(
    page_join_mode: MdPageJoinMode,
    expected_page_count: Optional[int],
    ocr_page_count: int,
) -> bool:
    """
    分页是否可信：Paddle 按 ---/页码切分且段数与 PDF 页数一致时，才允许整页丢失恢复。
    """
    if page_join_mode == MdPageJoinMode.SINGLE:
        return False
    if not expected_page_count or expected_page_count <= 1:
        return False
    return ocr_page_count == expected_page_count


def _classify_page_supplement_mode(
    ocr_text: str,
    native_text: str,
    page_join_mode: MdPageJoinMode,
    expected_page_count: Optional[int],
    ocr_page_count: int,
    supplement_config: Dict[str, Any],
) -> str:
    """
    判定单页补全策略。

    Returns:
        ``skip`` | ``normal`` | ``whole_page_loss``
    """
    min_ocr_chars = int(supplement_config.get("min_ocr_page_chars", 30))
    whole_enabled = bool(supplement_config.get("whole_page_loss_enabled", True))
    whole_ocr_max = int(supplement_config.get("whole_page_loss_ocr_max_chars", 30))
    whole_native_min = int(supplement_config.get("whole_page_loss_native_min_chars", 40))

    ocr_plain = _strip_html_for_diff(ocr_text).strip()
    native_len = len(_collapse_text(native_text))

    if not native_text.strip():
        return "skip"

    alignment_trusted = _is_page_alignment_trusted(
        page_join_mode, expected_page_count, ocr_page_count
    )

    if (
        whole_enabled
        and alignment_trusted
        and len(ocr_plain) < whole_ocr_max
        and native_len >= whole_native_min
    ):
        return "whole_page_loss"

    if len(ocr_plain) < min_ocr_chars:
        logger.debug(
            f"文本层补全跳过 | OCR 过短且不满足整页丢失条件 | "
            f"OCR={len(ocr_plain)} 对齐可信={alignment_trusted}"
        )
        return "skip"

    return "normal"


def _verify_line_on_page(
    doc: Any,
    page_idx: int,
    line: str,
) -> bool:
    """在同页文本层中能否定位到该行（用于保守校验）"""
    if doc is None or fitz is None:
        return False
    if page_idx < 0 or page_idx >= doc.page_count:
        return False
    from src.utils.pdf_text_layer_bbox import find_text_bbox_on_page

    page = doc[page_idx]
    return find_text_bbox_on_page(page, line) is not None


def _extract_missing_lines_for_page(
    ocr_text: str,
    native_text: str,
    page_idx: int,
    doc: Any,
    doc_page_idx: int,
    supplement_config: Dict[str, Any],
    page_mode: str = "normal",
) -> List[str]:
    """
    方案 A：逐页 diff，返回可安全注入的缺失行列表。

    page_mode:
        - ``normal``：常规行级 diff（OCR 有部分正文）
        - ``whole_page_loss``：整页 OCR 丢失，从文本层恢复（更严行数上限）
    """
    if page_mode == "skip":
        return []

    min_line_chars = int(supplement_config.get("min_line_chars", 6))
    max_lines = int(supplement_config.get("max_lines_per_page", 20))
    if page_mode == "whole_page_loss":
        max_lines = int(supplement_config.get("whole_page_loss_max_lines", 15))
    require_bbox = bool(supplement_config.get("require_bbox_on_page", True))

    if not native_text.strip():
        return []

    if page_mode == "whole_page_loss":
        logger.info(
            f"文本层整页丢失恢复 | 页 {page_idx + 1} | "
            f"OCR 正文={len(_strip_html_for_diff(ocr_text).strip())} 字 | "
            f"文本层={len(_collapse_text(native_text))} 字"
        )

    missing: List[str] = []
    for line in _extract_logical_lines_from_native_page(native_text):
        if not _is_meaningful_supplement_line(line, min_line_chars):
            continue
        if page_mode == "normal" and _line_present_in_ocr(line, ocr_text):
            continue
        if require_bbox and not _verify_line_on_page(doc, doc_page_idx, line):
            logger.debug(
                f"文本层补全跳过（未在同页定位）| 页 {page_idx + 1} | {line[:50]}..."
            )
            continue
        missing.append(line)
        if len(missing) >= max_lines:
            logger.warning(
                f"文本层补全达到单页上限 | 页 {page_idx + 1} | "
                f"mode={page_mode} max_lines={max_lines}"
            )
            break

    return _dedupe_preserve_order(missing)


def _build_supplement_block(lines: List[str]) -> str:
    unique_lines = _dedupe_preserve_order(lines)
    return "\n".join(
        [
            _SUPPLEMENT_START,
            "【PDF文本层补全】",
            *unique_lines,
            _SUPPLEMENT_END,
        ]
    )


def compute_page_supplements(
    ocr_page_sections: Dict[int, str],
    text_layer_pages: Dict[int, str],
    field_rules: Tuple[FieldSupplementRule, ...] = DEFAULT_FIELD_RULES,
    expected_page_count: Optional[int] = None,
    doc: Any = None,
    page_offset: int = 0,
    supplement_config: Optional[Dict[str, Any]] = None,
    page_join_mode: MdPageJoinMode = MdPageJoinMode.SINGLE,
) -> Dict[int, str]:
    """
    对比 OCR 分页文本与 PDF 文本层，生成每页需注入的补全块（方案 A：逐页 diff）。

    仅处理 Paddle OCR 已分页的页码；field_rules 保留以兼容旧调用，不再参与 diff 逻辑。

    Returns:
        page_idx (0-based) -> 补全文本（含标记注释）
    """
    if supplement_config is None:
        from config.paddle_config import get_text_layer_supplement_config

        supplement_config = get_text_layer_supplement_config()

    if field_rules is not DEFAULT_FIELD_RULES:
        logger.debug("compute_page_supplements: field_rules 参数已忽略，使用 page_diff 模式")

    supplements: Dict[int, str] = {}
    page_indices = _ocr_page_indices_for_supplement(
        ocr_page_sections,
        expected_page_count,
    )
    ocr_page_count = len(page_indices)

    for page_idx in page_indices:
        ocr_text = ocr_page_sections.get(page_idx, "")
        native_text = text_layer_pages.get(page_idx, "")
        doc_page_idx = page_offset + page_idx

        page_mode = _classify_page_supplement_mode(
            ocr_text=ocr_text,
            native_text=native_text,
            page_join_mode=page_join_mode,
            expected_page_count=expected_page_count,
            ocr_page_count=ocr_page_count,
            supplement_config=supplement_config,
        )

        missing_lines = _extract_missing_lines_for_page(
            ocr_text=ocr_text,
            native_text=native_text,
            page_idx=page_idx,
            doc=doc,
            doc_page_idx=doc_page_idx,
            supplement_config=supplement_config,
            page_mode=page_mode,
        )
        if missing_lines:
            supplements[page_idx] = _build_supplement_block(missing_lines)
            logger.debug(
                f"文本层补全 | 页 {page_idx + 1} | mode={page_mode} "
                f"注入 {len(missing_lines)} 行"
            )

    # 标的基本情况：文档级补全（OCR 无任何二级分类详情时，结构化注入一行）
    ocr_full = "\n".join(
        ocr_page_sections.get(i, "") for i in sorted(ocr_page_sections)
    )
    native_full = "\n".join(
        text_layer_pages.get(i, "") for i in sorted(text_layer_pages)
    )
    asset_line = _compute_asset_basic_supplement(ocr_full, native_full)
    if asset_line:
        inject_page = _find_asset_basic_injection_page(text_layer_pages)
        if (
            inject_page in page_indices
            and not _line_present_in_ocr(asset_line, ocr_full)
        ):
            doc_page_idx = page_offset + inject_page
            require_bbox = bool(supplement_config.get("require_bbox_on_page", True))
            bbox_ok = (
                not require_bbox
                or _verify_line_on_page(doc, doc_page_idx, asset_line)
            )
            existing_block = supplements.get(inject_page, "")
            if bbox_ok and asset_line not in existing_block:
                supplements[inject_page] = _merge_supplement_block(
                    existing_block,
                    asset_line,
                )
                logger.debug(
                    f"标的基本情况补全已注入第 {inject_page + 1} 页 | 行: {asset_line[:120]}..."
                )
            elif not bbox_ok:
                logger.debug(
                    f"标的基本情况补全跳过（未在同页定位）| 页 {inject_page + 1}"
                )

    return supplements


def supplement_md_content(
    md_content: str,
    text_layer_pages: Dict[int, str],
    field_rules: Tuple[FieldSupplementRule, ...] = DEFAULT_FIELD_RULES,
    expected_page_count: Optional[int] = None,
    doc: Any = None,
    page_offset: int = 0,
    supplement_config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[int, str]]:
    """
    将文本层补全块写入对应页码的 OCR 片段末尾，并拼回完整 md_content

    页码为 0-based，与 PyMuPDF 及 Paddle ``page.page_num`` 一致。

    Returns:
        (补全后的 md_content, page_idx -> 补全块文本)
    """
    if not md_content or not text_layer_pages:
        return md_content, {}

    split_result = split_md_content_by_page(md_content, expected_page_count)
    ocr_sections = _align_page_sections(
        split_result.sections,
        expected_page_count,
    )
    page_supplements = compute_page_supplements(
        ocr_sections,
        text_layer_pages,
        field_rules,
        expected_page_count=expected_page_count,
        doc=doc,
        page_offset=page_offset,
        supplement_config=supplement_config,
        page_join_mode=split_result.join_mode,
    )

    if not page_supplements:
        return md_content, {}

    ocr_sections = _align_page_sections(
        ocr_sections,
        expected_page_count,
        supplement_pages=set(page_supplements.keys()),
    )

    new_md = _merge_md_page_sections(
        ocr_sections,
        page_supplements,
        split_result.join_mode,
        expected_page_count=expected_page_count,
    )
    pages_with_supplement = sorted(page_supplements.keys())
    logger.info(
        f"PDF 文本层补全完成 | 补全页数: {len(page_supplements)} | "
        f"注入页码(0-based): {pages_with_supplement} | "
        f"分页模式: {split_result.join_mode.value} | "
        f"原长度: {len(md_content)} | 新长度: {len(new_md)}"
    )
    return new_md, page_supplements


def _parse_supplement_block_to_lines(block: str) -> List[str]:
    """从补全块中提取可溯源的纯文本行（去掉标记行）"""
    lines: List[str] = []
    for raw in block.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("<!--") or ln.endswith("-->"):
            continue
        if ln == "【PDF文本层补全】":
            continue
        lines.append(ln)
    return lines


def build_supplement_segments_for_block(
    block: str,
    default_page_idx: int,
    doc: Any,
    page_offset: int = 0,
    highlight_full_page: bool = True,
) -> List[TextLayerSupplementSegment]:
    """
    为补全块内每一行生成可溯源片段（144 DPI 像素 bbox）

    highlight_full_page=True（默认）：整页 bbox，供模型命中文本层补全锚点时整页高亮。
    False：按 PyMuPDF 文本层反查字级 bbox（历史行为，易圈定偏窄或错位）。
    """
    from src.utils.pdf_text_layer_bbox import (
        find_text_bbox_in_document,
        get_page_paddle_bbox,
    )

    if doc is None:
        return []

    segments: List[TextLayerSupplementSegment] = []
    local_page = default_page_idx - page_offset
    doc_page_idx = local_page if local_page >= 0 else default_page_idx

    page_bbox: Optional[List[float]] = None
    if highlight_full_page:
        page_bbox = get_page_paddle_bbox(doc, doc_page_idx)
        if not page_bbox:
            logger.debug(
                f"文本层补全整页 bbox 未获取 | doc页 {doc_page_idx} | 将尝试字级检索"
            )

    for line in _parse_supplement_block_to_lines(block):
        if not line.strip():
            continue

        if page_bbox:
            segments.append(
                TextLayerSupplementSegment(
                    text=line,
                    page_idx=default_page_idx,
                    bbox=page_bbox,
                )
            )
            logger.debug(
                f"文本层补全整页溯源 | 页 {default_page_idx + 1} | "
                f"行: {line[:40]}... | bbox={[round(x, 1) for x in page_bbox]}"
            )
            continue

        hit = find_text_bbox_in_document(
            doc,
            line,
            preferred_page_idx=doc_page_idx if doc_page_idx >= 0 else None,
        )
        if hit:
            segments.append(
                TextLayerSupplementSegment(
                    text=line,
                    page_idx=page_offset + hit.page_idx,
                    bbox=hit.bbox,
                )
            )
            logger.debug(
                f"文本层补全字级坐标 | 页 {hit.page_idx + 1} | query={hit.matched_query[:30]!r} | "
                f"bbox={[round(x, 1) for x in hit.bbox]}"
            )
        else:
            logger.debug(
                f"文本层补全未命中坐标（将无法高亮）| 页 {default_page_idx + 1} | "
                f"行: {line[:60]}..."
            )
    return segments


def apply_supplement_to_parse_results(
    parse_results: List[Any],
    pdf_bytes: bytes,
    field_rules: Tuple[FieldSupplementRule, ...] = DEFAULT_FIELD_RULES,
) -> Tuple[
    Dict[int, str],
    Dict[int, List[TextLayerSupplementSegment]],
    Dict[int, List[float]],
]:
    """
    对 parse_result 列表就地更新 md_content，并返回补全块与可溯源片段

    Args:
        parse_results: Paddle/MinerU 解析结果对象列表
        pdf_bytes: 原始或转换后的 PDF 字节
        field_rules: 补全规则

    Returns:
        (
            page_idx -> 补全块 Markdown,
            page_idx -> 带 bbox 的补全片段列表,
            page_idx -> 该页整页 bbox（144 DPI，供 Anchor 降级/覆盖）,
        )
    """
    from src.utils.pdf_text_layer_bbox import get_page_paddle_bbox, open_pdf_document
    from config.paddle_config import get_text_layer_supplement_config

    supplement_cfg = get_text_layer_supplement_config()
    highlight_full_page = supplement_cfg.get("highlight_full_page", True)

    text_layer_pages = extract_page_texts(pdf_bytes)
    if not text_layer_pages:
        return {}, {}, {}

    doc = open_pdf_document(pdf_bytes)
    combined_page_supplements: Dict[int, str] = {}
    combined_segments: Dict[int, List[TextLayerSupplementSegment]] = {}
    combined_page_paddle_bboxes: Dict[int, List[float]] = {}
    page_offset = 0

    try:
        for result in parse_results:
            md = getattr(result, "md_content", None) or ""
            if not md:
                page_offset += getattr(result, "total_pages", 0) or 0
                continue

            expected_pages = len(text_layer_pages)
            total_attr = getattr(result, "total_pages", 0) or 0
            if total_attr > 0:
                expected_pages = total_attr

            new_md, page_supplements = supplement_md_content(
                md,
                text_layer_pages,
                field_rules,
                expected_page_count=expected_pages,
                doc=doc,
                page_offset=page_offset,
                supplement_config=supplement_cfg,
            )

            for local_idx, block in page_supplements.items():
                global_idx = page_offset + local_idx
                combined_page_supplements[global_idx] = block
                doc_page_idx = page_offset + local_idx
                if highlight_full_page and doc is not None:
                    page_bbox = get_page_paddle_bbox(doc, doc_page_idx)
                    if page_bbox:
                        combined_page_paddle_bboxes[global_idx] = page_bbox
                segs = build_supplement_segments_for_block(
                    block,
                    default_page_idx=global_idx,
                    doc=doc,
                    page_offset=page_offset,
                    highlight_full_page=highlight_full_page,
                )
                if segs:
                    combined_segments.setdefault(global_idx, []).extend(segs)

            if hasattr(result, "md_content"):
                result.md_content = new_md

            total_pages = getattr(result, "total_pages", 0) or 0
            if total_pages <= 0:
                total_pages = len(text_layer_pages)
            page_offset += total_pages
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    hit_count = sum(len(v) for v in combined_segments.values())
    if hit_count:
        logger.info(
            f"文本层补全坐标解析完成 | 可溯源片段: {hit_count} | "
            f"分布页数: {len(combined_segments)}"
        )

    return combined_page_supplements, combined_segments, combined_page_paddle_bboxes


def serialize_supplement_segments(
    segments_by_page: Dict[int, List[TextLayerSupplementSegment]],
) -> Dict[int, List[Dict[str, Any]]]:
    """转为可 JSON 序列化的结构，供 parsed_files / Anchor 使用"""
    return {
        page_idx: [
            {
                "text": seg.text,
                "page_idx": seg.page_idx,
                "bbox": seg.bbox,
                "segment_type": seg.segment_type,
            }
            for seg in segs
        ]
        for page_idx, segs in segments_by_page.items()
    }


def deserialize_supplement_segments(
    data: Optional[Dict[int, Any]],
) -> Dict[int, List[TextLayerSupplementSegment]]:
    if not data:
        return {}
    result: Dict[int, List[TextLayerSupplementSegment]] = {}
    for page_idx, items in data.items():
        page_key = int(page_idx) if not isinstance(page_idx, int) else page_idx
        segs: List[TextLayerSupplementSegment] = []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, TextLayerSupplementSegment):
                segs.append(item)
            elif isinstance(item, dict) and item.get("text"):
                bbox = item.get("bbox") or []
                segs.append(
                    TextLayerSupplementSegment(
                        text=str(item["text"]),
                        page_idx=int(item.get("page_idx", page_key)),
                        bbox=list(bbox) if bbox else [],
                        segment_type=str(
                            item.get("segment_type", "text_layer_supplement")
                        ),
                    )
                )
        if segs:
            result[page_key] = segs
    return result


def should_apply_for_file_type(file_type: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """是否对该业务文件类型启用文本层补全"""
    if config is None:
        from config.paddle_config import get_text_layer_supplement_config

        config = get_text_layer_supplement_config()

    if not config.get("enabled", True):
        return False

    allowed = config.get("file_types") or ["info_disclosure_application"]
    return file_type in allowed
