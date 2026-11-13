"""The production draft must reach a real DOCX and the publisher without rewrites."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts.verify_one_pager_delivery import verify_delivery

from report_agent.domain.one_pager import BusinessType
from report_agent.domain.source_markers import strip_source_markers
from report_agent.infrastructure.word import one_pager_authoring


def test_logged_draft_renders_and_publishes_for_both_templates(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "one_pager_hotel_sources.md"
    reports = verify_delivery(fixture, tmp_path)
    assert len(reports) == 2 and all(r["status"] == "published" for r in reports)
    # The failed run reported 500-700 characters by counting provenance tags.
    assert reports[0]["body_lengths"] == [267, 310, 198, 209, 199, 189]


@pytest.mark.parametrize("kind", list(BusinessType))
def test_templates_resolve_in_non_editable_linux_install_without_skill_mount(tmp_path, monkeypatch, kind):
    source = one_pager_authoring.resolve_template(kind)
    package = tmp_path / "lib" / "python3.12" / "site-packages" / "report_agent"
    installed_module = package / "infrastructure" / "word" / "one_pager_authoring.py"
    assets = package / "resources" / "one_pager"
    assets.mkdir(parents=True)
    expected = assets / source.name
    shutil.copyfile(source, expected)
    monkeypatch.setattr(one_pager_authoring, "__file__", str(installed_module))
    assert one_pager_authoring.resolve_template(kind) == expected
    with pytest.raises(FileNotFoundError):
        one_pager_authoring.resolve_template(kind, assets_dir=tmp_path / "explicit-missing-assets")


def test_source_tags_with_multiline_and_angle_brackets_preserve_visible_facts():
    md = '会议约1180人。<src\n cite="evidence_a" note="容量 > 1000"/>保留事实。<!-- src: 注释\n -->'
    assert strip_source_markers(md) == "会议约1180人。保留事实。"
