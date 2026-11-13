"""Detect supported office formats from content signatures."""

from __future__ import annotations

import zipfile
from pathlib import Path

from report_agent.domain.materials import MaterialFormat


class UnsupportedMaterialError(ValueError):
    pass


def detect_material_format(path: Path) -> MaterialFormat:
    header = path.read_bytes()[:8]
    suffix = path.suffix.lower()
    if header.startswith(b"%PDF-"):
        return MaterialFormat.PDF
    if header.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        if "word/document.xml" in names:
            return MaterialFormat.DOCX
        if "ppt/presentation.xml" in names:
            return MaterialFormat.PPTX
        if "xl/workbook.xml" in names:
            return MaterialFormat.XLSX
    if header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        legacy = {
            ".doc": MaterialFormat.DOC,
            ".ppt": MaterialFormat.PPT,
            ".xls": MaterialFormat.XLS,
        }
        if suffix in legacy:
            return legacy[suffix]
    if suffix == ".csv":
        return MaterialFormat.CSV
    raise UnsupportedMaterialError(f"unsupported or mismatched material format: {path.name}")
