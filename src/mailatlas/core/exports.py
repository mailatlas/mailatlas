from __future__ import annotations

import html
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .models import DocumentRecord, StoredAsset
from .pdf import render_pdf_from_html
from .storage import WorkspaceStore


_HTML_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
_HTML_IGNORED_TAGS = {"head", "meta", "style", "script", "title", "link"}
_HTML_TRANSPARENT_BLOCK_TAGS = {"article", "body", "div", "footer", "header", "html", "main", "section"}
_HTML_TRANSPARENT_INLINE_TAGS = {"label", "small", "span", "sub", "sup"}
_HTML_RAW_BLOCK_TAGS = {
    "canvas",
    "details",
    "dl",
    "figure",
    "figcaption",
    "form",
    "iframe",
    "math",
    "object",
    "svg",
    "table",
    "textarea",
    "video",
}
_MARKDOWN_LINK_NEEDS_BRACKETS = re.compile(r"[\s()<>]")
_MARKDOWN_ORDINAL_PREFIX = re.compile(r"^\d{3}-")
_MARKDOWN_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _path_to_posix(value: str | Path) -> str:
    return str(value).replace("\\", "/")


def _escape_markdown_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ").strip()


def _markdown_link_destination(value: str) -> str:
    return f"<{value}>" if _MARKDOWN_LINK_NEEDS_BRACKETS.search(value) else value


def _asset_display_name(asset: StoredAsset) -> str:
    filename = Path(asset.file_path).name
    return _MARKDOWN_ORDINAL_PREFIX.sub("", filename)


@dataclass
class _HtmlElement:
    tag: str
    attrs: dict[str, str]
    children: list[str | "_HtmlElement"] = field(default_factory=list)


class _HtmlTreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlElement(tag="document", attrs={})
        self._stack: list[_HtmlElement] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = _HtmlElement(
            tag=tag.lower(),
            attrs={name.lower(): value or "" for name, value in attrs},
        )
        self._stack[-1].children.append(element)
        if element.tag not in _HTML_VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = _HtmlElement(
            tag=tag.lower(),
            attrs={name.lower(): value or "" for name, value in attrs},
        )
        self._stack[-1].children.append(element)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == normalized:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


@dataclass(frozen=True)
class _MarkdownAssetReference:
    asset: StoredAsset
    source_path: Path
    target_ref: str
    display_name: str
    bundle_path: Path | None = None


def _extract_text(nodes: list[str | _HtmlElement], *, preserve_whitespace: bool = False) -> str:
    chunks: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            chunks.append(node if preserve_whitespace else re.sub(r"\s+", " ", node))
            continue
        if node.tag == "br" and not preserve_whitespace:
            chunks.append("\n")
            continue
        if node.tag == "img":
            chunks.append(node.attrs.get("alt", "").strip())
            continue
        chunks.append(_extract_text(node.children, preserve_whitespace=preserve_whitespace))
    return "".join(chunks)


def _build_markdown_asset_references(
    store: WorkspaceStore,
    document: DocumentRecord,
    bundle_dir: Path | None,
) -> tuple[list[_MarkdownAssetReference], dict[str, _MarkdownAssetReference], dict[Path, _MarkdownAssetReference]]:
    references: list[_MarkdownAssetReference] = []
    by_reference: dict[str, _MarkdownAssetReference] = {}
    by_path: dict[Path, _MarkdownAssetReference] = {}
    html_path = store.resolve_path(document.body_html_path)

    for asset in document.assets:
        source_path = store.resolve_path(asset.file_path)
        if source_path is None:
            continue
        resolved_source = source_path.resolve()
        bundle_path = bundle_dir / "assets" / Path(asset.file_path).name if bundle_dir else None
        target_ref = (
            Path("assets") / Path(asset.file_path).name
            if bundle_path is not None
            else Path(resolved_source.as_posix())
        )
        reference = _MarkdownAssetReference(
            asset=asset,
            source_path=resolved_source,
            target_ref=target_ref.as_posix(),
            display_name=_asset_display_name(asset),
            bundle_path=bundle_path,
        )
        references.append(reference)
        by_path[resolved_source] = reference

        candidate_values = {
            resolved_source.as_posix(),
            _path_to_posix(asset.file_path),
            Path(asset.file_path).name,
        }
        if html_path is not None:
            relative_to_html = os.path.relpath(resolved_source, html_path.parent)
            candidate_values.add(_path_to_posix(relative_to_html))
        if asset.cid:
            candidate_values.add(f"cid:{asset.cid}")

        for candidate in candidate_values:
            by_reference[candidate] = reference

    return references, by_reference, by_path


