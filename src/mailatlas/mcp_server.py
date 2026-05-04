from __future__ import annotations

import argparse
from pathlib import Path

from .core.mcp_tools import MailAtlasMcpTools


def build_mcp_server(
    *,
    root: str | Path | None = None,
    allow_send: bool | None = None,
    allow_receive: bool | None = None,
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("Install MailAtlas with the MCP extra first: python -m pip install 'mailatlas[mcp]'") from error

    toolkit = MailAtlasMcpTools(root=root, allow_send=allow_send, allow_receive=allow_receive)
    mcp = FastMCP("MailAtlas")

    @mcp.tool()
    def mailatlas_list_documents(query: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        """List stored MailAtlas documents."""
        return toolkit.list_documents(query=query, limit=limit, offset=offset)

    @mcp.tool()
    def mailatlas_get_document(document_id: str) -> dict:
        """Get one stored MailAtlas document by id."""
        return toolkit.get_document(document_id)

    @mcp.tool()
    def mailatlas_export_document(document_id: str, format: str = "json", out_path: str | None = None) -> dict:
        """Export one stored document as json, markdown, html, or pdf."""
        return toolkit.export_document(document_id, format=format, out_path=out_path)

    @mcp.tool()
    def mailatlas_list_outbound(query: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        """List outbound audit records. BCC recipients are not included in this list view."""
        return toolkit.list_outbound(query=query, limit=limit, offset=offset)

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
            gmail_token_store: str | None = None,
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
                gmail_token_store=gmail_token_store,
            )

    if toolkit.allow_receive:

        @mcp.tool()
        def mailatlas_receive(
            provider: str | None = None,
            account_id: str | None = None,
            label: str | None = None,
            query: str | None = None,
            limit: int | None = None,
            full_sync: bool = False,
            include_spam_trash: bool | None = None,
            gmail_access_token: str | None = None,
            gmail_api_base: str | None = None,
            gmail_user_id: str | None = None,
            token_file: str | None = None,
            token_store: str | None = None,
            imap_host: str | None = None,
            imap_port: int | None = None,
            imap_username: str | None = None,
            imap_password: str | None = None,
            imap_access_token: str | None = None,
            imap_folders: list[str] | None = None,
        ) -> dict:
            """Consequential action: contact a mailbox provider and store private email in the local MailAtlas workspace."""
            return toolkit.receive(
                provider=provider,
                account_id=account_id,
                label=label,
                query=query,
                limit=limit,
                full_sync=full_sync,
                include_spam_trash=include_spam_trash,
                gmail_access_token=gmail_access_token,
                gmail_api_base=gmail_api_base,
                gmail_user_id=gmail_user_id,
                token_file=token_file,
                token_store=token_store,
                imap_host=imap_host,
                imap_port=imap_port,
                imap_username=imap_username,
                imap_password=imap_password,
                imap_access_token=imap_access_token,
                imap_folders=imap_folders,
            )

        @mcp.tool()
        def mailatlas_receive_status(account_id: str | None = None) -> dict:
            """Inspect local receive accounts, cursors, recent runs, and recent receive errors."""
            return toolkit.receive_status(account_id=account_id)

    return mcp


def run_mcp_server(
    *,
    root: str | Path | None = None,
    transport: str = "stdio",
    allow_send: bool | None = None,
    allow_receive: bool | None = None,
) -> int:
    if transport != "stdio":
        raise ValueError("MailAtlas MCP currently supports only the stdio transport.")
    server = build_mcp_server(root=root, allow_send=allow_send, allow_receive=allow_receive)
    server.run(transport=transport)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MailAtlas MCP server.")
    parser.add_argument("--root", default=None, help="MailAtlas root directory.")
    parser.add_argument("--transport", choices=["stdio"], default="stdio", help="MCP transport. Defaults to stdio.")
    parser.add_argument(
        "--allow-send",
        action="store_const",
        const=True,
        default=None,
        help="Expose the live mailatlas_send_email MCP tool. Defaults to MAILATLAS_MCP_ALLOW_SEND.",
    )
    parser.add_argument(
        "--allow-receive",
        action="store_const",
        const=True,
        default=None,
        help="Expose MCP mailbox receive tools. Defaults to MAILATLAS_MCP_ALLOW_RECEIVE.",
    )
    args = parser.parse_args(argv)
    return run_mcp_server(
        root=args.root,
        transport=args.transport,
        allow_send=args.allow_send,
        allow_receive=args.allow_receive,
    )


if __name__ == "__main__":
    raise SystemExit(main())
