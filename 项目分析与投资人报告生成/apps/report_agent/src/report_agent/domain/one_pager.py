"""Domain model for the one-pager promotion document.

A one-pager is a single-page Word deliverable produced from two mutually
exclusive template variants:

* ``BusinessType.PROPERTY`` — an equity transfer (产权/股权转让) with a
  ``转让底价`` field.
* ``BusinessType.CAPITAL`` — a capital increase (增资/增资扩股) with
  ``对应持股比例`` and ``拟募集金额`` fields.

Both variants share the remaining 17 placeholders, so the two business types
differ only in template selection and in which deal fields are mandatory.
"""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from report_agent.domain.report_content import EvidenceCitation, MissingItem

# --- business type detection -------------------------------------------------

PROPERTY_KEYWORDS: tuple[str, ...] = (
    "股权转让",
    "产权转让",
    "转让底价",
    "受让方",
    "受让条件",
    "转让方",
    "挂牌转让",
    "股权比例",
)

CAPITAL_KEYWORDS: tuple[str, ...] = (
    "增资",
    "增资扩股",
    "募集资金",
    "拟募集金额",
    "新增注册资本",
    "认购",
    "投资方",
    "增资款",
)

#: Minimum keyword-count gap before the material text decides on its own.
DETECTION_SCORE_MARGIN = 2


class BusinessType(StrEnum):
    PROPERTY = "产权"
    CAPITAL = "增资"


class DetectionConfidence(StrEnum):
    HIGH = "high"
    FILENAME = "filename"
    USER = "user"
    NONE = "none"


