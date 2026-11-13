"""Quality and AI-tell detection for finished report markdown.

Two pure-function classes:

* :class:`QualityChecker` — structure, citations, required fields,
  format, authenticity, professional polish
* :class:`AITellDetector` — LLM writing patterns (template transitions,
  bureaucratic phrasing, em-dash overuse, list-stacking, etc.)

Both return a list of :class:`~report_agent.domain.review_issue.ReportIssue`.
The ``check_report`` harness tool (harness/review_tools.py) wraps both
classes behind a single JSON-serializing entry point.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from statistics import mean, pstdev
from typing import TYPE_CHECKING, Any

from report_agent.domain.one_pager import (
    SECTION_REPEAT_THRESHOLD,
    SHINGLE_SIZE,
)
from report_agent.domain.outline import outline_loader
from report_agent.domain.review_issue import ReportIssue
from report_agent.domain.source_markers import strip_source_markers

if TYPE_CHECKING:
    pass

_PARAGRAPH_RE = re.compile(r"\n\s*\n", re.MULTILINE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_SECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_CITE_RE = re.compile(r"<!--\s*cite:\s*(evidence_[a-f0-9]{32})")

#: Status words assert a state of the world. When a material draws that state
#: as a shape — a progress matrix of filled/hollow dots, a milestone
#: flowchart — no text extractor can recover it, and a report that guesses is
#: worse than one that says "not disclosed". The word must therefore appear
#: in the evidence the paragraph actually cites.
STATE_TERMS = (
    "已完成",
    "进行中",
    "未开始",
    "验证",
    "量产",
    "批量供货",
    "小批量",
    "定点",
    "导入",
    "推进",
)

#: ``<!-- src: material parse_materials /data/blocks/11/text ; ... -->``
_SRC_BLOCK_RE = re.compile(
    r"<!--\s*src:\s*material\s+parse_materials\s+/data/blocks/(\d+)/text"
)

#: ``<!-- src: web search_company_web /data/searches/0 ; note -->``
_SRC_MARKER_RE = re.compile(
    r"<!--\s*src:\s*(\w+)\s+(\w+)\s+(\S+)\s*;\s*(.*?)\s*-->"
)

_URL_RE = re.compile(r"https?://\S+")
_DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2})?")
_CITE_EID_RE = re.compile(r"<!--\s*cite:\s*(evidence_[a-f0-9]{32})")
_PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|xxx|\.{3,})\b")
_FABRICATED_NUM_RE = re.compile(
    r"(约|大致|差不多)\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|％|亿元|万元|千元|元|亿|万|千|人|间|个|家|项|平方米)?"
)
_EVIDENCE_NUMBER_RE = re.compile(
    r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>%|％|亿元|万元|千元|元|亿|万|千|人|间|个|家|项|平方米)"
)


def _evidence_number_key(match: re.Match[str]) -> tuple[Decimal, str]:
    unit = match["unit"]
    factors = {"亿元": 100_000_000, "万元": 10_000, "千元": 1_000, "元": 1}
    value = Decimal(match["value"].replace(",", ""))
    if unit in factors:
        return value * factors[unit], "元"
    return value, "%" if unit == "％" else unit
_NUMBER_FORMAT_RE = re.compile(r"(\d+\.\d+|\d{1,3}(?:,\d{3})+)\s*(亿|万|%)?")
_ABBREV_RE = re.compile(r"\b([A-Z]{2,5})\b")

#: Business numbers that must be traceable: money, ratios, physical counts.
#: Deliberately excludes years/months/ordinals, which are usually context.
_UNCITED_NUMBER_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|％|万元|亿元|万|亿|元|辆|家|项|座|平米|平方米|个百分点)"
)
#: Policy titles, e.g. 《关于加快新能源汽车推广应用的指导意见》.
_POLICY_RE = re.compile(r"《[^》]{2,60}》")
#: Policy/regulation *phrases* that carry no book-title markers but still need a
#: source: "利率市场化改革"、"LPR 改革"、"监管要求" 等。
_POLICY_TERMS_RE = re.compile(
    r"(利率市场化|LPR\s*改革|存款利率|贷款利率|监管要求|监管规定|监管政策|"
    r"行业监管|政策支持|政策导向|产业政策|指导意见|实施细则|管理办法|"
    r"银保监|人民银行|证监会|发改委|金融监督管理)"
)
#: Report header section holds task metadata (date, transferor), not claims.
_HEADER_SECTION_RE = re.compile(r"^[\s一二三四五六七八九十]*[、.]?\s*报告头部")
#: Raw numbers, used to check a cited sentence against its evidence file.
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> list[str]:
    return [match.group(0) for match in _NUM_RE.finditer(text or "")]


def _normalize_number(value: str) -> str:
    """Strip separators and trailing zeros so ``13,180.00`` == ``13180``."""
    text = value.replace(",", "").strip()
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text

#: Longest common substring allowed between two prose blocks before the
#: shorter one is considered redundant.
_MAX_SHARED_RUN = 24


def _compact(text: str) -> str:
    return "".join(text.split())


def _iter_h3_blocks(md_text: str) -> list[tuple[str, str]]:
    """``(heading, body)`` pairs for every ``###`` section in the markdown."""
    body = re.sub(r"<!--.*?-->", "", md_text, flags=re.DOTALL)
    marks = [(m.start(), m.end(), m.group(1).strip()) for m in _H3_SECTION_RE.finditer(body)]
    blocks: list[tuple[str, str]] = []
    for index, (_start, end, title) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else len(body)
        blocks.append((title, body[end:stop].strip()))
    return blocks