def _resolve_asset_reference(
    value: str,
    html_base: Path | None,
    by_reference: dict[str, _MarkdownAssetReference],
    by_path: dict[Path, _MarkdownAssetReference],
) -> _MarkdownAssetReference | None:
    normalized = _path_to_posix(value.strip())
    if not normalized:
        return None
    if normalized in by_reference:
        return by_reference[normalized]

    if html_base is None or normalized.startswith("#") or _MARKDOWN_SCHEME_RE.match(normalized):
        return None

    candidate_path = (html_base / normalized).resolve()
    return by_path.get(candidate_path)


def _serialize_html_node(
    node: str | _HtmlElement,
    html_base: Path | None,
    by_reference: dict[str, _MarkdownAssetReference],
    by_path: dict[Path, _MarkdownAssetReference],
    rendered_image_asset_ids: set[str],
) -> str:
    if isinstance(node, str):
        return html.escape(node, quote=False)

    attrs: list[str] = []
    for name, value in node.attrs.items():
        rewritten = value
        if name in {"href", "src"} and value:
            asset_ref = _resolve_asset_reference(value, html_base, by_reference, by_path)
            if asset_ref is not None:
                rewritten = asset_ref.target_ref
                if name == "src" and asset_ref.asset.mime_type.startswith("image/"):
                    rendered_image_asset_ids.add(asset_ref.asset.id)
        escaped_value = html.escape(rewritten, quote=True)
        attrs.append(f'{name}="{escaped_value}"')

    start_tag = f"<{node.tag}"
    if attrs:
        start_tag += " " + " ".join(attrs)
    start_tag += ">"
    if node.tag in _HTML_VOID_TAGS:
        return start_tag
    inner_html = "".join(
        _serialize_html_node(child, html_base, by_reference, by_path, rendered_image_asset_ids)
        for child in node.children
    )
    return f"{start_tag}{inner_html}</{node.tag}>"


