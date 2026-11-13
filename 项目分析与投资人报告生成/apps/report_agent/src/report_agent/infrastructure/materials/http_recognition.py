"""Sync HTTP adapters for multimodal vision recognition and PaddleOCR layout parsing."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from report_agent.application.recognition import PageRecognition
from report_agent.domain.materials import PageImage

logger = logging.getLogger(__name__)

VALID_LAYOUTS = {"text", "table", "image", "title", "chart", "mixed"}

# CoT prompt adapted from knowledge-pipeline-hub/pipelines/ppt_pipeline/chunker.py.
# One page = one chunk; the model returns JSON ``{chunks:[{layout,text}]}``.
VISION_PROMPT = """你是一个专业的文档页面信息提取助手。请仔细分析这张页面图片，提取其中的有效信息。

请先进行思考分析，然后输出结构化结果。

## 核心原则（最重要）
**一页 = 一个切片（chunk）**。无论这一页内容多复杂、包含多少模块（标题/正文/表格/图示/流程图等），都必须整合输出为**唯一一个** chunk，把整页的完整文本内容放入该 chunk 的 text 字段。
- 严禁把一页拆分为多个 chunk
- 严禁只提取页面某一部分而遗漏其他部分
- text 必须承载该页的**全部有效信息**，保持完整语义

## 分析步骤（思维链）
请先在 `思维过程` 标签内进行思考，包括：
1. 观察页面整体布局，判断主要内容类型（文本/表格/图表/图片/标题）
2. 识别页面的信息结构（标题、段落、列表、表格行列、图示说明等）
3. 规划如何将本页**所有内容整合为一段结构化文本**，按阅读顺序组织，保留层级和逻辑关系
4. 自检：是否遗漏了页面任何有效信息区域？是否误把整页拆成多块？

## 提取要求
1. layout：该页布局类型，取值之一：text（纯文本）、table（表格）、image（图片为主）、title（标题页）、chart（图表）、mixed（混合，指一页中同时存在多种内容形态）
2. text：该页**全部**有效文本内容，要求：
   - 保留信息的完整性和层级关系
   - 表格内容用 markdown 表格格式输出
   - 列表内容保留层级缩进
   - 多个信息块之间用合理的标题层级（# / ## / ###）或空行分隔，使整页内容在一段文本内保持可读的结构
   - 忽略纯装饰性元素（背景图、页码、Logo 等）
3. **图示里的状态必须逐格读出，不能用整页概括代替**。进度矩阵、里程碑流程图、点阵图等
   用形状（实心圆 / 空心圆 / 灰色圆点）表达的状态，是这页最关键的信息：
   - 写成 markdown 表格：行=主体（如「三一（工程机械）」），列=阶段（如「送样/台架/整机/准入/批量」），单元格=状态
   - 状态用原文词：已完成 / 进行中 / 未开始（按页面图例的措辞）
   - 一格也读不出来时写「未能辨认」，**不要猜**，也不要跳过这行
   - 只写「多数客户已完成整机验证」这种概括，等于丢掉这页的信息

## 输出格式
思考完成后，请用 ```json ```代码块输出最终结果，格式如下：

<思维过程>
你的分析思考过程...
</思维过程>

```json
{
  "chunks": [
    {
      "layout": "mixed",
      "text": "该页提取的完整文本内容（整合所有信息块）"
    }
  ]
}
```

注意：
- chunks 数组**有且仅有一个**元素
- 该 chunk 的 text 不能为空
- 只在 ```json ```代码块中输出 JSON，思考过程放在 <思维过程> 标签内"""


def _extract_json_block(text: str) -> str:
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0).strip()
    return ""


@dataclass(slots=True)
class OpenAICompatibleVisionAdapter:
    """Sync multimodal recognizer: one page image -> structured text."""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 180
    max_retries: int = 3

    def recognize(self, page: PageImage) -> PageRecognition:
        messages: list[dict[str, object]] = [{"role": "user", "content": VISION_PROMPT}]
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                content = self._complete(messages, page)
            except Exception as exc:  # noqa: BLE001 - retry on any transport/parse error
                last_error = str(exc)
                logger.warning("vision recognize attempt %d failed: %s", attempt, last_error)
                continue
            text = self._parse_chunk_text(content)
            if text is not None:
                return PageRecognition(text=text)
            last_error = "model output did not contain a valid chunk"
            if attempt < self.max_retries:
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        f"你上次的输出解析失败，错误原因：{last_error}\n"
                        "请重新输出：用 ```json 代码块输出合法 JSON，"
                        "chunks 数组有且仅有一个元素，text 字段为整页完整内容且非空。"
                    ),
                })
        return PageRecognition(text=f"[vision recognition failed: {last_error}]", confidence=0.0)

    def _parse_chunk_text(self, content: str) -> str | None:
        if not content or not content.strip():
            return None
        json_str = _extract_json_block(content)
        if not json_str:
            return None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        chunks_data = data.get("chunks")
        if not isinstance(chunks_data, list) or not chunks_data:
            return None
        texts = [
            item.get("text", "")
            for item in chunks_data
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
        ]
        return "\n\n".join(texts) if texts else None

    def _complete(self, messages: list[dict[str, object]], page: PageImage) -> str:
        encoded = base64.b64encode(page.path.read_bytes()).decode("ascii")
        user_content: list[dict[str, object]] = [
            {"type": "text", "text": str(messages[-1].get("content", ""))},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{page.media_type};base64,{encoded}"},
            },
        ]
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": user_content}],
                },
            )
            response.raise_for_status()
            payload = response.json()
        return str(payload["choices"][0]["message"]["content"])


def _find_text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("markdown", "text", "content", "result"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for candidate in value.values():
            found = _find_text(candidate)
            if found:
                return found
    if isinstance(value, list):
        parts = [_find_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    return ""


@dataclass(slots=True)
class PaddleLayoutAdapter:
    """Sync PaddleOCR layout-parsing adapter: whole PDF -> per-page markdown."""

    endpoint: str
    token: str
    timeout_seconds: int = 300

    def recognize_pdf(self, pdf_path: Path) -> list[PageRecognition]:
        """Call layout-parsing(-vl) with JSON base64 body.

        UAT/prod VL gateways reject multipart uploads with HTTP 422
        (``model_attributes_type``). They require ``file`` as raw base64 and
        ``fileType`` 0 for PDF / 1 for image.
        """
        encoded = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
        body = {
            "file": encoded,
            "fileType": 0,
            "useLayoutDetection": True,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(body),
            )
            response.raise_for_status()
            payload = response.json()
        results = self._extract_page_markdowns(payload)
        if not results:
            raise ValueError("PaddleOCR response contains no recognized pages")
        return results

    @staticmethod
    def _extract_page_markdowns(payload: dict[str, object]) -> list[PageRecognition]:
        """Parse ``result.layoutParsingResults[].markdown.text`` into per-page recognitions.

        Falls back to a single whole-document text when the structured layout
        array is absent (older endpoint variants).
        """
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            text = _find_text(payload)
            return [PageRecognition(text=text)] if text else []
        pages = result.get("layoutParsingResults")
        if isinstance(pages, list) and pages:
            recognitions: list[PageRecognition] = []
            for item in pages:
                if not isinstance(item, dict):
                    continue
                markdown = item.get("markdown")
                text = ""
                if isinstance(markdown, dict):
                    text = str(markdown.get("text") or "").strip()
                if not text:
                    text = _find_text(item)
                if text:
                    recognitions.append(PageRecognition(text=text))
            return recognitions
        text = _find_text(result)
        return [PageRecognition(text=text)] if text else []
