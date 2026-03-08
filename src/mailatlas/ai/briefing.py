from __future__ import annotations

import html
import os
import uuid
from pathlib import Path
from typing import Any

from mailatlas.core.storage import WorkspaceStore


def _truncate_paragraphs(text: str, limit: int = 2) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    if paragraphs:
        return paragraphs[:limit]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    return [" ".join(lines[: min(6, len(lines))])]


def _build_fallback_brief_html(documents: list[dict[str, Any]]) -> str:
    articles: list[str] = []
    for document in documents:
        paragraphs = _truncate_paragraphs(document["body_text"])
        body = "\n".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs) or "<p>No body text available.</p>"
        meta_parts = [document["author"], document["published_at"] or document["received_at"]]
        meta = " | ".join(part for part in meta_parts if part)
        articles.append(
            "<article>"
            f"<h2>{html.escape(document['subject'])}</h2>"
            f"<p><small>{html.escape(meta)}</small></p>"
            f"{body}"
            "</article>"
        )

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head><meta charset=\"utf-8\"><title>Generated Brief</title></head>\n"
        "<body>\n"
        "<header><h1>Generated Brief</h1></header>\n"
        f"{''.join(articles)}\n"
        "</body>\n"
        "</html>\n"
    )


def generate_brief(
    document_ids: list[str] | None = None,
    query: str | None = None,
    output_path: str | None = None,
    model_config: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    workspace_path: str | Path | None = None,
) -> str:
    db = db_path or ".mailatlas/store.db"
    workspace = workspace_path or ".mailatlas/workspace"
    store = WorkspaceStore(db, workspace)

    if document_ids:
        documents = [store.get_document(document_id).to_dict() for document_id in document_ids]
    else:
        refs = store.list_documents(query=query)
        documents = [store.get_document(reference.id).to_dict() for reference in refs]

    if not documents:
        raise ValueError("No documents available for briefing")

    model_config = dict(model_config or {})
    provider = (model_config.get("provider") or os.getenv("MAILATLAS_BRIEF_PROVIDER") or "fallback").lower()

    if provider != "fallback":
        model_config["provider"] = provider
        html_content = _generate_llm_brief(documents, model_config)
    else:
        model_config["provider"] = "fallback"
        html_content = _build_fallback_brief_html(documents)

    destination = Path(output_path).expanduser().resolve() if output_path else store.briefs_dir / f"{uuid.uuid4()}.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html_content, encoding="utf-8")
    store.save_brief_run(destination.as_posix(), [document["id"] for document in documents], model_config)
    return destination.as_posix()


def _generate_llm_brief(documents: list[dict[str, Any]], model_config: dict[str, Any]) -> str:
    provider = model_config["provider"]
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        model_name = model_config.get("model") or os.getenv("OPENAI_MODEL_NAME", "gpt-4.1-mini")
        llm = ChatOpenAI(model=model_name)
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model_name = model_config.get("model") or os.getenv("ANTHROPIC_MODEL_NAME", "claude-3-5-sonnet-latest")
        llm = ChatAnthropic(model=model_name, max_tokens=4000)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = model_config.get("model") or os.getenv("GOOGLE_MODEL_NAME", "gemini-2.0-flash")
        llm = ChatGoogleGenerativeAI(model=model_name)
    else:
        raise ValueError(f"Unsupported brief provider: {provider}")

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    sources = "\n\n".join(
        [
            f"Subject: {document['subject']}\n"
            f"Author: {document['author']}\n"
            f"Published: {document['published_at'] or document['received_at']}\n"
            f"Body:\n{document['body_text'][:6000]}"
            for document in documents
        ]
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You generate concise HTML briefings from structured document sources. Output a full HTML document.",
            ),
            ("user", "{sources}"),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"sources": sources})