class _MarkdownRenderer:
    def __init__(
        self,
        html_base: Path | None,
        by_reference: dict[str, _MarkdownAssetReference],
        by_path: dict[Path, _MarkdownAssetReference],
    ) -> None:
        self.html_base = html_base
        self.by_reference = by_reference
        self.by_path = by_path
        self.rendered_image_asset_ids: set[str] = set()

    def render(self, root: _HtmlElement) -> str:
        body = self._join_blocks(self._render_block_nodes(root.children))
        return body.strip()

    def _join_blocks(self, blocks: list[str]) -> str:
        return "\n\n".join(block.strip() for block in blocks if block and block.strip())

    def _render_block_nodes(self, nodes: list[str | _HtmlElement], *, list_depth: int = 0) -> list[str]:
        blocks: list[str] = []
        inline_nodes: list[str | _HtmlElement] = []

        def flush_inline() -> None:
            if not inline_nodes:
                return
            text = self._render_inline_nodes(inline_nodes).strip()
            inline_nodes.clear()
            if text:
                blocks.append(text)

        for node in nodes:
            if isinstance(node, str):
                if node.strip():
                    inline_nodes.append(node)
                continue

            tag = node.tag
            if tag in _HTML_IGNORED_TAGS:
                continue
            if tag == "br":
                inline_nodes.append(node)
                continue
            if tag in _HTML_TRANSPARENT_BLOCK_TAGS:
                flush_inline()
                blocks.extend(self._render_block_nodes(node.children, list_depth=list_depth))
                continue
            if tag in _HTML_RAW_BLOCK_TAGS:
                flush_inline()
                blocks.append(
                    _serialize_html_node(
                        node,
                        self.html_base,
                        self.by_reference,
                        self.by_path,
                        self.rendered_image_asset_ids,
                    )
                )
                continue
            if tag == "p":
                flush_inline()
                text = self._render_inline_nodes(node.children).strip()
                if text:
                    blocks.append(text)
                continue
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                flush_inline()
                text = self._render_inline_nodes(node.children).strip()
                if text:
                    blocks.append(f"{'#' * int(tag[1])} {text}")
                continue
            if tag in {"ul", "ol"}:
                flush_inline()
                rendered_list = self._render_list(node, ordered=tag == "ol", depth=list_depth)
                if rendered_list:
                    blocks.append(rendered_list)
                continue
            if tag == "blockquote":
                flush_inline()
                quoted = self._join_blocks(self._render_block_nodes(node.children, list_depth=list_depth)).strip()
                if not quoted:
                    quoted = self._render_inline_nodes(node.children).strip()
                if quoted:
                    lines = [f"> {line}" if line.strip() else ">" for line in quoted.splitlines()]
                    blocks.append("\n".join(lines))
                continue
            if tag == "pre":
                flush_inline()
                code_content = _extract_text(node.children, preserve_whitespace=True).strip("\n")
                if code_content:
                    blocks.append(f"```\n{code_content}\n```")
                continue
            if tag == "hr":
                flush_inline()
                blocks.append("---")
                continue

            inline_nodes.append(node)

        flush_inline()
        return blocks

    def _render_list(self, node: _HtmlElement, *, ordered: bool, depth: int) -> str:
        lines: list[str] = []
        item_index = 1
        for child in node.children:
            if not isinstance(child, _HtmlElement) or child.tag != "li":
                continue

            content_nodes: list[str | _HtmlElement] = []
            nested_lists: list[_HtmlElement] = []
            for item_child in child.children:
                if isinstance(item_child, _HtmlElement) and item_child.tag in {"ul", "ol"}:
                    nested_lists.append(item_child)
                    continue
                if isinstance(item_child, _HtmlElement) and item_child.tag in {"p", "div"}:
                    content_nodes.extend(item_child.children)
                    content_nodes.append("\n")
                    continue
                content_nodes.append(item_child)

            marker = f"{item_index}. " if ordered else "- "
            prefix = "  " * depth + marker
            text = self._render_inline_nodes(content_nodes).strip()
            lines.append(prefix + (text or ""))
            for nested in nested_lists:
                nested_text = self._render_list(nested, ordered=nested.tag == "ol", depth=depth + 1)
                if nested_text:
                    lines.extend(nested_text.splitlines())
            item_index += 1
        return "\n".join(line.rstrip() for line in lines if line.strip())

    def _render_inline_nodes(self, nodes: list[str | _HtmlElement]) -> str:
        pieces: list[str] = []
        for node in nodes:
            if isinstance(node, str):
                collapsed = re.sub(r"\s+", " ", node)
                pieces.append(collapsed)
                continue

            tag = node.tag
            if tag in _HTML_IGNORED_TAGS:
                continue
            if tag in _HTML_TRANSPARENT_INLINE_TAGS or tag in {"div", "p"}:
                pieces.append(self._render_inline_nodes(node.children))
                continue
            if tag == "br":
                pieces.append("  \n")
                continue
            if tag in {"strong", "b"}:
                text = self._render_inline_nodes(node.children).strip()
                pieces.append(f"**{text}**" if text else "")
                continue
            if tag in {"em", "i"}:
                text = self._render_inline_nodes(node.children).strip()
                pieces.append(f"*{text}*" if text else "")
                continue
            if tag == "code":
                text = _extract_text(node.children, preserve_whitespace=True).strip()
                pieces.append(f"`{text}`" if text else "")
                continue
            if tag == "a":
                href = node.attrs.get("href", "").strip()
                asset_ref = _resolve_asset_reference(href, self.html_base, self.by_reference, self.by_path) if href else None
                destination = asset_ref.target_ref if asset_ref is not None else href
                label = self._render_inline_nodes(node.children).strip() or destination
                if destination:
                    pieces.append(f"[{_escape_markdown_label(label)}]({_markdown_link_destination(destination)})")
                else:
                    pieces.append(label)
                continue
            if tag == "img":
                src = node.attrs.get("src", "").strip()
                asset_ref = _resolve_asset_reference(src, self.html_base, self.by_reference, self.by_path) if src else None
                if asset_ref is not None:
                    destination = asset_ref.target_ref
                    self.rendered_image_asset_ids.add(asset_ref.asset.id)
                else:
                    destination = src
                label = (
                    node.attrs.get("alt", "").strip()
                    or (asset_ref.display_name if asset_ref is not None else Path(src).name)
                    or "image"
                )
                if destination:
                    pieces.append(f"![{_escape_markdown_label(label)}]({_markdown_link_destination(destination)})")
                continue
            if tag in {"ul", "ol", "blockquote", "pre", "hr", "h1", "h2", "h3", "h4", "h5", "h6"}:
                pieces.append(self._join_blocks(self._render_block_nodes([node])).strip())
                continue
            if tag in _HTML_RAW_BLOCK_TAGS:
                pieces.append(
                    _serialize_html_node(
                        node,
                        self.html_base,
                        self.by_reference,
                        self.by_path,
                        self.rendered_image_asset_ids,
                    )
                )
                continue
            pieces.append(self._render_inline_nodes(node.children))

        text = "".join(pieces)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text