class BusinessTypeDetection(BaseModel):
    """Outcome of :func:`detect_business_type`, including how it was decided."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    business_type: BusinessType | None = None
    confidence: DetectionConfidence = DetectionConfidence.NONE
    property_score: int = 0
    capital_score: int = 0
    conflict: bool = False
    reason: str = ""

    @property
    def decided(self) -> bool:
        return self.business_type is not None


def _score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _detect_from_filename(filename: str) -> BusinessType | None:
    if "增资" in filename:
        return BusinessType.CAPITAL
    if "转让" in filename or "产权" in filename:
        return BusinessType.PROPERTY
    return None


def detect_business_type(
    material_text: str,
    filename: str = "",
    user_hint: BusinessType | None = None,
) -> BusinessType | None:
    """Return the detected business type, or ``None`` when it is ambiguous.

    Priority is material text, then filename, then the explicit user hint.
    The material decides on its own only when the keyword-score gap reaches
    :data:`DETECTION_SCORE_MARGIN`; a narrower gap falls back to the filename.
    """
    return detect_business_type_detail(material_text, filename, user_hint).business_type


def detect_business_type_detail(
    material_text: str,
    filename: str = "",
    user_hint: BusinessType | None = None,
) -> BusinessTypeDetection:
    """Same as :func:`detect_business_type` but reports scores and provenance."""
    text = material_text or ""
    property_score = _score(text, PROPERTY_KEYWORDS)
    capital_score = _score(text, CAPITAL_KEYWORDS)
    gap = property_score - capital_score

    from_name = _detect_from_filename(filename or "")

    if abs(gap) >= DETECTION_SCORE_MARGIN:
        winner = BusinessType.PROPERTY if gap > 0 else BusinessType.CAPITAL
        return BusinessTypeDetection(
            business_type=winner,
            confidence=DetectionConfidence.HIGH,
            property_score=property_score,
            capital_score=capital_score,
            conflict=from_name is not None and from_name is not winner,
            reason=f"材料关键词判定为{winner.value}（产权命中{property_score}个，增资命中{capital_score}个）",
        )

    if from_name is not None:
        return BusinessTypeDetection(
            business_type=from_name,
            confidence=DetectionConfidence.FILENAME,
            property_score=property_score,
            capital_score=capital_score,
            reason=f"材料关键词不足以判定（产权{property_score}/增资{capital_score}），按文件名判定为{from_name.value}",
        )

    if user_hint is not None:
        return BusinessTypeDetection(
            business_type=user_hint,
            confidence=DetectionConfidence.USER,
            property_score=property_score,
            capital_score=capital_score,
            reason=f"材料与文件名均无法判定，按用户输入取{user_hint.value}",
        )

    return BusinessTypeDetection(
        property_score=property_score,
        capital_score=capital_score,
        reason="材料关键词与文件名均无法判定，需用户指定产权或增资",
    )


# --- template placeholder contract -------------------------------------------


#: Placeholders present in every variant of the template.
SHARED_PLACEHOLDERS: tuple[str, ...] = (
    "项目名称",
    "公司全称",
    "所属区域",
    "所属行业",
    "原始简介",
    "联系人名称",
    "项目介绍标题1",
    "项目介绍正文1",
    "项目介绍标题2",
    "项目介绍正文2",
    "项目介绍标题3",
    "项目介绍正文3",
    "项目亮点标题1",
    "项目亮点正文1",
    "项目亮点标题2",
    "项目亮点正文2",
    "项目亮点标题3",
    "项目亮点正文3",
)

PROPERTY_PLACEHOLDERS: tuple[str, ...] = (*SHARED_PLACEHOLDERS, "转让底价")
CAPITAL_PLACEHOLDERS: tuple[str, ...] = (
    *SHARED_PLACEHOLDERS,
    "对应持股比例",
    "拟募集金额",
)

PLACEHOLDERS_BY_BUSINESS_TYPE: dict[BusinessType, tuple[str, ...]] = {
    BusinessType.PROPERTY: PROPERTY_PLACEHOLDERS,
    BusinessType.CAPITAL: CAPITAL_PLACEHOLDERS,
}

#: Placeholder name -> model attribute on :class:`OnePagerContent`.
PLACEHOLDER_FIELDS: dict[str, str] = {
    "项目名称": "project_name",
    "公司全称": "company_full_name",
    "所属区域": "region",
    "所属行业": "industry",
    "原始简介": "original_intro",
    "联系人名称": "contact_name",
    "转让底价": "transfer_floor_price",
    "对应持股比例": "equity_ratio",
    "拟募集金额": "capital_raise_amount",
}


# --- content model -----------------------------------------------------------

SECTION_COUNT = 3

# Character bands for one-pager body copy (whitespace excluded).
INTRO_BODY_RANGE = (225, 250)
HIGHLIGHT_BODY_RANGE = (170, 185)
#: 目标区间只作写作建议；不得因差几字或材料信息偏少而反复改稿。
#: preflight 和域模型只拦截下面的极端溢出上限。
INTRO_BODY_HARD_LIMIT = 400
HIGHLIGHT_BODY_HARD_LIMIT = 220
# Intro titles sit in a narrow vertical box (28pt wide, 99pt tall), highlights
# in a horizontal rail 153pt wide.
INTRO_TITLE_RANGE = (3, 6)
HIGHLIGHT_TITLE_RANGE = (5, 9)
INTRO_MAX_CHARS = 100

MAX_INTERNAL_INVESTORS = 20
MAX_WEB_INVESTORS = 10

#: Titles the decision table pins when the matching slot is populated.
FIXED_INTRO_TITLE_WITH_FINANCIALS = "经营分析"
FIXED_INTRO_TITLE_WITH_RISK = "风险提示"
FIXED_FIRST_INTRO_TITLE = "核心产品"

#: Causal connectives the workflow forbids unless the material states the link.
FORBIDDEN_ATTRIBUTIONS = (
    "源于",
    "得益于",
    "反映出",
    "受益于",
    "得益于",
    "正是由于",
    "归功于",
    "助力实现",
    "保驾护航",
)


def _char_len(text: str) -> int:
    """Length in Chinese-report convention: whitespace does not count."""
    return len("".join(text.split()))


#: Length of the character shingles used for section-overlap detection.
SHINGLE_SIZE = 12
#: Jaccard overlap above which two sections are considered restatements.
SECTION_REPEAT_THRESHOLD = 0.35


def _shingles(text: str, size: int = SHINGLE_SIZE) -> set[str]:
    compact = "".join(text.split())
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[i : i + size] for i in range(len(compact) - size + 1)}


def _shingle_overlap(left: str, right: str) -> float:
    a, b = _shingles(left), _shingles(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def section_repeat_ratio(sections: tuple[OnePagerSection, ...]) -> float:
    """Highest pairwise shingle overlap among ``sections``.

    Exposed so the review checker can report the measurement instead of only
    raising; 0.0 when there are fewer than two sections.
    """
    worst = 0.0
    for index, section in enumerate(sections):
        for other in sections[index + 1 :]:
            worst = max(worst, _shingle_overlap(section.body, other.body))
    return worst


def unsupported_attributions(text: str) -> tuple[str, ...]:
    """Causal connectives the workflow forbids without a stated cause."""
    return tuple(word for word in FORBIDDEN_ATTRIBUTIONS if word in text)


class OnePagerSection(BaseModel):
    """One titled paragraph block. Length bounds differ by kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    kind: Literal["intro", "highlight"] = "intro"

    @model_validator(mode="after")
    def validate_lengths(self) -> OnePagerSection:
        """标题按模板槽位硬校验；正文只拦截明显溢出。

        写作目标：介绍 ``INTRO_BODY_RANGE``、亮点 ``HIGHLIGHT_BODY_RANGE``。
        目标区间是建议，不要求逐字凑齐。preflight 与这里使用同一硬上限，
        避免渲染前后口径不同造成反复改稿。
        """
        if self.kind == "intro":
            title_range = INTRO_TITLE_RANGE
            body_limit = INTRO_BODY_HARD_LIMIT
        else:
            title_range = HIGHLIGHT_TITLE_RANGE
            body_limit = HIGHLIGHT_BODY_HARD_LIMIT
        title_len = _char_len(self.title)
        if not title_range[0] <= title_len <= title_range[1]:
            raise ValueError(
                f"{self.kind} 标题需 {title_range[0]}-{title_range[1]} 字，实际 {title_len} 字: "
                f"{self.title!r}"
            )
        length = _char_len(self.body)
        if length > body_limit:
            raise ValueError(
                f"{self.kind} 正文上限 {body_limit} 字，实际 {length} 字"
                f"（超出 {length - body_limit} 字，已明显撑破版式）"
            )
        return self


