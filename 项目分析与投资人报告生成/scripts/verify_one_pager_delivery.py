"""Verify a logged draft through real DOCX rendering and a local publish callback.

No model, shell sandbox, Data MCP, or object-storage connection is required.
Use --wheel to test the exact non-editable package deployed on Linux.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile


def verify_delivery(fixture: Path, output: Path, *, render_pdf: bool = False) -> list[dict]:
    from lxml import etree
    from report_agent.application.interactions import update_interaction
    from report_agent.application.one_pager_reports import OnePagerReportService
    from report_agent.application.review_checker import QualityChecker
    from report_agent.domain.artifacts import PublishedArtifact
    from report_agent.domain.one_pager import BusinessType
    from report_agent.harness.one_pager_tools import (
        build_one_pager_tools,
        preflight_one_pager_md,
    )
    from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
    from report_agent.infrastructure.word.one_pager_authoring import resolve_template
    from report_agent.infrastructure.word.one_pager_md_parser import (
        parse_one_pager_markdown,
    )
    from report_agent.infrastructure.word.rendering import LibreOfficeRenderer
    from report_agent.runtime.workspace import TaskWorkspace

    reports = []
    for business_type in BusinessType:
        workspace = TaskWorkspace(output / business_type.name.lower())
        workspace.initialize()
        md = fixture.read_text(encoding="utf-8")
        if business_type is BusinessType.CAPITAL:
            md = md.replace("| 转让底价 | 面议 |", "| 拟募集金额 | 面议 |")
        before = md
        assert preflight_one_pager_md(md, business_type.value) == []
        parsed = parse_one_pager_markdown(md, business_type=business_type, report_id="log-replay")
        assert len(parsed.intro_sections) == len(parsed.highlight_sections) == 3
        assert all("<src" not in s.body for s in (*parsed.intro_sections, *parsed.highlight_sections))
        assert "约1180人" in parsed.highlight_sections[1].body
        WorkspaceEvidenceStore(workspace).put("parse_materials", {
            "tool": "parse_materials", "status": "success", "summary": "日志材料中的数字原文",
            "data": {"blocks": [{"text": "会议设备齐全，总共可容纳约1180人。资产负债率约11%。"}]},
        })
        checks = QualityChecker(workspace=workspace).check(md)
        assert not [i for i in checks if i.severity == "block"], checks
        md_path = "/workspace/report/one-pager.md"
        workspace.write_text(md_path, md)
        update_interaction(workspace, business_type_selection={"value": business_type.value, "source": "user"})
        service = OnePagerReportService(
            workspace, skill_version="0" * 64,
            renderer=LibreOfficeRenderer() if render_pdf else None,
        )
        publications = []

        def publish(staged_path: str, *, report_workspace=workspace, sent=publications) -> PublishedArtifact:
            content = report_workspace.export_staged(staged_path)
            digest = hashlib.sha256(content).hexdigest()
            result = PublishedArtifact(
                artifact_id="artifact_" + digest[:32], filename=Path(staged_path).name,
                sha256=digest, size=len(content), bucket="local-verification",
                object_key=Path(staged_path).name,
                download_url="https://example.invalid/local-verification.docx",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            sent.append(result)
            return result

        tools = {t.name: t for t in build_one_pager_tools(workspace, service=service, publish=publish)}
        rendered = json.loads(tools["render_one_pager"].invoke({
            "md_path": md_path, "business_type": business_type.value,
            "report_id": "log-replay", "filename": business_type.name.lower() + ".docx",
        }))
        assert rendered["status"] == "ok", rendered
        assert not [i for i in rendered["issues"] if i["code"] != "PAGE_LIMIT_EXCEEDED"], rendered
        if render_pdf:
            assert rendered["pages"] is not None, "LibreOffice did not produce a PDF"
        published = json.loads(tools["validate_and_publish_one_pager"].invoke({"artifact_id": rendered["artifact_id"]}))
        assert published["status"] == "published", published
        assert len(publications) == 1
        assert workspace.read_text(md_path) == before, "rendering must not rewrite facts to meet word counts"
        docx = workspace.resolve(rendered["path"])
        with ZipFile(docx) as archive:
            xml = etree.fromstring(archive.read("word/document.xml"))
            text = "".join(xml.itertext())
            assert "<src" not in text and "evidence_" not in text and "{{" not in text
            assert "约1180人" in text and "示例酒店股份有限公司" in text
        reports.append({"business_type": business_type.value, "template": str(resolve_template(business_type)),
                        "status": published["status"], "docx": str(docx), "pages": rendered["pages"],
                        "body_lengths": [len("".join(s.body.split()))
                                         for s in (*parsed.intro_sections, *parsed.highlight_sections)]})
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--render-pdf", action="store_true")
    args = parser.parse_args()
    if args.wheel:
        installed = args.output / "installed"
        with ZipFile(args.wheel) as archive:
            archive.extractall(installed)
        sys.path.insert(0, str(installed))
    print(json.dumps(verify_delivery(args.fixture, args.output, render_pdf=args.render_pdf),
                     ensure_ascii=False, indent=2))