def _shingle_overlap(left: str, right: str, size: int = SHINGLE_SIZE) -> float:
    """Jaccard overlap of fixed-length character shingles."""
    a, b = _compact(left), _compact(right)
    if len(a) <= size or len(b) <= size:
        return 1.0 if a and a == b else 0.0
    sa = {a[i : i + size] for i in range(len(a) - size + 1)}
    sb = {b[i : i + size] for i in range(len(b) - size + 1)}
    return len(sa & sb) / len(sa | sb)


class QualityChecker:
    """Run 6 quality dimensions on a finished report markdown."""

    REQUIRED_DATA_FIELDS_DEFAULT = ["注册资本", "股权", "营业收入", "赛道标签", "投资人"]

    def __init__(
        self,
        required_sections: list[str] | None = None,
        required_fields: list[str] | None = None,
        outline_path: str | None = None,
        workspace: Any | None = None,
    ):
        self.outline_path = outline_path
        if required_sections is None and outline_path is not None:
            required_sections = outline_loader(outline_path)
        self.required_sections = required_sections or []
        self.required_fields = required_fields or self.REQUIRED_DATA_FIELDS_DEFAULT
        # Optional: needed to verify that a cited number really exists in the
        # referenced evidence file.
        self.workspace = workspace

    def check(self, md_text: str) -> list[ReportIssue]:
        issues: list[ReportIssue] = []
        issues += self._check_sections(md_text)
        issues += self._check_citations(md_text)
        issues += self._check_uncited_numbers(md_text)
        issues += self._check_state_claims(md_text)
        issues += self._check_web_sources(md_text)
        issues += self._check_data_fields(md_text)
        issues += self._check_balance(md_text)
        issues += self._check_format(md_text)
        issues += self._check_authenticity(md_text)
        issues += self._check_professionalism(md_text)
        return issues

    # ---- status claims ----
    def _check_state_claims(self, md_text: str) -> list[ReportIssue]:
        """A status word must be supported by the evidence the paragraph cites.

        A material that draws its progress matrix as shapes yields no status
        in the text layer. The report must then say "not disclosed" instead of
        guessing — the failure mode this catches is a completed customer
        written up as "still in validation".
        """
        if self.workspace is None:
            return []
        evidence = self._evidence_index()
        if not evidence:
            return []
        issues: list[ReportIssue] = []
        for offset, para in enumerate(self._paragraphs(md_text)):
            # The src marker quotes the original text, so it carries status
            # words of its own. Scan the prose, not the annotation.
            prose = strip_source_markers(para)
            terms = [term for term in STATE_TERMS if term in prose]
            if not terms:
                continue
            cited = set(_CITE_RE.findall(para))
            block_indexes = {int(value) for value in _SRC_BLOCK_RE.findall(para)}
            status = self._status_supported(evidence, cited, block_indexes, terms)
            if status == "supported":
                continue
            if status == "no_source":
                message = "状态词没有任何来源标注：" + "、".join(terms[:4])
                suggestion = "补 src 指向写出该状态的证据块；材料未披露就写「材料未披露该状态」"
            else:
                message = "状态词在所引证据中没有找到：" + "、".join(terms[:4])
                suggestion = (
                    "核对证据原文里的状态；材料未披露就写「材料未披露该状态」，"
                    "不要凭推测写成「已完成/进行中」"
                )
            issues.append(ReportIssue(
                kind="state_claim_without_source",
                severity="warn",
                locations=[offset],
                paragraph=offset,
                excerpt=para[:120],
                terms=terms[:8],
                message=message,
                suggestion=suggestion,
            ))
        return issues

    def _check_web_sources(self, md_text: str) -> list[ReportIssue]:
        """A web citation must carry the four elements a reader needs to re-check it.

        Publisher, title, link and retrieval date. Without them the reader
        cannot tell what was found, how old it is, or whether it was real.
        """
        issues: list[ReportIssue] = []
        for match in _SRC_MARKER_RE.finditer(md_text):
            kind, _tool, _pointer, note = match.groups()
            if kind not in {"web", "web_reasoned"}:
                continue
            missing: list[str] = []
            if not note.strip():
                missing.append("来源机构与标题")
            if not _URL_RE.search(note):
                missing.append("链接")
            if not _DATE_RE.search(note):
                missing.append("检索日期")
            if not missing:
                continue
            issues.append(ReportIssue(
                kind="web_source_incomplete",
                severity="warn",
                locations=[self._paragraph_index(md_text, match.start())],
                excerpt=note[:120],
                terms=missing,
                message="网上来源缺少：" + "、".join(missing),
                suggestion=(
                    "批注里写全「发布机构｜标题或公告号｜链接｜检索日期」；"
                    "read_evidence 返回的 src.note 已经带齐这四项，直接用它"
                ),
            ))
        return issues

    def _evidence_index(self) -> dict[str, Any]:
        """Evidence id -> payload, plus the parsed-material block texts."""
        from report_agent.infrastructure.evidence import WorkspaceEvidenceStore

        store = WorkspaceEvidenceStore(self.workspace)
        root = self.workspace.resolve("/workspace/evidence")
        payloads: dict[str, Any] = {}
        material_blocks: list[list[str]] = []
        for path in root.glob("evidence_*.json"):
            try:
                payload = store.get(path.stem)
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            payloads[path.stem] = payload
            if payload.get("tool") == "parse_materials":
                blocks = (payload.get("data") or {}).get("blocks") or []
                material_blocks.append(
                    [str(block.get("text") or "") for block in blocks if isinstance(block, dict)]
                )
        return {"payloads": payloads, "material_blocks": material_blocks}

    def _status_supported(
        self,
        evidence: dict[str, Any],
        cited: set[str],
        block_indexes: set[int],
        terms: list[str],
    ) -> str:
        """``supported`` / ``not_found`` / ``no_source``."""
        texts: list[str] = []
        for evidence_id in cited:
            payload = evidence["payloads"].get(evidence_id)
            if payload is None:
                continue
            texts.append(json.dumps(payload.get("data", {}), ensure_ascii=False))
        for blocks in evidence["material_blocks"]:
            for index in block_indexes:
                if 0 <= index < len(blocks):
                    texts.append(blocks[index])
        if not texts:
            return "no_source"
        joined = "\n".join(texts)
        return "supported" if any(term in joined for term in terms) else "not_found"

    # ---- sections ----

    def _check_sections(self, md_text: str) -> list[ReportIssue]:
        if not self.required_sections:
            return []
        if len(md_text.strip()) < 50:
            return []
        present = self._collect_section_titles(md_text)
        present_normalized = {self._normalize_heading(p) for p in present}
        issues: list[ReportIssue] = []
        for required in self.required_sections:
            stripped = self._normalize_heading(required)
            if stripped in present_normalized:
                continue
            # The outline carries descriptive suffixes ("项目分析（报告基础盘）")
            # that SKILL.md tells the model to drop, so either side may be the
            # shorter one.
            if any(stripped in p or p in stripped for p in present_normalized):
                continue
            issues.append(ReportIssue(
                kind="missing_section", severity="block",
                message=f"必需章节缺失: {required}",
                suggestion=f"补章节: {required}",
            ))
        return issues

    @staticmethod
    def _strip_ordinal(title: str) -> str:
        return re.sub(r"^[一二三四五六七八九十]+、\s*", "", title).strip()

    @staticmethod
    def _normalize_heading(title: str) -> str:
        """Drop the ordinal prefix and any trailing parenthetical gloss.

        ``二、项目分析（报告基础盘）`` and ``二、项目分析`` name the same
        section: report-outline.md carries the gloss, SKILL.md does not.
        """
        stripped = QualityChecker._strip_ordinal(title)
        return re.sub(r"[（(][^）)]*[）)]\s*$", "", stripped).strip() or stripped

    def _collect_section_titles(self, md_text: str) -> list[str]:
        return [m.group(1).strip() for m in _SECTION_RE.finditer(md_text)]

    # ---- citations (verified, not guessed) ----

    def check_citation(self, md_text: str) -> list[ReportIssue]:
        """Verify the citations that already exist in the report.

        Two failure modes matter:
        - the cited evidence id does not exist (orphan);
        - a number in the cited sentence is absent from that evidence.
        Whether a paragraph "should" carry a citation is left to the agent.
        """
        issues: list[ReportIssue] = []
        known = self._extract_known_eids(md_text)
        counts = self._citation_counts(md_text)

        for eid, count in counts.items():
            if known is not None and eid not in known:
                issues.append(ReportIssue(
                    kind="orphaned_citation", severity="block",
                    evidence_id=eid, count=count,
                    message=f"引用的证据不存在: {eid}",
                    suggestion="删除该 cite，或补上对应证据",
                ))

        if self.workspace is None or not counts:
            return issues

        from report_agent.infrastructure.evidence import WorkspaceEvidenceStore

        store = WorkspaceEvidenceStore(self.workspace)
        sections = self._split_by_section(md_text)
        offset = 0
        for title, content in sections:
            paras = self._paragraphs(content)
            for local_i, para in enumerate(paras):
                for match in _CITE_RE.finditer(para):
                    eid = match.group(1)
                    try:
                        payload = store.get(eid)
                    except Exception:
                        continue
                    blob = _normalize_number(json.dumps(payload, ensure_ascii=False))
                    start = max(0, match.start() - 220)
                    # Strip the cite comment itself: its id contains hex digits
                    # that would otherwise be mistaken for numeric claims.
                    sentence = _CITE_RE.sub("", para[start:match.start()]).strip()
                    for number in _numbers_in(sentence):
                        if len(number.replace(",", "").replace(".", "")) < 2:
                            continue
                        if _normalize_number(number) not in blob:
                            issues.append(ReportIssue(
                                section=title,
                                kind="citation_mismatch", severity="warn",
                                excerpt=sentence[:120],
                                paragraph=offset + local_i,
                                evidence_id=eid,
                                message=f"数字 {number} 未在引用的证据中找到",
                                suggestion="核对证据后修改数字，或换用正确的 evidence",
                            ))
                            break
            offset += len(paras)
        # 补上"该有引用却没有"的段落：数字/政策表述无来源。只作写作建议，
        # 不改变 check_citation 原有的"引用正确性"职责。
        issues.extend(self.check_uncited_sensitive(md_text))
        return issues

    # ---- section completeness (advice only) ----

    SECTION_KEY_POINTS: dict[str, list[str]] = {
        "项目分析": ["注册资本", "股权", "业务"],
        "市场分析": ["市场", "竞争"],
        "对标与估值参考": ["可比公司", "估值"],
        "投资匹配分析": ["投资人", "匹配"],
        "匹配投资人明细": ["投资人"],
    }

    def check_data_field(self, md_text: str) -> list[ReportIssue]:
        """Report section completeness as advice, never as a blocker."""
        issues: list[ReportIssue] = []
        sections = self._split_by_section(md_text)
        present = {self._normalize_heading(title): (title, content) for title, content in sections}
        expected = self.required_sections or list(self.SECTION_KEY_POINTS)

        for required in expected:
            key = self._normalize_heading(required)
            if key not in present:
                issues.append(ReportIssue(
                    kind="missing_section", severity="warn",
                    section=required,
                    message=f"章节缺失: {required}",
                    suggestion="按 outline 补写该章节",
                ))
                continue
            title, content = present[key]
            points = self.SECTION_KEY_POINTS.get(key, [])
            missing = [point for point in points if point not in content]
            if missing:
                issues.append(ReportIssue(
                    kind="missing_data_field", severity="warn",
                    section=title,
                    message=f"该章节可能缺少关键点: {', '.join(missing)}",
                    suggestion="材料有则补写，材料无则写『材料未披露』",
                    terms=missing,
                    fixable=False,
                ))
        return issues

    # ---- citations ----

    def _check_citations(self, md_text: str) -> list[ReportIssue]:
        """Legacy ``check_report`` entry point.

        Only orphan detection remains: "this paragraph has no cite" was a poor
        proxy for a real citation problem — analytical paragraphs legitimately
        carry none. Citation quality is now handled by :meth:`check_citation`,
        which verifies the citations that actually exist.
        """
        issues: list[ReportIssue] = []
        known_eids = self._extract_known_eids(md_text)
        for eid, count in self._citation_counts(md_text).items():
            if known_eids and eid not in known_eids:
                issues.append(ReportIssue(
                    kind="orphaned_citation", severity="block",
                    evidence_id=eid, count=count,
                    message=f"孤立 cite '{eid}'（不在 evidence/index.json）",
                    suggestion="删除孤立 cite 或补 evidence 索引",
                ))
        return issues

    def _check_uncited_numbers(self, md_text: str) -> list[ReportIssue]:
        """Numbers and policy names are the most scrutinised claims.

        A paragraph carrying a business number (money, ratio, count) or a policy
        title must point at evidence, even when it is shorter than the generic
        citation threshold.
        """
        issues: list[ReportIssue] = []
        sections = self._split_by_section(md_text)
        offset = 0
        for title, content in sections:
            paras = self._paragraphs(content)
            for local_i, para in enumerate(paras):
                # A ``src`` marker is the project's *primary* provenance tag: it
                # carries both the citation and the Word comment. Checking only
                # ``cite`` flagged every correctly-sourced paragraph in a
                # one-pager report (11 false positives on one run).
                if _CITE_RE.search(para) or _SRC_MARKER_RE.search(para):
                    continue
                policy = _POLICY_RE.search(para)
                has_number = bool(_UNCITED_NUMBER_RE.search(para))
                if not has_number and not policy:
                    continue
                what = "政策名称" if policy else "数字"
                issues.append(ReportIssue(
                    section=title,
                    kind="uncited_fact", severity="warn",
                    locations=[offset + local_i],
                    paragraph=offset + local_i,
                    excerpt=para.strip()[:120],
                    terms=[policy.group(0)] if policy else [],
                    message=f"含{what}但段落无来源引用",
                    suggestion=f"补 <!-- cite: evidence_xxx -->，或删除无来源的{what}",
                ))
            offset += len(paras)
        return issues

    def check_uncited_sensitive(self, md_text: str) -> list[ReportIssue]:
        """段落含敏感数字或政策表述却没有 cite → warn（写作建议，不阻塞）。

        和 ``check_citation`` 的分工：

        * ``check_citation`` 验证**已有**引用是否正确（孤儿 id、数字对不上）
        * 本方法找**该有引用却没有**的段落

        排除三类不该被要求引用的内容：

        * 报告头部（任务元数据：日期、转让方）
        * 表格块（表格的 cite 通常写在表格后一行，单独判定会误报）
        * 纯标题行
        """
        issues: list[ReportIssue] = []
        sections = self._split_by_section(md_text)
        offset = 0
        for title, content in sections:
            if _HEADER_SECTION_RE.search(title.strip()):
                offset += len(self._paragraphs(content))
                continue
            paras = self._paragraphs(content)
            for local_i, para in enumerate(paras):
                body = para.strip()
                if not body or body.startswith("#"):
                    continue
                if body.startswith("|"):
                    continue
                if _CITE_RE.search(para):
                    continue

                policy_title = _POLICY_RE.search(body)
                policy_term = _POLICY_TERMS_RE.search(body)
                numbers = [m.group(0).strip() for m in _UNCITED_NUMBER_RE.finditer(body)]
                if not policy_title and not policy_term and not numbers:
                    continue

                terms: list[str] = []
                if policy_title:
                    terms.append(policy_title.group(0))
                if policy_term:
                    terms.append(policy_term.group(1))
                # 数字去重保序，最多展示 4 个
                for number in numbers:
                    if number not in terms:
                        terms.append(number)

                parts: list[str] = []
                if numbers:
                    parts.append("数字 " + "、".join(dict.fromkeys(numbers))[:60])
                if policy_title or policy_term:
                    label = (policy_title or policy_term).group(0)
                    parts.append(f"政策表述「{label}」")

                issues.append(ReportIssue(
                    section=title,
                    kind="uncited_sensitive",
                    severity="warn",
                    locations=[offset + local_i],
                    paragraph=offset + local_i,
                    excerpt=body[:120],
                    terms=terms[:8],
                    message="敏感内容缺少来源：" + "；".join(parts),
                    suggestion=(
                        "补 <!-- cite: evidence_xxx -->；若材料本身没披露，"
                        "改写为「材料未披露」而不是给出无来源数值"
                    ),
                    fixable=False,
                ))
            offset += len(paras)
        return issues

    def _extract_known_eids(self, md_text: str = "") -> set[str] | None:
        """Load the evidence ids registered for *this* run.

        Must use the current workspace: globbing ``.runtime/...`` returns
        whichever task happens to sort first, which made every citation of a
        different task look orphaned.
        """
        import json
        from pathlib import Path

        candidates: list[Path] = []
        if self.workspace is not None:
            try:
                candidates.append(self.workspace.resolve("/workspace/evidence/index.json"))
            except (OSError, ValueError):
                pass
        if not candidates:
            candidates = list(
                Path(".runtime/report-agent-workspaces").glob("*/evidence/index.json")
            )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            ids: set[str] = set()
            for key in ("evidence", "evidence_ids"):
                value = data.get(key)
                if isinstance(value, dict):
                    ids.update(value.keys())
                elif isinstance(value, list):
                    ids.update(str(item) for item in value)
            return ids
        return None

    @staticmethod
    def _citation_counts(md_text: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in _CITE_EID_RE.finditer(md_text):
            eid = m.group(1)
            counts[eid] = counts.get(eid, 0) + 1
        return counts

    # ---- required data fields ----

    def _check_data_fields(self, md_text: str) -> list[ReportIssue]:
        """Legacy required-field scan. Advisory only: whether the section is
        good enough is a writing judgement, not a blocking gate."""
        if len(md_text.strip()) < 50:
            return []
        issues: list[ReportIssue] = []
        for field in self.required_fields:
            if field not in md_text:
                issues.append(ReportIssue(
                    kind="missing_data_field", severity="warn",
                    message=f"必填字段缺失: {field}",
                    suggestion=f"材料有则补写 {field}，材料无则写『材料未披露』",
                    terms=[field],
                    fixable=False,
                ))
        return issues

    # ---- chapter balance ----

    def _check_balance(self, md_text: str) -> list[ReportIssue]:
        sections = self._split_by_section(md_text)
        if len(sections) < 3:
            return []
        sizes = [len(content) for _, content in sections]
        avg = mean(sizes)
        issues: list[ReportIssue] = []
        if max(sizes) > avg * 2.5 and avg > 0:
            issues.append(ReportIssue(
                kind="imbalanced_chapters", severity="warn",
                message=f"章节字数不均：最长 {max(sizes)}，平均 {int(avg)}",
                suggestion="重平衡章节",
            ))
        for title, content in sections:
            if len(content) < 200:
                issues.append(ReportIssue(
                    section=title,
                    kind="truncated_section", severity="warn",
                    message=f"章节过短: {len(content)} 字",
                    suggestion="扩展章节内容",
                ))
        return issues

    # ---- number / date / unit format ----

    def _check_format(self, md_text: str) -> list[ReportIssue]:
        issues: list[ReportIssue] = []
        formats = _NUMBER_FORMAT_RE.findall(md_text)
        seen_units: set[str] = set()
        for _, unit in formats:
            if unit:
                seen_units.add(unit)
        if "亿" in seen_units and (re.search(r"\d{1,3}(?:,\d{3}){2,}", md_text) or "万" in seen_units):
            issues.append(ReportIssue(
                kind="inconsistent_number_format", severity="warn",
                message="同一指标数字格式不一（亿 vs 元/万）",
                suggestion="统一为 X.XX 亿元",
            ))
        return issues

    # ---- authenticity: placeholders, fabricated numbers ----

    def _source_number_keys(self, md_text: str) -> set[tuple[Decimal, str]]:
        """Read numbers from this task's immutable materials / cited evidence.

        Source comments written by the model are not evidence. Uncited MCP
        results also cannot justify a claim merely by sharing a number.
        """
        if self.workspace is None:
            return set()
        from report_agent.infrastructure.evidence import WorkspaceEvidenceStore

        store = WorkspaceEvidenceStore(self.workspace)
        cited = set(self._citation_counts(md_text))
        # One-pagers use src markers carrying the tool name rather than an eid.
        source_tools = set(re.findall(r"<!--\s*src:\s*mcp\s+(\w+)", md_text))
        keys: set[tuple[Decimal, str]] = set()
        root = self.workspace.resolve("/workspace/evidence")
        for path in root.glob("evidence_*.json"):
            try:
                payload = store.get(path.stem)
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            tool = payload.get("tool")
            if tool != "parse_materials" and path.stem not in cited and tool not in source_tools:
                continue
            text = json.dumps(payload.get("data", {}), ensure_ascii=False)
            keys.update(_evidence_number_key(m) for m in _EVIDENCE_NUMBER_RE.finditer(text))
        return keys

    def _check_authenticity(self, md_text: str) -> list[ReportIssue]:
        # Strip HTML comments first so cite markers like '<!-- ... -->'
        # don't trigger the placeholder regex (e.g. on the ellipsis).
        stripped = strip_source_markers(md_text)
        issues: list[ReportIssue] = []
        for m in _PLACEHOLDER_RE.finditer(stripped):
            issues.append(ReportIssue(
                kind="placeholder_text", severity="block",
                locations=[self._paragraph_index(md_text, m.start())],
                message=f"含占位符 '{m.group(0)}'",
                suggestion="删除占位符或填真实内容",
            ))
        approximate = list(_FABRICATED_NUM_RE.finditer(stripped))
        source_numbers = self._source_number_keys(md_text) if approximate else set()
        for m in approximate:
            number = _EVIDENCE_NUMBER_RE.search(m.group(0))
            if number is not None and _evidence_number_key(number) in source_numbers:
                continue
            issues.append(ReportIssue(
                kind="fabricated_number", severity="block",
                locations=[self._paragraph_index(md_text, m.start())],
                message=f"材料未披露的模糊数 '{m.group(0)}'",
                suggestion="改用具体值或写'材料未披露'",
            ))
        return issues

    # ---- professional polish: terminology, abbreviations ----

    def _check_professionalism(self, md_text: str) -> list[ReportIssue]:
        issues: list[ReportIssue] = []
        abbrev_seen: set[str] = set()
        for m in _ABBREV_RE.finditer(md_text):
            abbrev = m.group(1)
            abbrev_seen.add(abbrev)
        if abbrev_seen:
            issues.append(ReportIssue(
                kind="abbreviation_undefined", severity="warn",
                message=f"缩写首次未展开: {', '.join(sorted(abbrev_seen))}",
                suggestion="首次出现给全称",
            ))
        return issues

    # ---- helpers ----

    @staticmethod
    def _paragraphs(md_text: str) -> list[str]:
        return [p for p in _PARAGRAPH_RE.split(md_text) if p.strip()]

    @staticmethod
    def _paragraph_index(md_text: str, char_pos: int) -> int:
        return md_text[:char_pos].count("\n\n")

    @staticmethod
    def _split_by_section(md_text: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        current_title = ""
        current_content: list[str] = []
        for line in md_text.splitlines():
            m = _SECTION_RE.match(line)
            if m:
                if current_title or current_content:
                    sections.append((current_title, "\n".join(current_content)))
                current_title = m.group(1)
                current_content = []
            else:
                current_content.append(line)
        if current_title or current_content:
            sections.append((current_title, "\n".join(current_content)))
        return sections


class AITellDetector:
    """Detect LLM writing patterns in finished report markdown.

    Five categories: template transitions, bureaucratic phrasing,
    em-dash overuse, list-stacking, and vocabulary tells.
    Investment reports are formal — this detector does NOT check
    for colloquial language.
    """

    PATTERNS: dict[str, tuple[str, int, str]] = {
        "template_transition": (
            r"(综上所述|由此可见|值得注意|首先.*?其次.*?最后|不难发现|显而易见|众所周知)",
            2,
            "block",
        ),
        "conclusion_cliche": (r"综上所述[，,。：:]|总而言之", 1, "block"),
        "bureaucratic_phrase": (
            r"(具有重要意义|发挥关键作用|持续优化|稳步推进|深入贯彻|充分体现|有力推动|全面提升|赋能|助力|提质增效|稳中有进)",
            3,
            "block",
        ),
        "ai_vocabulary": (
            r"(至关重要|显著提升|大幅增长|不断深化|全面加强|扎实推进|凸显|聚焦|统筹)",
            3,
            "block",
        ),
        "fake_specificity": (r"(约|大致)\s*\d+(\.\d+)?\s*(%|亿|万)?", 3, "warn"),
        "unsupported_attribution": (
            # A long investment report legitimately uses causal wording a few
            # times; one stray connector should not block delivery, but a
            # pattern of them means the prose is asserting causation the
            # material never established.
            r"(源于|得益于|反映出|受益于|正是由于|归功于|保驾护航)",
            3,
            "block",
        ),
        # 绝对化 / 夸大 / 承诺性表述。
        #
        # 这类词**不一定错**：「中国首台」「唯一具备全产业链」在材料支持时是真事实。
        # 所以只给 warn，并且提示要出处——没有出处的绝对化表述是投资人最先质疑的地方。
        "absolute_claim": (
            r"(最先进|最大|最强|最优|最高端|唯一|首个|首家|首台|填补空白|零的突破|"
            r"完全替代|全面领先|绝对领先|必然|一定能够|百分之百|100%)",
            2,
            "warn",
        ),
        "exaggerated_claim": (
            r"(巨大|颠覆|革命性|遥遥领先|爆发式|井喷|空前|史无前例|无可比拟|"
            r"无可替代|独一无二|垄断地位)",
            2,
            "warn",
        ),
        "promissory_claim": (
            r"(保证|承诺|必将|势必|稳赚|无风险|包赚|确定性强|必然实现|确保收益)",
            1,
            "warn",
        ),
    }

    SUGGESTIONS: dict[str, str] = {
        "template_transition": "改用具体引导（'按上述数据，…'）",
        "conclusion_cliche": "用具体结论代替",
        "bureaucratic_phrase": "改用数据描述（'贡献集团合并收入 23%'）",
        "ai_vocabulary": "用具体数据 / 因果链代替",
        "fake_specificity": "删去或写'材料未披露具体数值'",
        "unsupported_attribution": "改为分别陈述事实与结果，或写'材料未说明原因'",
        "absolute_claim": "绝对化表述要么补出处（如'材料第 N 页称中国首台'），要么改成具体事实",
        "exaggerated_claim": "换成可复核的数据或事实描述",
        "promissory_claim": "删除承诺性表述——报告只能陈述事实，不能替标的作承诺",
    }

    def check(self, md_text: str) -> list[ReportIssue]:
        """Report AI-style wording as advice with concrete terms and excerpts.

        Always ``warn``: this is decision support for the agent, not a gate.
        The excerpt lets the agent jump straight to edit_file without grepping.
        """
        issues: list[ReportIssue] = []
        for kind, (pattern, threshold, _severity) in self.PATTERNS.items():
            hits = list(re.finditer(pattern, md_text))
            if len(hits) < threshold:
                continue
            terms = sorted({match.group(0) for match in hits})
            first = hits[0]
            para_index = md_text[: first.start()].count("\n\n")
            excerpt = _CITE_RE.sub(
                "", md_text[max(0, first.start() - 40) : first.end() + 40]
            )
            issues.append(ReportIssue(
                kind=kind,
                severity="warn",
                count=len(hits),
                terms=terms,
                paragraph=para_index,
                excerpt=excerpt.replace("\n", " ").strip()[:120],
                message=f"AI 用语 '{kind}' 出现 {len(hits)} 次：{', '.join(terms[:6])}",
                suggestion=self.SUGGESTIONS[kind],
            ))
        issues += self._check_em_dash(md_text)
        issues += self._check_list_overuse(md_text)
        issues += self._check_uniform_paragraph(md_text)
        issues += AITellDetector._check_section_restatement(md_text)
        return issues

    @staticmethod
    def _check_section_restatement(md_text: str) -> list[ReportIssue]:
        """Flag prose blocks that mostly restate one another.

        The Lingda workflow splits intro and highlight prose across two prompts
        so restatement cannot happen; a single-pass write still can. The first
        live run produced three near-identical paragraphs that every existing
        rule happily passed.
        """
        blocks = [
            body for _title, body in _iter_h3_blocks(md_text) if len(_compact(body)) >= SHINGLE_SIZE * 2
        ]
        if len(blocks) < 2:
            return []
        worst = 0.0
        for index, left in enumerate(blocks):
            for right in blocks[index + 1 :]:
                worst = max(worst, _shingle_overlap(left, right))
        if worst <= SECTION_REPEAT_THRESHOLD:
            return []
        return [ReportIssue(
            kind="section_restatement",
            severity="block",
            count=2,
            message=(
                f"存在近乎重复的段落（重合度 {worst:.0%}，阈值 {SECTION_REPEAT_THRESHOLD:.0%}）。"
                "项目介绍只写「是什么」，项目亮点只写「为什么值得投」，同一事实只出现在其中一处。"
            ),
            suggestion="按分工边界重写：数据/资质/成果归亮点，定位/构成/业务范围归介绍。",
        )]

    @staticmethod
    def _check_em_dash(md_text: str) -> list[ReportIssue]:
        if len(md_text) < 10:
            return []
        em_count = md_text.count("——")
        ratio = em_count / len(md_text)
        if ratio > 0.05:
            return [ReportIssue(
                kind="em_dash_overuse", severity="warn", count=em_count,
                message=f"破折号 '——' 占比 {ratio:.1%}（> 5%）",
                suggestion="替换为句号 / 顿号（投资报告避免文学化破折号）",
            )]
        return []

    @staticmethod
    def _check_list_overuse(md_text: str) -> list[ReportIssue]:
        consecutive = 0
        max_consecutive = 0
        for line in md_text.splitlines():
            if re.match(r"^\s*\d+[.、]\s", line):
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0
        if max_consecutive >= 3:
            return [ReportIssue(
                kind="list_overuse", severity="warn", count=max_consecutive,
                message=f"连续 {max_consecutive} 个 bullet list（投资报告应少用）",
                suggestion="合并为段落叙事（'如 X、Y、Z 三方面'）",
            )]
        return []

    @staticmethod
    def _check_uniform_paragraph(md_text: str) -> list[ReportIssue]:
        paragraphs = [p for p in _PARAGRAPH_RE.split(md_text) if len(p) > 30]
        if len(paragraphs) < 3:
            return []
        sizes = [len(p) for p in paragraphs]
        m = mean(sizes)
        if m < 50:
            return []
        cv = pstdev(sizes) / m
        if cv < 0.20:
            return [ReportIssue(
                kind="uniform_paragraph", severity="warn",
                message=f"段长变异系数 {cv:.2f} < 0.20（机器人齐整感）",
                suggestion="长段分析 + 短段结论，错落",
            )]
        return []