#: 大纲工具的中文 schema 说明：模型猜错字段名时直接回传这份，避免一轮只报一个错。
OUTLINE_SCHEMA_HINT: dict[str, object] = {
    "report_id": "字符串，形如 task_xxx；与 render_one_pager 的 report_id 一致",
    "business_type": "产权 | 增资",
    "has_financial_analysis": "布尔：材料里有财务报表/营收利润数据才为 true",
    "has_risk_facts": "布尔：材料里有非优质/负面信息才为 true",
    "intro_sections": "恰好 3 项，index 依次 1/2/3",
    "highlight_sections": "恰好 3 项，index 依次 1/2/3",
    "slot": {
        "index": "1-3",
        "title": f"介绍标题 {INTRO_TITLE_RANGE[0]}-{INTRO_TITLE_RANGE[1]} 字；"
                 f"亮点标题 {HIGHLIGHT_TITLE_RANGE[0]}-{HIGHLIGHT_TITLE_RANGE[1]} 字",
        "kind": "intro | highlight（必须与本组一致）",
        "key_points": "非空字符串数组",
        "source_quote": "材料原句，可为空字符串",
    },
    "禁用": "不得出现 intro_1/intro1/has_caiwufenxi/has_bad_info 等未定义字段（extra=forbid）",
}

#: 一份合法大纲，模型可直接照抄结构替换内容。
OUTLINE_EXAMPLE: dict[str, object] = {
    "report_id": "task_00000000000000000000000000000000",
    "business_type": "产权",
    "has_financial_analysis": False,
    "has_risk_facts": False,
    "intro_sections": [
        {"index": 1, "title": "核心产品", "kind": "intro",
         "key_points": ["主营产品与定位"], "source_quote": "材料原句"},
        {"index": 2, "title": "经营数据", "kind": "intro",
         "key_points": ["营收与利润"], "source_quote": "材料原句"},
        {"index": 3, "title": "市场挑战", "kind": "intro",
         "key_points": ["行业竞争与价格压力"], "source_quote": "材料原句"},
    ],
    "highlight_sections": [
        {"index": 1, "title": "规模与盈利", "kind": "highlight",
         "key_points": ["体量领先"], "source_quote": "材料原句"},
        {"index": 2, "title": "业务结构优化", "kind": "highlight",
         "key_points": ["收入结构改善"], "source_quote": "材料原句"},
        {"index": 3, "title": "综合金融优势", "kind": "highlight",
         "key_points": ["集团协同"], "source_quote": "材料原句"},
    ],
}

#: 模型常见的别名写法 -> 正式字段名。
_OUTLINE_FIELD_ALIASES: dict[str, str] = {
    "has_caiwufenxi": "has_financial_analysis",
    "has_finance": "has_financial_analysis",
    "financial_analysis": "has_financial_analysis",
    "has_bad_info": "has_risk_facts",
    "has_risk_info": "has_risk_facts",
    "has_risk": "has_risk_facts",
    "project_id": "report_id",
    "id": "report_id",
}

