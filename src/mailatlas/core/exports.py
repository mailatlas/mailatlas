from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path

from .pdf import render_pdf_from_html
from .storage import WorkspaceStore


def _document_to_markdown(store: WorkspaceStore, document_id: str) -> str:
    document = store.get_document(document_id)
    lines = [f"# {document.subject}", ""]
    if document.author:
        lines.append(f"Author: {document.author}")
    if document.received_at:
        lines.append(f"Received: {document.received_at}")
    if document.published_at:
        lines.append(f"Published: {document.published_at}")
    lines.extend(["", document.body_text.strip(), ""])

    if document.assets:
        lines.append("## Assets")
        lines.append("")
        for asset in document.assets:
            lines.append(f"- {asset.kind}: {asset.file_path} ({asset.mime_type})")
    return "\n".join(lines).strip() + "\n"


def _rewrite_export_asset_references(store: WorkspaceStore, document_id: str, html_content: str, destination: Path) -> str:
    document = store.get_document(document_id)
    source_html_path = store.resolve_path(document.body_html_path)
    if not source_html_path:
        return html_content

    rewritten = html_content
    for asset in document.assets:
        asset_path = store.resolve_path(asset.file_path)
        if not asset_path:
            continue
        source_relative = os.path.relpath(asset_path, source_html_path.parent)
        destination_relative = os.path.relpath(asset_path, destination.parent)
        rewritten = rewritten.replace(source_relative, destination_relative)
    return rewritten


def _document_to_html(store: WorkspaceStore, document_id: str, destination: Path | None = None) -> str:
    document = store.get_document(document_id)
    html_path = store.resolve_path(document.body_html_path)
    if html_path and html_path.exists():
        html_content = html_path.read_text(encoding="utf-8")
        if destination is not None:
            return _rewrite_export_asset_references(store, document_id, html_content, destination)
        return html_content

    meta_lines = []
    if document.author:
        meta_lines.append(f"<p><strong>Author:</strong> {html.escape(document.author)}</p>")
    if document.received_at:
        meta_lines.append(f"<p><strong>Received:</strong> {html.escape(document.received_at)}</p>")
    if document.published_at:
        meta_lines.append(f"<p><strong>Published:</strong> {html.escape(document.published_at)}</p>")

    paragraphs = [
        f"<p>{html.escape(paragraph.strip())}</p>"
        for paragraph in document.body_text.split("\n\n")
        if paragraph.strip()
    ]
    if not paragraphs:
        paragraphs = ["<p>No body text available.</p>"]

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        f"  <title>{html.escape(document.subject)}</title>\n"
        "  <style>\n"
        "    body { font-family: Georgia, 'Times New Roman', serif; margin: 2rem auto; max-width: 48rem; color: #1e293b; }\n"
        "    h1 { font-size: 2rem; margin-bottom: 0.5rem; }\n"
        "    .meta { color: #475569; font-size: 0.95rem; margin-bottom: 1.5rem; }\n"
        "    p { line-height: 1.65; margin: 0 0 1rem; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{html.escape(document.subject)}</h1>\n"
        f"  <div class=\"meta\">{''.join(meta_lines)}</div>\n"
        f"  {''.join(paragraphs)}\n"
        "</body>\n"
        "</html>\n"
    )


def _export_destination(store: WorkspaceStore, document_id: str, format_name: str, out_path: str | Path | None) -> Path:
    if out_path:
        return Path(out_path).expanduser().resolve()
    return store.exports_dir / f"{document_id}.{format_name}"


def export_document(
    document_id: str,
    format: str = "json",
    db_path: str | Path | None = None,
    workspace_path: str | Path | None = None,
    out_path: str | Path | None = None,
) -> str:
    db = db_path or ".mailatlas/store.db"
    workspace = workspace_path or ".mailatlas"
    store = WorkspaceStore(db, workspace)

    if format == "json":
        content = json.dumps(store.get_document(document_id).to_dict(), indent=2)
    elif format == "markdown":
        content = _document_to_markdown(store, document_id)
    elif format == "html":
        destination = Path(out_path).expanduser().resolve() if out_path else None
        content = _document_to_html(store, document_id, destination=destination)
    elif format == "pdf":
        destination = _export_destination(store, document_id, "pdf", out_path)
        html_path = store.resolve_path(store.get_document(document_id).body_html_path)
        if html_path and html_path.exists():
            source_html_path = html_path
        else:
            with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as handle:
                handle.write(_document_to_html(store, document_id))
                source_html_path = Path(handle.name)
        try:
            rendered_path = render_pdf_from_html(source_html_path, destination)
        finally:
            if source_html_path != html_path and source_html_path.exists():
                source_html_path.unlink()
        return rendered_path.as_posix()
    else:
        raise ValueError(f"Unsupported export format: {format}")

    if out_path:
        destination = Path(out_path).expanduser().resolve()
        destination.write_text(content, encoding="utf-8")
        return destination.as_posix()
    return content
