"""Render DOCX to PDF and per-page PNG files using LibreOffice and PyMuPDF."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True, slots=True)
class RenderResult:
    pdf: Path
    pages: tuple[Path, ...]


class LibreOfficeRenderer:
    def __init__(self, executable: str = "soffice", timeout_seconds: int = 180) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def render(self, source: Path, output_dir: Path) -> RenderResult:
        source = source.resolve(strict=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as profile:
            completed = subprocess.run(
                [
                    self.executable,
                    "--headless",
                    f"-env:UserInstallation={Path(profile).as_uri()}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(source),
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env={**os.environ, "HOME": profile},
            )
        if completed.returncode != 0:
            raise RuntimeError(f"LibreOffice render failed: {completed.stderr.strip()}")
        pdf = output_dir / f"{source.stem}.pdf"
        if not pdf.is_file() or pdf.stat().st_size == 0:
            raise RuntimeError("LibreOffice did not produce a non-empty PDF")
        pages: list[Path] = []
        with pymupdf.open(pdf) as document:
            for index, page in enumerate(document, 1):
                target = output_dir / f"page-{index}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(target)
                pages.append(target)
        if not pages:
            raise RuntimeError("rendered PDF has no pages")
        return RenderResult(pdf=pdf, pages=tuple(pages))