_SLOT_FIELD_ALIASES: dict[str, str] = {
    "name": "title",
    "heading": "title",
    "point": "key_points",
    "points": "key_points",
    "key_point": "key_points",
    "quote": "source_quote",
    "source": "source_quote",
    "idx": "index",
}


def normalize_outline_payload(payload: object) -> dict[str, object]:
    """把模型的大纲写法收敛成 OnePagerOutline 的字段，再交给严格校验。

    实测模型会写 ``intro_1/intro_2/intro_3``、``has_caiwufenxi``、``point``
    这类别名，严格校验一次只报一层错，于是要来回 8 轮。这里先做无损归一化：
    只改键名、补 index/kind、把字符串 key_points 包成数组，不改内容。
    """
    if not isinstance(payload, dict):
        return {}
    data = dict(payload)

    for alias, target in _OUTLINE_FIELD_ALIASES.items():
        if alias in data:
            value = data.pop(alias)
            data.setdefault(target, value)

    for group, prefixes in (
        ("intro_sections", ("intro_section", "intro", "介绍")),
        ("highlight_sections", ("highlight_section", "highlight", "亮点")),
    ):
        if isinstance(data.get(group), (list, tuple)):
            continue
        collected: list[object] = []
        for index in (1, 2, 3):
            for prefix in prefixes:
                for key in (f"{prefix}_{index}", f"{prefix}{index}"):
                    if key in data:
                        collected.append(data.pop(key))
                        break
                else:
                    continue
                break
        if collected:
            data[group] = collected

    for group, kind in (("intro_sections", "intro"), ("highlight_sections", "highlight")):
        slots = data.get(group)
        if not isinstance(slots, (list, tuple)):
            continue
        fixed: list[object] = []
        for position, slot in enumerate(slots, start=1):
            if not isinstance(slot, dict):
                fixed.append(slot)
                continue
            item = dict(slot)
            for alias, target in _SLOT_FIELD_ALIASES.items():
                if alias in item:
                    value = item.pop(alias)
                    item.setdefault(target, value)
            if isinstance(item.get("key_points"), str):
                item["key_points"] = [item["key_points"]]
            item.setdefault("index", position)
            item.setdefault("kind", kind)
            fixed.append(item)
        data[group] = fixed

    return data