def _metadata_header_lines(document: DocumentRecord) -> list[str]:
    lines = [f"# {document.subject}"]
    if document.author:
        lines.append(f"Author: {document.author}")
    if document.received_at:
        lines.append(f"Received: {document.received_at}")
    if document.published_at:
        lines.append(f"Published: {document.published_at}")
    return lines


def _render_attachment_links(assets: list[_MarkdownAssetReference]) -> str:
    lines = []
    for asset in assets:
        label = _escape_markdown_label(asset.display_name)
        lines.append(f"- [{label}]({_markdown_link_destination(asset.target_ref)}) ({asset.asset.mime_type})")
    return "\n".join(lines)


def _render_image_links(assets: list[_MarkdownAssetReference]) -> str:
    return "\n\n".join(
        f"![{_escape_markdown_label(asset.display_name)}]({_markdown_link_destination(asset.target_ref)})"
        for asset in assets
    )


def _build_markdown_content(
    store: WorkspaceStore,
    document: DocumentRecord,
    *,
    bundle_dir: Path | None,
) -> str:
    references, by_reference, by_path = _build_markdown_asset_references(store, document, bundle_dir=bundle_dir)
    html_path = store.resolve_path(document.body_html_path)
    body_markdown = document.body_text.strip()
    rendered_image_asset_ids: set[str] = set()

    if html_path and html_path.exists():
        builder = _HtmlTreeBuilder()
        builder.feed(html_path.read_text(encoding="utf-8"))
        builder.close()
        renderer = _MarkdownRenderer(html_path.parent.resolve(), by_reference, by_path)
        rendered = renderer.render(builder.root)
        if rendered:
            body_markdown = rendered
        rendered_image_asset_ids = renderer.rendered_image_asset_ids

    image_assets = [
        asset_ref
        for asset_ref in references
        if asset_ref.asset.mime_type.startswith("image/") and asset_ref.asset.id not in rendered_image_asset_ids
    ]
    attachment_assets = [asset_ref for asset_ref in references if not asset_ref.asset.mime_type.startswith("image/")]

    sections = ["\n".join(_metadata_header_lines(document))]
    if body_markdown:
        sections.append(body_markdown)
    if image_assets:
        sections.append("## Images\n\n" + _render_image_links(image_assets))
    if attachment_assets:
        sections.append("## Attachments\n\n" + _render_attachment_links(attachment_assets))
    return "\n\n".join(section.strip() for section in sections if section.strip()) + "\n"


def _write_markdown_bundle(
    store: WorkspaceStore,
    document: DocumentRecord,
    bundle_dir: Path,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = bundle_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    references, _, _ = _build_markdown_asset_references(store, document, bundle_dir=bundle_dir)
    for asset_ref in references:
        if asset_ref.bundle_path is None:
            continue
        asset_ref.bundle_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset_ref.source_path, asset_ref.bundle_path)

    markdown_path = bundle_dir / "document.md"
    markdown_path.write_text(_build_markdown_content(store, document, bundle_dir=bundle_dir), encoding="utf-8")
    return markdown_path


def _document_to_markdown(store: WorkspaceStore, document_id: str, bundle_dir: Path | None = None) -> str | Path:
    document = store.get_document(document_id)
    if bundle_dir is not None:
        return _write_markdown_bundle(store, document, bundle_dir)
    return _build_markdown_content(store, document, bundle_dir=None)


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
        bundle_dir = Path(out_path).expanduser().resolve() if out_path else None
        rendered = _document_to_markdown(store, document_id, bundle_dir=bundle_dir)
        if isinstance(rendered, Path):
            return rendered.as_posix()
        content = rendered
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
