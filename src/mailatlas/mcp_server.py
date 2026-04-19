from __future__ import annotations

import argparse
from pathlib import Path

from .core.mcp_tools import MailAtlasMcpTools


def build_mcp_server(*, root: str | Path | None = None, allow_send: bool | None = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("Install MailAtlas with the MCP extra first: python -m pip install 'mailatlas[mcp]'") from error

    toolkit = MailAtlasMcpTools(root=root, allow_send=allow_send)
    mcp = FastMCP("MailAtlas")

    @mcp.tool()
    def mailatlas_list_documents(query: str | None = None) -> dict:
        """List stored MailAtlas documents."""
        return toolkit.list_documents(query=query)

    @mcp.tool()
    def mailatlas_get_document(document_id: str) -> dict:
        """Get one stored MailAtlas document by id."""
        return toolkit.get_document(document_id)

    @mcp.tool()
    def mailatlas_export_document(document_id: str, format: str = "json", out_path: str | None = None) -> dict:
        """Export one stored document as json, markdown, html, or pdf."""
        return toolkit.export_document(document_id, format=format, out_path=out_path)

    @mcp.tool()
    def mailatlas_list_outbound(query: str | None = None) -> dict:
        """List outbound audit records. BCC recipients are not included in this list view."""
        return toolkit.list_outbound(query=query)

    @mcp.tool()
    def mailatlas_get_outbound(outbound_id: str, include_bcc: bool = False) -> dict:
        """Get one outbound audit record. Pass include_bcc=true only when BCC audit details are needed."""
        return toolkit.get_outbound(outbound_id, include_bcc=include_bcc)

    @mcp.tool()
    def mailatlas_draft_email(
        from_email: str,
        to: list[str],
        subject: str,
        text: str | None = None,
        html: str | None = None,
        from_name: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: list[str] | None = None,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
        headers: dict[str, str] | None = None,
        attachments: list[str] | None = None,
        source_document_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Draft and audit an outbound email without contacting a send provider."""
        return toolkit.draft_email(
            from_email=from_email,
            from_name=from_name,
            to=to,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            subject=subject,
            text=text,
            html=html,
            headers=headers,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
            source_document_id=source_document_id,
            idempotency_key=idempotency_key,
        )

    if toolkit.allow_send:

        @mcp.tool()
        def mailatlas_send_email(
            from_email: str,
            to: list[str],
            subject: str,
            text: str | None = None,
            html: str | None = None,
            provider: str | None = None,
            dry_run: bool = False,
            from_name: str | None = None,
            cc: list[str] | None = None,
            bcc: list[str] | None = None,
            reply_to: list[str] | None = None,
            in_reply_to: str | None = None,
            references: list[str] | None = None,
            headers: dict[str, str] | None = None,
            attachments: list[str] | None = None,
            source_document_id: str | None = None,
            idempotency_key: str | None = None,
            smtp_host: str | None = None,
            smtp_port: int | None = None,
            smtp_username: str | None = None,
            smtp_password: str | None = None,
            smtp_starttls: bool | None = None,
            smtp_ssl: bool | None = None,
            cloudflare_account_id: str | None = None,
            cloudflare_api_token: str | None = None,
            cloudflare_api_base: str | None = None,
            gmail_access_token: str | None = None,
            gmail_api_base: str | None = None,
            gmail_user_id: str | None = None,
            gmail_token_file: str | None = None,
        ) -> dict:
            """Consequential action: send an outbound email through a configured provider."""
            return toolkit.send_email(
                from_email=from_email,
                from_name=from_name,
                to=to,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                subject=subject,
                text=text,
                html=html,
                headers=headers,
                in_reply_to=in_reply_to,
                references=references,
                attachments=attachments,
                source_document_id=source_document_id,
                idempotency_key=idempotency_key,
                provider=provider,
                dry_run=dry_run,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_password=smtp_password,
                smtp_starttls=smtp_starttls,
                smtp_ssl=smtp_ssl,
                cloudflare_account_id=cloudflare_account_id,
                cloudflare_api_token=cloudflare_api_token,
                cloudflare_api_base=cloudflare_api_base,
                gmail_access_token=gmail_access_token,
                gmail_api_base=gmail_api_base,
                gmail_user_id=gmail_user_id,
                gmail_token_file=gmail_token_file,
            )

    return mcp


def run_mcp_server(*, root: str | Path | None = None, transport: str = "stdio") -> int:
    if transport != "stdio":
        raise ValueError("MailAtlas MCP currently supports only the stdio transport.")
    server = build_mcp_server(root=root)
    server.run(transport=transport)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MailAtlas MCP server.")
    parser.add_argument("--root", default=None, help="MailAtlas root directory.")
    parser.add_argument("--transport", choices=["stdio"], default="stdio", help="MCP transport. Defaults to stdio.")
    args = parser.parse_args(argv)
    return run_mcp_server(root=args.root, transport=args.transport)


if __name__ == "__main__":
    raise SystemExit(main())