class OutlineSlot(BaseModel):
    """One planned section before any prose exists.

    The Lingda workflow separates outline from prose on purpose: all six
    titles are decided in a single pass so they cannot overlap or sit at
    mismatched levels, and each slot carries its own source anchor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=1, le=SECTION_COUNT)
    title: str = Field(min_length=1)
    kind: Literal["intro", "highlight"] = "intro"
    key_points: tuple[str, ...] = Field(min_length=1)
    source_quote: str = ""

    @model_validator(mode="after")
    def validate_title_length(self) -> OutlineSlot:
        title_range = INTRO_TITLE_RANGE if self.kind == "intro" else HIGHLIGHT_TITLE_RANGE
        length = _char_len(self.title)
        if not title_range[0] <= length <= title_range[1]:
            raise ValueError(
                f"{self.kind} 大纲标题需 {title_range[0]}-{title_range[1]} 字，"
                f"实际 {length} 字: {self.title!r}"
            )
        return self


class OnePagerOutline(BaseModel):
    """Six planned sections plus the two conditional slots that pin titles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    business_type: BusinessType
    has_financial_analysis: bool = False
    has_risk_facts: bool = False
    include_risk_facts: bool | None = None
    intro_sections: tuple[OutlineSlot, ...]
    highlight_sections: tuple[OutlineSlot, ...]

    @model_validator(mode="after")
    def validate_outline(self) -> OnePagerOutline:
        for label, slots, expected_kind in (
            ("项目介绍", self.intro_sections, "intro"),
            ("项目亮点", self.highlight_sections, "highlight"),
        ):
            if len(slots) != SECTION_COUNT:
                raise ValueError(f"{label} 大纲必须恰好 {SECTION_COUNT} 项，实际 {len(slots)} 项")
            if sorted(slot.index for slot in slots) != list(range(1, SECTION_COUNT + 1)):
                raise ValueError(f"{label} 大纲 index 必须为 1..{SECTION_COUNT}")
            for slot in slots:
                if slot.kind != expected_kind:
                    raise ValueError(f"{label} 大纲项 kind 必须为 {expected_kind}")
            titles = [slot.title for slot in slots]
            if len(set(titles)) != len(titles):
                raise ValueError(f"{label} 大纲标题不得重复: {titles}")

        if self.intro_sections[0].title != FIXED_FIRST_INTRO_TITLE:
            raise ValueError(
                f"项目介绍第 1 个标题固定为「{FIXED_FIRST_INTRO_TITLE}」，"
                f"实际 {self.intro_sections[0].title!r}"
            )
        second = self.intro_sections[1].title
        if self.has_financial_analysis:
            if second != FIXED_INTRO_TITLE_WITH_FINANCIALS:
                raise ValueError(
                    f"有财务数据分析时第 2 个标题固定为「{FIXED_INTRO_TITLE_WITH_FINANCIALS}」"
                )
        elif second == FIXED_INTRO_TITLE_WITH_FINANCIALS:
            raise ValueError("无财务数据时不得使用「经营分析」标题")

        # 「风险提示」不再占用介绍槽位：它作为第二页末尾的小字出现（客户反馈
        # 正文里单开风险模块会挤掉真正的项目介绍）。这里只禁止继续用这个标题。
        if self.intro_sections[2].title == FIXED_INTRO_TITLE_WITH_RISK:
            raise ValueError("「风险提示」不再占用介绍槽位，请换一个 3-6 字标题")

        intro_titles = {slot.title for slot in self.intro_sections}
        overlap = intro_titles & {slot.title for slot in self.highlight_sections}
        if overlap:
            raise ValueError(f"项目介绍与项目亮点标题不得交叉: {sorted(overlap)}")
        return self

    @property
    def show_risk_facts(self) -> bool:
        return self.has_risk_facts and self.include_risk_facts is not False

    def decision_table(self) -> tuple[str, ...]:
        """Human-readable record of which pinned titles applied."""
        rows = [f"第1个介绍标题：{FIXED_FIRST_INTRO_TITLE}（恒定）"]
        rows.append(
            f"第2个介绍标题：{FIXED_INTRO_TITLE_WITH_FINANCIALS}（有财务数据分析=是）"
            if self.has_financial_analysis
            else f"第2个介绍标题：{self.intro_sections[1].title}（有财务数据分析=否，自拟）"
        )
        rows.append(f"第3个介绍标题：{self.intro_sections[2].title}（自拟；风险提示改在第二页末尾小字）")
        return tuple(rows)


class MatchedTag(BaseModel):
    """A track tag that contributed to an investor's match score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str = Field(min_length=1)
    weight: float | None = None


class InvestorRow(BaseModel):
    """One row of the appended investor-matching table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["internal", "web"]
    investor_type: Literal["机构", "个人"]
    name: str = Field(min_length=1)
    match_reason: str = ""
    score: float | None = None
    matched_tags: tuple[MatchedTag, ...] = ()
    citations: tuple[EvidenceCitation, ...] = ()

    def tag_label(self, *, digits: int = 3) -> str:
        """Rendered ``matched_tags`` for a table cell, empty when absent."""
        return "、".join(
            tag.tag if tag.weight is None else f"{tag.tag}({tag.weight:.{digits}f})"
            for tag in self.matched_tags
        )


