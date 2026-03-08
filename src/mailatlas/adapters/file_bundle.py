from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


class _BundleHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        normalized = data.strip()
        if normalized:
            self.chunks.append(normalized)


@dataclass
class BundleDocument:
    path: str
    subject: str
    content: str


def load_file_bundle(paths: list[str | Path]) -> list[BundleDocument]:
    results: list[BundleDocument] = []
    for path_value in paths:
        path = Path(path_value).expanduser().resolve()
        raw = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() in {".html", ".htm"}:
            parser = _BundleHTMLTextExtractor()
            parser.feed(raw)
            content = "\n".join(parser.chunks)
        else:
            content = raw
        results.append(BundleDocument(path=path.as_posix(), subject=path.stem, content=content.strip()))
    return results
