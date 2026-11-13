"""External document conversion and extraction services (sync HTTP)."""

from __future__ import annotations

from pathlib import Path

import httpx


class GotenbergConverter:
    """Convert Office documents to PDF via the Gotenberg LibreOffice route."""

    def __init__(self, url: str, timeout_seconds: int = 300) -> None:
        self.url = url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def to_pdf(self, source: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        endpoint = f"{self.url}/forms/libreoffice/convert"
        with httpx.Client(timeout=self.timeout_seconds) as client, source.open("rb") as handle:
            response = client.post(
                endpoint,
                files={"files": (source.name, handle, "application/octet-stream")},
            )
            response.raise_for_status()
        target = output_dir / f"{source.stem}.pdf"
        target.write_bytes(response.content)
        return target


class TikaTextExtractor:
    """Extract plain text from Office documents via Apache Tika `/tika`."""

    def __init__(self, url: str, timeout_seconds: int = 300) -> None:
        self.url = url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def extract(self, source: Path) -> str:
        endpoint = f"{self.url}/tika"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.put(
                endpoint,
                headers={"Accept": "text/plain"},
                content=source.read_bytes(),
            )
            response.raise_for_status()
        text = response.text
        if not text.strip():
            raise ValueError(f"Tika returned empty text for {source.name}")
        return text