class OnePagerContent(BaseModel):
    """Fully-populated one-pager, ready to render into a template."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    business_type: BusinessType
    project_name: str = Field(min_length=1)
    company_full_name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    original_intro: str = Field(min_length=1)
    contact_name: str = Field(min_length=1)

    # Property-only
    transfer_floor_price: str | None = None
    # Capital-only
    equity_ratio: str | None = None
    capital_raise_amount: str | None = None

    intro_sections: tuple[OnePagerSection, ...]
    highlight_sections: tuple[OnePagerSection, ...]
    investors: tuple[InvestorRow, ...] = ()
    missing_items: tuple[MissingItem, ...] = ()

    # Conditional slots carried over from the Lingda workflow. When present they
    # pin the matching outline title; when absent the agent must invent a title
    # instead of reusing the pinned wording.
    financial_analysis: str | None = None
    risk_facts: str | None = None

    @property
    def has_financial_analysis(self) -> bool:
        return bool((self.financial_analysis or "").strip())

    def risk_notes(self) -> tuple[str, ...]:
        """把 risk_facts 拆成逐条小字，供第二页末尾渲染。"""
        text = (self.risk_facts or "").strip()
        if not text:
            return ()
        parts = re.split(r"[\n\r；;]+", text)
        cleaned = [part.strip(" -•·\t") for part in parts]
        return tuple(part for part in cleaned if part)

    @property
    def has_risk_facts(self) -> bool:
        return bool((self.risk_facts or "").strip())

    @model_validator(mode="after")
    def validate_content(self) -> OnePagerContent:
        if self.business_type is BusinessType.PROPERTY:
            if not self.transfer_floor_price:
                raise ValueError("产权版必须提供 转让底价")
            if self.equity_ratio or self.capital_raise_amount:
                raise ValueError("产权版不得携带 对应持股比例/拟募集金额")
        else:
            if not self.equity_ratio:
                raise ValueError("增资版必须提供 对应持股比例")
            if not self.capital_raise_amount:
                raise ValueError("增资版必须提供 拟募集金额")
            if self.transfer_floor_price:
                raise ValueError("增资版不得携带 转让底价")

        if _char_len(self.original_intro) > INTRO_MAX_CHARS:
            raise ValueError(f"原始简介超过 {INTRO_MAX_CHARS} 字")

        for label, sections, expected_kind in (
            ("项目介绍", self.intro_sections, "intro"),
            ("项目亮点", self.highlight_sections, "highlight"),
        ):
            if len(sections) != SECTION_COUNT:
                raise ValueError(f"{label} 必须恰好 {SECTION_COUNT} 段，实际 {len(sections)} 段")
            for section in sections:
                if section.kind != expected_kind:
                    raise ValueError(f"{label} 段 kind 必须为 {expected_kind}")
            titles = [section.title for section in sections]
            if len(set(titles)) != len(titles):
                raise ValueError(f"{label} 标题不得重复")

        overlap = {s.title for s in self.intro_sections} & {
            s.title for s in self.highlight_sections
        }
        if overlap:
            raise ValueError(f"项目介绍与项目亮点标题不得交叉: {sorted(overlap)}")

        # Section prose must not restate the same fact twice. The Lingda
        # workflow reaches this by splitting the two blocks across two prompts
        # (intro = what it is, highlight = why it is worth investing in); this
        # check is the belt-and-braces for a single-pass write.
        bodies = [s.body for s in self.intro_sections]
        for index, body in enumerate(bodies):
            for other in bodies[index + 1 :]:
                if _shingle_overlap(body, other) > SECTION_REPEAT_THRESHOLD:
                    raise ValueError("项目介绍各段之间重复度过高，请按「分工边界」重写")

        internal = [row for row in self.investors if row.source == "internal"]
        web = [row for row in self.investors if row.source == "web"]
        if len(internal) > MAX_INTERNAL_INVESTORS:
            raise ValueError(f"内部投资人最多 {MAX_INTERNAL_INVESTORS} 行，实际 {len(internal)} 行")
        if len(web) > MAX_WEB_INVESTORS:
            raise ValueError(f"网络投资人最多 {MAX_WEB_INVESTORS} 行，实际 {len(web)} 行")
        names = [row.name for row in self.investors]
        if len(names) != len(set(names)):
            raise ValueError("投资人清单不得出现重复名称")
        return self

    def placeholder_values(self) -> dict[str, str]:
        """Map every template placeholder to its rendered string.

        Section placeholders use the 1-based index that appears in the
        template (``项目介绍标题1`` … ``项目亮点正文3``).
        """
        values = {
            "项目名称": self.project_name,
            "公司全称": self.company_full_name,
            "所属区域": self.region,
            "所属行业": self.industry,
            "原始简介": self.original_intro,
            "联系人名称": self.contact_name,
            "转让底价": self.transfer_floor_price or "",
            "对应持股比例": self.equity_ratio or "",
            "拟募集金额": self.capital_raise_amount or "",
        }
        for index, section in enumerate(self.intro_sections, start=1):
            values[f"项目介绍标题{index}"] = section.title
            values[f"项目介绍正文{index}"] = section.body
        for index, section in enumerate(self.highlight_sections, start=1):
            values[f"项目亮点标题{index}"] = section.title
            values[f"项目亮点正文{index}"] = section.body
        return values

    def required_placeholders(self) -> tuple[str, ...]:
        return PLACEHOLDERS_BY_BUSINESS_TYPE[self.business_type]
