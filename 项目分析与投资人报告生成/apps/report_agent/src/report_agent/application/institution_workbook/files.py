"""Bounded MCP/file boundary. No raw validation exceptions or Base64 in logs."""

from __future__ import annotations

import base64
import hashlib
import io
import math
import zipfile
from pathlib import Path

from report_agent.infrastructure.mcp.contracts import McpContractRegistry

TOOL = "export_matched_institutions"
FILENAME = "投资机构匹配.xlsx"
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = ["投资机构名称", "权重分数", "匹配标签数（接口）", "匹配到的标签"]


class ExportFailure(ValueError):
    """Only fixed codes belong in this exception."""

    @property
    def public_message(self):
        messages = {
            "DMP_EXPORT_NOT_CONFIGURED": "DMP 附件查询未配置，请联系管理员检查当前环境配置。",
            "DMP_EXPORT_HTTP_ERROR": "DMP 附件接口返回请求错误，请稍后重试附件。",
            "DMP_EXPORT_UNAVAILABLE": "当前环境无法连接 DMP，请稍后重试或联系管理员确认访问条件。",
            "DMP_EXPORT_TIMEOUT": "DMP 附件查询超时，请稍后重试附件。",
            "DMP_EXPORT_INVALID_RESPONSE": "DMP 附件响应格式无效，请联系管理员检查接口返回。",
            "DMP_EXPORT_RESPONSE_TOO_LARGE": "DMP 附件响应超过大小上限，请缩小标签范围。",
            "WORKBOOK_EXPORT_BUSY": "附件导出服务繁忙，请稍后重试。",
            "DMP_EXPORT_FAILED": "DMP 附件导出失败，请稍后重试附件。",
            "EXPORT_TRANSPORT_ERROR": "无法连接附件导出服务，请稍后重试附件。",
            "EXPORT_CONTRACT_ERROR": "附件导出配置或标签参数无效，请联系管理员检查。",
            "INVALID_EXPORT_RESPONSE": "附件导出服务响应格式无效，请联系管理员检查。",
            "INVALID_WORKBOOK_FILE": "Excel 文件校验失败，请重新生成附件。",
        }
        return messages.get(str(self), "附件处理失败，请重试附件；原报告已保留。")


async def call_export(transport, contracts_root: Path, tags: list[str]) -> dict:
    try:
        registry = McpContractRegistry(contracts_root, (TOOL,))
        registry.validate_input(TOOL, {"track_tags": tags})
    except Exception:
        raise ExportFailure("EXPORT_CONTRACT_ERROR") from None
    try:
        payload = await transport.call_tool(TOOL, {"track_tags": tags})
    except TimeoutError:
        raise ExportFailure("DMP_EXPORT_TIMEOUT") from None
    except Exception:
        raise ExportFailure("EXPORT_TRANSPORT_ERROR") from None
    try:
        registry.validate_output(TOOL, payload)
    except Exception:
        raise ExportFailure("INVALID_EXPORT_RESPONSE") from None
    if payload["status"] == "failed":
        codes = {
            "DMP_EXPORT_NOT_CONFIGURED",
            "DMP_EXPORT_HTTP_ERROR",
            "DMP_EXPORT_UNAVAILABLE",
            "DMP_EXPORT_TIMEOUT",
            "DMP_EXPORT_INVALID_RESPONSE",
            "DMP_EXPORT_RESPONSE_TOO_LARGE",
            "WORKBOOK_EXPORT_BUSY",
        }
        code = next(
            (w["code"] for w in payload["warnings"] if w["code"] in codes), "DMP_EXPORT_FAILED"
        )
        raise ExportFailure(code)
    return payload


def validate_file(payload: dict, tags: list[str], max_bytes: int) -> tuple[bytes, dict]:
    try:
        return _validate_file(payload, tags, max_bytes)
    except Exception:
        raise ExportFailure("INVALID_WORKBOOK_FILE") from None


def _parse_weight_score(score: object) -> float:
    """Accept numeric cells or text cells written for display (e.g. ``\"82.5\"``, ``\"90\"``)."""
    if isinstance(score, bool):
        raise ValueError()
    if isinstance(score, (int, float)):
        number = float(score)
    elif isinstance(score, str):
        text = score.strip()
        if not text:
            raise ValueError()
        number = float(text)
    else:
        raise ValueError()
    if not math.isfinite(number):
        raise ValueError()
    return number


def _validate_file(payload, tags, max_bytes):
    from openpyxl import load_workbook

    data = payload["data"]
    encoded = data["content_base64"]
    if (
        data["filename"] != FILENAME
        or data["query_tags"] != tags
        or not isinstance(encoded, str)
        or len(encoded) > 4 * ((max_bytes + 2) // 3)
    ):
        raise ValueError()
    content = base64.b64decode(encoded, validate=True)
    if (
        not content
        or len(content) > max_bytes
        or hashlib.sha256(content).hexdigest() != data["sha256"]
    ):
        raise ValueError()
    count = data["row_count"]
    if type(count) is not int or not 0 <= count <= 200:
        raise ValueError()
    for key in ("unverified_row_count", "count_mismatch_row_count"):
        if type(data[key]) is not int or not 0 <= data[key] <= count:
            raise ValueError()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        if (
            len(infos) > 100
            or sum(i.file_size for i in infos) > 16 * 1024 * 1024
            or any(
                i.flag_bits & 1 or i.filename.startswith("/") or ".." in i.filename.split("/")
                for i in infos
            )
            or not {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"}
            <= set(archive.namelist())
            or any("vbaProject" in i.filename or "externalLinks" in i.filename for i in infos)
        ):
            raise ValueError()
    book = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
    try:
        if book.sheetnames != ["投资机构"]:
            raise ValueError()
        sheet = book.active
        if sheet is None or sheet.max_row != count + 1 or sheet.max_column != 4:
            raise ValueError()
        rows = list(sheet.iter_rows(max_row=201, max_col=4))[: count + 1]
        if [c.value for c in rows[0]] != HEADERS:
            raise ValueError()
        preview = []
        last_score = math.inf
        count_mismatch = 0
        for index, row in enumerate(rows[1:]):
            name, score, number, labels = [c.value for c in row]
            try:
                parsed_score = _parse_weight_score(score)
            except (TypeError, ValueError):
                raise ValueError() from None
            if (
                any(c.data_type in {"f", "e"} for c in row)
                or not isinstance(name, str)
                or not name.strip()
                or len(name) > 1000
                or parsed_score > last_score
                or (
                    number is not None and (type(number) is not int or not 0 <= number <= 2**31 - 1)
                )
                or (labels is not None and (not isinstance(labels, str) or len(labels) > 1610))
            ):
                raise ValueError()
            last_score = parsed_score
            verified = labels.split("、") if labels else []
            if verified != [tag for tag in tags if tag in verified]:
                raise ValueError()
            if number is not None and number != len(verified):
                count_mismatch += 1
            if index < 20:
                preview.append([name, score, number, labels or ""])
        if (
            len(rows) != count + 1
            or (payload["status"] == "empty") != (count == 0)
            or count_mismatch != data["count_mismatch_row_count"]
        ):
            raise ValueError()
        return content, {
            "columns": HEADERS,
            "rows": preview,
            "row_count": count,
            "query_tags": tags,
            "unverified_row_count": data["unverified_row_count"],
            "count_mismatch_row_count": data["count_mismatch_row_count"],
            "note": "首批最多 200 家；第三列为接口数量，第四列为可核验的标签名称。",
        }
    finally:
        book.close()
