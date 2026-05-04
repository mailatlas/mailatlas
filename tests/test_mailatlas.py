from __future__ import annotations

import imaplib
import io
import mailbox
import base64
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import urllib.parse
import unittest
from unittest import mock
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mailatlas.cli as mailatlas_cli
import mailatlas.mcp_server as mailatlas_mcp_server
from mailatlas.core import (
    GMAIL_READONLY_SCOPE,
    MailAtlas,
    MailAtlasMcpTools,
    OutboundAttachment,
    OutboundMessage,
    ParserConfig,
    ReceiveConfig,
    ReceiveResult,
    SendConfig,
    SendResult,
    mcp_tool_names,
    parse_eml,
)
from mailatlas.core import pdf as pdf_module
from mailatlas.core.gmail_auth import (
    FileTokenStore,
    GmailAuthConfig,
    GmailAuthResult,
    KeyringTokenStore,
    create_gmail_token_store,
    exchange_gmail_authorization_code,
)


SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="280" viewBox="0 0 640 280">'
    b'<rect width="640" height="280" fill="#f6efe5"/>'
    b'<text x="24" y="38" font-family="Arial, sans-serif" font-size="20" fill="#13253a">'
    b'Port dwell time vs 8-week average</text>'
    b'<line x1="72" y1="70" x2="72" y2="228" stroke="#415d78" stroke-width="2"/>'
    b'<line x1="72" y1="228" x2="592" y2="228" stroke="#415d78" stroke-width="2"/>'
    b'<polyline points="92,196 176,164 260,150 344,118 428,106 512,92" '
    b'fill="none" stroke="#b97443" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
    b'<polyline points="92,172 176,168 260,160 344,156 428,150 512,146" '
    b'fill="none" stroke="#3f627f" stroke-width="6" stroke-dasharray="10 8" '
    b'stroke-linecap="round" stroke-linejoin="round"/>'
    b'<circle cx="512" cy="92" r="6" fill="#b97443"/>'
    b'<circle cx="512" cy="146" r="6" fill="#3f627f"/>'
    b'<rect x="406" y="28" width="18" height="18" rx="4" fill="#b97443"/>'
    b'<text x="432" y="42" font-family="Arial, sans-serif" font-size="14" fill="#13253a">Current median</text>'
    b'<rect x="406" y="52" width="18" height="18" rx="4" fill="#3f627f"/>'
    b'<text x="432" y="66" font-family="Arial, sans-serif" font-size="14" fill="#13253a">8-week average</text>'
    b'</svg>'
)
CSV_BYTES = b"port,dwell_days\nLAX,3.1\nSEA,2.4\n"


def _write_message(path: Path, message: EmailMessage) -> None:
    path.write_bytes(message.as_bytes())


def _write_fake_pdf_browser(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    --print-to-pdf=*)\n"
        "      out=\"${arg#--print-to-pdf=}\"\n"
        "      ;;\n"
        "  esac\n"
        "done\n"
        "printf '%s' '%PDF-1.4\\n% fake mailatlas pdf\\n' > \"$out\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _plain_message(subject: str = "Plain Subject") -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "Alice Example <alice@example.com>"
    message["To"] = "team@example.com"
    message["Date"] = "Fri, 01 Mar 2024 10:00:00 +0000"
    message["Message-ID"] = "<plain-1@example.com>"
    message.set_content("First paragraph.\n\nSecond paragraph.")
    return message


def _forwarded_message() -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Fwd: Market note"
    message["From"] = "Bob Example <bob@example.com>"
    message["To"] = "team@example.com"
    message["Date"] = "Sat, 02 Mar 2024 09:00:00 +0000"
    message["Message-ID"] = "<forward-1@example.com>"
    message.set_content(
        "Intro.\n\n---------- Forwarded message ---------\n"
        "From: Source Author <source@example.com>\n"
        "Date: Thu, 29 Feb 2024 13:30:00 +0000\n"
        "Subject: The original piece\n\n"
        "Forwarded body."
    )
    return message


def _html_inline_message() -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Inline HTML"
    message["From"] = "Inline Author <inline@example.com>"
    message["To"] = "team@example.com"
    message["Date"] = "Sun, 03 Mar 2024 11:00:00 +0000"
    message["Message-ID"] = "<html-1@example.com>"
    message.set_content("Fallback body")
    message.add_alternative(
        "<html><body><p>Hello HTML world.</p><img src=\"cid:chart-1\"></body></html>",
        subtype="html",
    )
    html_part = message.get_payload()[1]
    html_part.add_related(SVG_BYTES, maintype="image", subtype="svg+xml", cid="<chart-1>", filename="chart.svg")
    return message


def _html_inline_attachment_message() -> EmailMessage:
    message = _html_inline_message()
    message.replace_header("Message-ID", "<html-attachment-1@example.com>")
    message.add_attachment(CSV_BYTES, maintype="text", subtype="csv", filename="port-dwell.csv")
    return message


def _plain_message_with_attachments() -> EmailMessage:
    message = _plain_message("Plain Attachments")
    message.replace_header("Message-ID", "<plain-attachments-1@example.com>")
    message.add_attachment(SVG_BYTES, maintype="image", subtype="svg+xml", filename="chart.svg")
    message.add_attachment(CSV_BYTES, maintype="text", subtype="csv", filename="port-dwell.csv")
    return message


def _imap_message_bytes(subject: str, message_id: str) -> bytes:
    message = _plain_message(subject)
    message.replace_header("Message-ID", message_id)
    return message.as_bytes()


def _gmail_raw(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


def _unquote_mailbox(mailbox: str) -> str:
    value = mailbox
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


class FakeImapConnection:
    def __init__(
        self,
        mailboxes: dict[str, dict[str, object]],
        *,
        fail_select: set[str] | None = None,
        fail_fetch: set[tuple[str, int]] | None = None,
        auth_error: str | None = None,
    ) -> None:
        self.mailboxes = mailboxes
        self.fail_select = fail_select or set()
        self.fail_fetch = fail_fetch or set()
        self.auth_error = auth_error
        self.selected_folder: str | None = None
        self.login_calls: list[tuple[str, str]] = []
        self.authenticate_calls: list[tuple[str, bytes]] = []
        self.fetch_calls: list[tuple[str, int]] = []
        self.logout_calls = 0

    def login(self, username: str, password: str):
        if self.auth_error:
            raise imaplib.IMAP4.error(self.auth_error)
        self.login_calls.append((username, password))
        return "OK", [b"LOGIN completed"]

    def authenticate(self, mechanism: str, callback):
        if self.auth_error:
            raise imaplib.IMAP4.error(self.auth_error)
        self.authenticate_calls.append((mechanism, callback(b"")))
        return "OK", [b"AUTH completed"]

    def select(self, mailbox: str, readonly: bool = False):
        folder = _unquote_mailbox(mailbox)
        if folder in self.fail_select:
            return "NO", [b"cannot select mailbox"]
        if folder not in self.mailboxes:
            return "NO", [b"unknown mailbox"]
        self.selected_folder = folder
        message_count = len(self.mailboxes[folder]["messages"])
        return "OK", [str(message_count).encode("ascii")]

    def response(self, code: str):
        if code.upper() == "UIDVALIDITY" and self.selected_folder:
            uidvalidity = self.mailboxes[self.selected_folder]["uidvalidity"]
            return code, [str(uidvalidity).encode("ascii")]
        return code, [None]

    def uid(self, command: str, *args):
        if not self.selected_folder:
            return "NO", [b"no mailbox selected"]

        command = command.upper()
        messages: dict[int, bytes] = self.mailboxes[self.selected_folder]["messages"]  # type: ignore[assignment]

        if command == "SEARCH":
            payload = b" ".join(str(uid).encode("ascii") for uid in sorted(messages))
            return "OK", [payload]

        if command == "FETCH":
            uid = int(args[0])
            self.fetch_calls.append((self.selected_folder, uid))
            if (self.selected_folder, uid) in self.fail_fetch:
                return "NO", [b"fetch failed"]
            raw_bytes = messages[uid]
            return "OK", [(f"{uid} (RFC822 {{{len(raw_bytes)}}})".encode("ascii"), raw_bytes), b")"]

        raise AssertionError(f"Unsupported IMAP UID command: {command}")

    def logout(self):
        self.logout_calls += 1
        return "BYE", [b"LOGOUT completed"]


class FakeSmtpServer:
    instances: list["FakeSmtpServer"] = []

    def __init__(self, host: str, port: int, timeout: int | None = None, context=None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.starttls_calls = 0
        self.login_calls: list[tuple[str, str]] = []
        self.send_calls: list[tuple[EmailMessage, str | None, list[str] | None]] = []
        FakeSmtpServer.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        self.starttls_calls += 1
        self.context = context
        return (220, b"ready")

    def login(self, username: str, password: str):
        self.login_calls.append((username, password))
        return (235, b"authenticated")

    def send_message(self, message: EmailMessage, from_addr: str | None = None, to_addrs: list[str] | None = None):
        self.send_calls.append((message, from_addr, to_addrs))
        return {}


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class PasswordDeleteError(Exception):
    pass


def _fake_keyring_module() -> types.ModuleType:
    fake_keyring = types.ModuleType("keyring")
    passwords: dict[tuple[str, str], str] = {}

    def get_password(service_name: str, username: str) -> str | None:
        return passwords.get((service_name, username))

    def set_password(service_name: str, username: str, password: str) -> None:
        passwords[(service_name, username)] = password

    def delete_password(service_name: str, username: str) -> None:
        key = (service_name, username)
        if key not in passwords:
            raise PasswordDeleteError("not found")
        del passwords[key]

    fake_keyring.get_password = get_password  # type: ignore[attr-defined]
    fake_keyring.set_password = set_password  # type: ignore[attr-defined]
    fake_keyring.delete_password = delete_password  # type: ignore[attr-defined]
    fake_keyring.errors = types.SimpleNamespace(PasswordDeleteError=PasswordDeleteError)  # type: ignore[attr-defined]
    return fake_keyring


class MailAtlasTests(unittest.TestCase):
    def test_parse_plain_eml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            eml_path = Path(temp_dir) / "plain.eml"
            _write_message(eml_path, _plain_message())

            parsed = parse_eml(eml_path)

            self.assertEqual(parsed.subject, "Plain Subject")
            self.assertEqual(parsed.sender_email, "alice@example.com")
            self.assertIn("First paragraph.", parsed.body_text)
            self.assertEqual(parsed.provenance["is_forwarded"], False)

    def test_default_cleaning_removes_forwarded_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            eml_path = Path(temp_dir) / "forwarded.eml"
            _write_message(eml_path, _forwarded_message())

            parsed = parse_eml(eml_path)

            self.assertNotIn("---------- Forwarded message ---------", parsed.body_text)
            self.assertNotIn("From: Source Author", parsed.body_text)
            self.assertIn("Intro.", parsed.body_text)
            self.assertIn("Forwarded body.", parsed.body_text)

    def test_parser_config_can_preserve_forwarded_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            eml_path = Path(temp_dir) / "forwarded.eml"
            _write_message(eml_path, _forwarded_message())

            parsed = parse_eml(
                eml_path,
                parser_config=ParserConfig(
                    strip_forwarded_headers=False,
                    strip_boilerplate=False,
                    strip_link_only_lines=False,
                    stop_at_footer=False,
                ),
            )

            self.assertIn("---------- Forwarded message ---------", parsed.body_text)
            self.assertIn("From: Source Author", parsed.body_text)

    def test_mailatlas_object_scopes_storage_and_parser_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "forwarded.eml"
            _write_message(eml_path, _forwarded_message())

            atlas = MailAtlas(
                db_path=root / "store.db",
                workspace_path=root / "workspace",
                parser_config=ParserConfig(
                    strip_forwarded_headers=False,
                    strip_boilerplate=False,
                    strip_link_only_lines=False,
                    stop_at_footer=False,
                ),
            )

            parsed = atlas.parse_eml(eml_path)
            refs = atlas.ingest_eml([eml_path])
            exported = atlas.export_document(refs[0].id, format="json")

            self.assertIn("---------- Forwarded message ---------", parsed.body_text)
            self.assertIn("From: Source Author", parsed.body_text)
            self.assertIn("\"id\":", exported)
            self.assertTrue((root / "workspace").exists())

    def test_ingest_html_inline_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline.eml"
            _write_message(eml_path, _html_inline_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            exported = json.loads(atlas.export_document(refs[0].id, format="json"))

            self.assertEqual(len(exported["assets"]), 1)
            self.assertTrue((atlas.workspace_path / exported["body_html_path"]).exists())
            html = atlas.export_document(refs[0].id, format="html")
            self.assertIn("../assets/", html)
            self.assertIn("chart.svg", html)
            asset_path = atlas.workspace_path / exported["assets"][0]["file_path"]
            self.assertIn("<svg", asset_path.read_text(encoding="utf-8"))

    def test_forwarded_metadata_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "forwarded.eml"
            _write_message(eml_path, _forwarded_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            exported = json.loads(atlas.export_document(refs[0].id, format="json"))

            self.assertTrue(exported["metadata"]["provenance"]["is_forwarded"])
            self.assertEqual(exported["author"], "Source Author <source@example.com>")
            self.assertNotIn("---------- Forwarded message ---------", exported["body_text"])
            self.assertTrue(exported["metadata"]["cleaning"]["removed_forwarded_headers"])

    def test_ingest_mbox_and_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "mailbox.mbox"

            archive = mailbox.mbox(archive_path)
            archive.lock()
            try:
                archive.add(_plain_message("MBX One"))
                archive.add(_plain_message("MBX One"))
                archive.flush()
            finally:
                archive.unlock()
                archive.close()

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            first = atlas.ingest_mbox(archive_path)
            second = atlas.ingest_mbox(archive_path)

            self.assertEqual(len(first), 2)
            self.assertEqual(first[0].id, second[0].id)

    def test_receive_imap_password_ingests_multiple_folders_and_tracks_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 101,
                        "messages": {
                            1: _imap_message_bytes("Inbox One", "<imap-1@example.com>"),
                            2: _imap_message_bytes("Inbox Two", "<imap-2@example.com>"),
                        },
                    },
                    "Archive": {
                        "uidvalidity": 202,
                        "messages": {
                            8: _imap_message_bytes("Inbox Two", "<imap-2@example.com>"),
                        },
                    },
                }
            )
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                result = atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                        imap_folders=("INBOX", "Archive"),
                    )
                )

            self.assertEqual(result.status, "ok")
            self.assertEqual(connection.login_calls, [("user@example.com", "app-password")])
            folders = result.details["folders"]
            self.assertEqual(len(folders), 2)
            self.assertEqual(folders[0]["ingested_count"], 2)
            self.assertEqual(folders[1]["duplicate_count"], 1)
            self.assertEqual(len(atlas.list_documents()), 2)

            exported = json.loads(atlas.export_document(folders[0]["document_refs"][0]["id"], format="json"))
            self.assertEqual(exported["source_kind"], "imap")
            self.assertEqual(exported["metadata"]["source"]["kind"], "imap")
            self.assertEqual(exported["metadata"]["source"]["host"], "imap.example.com")
            self.assertEqual(exported["metadata"]["source"]["folder"], "INBOX")
            self.assertEqual(exported["metadata"]["source"]["uid"], 1)
            self.assertEqual(exported["metadata"]["source"]["uidvalidity"], "101")
            self.assertTrue(exported["raw_path"].endswith(".eml"))

            cursor_by_folder = {folder["folder"]: folder for folder in result.cursor["folders"]}
            self.assertEqual(cursor_by_folder["INBOX"]["uidvalidity"], "101")
            self.assertEqual(cursor_by_folder["INBOX"]["last_uid"], 2)
            self.assertEqual(cursor_by_folder["Archive"]["uidvalidity"], "202")
            self.assertEqual(cursor_by_folder["Archive"]["last_uid"], 8)

    def test_receive_imap_ingests_live_mailbox_and_records_receive_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 101,
                        "messages": {
                            1: _imap_message_bytes("Inbox One", "<imap-receive-1@example.com>"),
                            2: _imap_message_bytes("Inbox Two", "<imap-receive-2@example.com>"),
                        },
                    }
                }
            )
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                result = atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                        imap_folders=("INBOX",),
                    )
                )

            self.assertEqual(result.status, "ok")
            self.assertEqual(result.provider, "imap")
            self.assertEqual(result.account_id, "imap:user@example.com:imap.example.com:INBOX")
            self.assertEqual(result.fetched_count, 2)
            self.assertEqual(result.ingested_count, 2)
            self.assertEqual(set(result.document_ids), {reference.id for reference in atlas.list_documents()})
            self.assertEqual(result.cursor["folders"][0]["folder"], "INBOX")
            self.assertEqual(result.cursor["folders"][0]["last_uid"], 2)
            self.assertEqual(result.details["folders"][0]["folder"], "INBOX")
            self.assertNotIn("app-password", json.dumps(result.to_dict()))

            status = atlas.receive_status(account_id=result.account_id)
            self.assertEqual(status["accounts"][0]["provider"], "imap")
            self.assertEqual(status["accounts"][0]["email"], "user@example.com")
            self.assertEqual(status["cursors"][0]["provider"], "imap")
            self.assertEqual(status["recent_runs"][0]["provider"], "imap")
            self.assertEqual(status["recent_runs"][0]["fetched_count"], 2)

    def test_receive_imap_incremental_runs_fetch_only_new_uids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 101,
                        "messages": {
                            1: _imap_message_bytes("One", "<imap-1@example.com>"),
                            2: _imap_message_bytes("Two", "<imap-2@example.com>"),
                        },
                    }
                }
            )
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                first = atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                    )
                )
                connection.mailboxes["INBOX"]["messages"][3] = _imap_message_bytes("Three", "<imap-3@example.com>")
                second = atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                    )
                )

            self.assertEqual(first.details["folders"][0]["fetched_count"], 2)
            self.assertEqual(second.details["folders"][0]["fetched_count"], 1)
            self.assertEqual(second.details["folders"][0]["ingested_count"], 1)
            self.assertEqual(connection.fetch_calls, [("INBOX", 1), ("INBOX", 2), ("INBOX", 3)])
            self.assertEqual(second.cursor["folders"][0]["last_uid"], 3)

    def test_receive_imap_uidvalidity_reset_rescans_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 101,
                        "messages": {
                            1: _imap_message_bytes("One", "<imap-1@example.com>"),
                            2: _imap_message_bytes("Two", "<imap-2@example.com>"),
                        },
                    }
                }
            )
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                    )
                )
                connection.mailboxes["INBOX"]["uidvalidity"] = 303
                second = atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                    )
                )

            self.assertEqual(second.details["folders"][0]["fetched_count"], 2)
            self.assertEqual(second.details["folders"][0]["duplicate_count"], 2)
            self.assertEqual(len(atlas.list_documents()), 2)
            self.assertEqual(connection.fetch_calls[-2:], [("INBOX", 1), ("INBOX", 2)])
            self.assertEqual(second.cursor["folders"][0]["uidvalidity"], "303")
            self.assertEqual(second.cursor["folders"][0]["last_uid"], 2)

    def test_receive_imap_xoauth2_uses_access_token_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 777,
                        "messages": {
                            4: _imap_message_bytes("Token Auth", "<imap-token@example.com>"),
                        },
                    }
                }
            )
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="oauth-user@example.com",
                        imap_auth="xoauth2",
                        imap_access_token="access-token",
                    )
                )

            self.assertEqual(connection.login_calls, [])
            self.assertEqual(connection.authenticate_calls[0][0], "XOAUTH2")
            self.assertIn(b"user=oauth-user@example.com", connection.authenticate_calls[0][1])
            self.assertIn(b"auth=Bearer access-token", connection.authenticate_calls[0][1])

    def test_receive_imap_folder_error_does_not_stop_other_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 101,
                        "messages": {
                            1: _imap_message_bytes("Healthy", "<imap-healthy@example.com>"),
                        },
                    },
                    "Broken": {
                        "uidvalidity": 202,
                        "messages": {
                            5: _imap_message_bytes("Broken", "<imap-broken@example.com>"),
                        },
                    },
                },
                fail_select={"Broken"},
            )
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                result = atlas.receive(
                    ReceiveConfig(
                        provider="imap",
                        imap_host="imap.example.com",
                        imap_username="user@example.com",
                        imap_password="app-password",
                        imap_folders=("INBOX", "Broken"),
                    )
                )

            self.assertEqual(result.status, "partial")
            self.assertEqual(result.error_count, 1)
            self.assertEqual(result.details["folders"][0]["status"], "ok")
            self.assertEqual(result.details["folders"][1]["status"], "error")
            self.assertEqual(len(atlas.list_documents()), 1)
            broken_cursor = result.cursor["folders"][1]
            self.assertEqual(broken_cursor["status"], "error")
            self.assertEqual(broken_cursor["last_uid"], 0)

    def test_draft_email_stores_outbound_record_and_omits_bcc_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            attachment_path = root / "report.txt"
            attachment_path.write_text("attached report", encoding="utf-8")
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            result = atlas.draft_email(
                OutboundMessage(
                    from_email="sender@example.com",
                    from_name="Sender Example",
                    to=("recipient@example.com",),
                    cc=("copy@example.com",),
                    bcc=("audit@example.com",),
                    reply_to=("reply@example.com",),
                    subject="Quarterly report",
                    text="Plain report body",
                    html="<p>Plain report body</p>",
                    headers={"X-Campaign-ID": "quarterly"},
                    attachments=(OutboundAttachment(path=attachment_path),),
                    source_document_id="doc-123",
                )
            )

            record = atlas.get_outbound(result.id)
            raw_bytes = (atlas.workspace_path / record.raw_path).read_bytes()

            self.assertEqual(result.status, "draft")
            self.assertEqual(record.provider, "local")
            self.assertEqual(record.bcc, ("audit@example.com",))
            self.assertEqual(len(record.attachments), 1)
            self.assertTrue((atlas.workspace_path / record.text_path).exists())
            self.assertTrue((atlas.workspace_path / record.html_path).exists())
            self.assertTrue((atlas.workspace_path / record.attachments[0].file_path).exists())
            self.assertNotIn(b"\nBcc:", raw_bytes)
            self.assertIn(b"X-Campaign-ID: quarterly", raw_bytes)
            self.assertEqual(atlas.list_outbound()[0].id, result.id)

    def test_outbound_validation_rejects_header_injection_and_missing_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with self.assertRaises(ValueError):
                atlas.draft_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        to=("recipient@example.com",),
                        subject="Hello",
                        text="Body",
                        headers={"X-Test": "safe\nInjected: bad"},
                    )
                )

            with self.assertRaises(ValueError):
                atlas.draft_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        to=("recipient@example.com",),
                        subject="Hello",
                        text="Body",
                        attachments=(OutboundAttachment(path=root / "missing.pdf"),),
                    )
                )

            with self.assertRaises(ValueError):
                atlas.draft_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        to=("not-an-address",),
                        subject="Hello",
                        text="Body",
                    )
                )

            with self.assertRaises(ValueError):
                atlas.draft_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        to=("recipient@example.com",),
                        subject="Hello",
                    )
                )

    def test_send_email_reuses_existing_idempotency_key_without_resending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            message = OutboundMessage(
                from_email="sender@example.com",
                to=("recipient@example.com",),
                subject="Idempotent",
                text="Body",
                idempotency_key="retry-123",
            )

            first = atlas.send_email(message, SendConfig(provider="smtp", dry_run=True))
            with mock.patch("mailatlas.adapters.smtp.smtplib.SMTP") as smtp_mock:
                second = atlas.send_email(
                    message,
                    SendConfig(provider="smtp", smtp_host="smtp.example.com", smtp_username="user", smtp_password="secret"),
                )

            self.assertEqual(first.id, second.id)
            self.assertEqual(second.status, "dry_run")
            smtp_mock.assert_not_called()
            self.assertEqual(len(atlas.list_outbound()), 1)

    def test_send_email_smtp_uses_starttls_auth_and_bcc_envelope(self) -> None:
        FakeSmtpServer.instances.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.smtp.smtplib.SMTP", FakeSmtpServer):
                result = atlas.send_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        to=("recipient@example.com",),
                        cc=("copy@example.com",),
                        bcc=("hidden@example.com",),
                        subject="SMTP send",
                        text="Body",
                    ),
                    SendConfig(
                        provider="smtp",
                        smtp_host="smtp.example.com",
                        smtp_port=2525,
                        smtp_username="smtp-user",
                        smtp_password="smtp-secret",
                    ),
                )

            server = FakeSmtpServer.instances[0]
            sent_message, from_addr, to_addrs = server.send_calls[0]
            record = atlas.get_outbound(result.id)

            self.assertEqual(result.status, "sent")
            self.assertEqual(server.host, "smtp.example.com")
            self.assertEqual(server.port, 2525)
            self.assertEqual(server.starttls_calls, 1)
            self.assertEqual(server.login_calls, [("smtp-user", "smtp-secret")])
            self.assertEqual(from_addr, "sender@example.com")
            self.assertEqual(to_addrs, ["recipient@example.com", "copy@example.com", "hidden@example.com"])
            self.assertNotIn("Bcc", sent_message)
            self.assertEqual(record.status, "sent")
            self.assertIsNotNone(record.sent_at)

    def test_send_email_smtp_ssl_allows_anonymous_send(self) -> None:
        FakeSmtpServer.instances.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.smtp.smtplib.SMTP_SSL", FakeSmtpServer):
                result = atlas.send_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        to=("recipient@example.com",),
                        subject="SMTP SSL",
                        text="Body",
                    ),
                    SendConfig(provider="smtp", smtp_host="smtp.example.com", smtp_ssl=True, smtp_starttls=False),
                )

            server = FakeSmtpServer.instances[0]
            self.assertEqual(result.status, "sent")
            self.assertEqual(server.login_calls, [])
            self.assertEqual(server.starttls_calls, 0)

    def test_send_email_error_persists_failure_without_provider_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            result = atlas.send_email(
                OutboundMessage(
                    from_email="sender@example.com",
                    to=("recipient@example.com",),
                    subject="Missing host",
                    text="Body",
                ),
                SendConfig(provider="smtp", smtp_username="user", smtp_password="smtp-secret"),
            )

            record = atlas.get_outbound(result.id)
            serialized = json.dumps(record.to_dict())
            self.assertEqual(result.status, "error")
            self.assertEqual(record.status, "error")
            self.assertIn("SMTP host is required", record.error)
            self.assertNotIn("smtp-secret", serialized)

    def test_send_email_cloudflare_posts_current_rest_shape(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {
                    "success": True,
                    "errors": [],
                    "messages": [],
                    "result": {"delivered": ["recipient@example.com"], "permanent_bounces": [], "queued": []},
                }
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            attachment_path = root / "invoice.txt"
            attachment_path.write_text("invoice", encoding="utf-8")
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.cloudflare.urllib.request.urlopen", side_effect=fake_urlopen):
                result = atlas.send_email(
                    OutboundMessage(
                        from_email="sender@example.com",
                        from_name="Sender",
                        to=("recipient@example.com",),
                        bcc=("archive@example.com",),
                        subject="Cloudflare send",
                        text="Body",
                        headers={"X-Test": "yes"},
                        attachments=(OutboundAttachment(path=attachment_path),),
                    ),
                    SendConfig(
                        provider="cloudflare",
                        cloudflare_account_id="account-123",
                        cloudflare_api_token="cf-secret-token",
                    ),
                )

            record = atlas.get_outbound(result.id)
            payload = captured["payload"]
            self.assertEqual(result.status, "sent")
            self.assertEqual(captured["url"], "https://api.cloudflare.com/client/v4/accounts/account-123/email/sending/send")
            self.assertEqual(captured["authorization"], "Bearer cf-secret-token")
            self.assertEqual(payload["from"], {"address": "sender@example.com", "name": "Sender"})
            self.assertEqual(payload["bcc"], "archive@example.com")
            self.assertEqual(payload["headers"], {"X-Test": "yes"})
            self.assertEqual(payload["attachments"][0]["filename"], "invoice.txt")
            self.assertNotIn("cf-secret-token", json.dumps(record.to_dict()))

    def test_send_email_gmail_posts_base64url_mime_and_metadata(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {
                    "id": "gmail-message-123",
                    "threadId": "gmail-thread-456",
                    "labelIds": ["SENT"],
                }
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                result = atlas.send_email(
                    OutboundMessage(
                        from_email="sender@gmail.com",
                        to=("recipient@example.com",),
                        subject="Gmail send",
                        text="Body",
                    ),
                    SendConfig(
                        provider="gmail",
                        gmail_access_token="gmail-secret-token",
                        gmail_api_base="https://gmail.test/gmail/v1",
                    ),
                )

            record = atlas.get_outbound(result.id)
            raw = captured["payload"]["raw"]
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))

            self.assertEqual(result.status, "sent")
            self.assertEqual(result.provider_message_id, "gmail-message-123")
            self.assertEqual(captured["url"], "https://gmail.test/gmail/v1/users/me/messages/send")
            self.assertEqual(captured["authorization"], "Bearer gmail-secret-token")
            self.assertIn(b"Subject: Gmail send", decoded)
            self.assertIn(b"To: recipient@example.com", decoded)
            self.assertNotIn(b"\nBcc:", decoded)
            self.assertEqual(record.metadata["gmail_thread_id"], "gmail-thread-456")
            self.assertEqual(record.metadata["gmail_label_ids"], ["SENT"])
            self.assertNotIn("gmail-secret-token", json.dumps(record.to_dict()))

    def test_send_email_gmail_missing_token_returns_error_without_persisting_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            result = atlas.send_email(
                OutboundMessage(
                    from_email="sender@gmail.com",
                    to=("recipient@example.com",),
                    subject="Gmail missing token",
                    text="Body",
                ),
                SendConfig(provider="gmail"),
            )

            record = atlas.get_outbound(result.id)
            self.assertEqual(result.status, "error")
            self.assertIn("Gmail access token is required", result.error)
            self.assertNotIn("access_token", json.dumps(record.to_dict()))

    def test_send_email_gmail_bcc_uses_provider_only_mime(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse({"id": "gmail-bcc-message", "threadId": "gmail-bcc-thread"})

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                result = atlas.send_email(
                    OutboundMessage(
                        from_email="sender@gmail.com",
                        to=("recipient@example.com",),
                        bcc=("hidden@example.com",),
                        subject="Gmail bcc",
                        text="Body",
                    ),
                    SendConfig(provider="gmail", gmail_access_token="gmail-secret-token"),
                )

            record = atlas.get_outbound(result.id)
            raw = (atlas.workspace_path / record.raw_path).read_bytes()
            gmail_raw = captured["payload"]["raw"]
            gmail_decoded = base64.urlsafe_b64decode(gmail_raw + "=" * (-len(gmail_raw) % 4))

            self.assertEqual(result.status, "sent")
            self.assertEqual(result.provider_message_id, "gmail-bcc-message")
            self.assertEqual(record.bcc, ("hidden@example.com",))
            self.assertNotIn(b"\nBcc:", raw)
            self.assertIn(b"\nBcc: hidden@example.com", gmail_decoded)
            self.assertIn("gmail-bcc-thread", json.dumps(record.metadata))

    def test_receive_gmail_ingests_raw_messages_and_tracks_cursor(self) -> None:
        captured_auth: list[str | None] = []
        message = _plain_message("Gmail Receive")
        message.replace_header("Message-ID", "<gmail-receive-1@example.com>")

        def fake_urlopen(request, timeout=None):
            captured_auth.append(request.get_header("Authorization"))
            url = urllib.parse.urlsplit(request.full_url)
            if url.path.endswith("/profile"):
                return FakeHttpResponse({"emailAddress": "user@gmail.com", "historyId": "900"})
            if url.path.endswith("/messages"):
                query = dict(urllib.parse.parse_qsl(url.query))
                self.assertEqual(query["labelIds"], "INBOX")
                self.assertEqual(query["maxResults"], "50")
                return FakeHttpResponse({"messages": [{"id": "gmail-message-1", "threadId": "thread-1"}]})
            if url.path.endswith("/messages/gmail-message-1"):
                return FakeHttpResponse(
                    {
                        "id": "gmail-message-1",
                        "threadId": "thread-1",
                        "labelIds": ["INBOX"],
                        "historyId": "901",
                        "internalDate": "1710000000000",
                        "raw": _gmail_raw(message),
                    }
                )
            raise AssertionError(f"Unexpected Gmail API URL: {request.full_url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                result = atlas.receive(
                    ReceiveConfig(
                        gmail_access_token="gmail-receive-token",
                        gmail_api_base="https://gmail.test/gmail/v1",
                    )
                )

            document = atlas.get_document(result.document_ids[0])
            status = atlas.receive_status()

            self.assertEqual(result.status, "ok")
            self.assertEqual(result.account_id, "gmail:user@gmail.com:INBOX")
            self.assertEqual(result.fetched_count, 1)
            self.assertEqual(result.ingested_count, 1)
            self.assertEqual(result.cursor["history_id"], "901")
            self.assertEqual(result.cursor["last_message_internal_date"], "1710000000000")
            self.assertEqual(document.source_kind, "gmail")
            self.assertEqual(document.raw_path.split(".", 1)[1], "eml")
            self.assertEqual(document.metadata["source_kind"], "gmail")
            self.assertEqual(document.metadata["source_uri"], "gmail://me/messages/gmail-message-1")
            self.assertEqual(document.metadata["gmail"]["message_id"], "gmail-message-1")
            self.assertEqual(document.metadata["gmail"]["account_id"], "gmail:user@gmail.com:INBOX")
            self.assertEqual(status["accounts"][0]["email"], "user@gmail.com")
            self.assertEqual(status["cursors"][0]["cursor_json"]["history_id"], "901")
            self.assertEqual(status["recent_runs"][0]["status"], "ok")
            self.assertTrue(all(value == "Bearer gmail-receive-token" for value in captured_auth))
            self.assertNotIn("gmail-receive-token", json.dumps(document.to_dict()))

    def test_receive_gmail_full_sync_dedupes_existing_messages(self) -> None:
        message = _plain_message("Gmail Duplicate")
        message.replace_header("Message-ID", "<gmail-duplicate@example.com>")

        def fake_urlopen(request, timeout=None):
            url = urllib.parse.urlsplit(request.full_url)
            if url.path.endswith("/profile"):
                return FakeHttpResponse({"emailAddress": "user@gmail.com", "historyId": "902"})
            if url.path.endswith("/messages"):
                return FakeHttpResponse({"messages": [{"id": "gmail-duplicate-1"}]})
            if url.path.endswith("/messages/gmail-duplicate-1"):
                return FakeHttpResponse(
                    {
                        "id": "gmail-duplicate-1",
                        "threadId": "thread-duplicate",
                        "labelIds": ["INBOX"],
                        "historyId": "902",
                        "internalDate": "1710000000001",
                        "raw": _gmail_raw(message),
                    }
                )
            raise AssertionError(f"Unexpected Gmail API URL: {request.full_url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            config = ReceiveConfig(
                gmail_access_token="gmail-receive-token",
                gmail_api_base="https://gmail.test/gmail/v1",
                full_sync=True,
            )

            with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                first = atlas.receive(config)
                second = atlas.receive(config)

            self.assertEqual(first.status, "ok")
            self.assertEqual(second.status, "duplicate")
            self.assertEqual(second.ingested_count, 0)
            self.assertEqual(second.duplicate_count, 1)
            self.assertEqual(first.document_ids, second.document_ids)

    def test_receive_gmail_history_expiration_requires_explicit_full_sync(self) -> None:
        account_id = "gmail:user@gmail.com:INBOX"

        def fake_urlopen(request, timeout=None):
            url = urllib.parse.urlsplit(request.full_url)
            if url.path.endswith("/profile"):
                return FakeHttpResponse({"emailAddress": "user@gmail.com", "historyId": "950"})
            if url.path.endswith("/history"):
                body = json.dumps({"error": {"message": "History ID is too old.", "code": 404}}).encode("utf-8")
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(body))
            raise AssertionError(f"Unexpected Gmail API URL: {request.full_url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            config = ReceiveConfig(
                account_id=account_id,
                gmail_access_token="gmail-receive-token",
                gmail_api_base="https://gmail.test/gmail/v1",
            )
            atlas.store.save_receive_account(
                account_id=account_id,
                provider="gmail",
                email="user@gmail.com",
                label="INBOX",
                query=None,
                config=config.to_safe_dict(),
            )
            atlas.store.save_receive_cursor(account_id, "gmail", {"history_id": "100"})

            with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                result = atlas.receive(config)

            self.assertEqual(result.status, "cursor_reset_required")
            self.assertEqual(result.cursor, {"history_id": "100"})
            self.assertEqual(result.ingested_count, 0)
            self.assertIn("History ID is too old", result.error)
            self.assertEqual(atlas.receive_status(account_id=account_id)["last_error"], result.error)

    def test_gmail_oauth_code_exchange_does_not_persist_token_values_in_status(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["form"] = dict(urllib.parse.parse_qsl(request.data.decode("utf-8")))
            return FakeHttpResponse(
                {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/gmail.send",
                    "token_type": "Bearer",
                }
            )

        with mock.patch("mailatlas.core.gmail_auth.urllib.request.urlopen", side_effect=fake_urlopen):
            token = exchange_gmail_authorization_code(
                GmailAuthConfig(
                    client_id="client-123",
                    client_secret="client-secret",
                    email="sender@gmail.com",
                    token_url="https://oauth.test/token",
                ),
                code="auth-code",
                redirect_uri="http://127.0.0.1:12345",
                code_verifier="verifier",
            )

        self.assertEqual(captured["url"], "https://oauth.test/token")
        self.assertEqual(captured["form"]["client_id"], "client-123")
        self.assertEqual(captured["form"]["client_secret"], "client-secret")
        self.assertEqual(captured["form"]["code_verifier"], "verifier")
        self.assertEqual(token["access_token"], "access-secret")
        self.assertEqual(token["refresh_token"], "refresh-secret")
        self.assertEqual(token["email"], "sender@gmail.com")

    def test_gmail_token_store_auto_prefers_keychain_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "gmail-token.json"
            with mock.patch("mailatlas.core.gmail_auth.KeyringTokenStore.is_available", return_value=True):
                auto_store = create_gmail_token_store(token_store="auto")
                explicit_store = create_gmail_token_store(token_path, token_store="keychain")

        self.assertIsInstance(auto_store, KeyringTokenStore)
        self.assertEqual(auto_store.store_type, "keychain")
        self.assertIsInstance(explicit_store, FileTokenStore)
        self.assertEqual(explicit_store.store_path, token_path.resolve().as_posix())

    def test_gmail_token_store_auto_falls_back_to_file_when_keychain_is_unavailable(self) -> None:
        with mock.patch("mailatlas.core.gmail_auth.KeyringTokenStore.is_available", return_value=False):
            store = create_gmail_token_store(token_store="auto")

        self.assertIsInstance(store, FileTokenStore)
        self.assertEqual(store.store_type, "file")

    def test_gmail_token_store_env_token_file_overrides_default_auto_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "gmail-token.json"
            with mock.patch.dict(os.environ, {"MAILATLAS_GMAIL_TOKEN_FILE": token_path.as_posix()}, clear=True):
                with mock.patch("mailatlas.core.gmail_auth.KeyringTokenStore.is_available", return_value=True):
                    store = create_gmail_token_store()

        self.assertIsInstance(store, FileTokenStore)
        self.assertEqual(store.store_path, token_path.resolve().as_posix())

    def test_cli_auth_status_and_logout_support_keychain_without_printing_tokens(self) -> None:
        fake_keyring = _fake_keyring_module()
        with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
            KeyringTokenStore().save(
                {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "client_id": "client-123",
                    "client_secret": "client-secret",
                    "expires_at": 1893456000,
                    "scope": "https://www.googleapis.com/auth/gmail.send",
                    "email": "sender@gmail.com",
                }
            )

            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                status_code = mailatlas_cli.main(["auth", "status", "gmail", "--token-store", "keychain"])

            status_output = stdout.getvalue()
            status_payload = json.loads(status_output)

            with mock.patch("sys.stdout", new_callable=io.StringIO) as logout_stdout:
                logout_code = mailatlas_cli.main(["auth", "logout", "gmail", "--token-store", "keychain"])

            logout_output = logout_stdout.getvalue()
            logout_payload = json.loads(logout_output)

            self.assertIsNone(KeyringTokenStore().load())

        self.assertEqual(status_code, 0)
        self.assertEqual(status_payload["status"], "configured")
        self.assertEqual(status_payload["store_type"], "keychain")
        self.assertEqual(status_payload["email"], "sender@gmail.com")
        self.assertIn("https://www.googleapis.com/auth/gmail.send", status_payload["scopes"])
        self.assertEqual(logout_code, 0)
        self.assertEqual(logout_payload["status"], "removed")
        for secret in ("access-secret", "refresh-secret", "client-secret"):
            self.assertNotIn(secret, status_output)
            self.assertNotIn(secret, logout_output)

    def test_cli_auth_keychain_mode_explains_missing_optional_dependency(self) -> None:
        with mock.patch.dict(sys.modules, {"keyring": None}):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                exit_code = mailatlas_cli.main(["auth", "status", "gmail", "--token-store", "keychain"])

        self.assertEqual(exit_code, 1)
        self.assertIn("mailatlas[keychain]", stderr.getvalue())

    def test_cli_sync_command_is_removed(self) -> None:
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as raised:
                mailatlas_cli.main(["sync"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice: 'sync'", stderr.getvalue())
        self.assertFalse(hasattr(MailAtlas, "sync_imap"))

    def test_cli_receive_imap_uses_env_defaults_and_cli_precedence(self) -> None:
        result = ReceiveResult(
            status="ok",
            provider="imap",
            account_id="imap:user@example.com:imap.example.com:INBOX",
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=0,
            document_ids=(),
            cursor={"folders": []},
            run_id="run-1",
            details={
                "status": "ok",
                "host": "imap.example.com",
                "port": 993,
                "username": "user@example.com",
                "auth": "password",
                "folder_count": 0,
                "error_count": 0,
                "fetched_count": 0,
                "ingested_count": 0,
                "duplicate_count": 0,
                "folders": [],
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"

            with mock.patch.object(mailatlas_cli.MailAtlas, "receive", return_value=result) as receive_mock:
                with mock.patch.dict(
                    os.environ,
                    {
                        "MAILATLAS_IMAP_HOST": "env.example.com",
                        "MAILATLAS_IMAP_PORT": "1993",
                        "MAILATLAS_IMAP_USERNAME": "env-user@example.com",
                        "MAILATLAS_IMAP_PASSWORD": "env-secret",
                    },
                    clear=False,
                ):
                    with mock.patch("sys.stdout", new_callable=io.StringIO):
                        exit_code = mailatlas_cli.main(["receive", "--root", root.as_posix(), "--provider", "imap"])
                        env_config = receive_mock.call_args.args[0]

                    with mock.patch("sys.stdout", new_callable=io.StringIO):
                        override_code = mailatlas_cli.main(
                            [
                                "receive",
                                "--root",
                                root.as_posix(),
                                "--provider",
                                "imap",
                                "--host",
                                "cli.example.com",
                                "--username",
                                "cli-user@example.com",
                                "--password",
                                "cli-secret",
                                "--folder",
                                "Inbox/Subfolder",
                            ]
                        )
                        cli_config = receive_mock.call_args.args[0]

        self.assertEqual(exit_code, 0)
        self.assertEqual(env_config.provider, "imap")
        self.assertEqual(env_config.imap_host, "env.example.com")
        self.assertEqual(env_config.imap_port, 1993)
        self.assertEqual(env_config.imap_username, "env-user@example.com")
        self.assertEqual(env_config.imap_password, "env-secret")
        self.assertEqual(env_config.imap_auth, "password")
        self.assertEqual(env_config.imap_folders, ("INBOX",))
        self.assertEqual(override_code, 0)
        self.assertEqual(cli_config.imap_host, "cli.example.com")
        self.assertEqual(cli_config.imap_username, "cli-user@example.com")
        self.assertEqual(cli_config.imap_password, "cli-secret")
        self.assertEqual(cli_config.imap_auth, "password")
        self.assertEqual(cli_config.imap_folders, ("Inbox/Subfolder",))

    def test_cli_receive_imap_returns_nonzero_when_any_folder_fails(self) -> None:
        result = ReceiveResult(
            status="error",
            provider="imap",
            account_id="imap:user@example.com:imap.example.com:INBOX",
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=1,
            document_ids=(),
            cursor={"folders": []},
            run_id="run-1",
            details={
                "status": "error",
                "host": "imap.example.com",
                "port": 993,
                "username": "user@example.com",
                "auth": "password",
                "folder_count": 1,
                "error_count": 1,
                "fetched_count": 0,
                "ingested_count": 0,
                "duplicate_count": 0,
                "folders": [
                    {
                        "folder": "INBOX",
                        "status": "error",
                        "uidvalidity": "101",
                        "last_uid": 0,
                        "fetched_count": 0,
                        "ingested_count": 0,
                        "duplicate_count": 0,
                        "document_refs": [],
                        "error": "cannot select mailbox",
                    }
                ],
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch.object(mailatlas_cli.MailAtlas, "receive", return_value=result):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    exit_code = mailatlas_cli.main(
                        [
                            "receive",
                            "--root",
                            root.as_posix(),
                            "--provider",
                            "imap",
                            "--host",
                            "imap.example.com",
                            "--username",
                            "user@example.com",
                            "--password",
                            "secret",
                        ]
                    )

        self.assertEqual(exit_code, 1)

    def test_cli_receive_imap_fetches_one_pass_and_prints_provider_neutral_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 101,
                        "messages": {
                            1: _imap_message_bytes("CLI IMAP Receive", "<cli-imap-receive@example.com>"),
                        },
                    }
                }
            )

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(
                        [
                            "receive",
                            "--root",
                            root.as_posix(),
                            "--provider",
                            "imap",
                            "--host",
                            "imap.example.com",
                            "--username",
                            "user@example.com",
                            "--password",
                            "app-password",
                            "--folder",
                            "INBOX",
                        ]
                    )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["provider"], "imap")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["fetched_count"], 1)
            self.assertEqual(payload["details"]["folders"][0]["folder"], "INBOX")
            self.assertNotIn("app-password", stdout.getvalue())

    def test_cli_send_dry_run_writes_outbound_record_and_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "mailatlas-root"
            body_path = root / "body.txt"
            body_path.write_text("CLI body", encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(
                        [
                            "send",
                            "--root",
                            storage_root.as_posix(),
                            "--dry-run",
                            "--from",
                            "sender@example.com",
                            "--to",
                            "recipient@example.com",
                            "--bcc",
                            "hidden@example.com",
                            "--subject",
                            "CLI dry run",
                            "--text-file",
                            body_path.as_posix(),
                        ]
                    )

            payload = json.loads(stdout.getvalue())
            atlas = MailAtlas(db_path=storage_root / "store.db", workspace_path=storage_root)
            record = atlas.get_outbound(payload["id"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["provider"], "smtp")
            self.assertEqual(record.bcc, ("hidden@example.com",))
            self.assertIn("CLI body", (atlas.workspace_path / record.raw_path).read_text(encoding="utf-8"))
            self.assertNotIn("\nBcc:", (atlas.workspace_path / record.raw_path).read_text(encoding="utf-8"))

    def test_cli_send_env_defaults_and_cli_precedence(self) -> None:
        result = SendResult(id="outbound-123", status="dry_run", provider="smtp")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch.object(mailatlas_cli.MailAtlas, "send_email", return_value=result) as send_mock:
                with mock.patch.dict(
                    os.environ,
                    {
                        "MAILATLAS_SEND_PROVIDER": "cloudflare",
                        "MAILATLAS_SMTP_HOST": "env-smtp.example.com",
                        "MAILATLAS_SMTP_PORT": "1025",
                        "MAILATLAS_SMTP_USERNAME": "env-user",
                        "MAILATLAS_SMTP_PASSWORD": "env-secret",
                        "MAILATLAS_SMTP_STARTTLS": "false",
                        "MAILATLAS_SMTP_SSL": "true",
                    },
                    clear=False,
                ):
                    with mock.patch("sys.stdout", new_callable=io.StringIO):
                        exit_code = mailatlas_cli.main(
                            [
                                "send",
                                "--root",
                                root.as_posix(),
                                "--provider",
                                "smtp",
                                "--smtp-host",
                                "cli-smtp.example.com",
                                "--smtp-port",
                                "2525",
                                "--no-smtp-ssl",
                                "--smtp-starttls",
                                "--dry-run",
                                "--from",
                                "sender@example.com",
                                "--to",
                                "recipient@example.com",
                                "--subject",
                                "Config precedence",
                                "--text",
                                "Body",
                            ]
                        )

        message_arg, config_arg = send_mock.call_args.args
        self.assertEqual(exit_code, 0)
        self.assertEqual(message_arg.subject, "Config precedence")
        self.assertEqual(config_arg.provider, "smtp")
        self.assertEqual(config_arg.smtp_host, "cli-smtp.example.com")
        self.assertEqual(config_arg.smtp_port, 2525)
        self.assertEqual(config_arg.smtp_username, "env-user")
        self.assertEqual(config_arg.smtp_password, "env-secret")
        self.assertTrue(config_arg.smtp_starttls)
        self.assertFalse(config_arg.smtp_ssl)

    def test_cli_send_missing_provider_config_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "mailatlas-root"
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(
                        [
                            "send",
                            "--root",
                            storage_root.as_posix(),
                            "--from",
                            "sender@example.com",
                            "--to",
                            "recipient@example.com",
                            "--subject",
                            "Missing SMTP",
                            "--text",
                            "Body",
                        ]
                    )

                payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("SMTP host is required", payload["error"])

    def test_mcp_tool_names_hide_send_until_enabled(self) -> None:
        self.assertIn("mailatlas_draft_email", mcp_tool_names(allow_send=False))
        self.assertNotIn("mailatlas_send_email", mcp_tool_names(allow_send=False))
        self.assertIn("mailatlas_send_email", mcp_tool_names(allow_send=True))
        self.assertNotIn("mailatlas_receive", mcp_tool_names(allow_receive=False))
        self.assertIn("mailatlas_receive", mcp_tool_names(allow_receive=True))

    def test_mcp_draft_email_returns_audit_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root", allow_send=False)

            payload = tools.draft_email(
                from_email="sender@example.com",
                to=["recipient@example.com"],
                bcc=["hidden@example.com"],
                subject="MCP draft",
                text="Draft body",
            )
            outbound = tools.list_outbound()["outbound"]
            record = tools.get_outbound(payload["id"])

            self.assertEqual(payload["status"], "draft")
            self.assertEqual(payload["provider"], "local")
            self.assertEqual(payload["to"], ["recipient@example.com"])
            self.assertEqual(payload["subject"], "MCP draft")
            self.assertEqual(outbound[0]["id"], payload["id"])
            self.assertEqual(record["bcc"], [])
            self.assertEqual(tools.get_outbound(payload["id"], include_bcc=True)["bcc"], ["hidden@example.com"])

    def test_mcp_list_documents_paginates_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tools = MailAtlasMcpTools(root=root / "mailatlas-root")
            for index, subject in enumerate(["Page One", "Page Two", "Page Three"], start=1):
                message = _plain_message(subject=subject)
                message.replace_header("Date", f"Fri, 0{index} Mar 2024 10:00:00 +0000")
                message.replace_header("Message-ID", f"<page-{index}@example.com>")
                eml_path = root / f"page-{index}.eml"
                _write_message(eml_path, message)
                tools.atlas.ingest_eml([eml_path])

            first_page = tools.list_documents(limit=2, offset=0)
            second_page = tools.list_documents(limit=2, offset=2)

            self.assertEqual(first_page["limit"], 2)
            self.assertEqual(first_page["offset"], 0)
            self.assertEqual(first_page["count"], 2)
            self.assertEqual([document["subject"] for document in first_page["documents"]], ["Page Three", "Page Two"])
            self.assertEqual(first_page["has_more"], True)
            self.assertEqual(second_page["count"], 1)
            self.assertEqual([document["subject"] for document in second_page["documents"]], ["Page One"])
            self.assertEqual(second_page["has_more"], False)

    def test_mcp_list_outbound_paginates_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root")
            for subject in ["Draft One", "Draft Two", "Draft Three"]:
                tools.draft_email(
                    from_email="agent@example.com",
                    to=["team@example.com"],
                    subject=subject,
                    text="Draft body.",
                )

            first_page = tools.list_outbound(limit=2, offset=0)
            second_page = tools.list_outbound(limit=2, offset=2)

            self.assertEqual(first_page["limit"], 2)
            self.assertEqual(first_page["offset"], 0)
            self.assertEqual(first_page["count"], 2)
            self.assertEqual(first_page["has_more"], True)
            self.assertEqual(second_page["count"], 1)
            self.assertEqual(second_page["has_more"], False)

    def test_mcp_send_email_is_disabled_by_default_without_storing_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root", allow_send=False)

            payload = tools.send_email(
                provider="smtp",
                smtp_host="smtp.example.com",
                from_email="sender@example.com",
                to=["recipient@example.com"],
                subject="MCP disabled",
                text="Body",
            )

            self.assertEqual(payload["status"], "disabled")
            self.assertIn("MAILATLAS_MCP_ALLOW_SEND=1", payload["error"])
            self.assertEqual(tools.list_outbound()["outbound"], [])

    def test_mcp_send_email_when_enabled_can_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root", allow_send=True)

            payload = tools.send_email(
                provider="smtp",
                dry_run=True,
                from_email="sender@example.com",
                to=["recipient@example.com"],
                subject="MCP dry run",
                text="Body",
            )

            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["provider"], "smtp")
            self.assertEqual(payload["to"], ["recipient@example.com"])
            self.assertEqual(tools.get_outbound(payload["id"])["subject"], "MCP dry run")

    def test_mcp_receive_is_disabled_by_default_and_hidden_from_read_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root", allow_receive=False, receive_on_read=False)

            with mock.patch.object(tools.atlas, "receive") as receive_mock:
                listed = tools.list_documents()
                payload = tools.receive(gmail_access_token="mcp-token")

            self.assertEqual(listed["documents"], [])
            self.assertEqual(listed["count"], 0)
            self.assertEqual(listed["has_more"], False)
            self.assertFalse(receive_mock.called)
            self.assertEqual(payload["status"], "disabled")
            self.assertIn("MAILATLAS_MCP_ALLOW_RECEIVE=1", payload["error"])

    def test_mcp_receive_when_enabled_returns_receive_payload(self) -> None:
        result = ReceiveResult(
            status="ok",
            provider="gmail",
            account_id="gmail:receiver@gmail.com:INBOX",
            fetched_count=1,
            ingested_count=1,
            duplicate_count=0,
            error_count=0,
            document_ids=("doc-1",),
            cursor={"history_id": "1001"},
            run_id="run-1",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root", allow_receive=True, receive_on_read=False)
            with mock.patch.object(tools.atlas, "receive", return_value=result) as receive_mock:
                payload = tools.receive(label="INBOX", limit=1, gmail_access_token="mcp-token")

            config_arg = receive_mock.call_args.args[0]

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["document_ids"], ["doc-1"])
            self.assertEqual(config_arg.limit, 1)
            self.assertEqual(config_arg.gmail_access_token, "mcp-token")

    def test_mcp_receive_supports_imap_provider_config(self) -> None:
        result = ReceiveResult(
            status="ok",
            provider="imap",
            account_id="imap:user@example.com:imap.example.com:INBOX",
            fetched_count=1,
            ingested_count=1,
            duplicate_count=0,
            error_count=0,
            document_ids=("doc-1",),
            cursor={"folders": []},
            run_id="run-1",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            tools = MailAtlasMcpTools(root=Path(temp_dir) / "mailatlas-root", allow_receive=True, receive_on_read=False)
            with mock.patch.object(tools.atlas, "receive", return_value=result) as receive_mock:
                payload = tools.receive(
                    provider="imap",
                    imap_host="imap.example.com",
                    imap_username="user@example.com",
                    imap_password="app-password",
                    imap_folders=["INBOX"],
                )

        config_arg = receive_mock.call_args.args[0]

        self.assertEqual(payload["provider"], "imap")
        self.assertEqual(config_arg.provider, "imap")
        self.assertEqual(config_arg.imap_host, "imap.example.com")
        self.assertEqual(config_arg.imap_username, "user@example.com")
        self.assertEqual(config_arg.imap_folders, ("INBOX",))

    def test_cli_mcp_delegates_to_mcp_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch("mailatlas.mcp_server.run_mcp_server", return_value=0) as run_mock:
                exit_code = mailatlas_cli.main(
                    [
                        "mcp",
                        "--root",
                        root.as_posix(),
                        "--transport",
                        "stdio",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_mock.call_args.kwargs["root"], root.resolve())
            self.assertEqual(run_mock.call_args.kwargs["transport"], "stdio")
            self.assertIsNone(run_mock.call_args.kwargs["allow_send"])
            self.assertIsNone(run_mock.call_args.kwargs["allow_receive"])

    def test_cli_mcp_accepts_explicit_capability_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch("mailatlas.mcp_server.run_mcp_server", return_value=0) as run_mock:
                exit_code = mailatlas_cli.main(
                    [
                        "mcp",
                        "--root",
                        root.as_posix(),
                        "--allow-send",
                        "--allow-receive",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIs(run_mock.call_args.kwargs["allow_send"], True)
            self.assertIs(run_mock.call_args.kwargs["allow_receive"], True)

    def test_cli_mcp_defaults_to_stdio_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch("mailatlas.mcp_server.run_mcp_server", return_value=0) as run_mock:
                exit_code = mailatlas_cli.main(["mcp", "--root", root.as_posix()])

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_mock.call_args.kwargs["transport"], "stdio")

    def test_run_mcp_server_passes_explicit_capabilities_to_builder(self) -> None:
        with mock.patch("mailatlas.mcp_server.build_mcp_server") as build_mock:
            server_mock = build_mock.return_value
            exit_code = mailatlas_mcp_server.run_mcp_server(
                root="mailatlas-root",
                transport="stdio",
                allow_send=True,
                allow_receive=True,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(build_mock.call_args.kwargs["root"], "mailatlas-root")
        self.assertIs(build_mock.call_args.kwargs["allow_send"], True)
        self.assertIs(build_mock.call_args.kwargs["allow_receive"], True)
        server_mock.run.assert_called_once_with(transport="stdio")

    def test_cli_send_gmail_uses_stored_token_when_env_token_is_absent(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["authorization"] = request.get_header("Authorization")
            return FakeHttpResponse({"id": "gmail-cli-message", "threadId": "gmail-cli-thread"})

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "mailatlas-root"
            token_path = root / "gmail-token.json"
            FileTokenStore(token_path).save(
                {
                    "access_token": "stored-gmail-token",
                    "refresh_token": "refresh-token",
                    "client_id": "client-123",
                    "expires_at": time.time() + 3600,
                    "scope": "https://www.googleapis.com/auth/gmail.send",
                    "email": "sender@gmail.com",
                }
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        exit_code = mailatlas_cli.main(
                            [
                                "send",
                                "--root",
                                storage_root.as_posix(),
                                "--provider",
                                "gmail",
                                "--gmail-token-file",
                                token_path.as_posix(),
                                "--from",
                                "sender@gmail.com",
                                "--to",
                                "recipient@example.com",
                                "--subject",
                                "Gmail CLI",
                                "--text",
                                "Body",
                            ]
                        )

            payload = json.loads(stdout.getvalue())
            atlas = MailAtlas(db_path=storage_root / "store.db", workspace_path=storage_root)
            record = atlas.get_outbound(payload["id"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["provider_message_id"], "gmail-cli-message")
            self.assertEqual(captured["authorization"], "Bearer stored-gmail-token")
            self.assertEqual(record.provider, "gmail")
            self.assertNotIn("stored-gmail-token", json.dumps(record.to_dict()))

    def test_cli_send_gmail_uses_keychain_token_store_when_requested(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["authorization"] = request.get_header("Authorization")
            return FakeHttpResponse({"id": "gmail-keychain-message", "threadId": "gmail-keychain-thread"})

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "mailatlas-root"
            fake_keyring = _fake_keyring_module()
            with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                KeyringTokenStore().save(
                    {
                        "access_token": "keychain-gmail-token",
                        "refresh_token": "refresh-token",
                        "client_id": "client-123",
                        "expires_at": time.time() + 3600,
                        "scope": "https://www.googleapis.com/auth/gmail.send",
                        "email": "sender@gmail.com",
                    }
                )

                with mock.patch.dict(os.environ, {}, clear=True):
                    with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                            exit_code = mailatlas_cli.main(
                                [
                                    "send",
                                    "--root",
                                    storage_root.as_posix(),
                                    "--provider",
                                    "gmail",
                                    "--gmail-token-store",
                                    "keychain",
                                    "--from",
                                    "sender@gmail.com",
                                    "--to",
                                    "recipient@example.com",
                                    "--subject",
                                    "Gmail keychain CLI",
                                    "--text",
                                    "Body",
                                ]
                            )

            payload = json.loads(stdout.getvalue())
            atlas = MailAtlas(db_path=storage_root / "store.db", workspace_path=storage_root)
            record = atlas.get_outbound(payload["id"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["provider_message_id"], "gmail-keychain-message")
            self.assertEqual(captured["authorization"], "Bearer keychain-gmail-token")
            self.assertNotIn("keychain-gmail-token", json.dumps(record.to_dict()))

    def test_cli_receive_uses_stored_readonly_token_and_returns_json(self) -> None:
        message = _plain_message("CLI Gmail Receive")
        message.replace_header("Message-ID", "<cli-gmail-receive@example.com>")
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured.setdefault("authorization", request.get_header("Authorization"))
            url = urllib.parse.urlsplit(request.full_url)
            if url.path.endswith("/profile"):
                return FakeHttpResponse({"emailAddress": "receiver@gmail.com", "historyId": "1000"})
            if url.path.endswith("/messages"):
                return FakeHttpResponse({"messages": [{"id": "cli-gmail-message"}]})
            if url.path.endswith("/messages/cli-gmail-message"):
                return FakeHttpResponse(
                    {
                        "id": "cli-gmail-message",
                        "threadId": "cli-thread",
                        "labelIds": ["INBOX"],
                        "historyId": "1001",
                        "internalDate": "1710000001000",
                        "raw": _gmail_raw(message),
                    }
                )
            raise AssertionError(f"Unexpected Gmail API URL: {request.full_url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "mailatlas-root"
            token_path = root / "gmail-token.json"
            FileTokenStore(token_path).save(
                {
                    "access_token": "stored-readonly-token",
                    "refresh_token": "refresh-token",
                    "client_id": "client-123",
                    "expires_at": time.time() + 3600,
                    "scope": GMAIL_READONLY_SCOPE,
                    "email": "receiver@gmail.com",
                }
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("mailatlas.adapters.gmail.urllib.request.urlopen", side_effect=fake_urlopen):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        exit_code = mailatlas_cli.main(
                            [
                                "receive",
                                "--root",
                                storage_root.as_posix(),
                                "--token-file",
                                token_path.as_posix(),
                                "--gmail-api-base",
                                "https://gmail.test/gmail/v1",
                            ]
                        )

            output = stdout.getvalue()
            payload = json.loads(output)
            atlas = MailAtlas(db_path=storage_root / "store.db", workspace_path=storage_root)
            document = atlas.get_document(payload["document_ids"][0])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["account_id"], "gmail:receiver@gmail.com:INBOX")
            self.assertEqual(captured["authorization"], "Bearer stored-readonly-token")
            self.assertEqual(document.subject, "CLI Gmail Receive")
            self.assertNotIn("stored-readonly-token", output)

    def test_cli_receive_rejects_stored_token_without_receive_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "mailatlas-root"
            token_path = root / "gmail-token.json"
            FileTokenStore(token_path).save(
                {
                    "access_token": "send-only-token",
                    "refresh_token": "refresh-token",
                    "client_id": "client-123",
                    "expires_at": time.time() + 3600,
                    "scope": "https://www.googleapis.com/auth/gmail.send",
                    "email": "sender@gmail.com",
                }
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(
                        [
                            "receive",
                            "--root",
                            storage_root.as_posix(),
                            "--token-file",
                            token_path.as_posix(),
                        ]
                    )

            output = stdout.getvalue()
            payload = json.loads(output)

            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["status"], "not_configured")
            self.assertIn("missing the receive scope", payload["error"])
            self.assertNotIn("send-only-token", output)

    def test_cli_receive_watch_prints_one_json_line_per_run(self) -> None:
        result = ReceiveResult(
            status="ok",
            provider="gmail",
            account_id="gmail:receiver@gmail.com:INBOX",
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=0,
            document_ids=(),
            cursor={"history_id": "1000"},
            run_id="run-1",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch.object(mailatlas_cli.MailAtlas, "receive", return_value=result) as receive_mock:
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(
                        [
                            "receive",
                            "watch",
                            "--root",
                            root.as_posix(),
                            "--gmail-access-token",
                            "one-off-token",
                            "--max-runs",
                            "1",
                        ]
                    )

        lines = stdout.getvalue().splitlines()
        payload = json.loads(lines[0])
        config_arg = receive_mock.call_args.args[0]

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(config_arg.gmail_access_token, "one-off-token")

    def test_cli_receive_watch_supports_imap_provider(self) -> None:
        result = ReceiveResult(
            status="ok",
            provider="imap",
            account_id="imap:user@example.com:imap.example.com:INBOX",
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=0,
            document_ids=(),
            cursor={"folders": []},
            run_id="run-1",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            with mock.patch.object(mailatlas_cli.MailAtlas, "receive", return_value=result) as receive_mock:
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(
                        [
                            "receive",
                            "watch",
                            "--root",
                            root.as_posix(),
                            "--provider",
                            "imap",
                            "--host",
                            "imap.example.com",
                            "--username",
                            "user@example.com",
                            "--password",
                            "app-password",
                            "--folder",
                            "INBOX",
                            "--max-runs",
                            "1",
                        ]
                    )

        lines = stdout.getvalue().splitlines()
        payload = json.loads(lines[0])
        config_arg = receive_mock.call_args.args[0]

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["provider"], "imap")
        self.assertEqual(config_arg.provider, "imap")
        self.assertEqual(config_arg.imap_host, "imap.example.com")
        self.assertEqual(config_arg.imap_folders, ("INBOX",))

    def test_cli_auth_status_and_logout_do_not_print_gmail_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "gmail-token.json"
            FileTokenStore(token_path).save(
                {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "client_id": "client-123",
                    "expires_at": 1893456000,
                    "scope": "https://www.googleapis.com/auth/gmail.send",
                    "email": "sender@gmail.com",
                }
            )

            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                status_code = mailatlas_cli.main(["auth", "status", "gmail", "--token-file", token_path.as_posix()])

            status_output = stdout.getvalue()
            status_payload = json.loads(status_output)

            with mock.patch("sys.stdout", new_callable=io.StringIO) as logout_stdout:
                logout_code = mailatlas_cli.main(["auth", "logout", "gmail", "--token-file", token_path.as_posix()])

            logout_payload = json.loads(logout_stdout.getvalue())

            self.assertEqual(status_code, 0)
            self.assertEqual(status_payload["status"], "configured")
            self.assertEqual(status_payload["email"], "sender@gmail.com")
            self.assertIn("https://www.googleapis.com/auth/gmail.send", status_payload["scopes"])
            self.assertNotIn("access-secret", status_output)
            self.assertNotIn("refresh-secret", status_output)
            self.assertEqual(logout_code, 0)
            self.assertEqual(logout_payload["status"], "removed")
            self.assertFalse(token_path.exists())

    def test_cli_auth_gmail_runs_explicit_flow_without_printing_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "gmail-token.json"
            fake_result = GmailAuthResult(
                status="ok",
                store_path=token_path.as_posix(),
                store_type="file",
                email="sender@gmail.com",
                scopes=("https://www.googleapis.com/auth/gmail.send",),
                expires_at=1893456000,
            )

            with mock.patch("mailatlas.cli.run_gmail_auth_flow", return_value=fake_result) as auth_mock:
                with mock.patch.dict(os.environ, {}, clear=True):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        exit_code = mailatlas_cli.main(
                            [
                                "auth",
                                "gmail",
                                "--client-id",
                                "client-123",
                                "--client-secret",
                                "client-secret",
                                "--email",
                                "sender@gmail.com",
                                "--token-file",
                                token_path.as_posix(),
                                "--no-browser",
                            ]
                        )

            output = stdout.getvalue()
            config_arg = auth_mock.call_args.args[0]

            self.assertEqual(exit_code, 0)
            self.assertEqual(config_arg.client_id, "client-123")
            self.assertEqual(config_arg.client_secret, "client-secret")
            self.assertEqual(config_arg.email, "sender@gmail.com")
            self.assertFalse(auth_mock.call_args.kwargs["open_browser"])
            self.assertEqual(json.loads(output)["status"], "ok")
            self.assertNotIn("client-secret", output)

    def test_cli_auth_gmail_capability_receive_requests_readonly_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "gmail-token.json"
            fake_result = GmailAuthResult(
                status="ok",
                store_path=token_path.as_posix(),
                store_type="file",
                email="receiver@gmail.com",
                scopes=(GMAIL_READONLY_SCOPE,),
                expires_at=1893456000,
                capabilities=("receive",),
            )

            with mock.patch("mailatlas.cli.run_gmail_auth_flow", return_value=fake_result) as auth_mock:
                with mock.patch.dict(os.environ, {}, clear=True):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        exit_code = mailatlas_cli.main(
                            [
                                "auth",
                                "gmail",
                                "--client-id",
                                "client-123",
                                "--email",
                                "receiver@gmail.com",
                                "--capability",
                                "receive",
                                "--token-file",
                                token_path.as_posix(),
                                "--no-browser",
                            ]
                        )

            config_arg = auth_mock.call_args.args[0]
            payload = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(config_arg.scopes, (GMAIL_READONLY_SCOPE,))
            self.assertEqual(payload["capabilities"], ["receive"])
            self.assertEqual(payload["scopes"], [GMAIL_READONLY_SCOPE])

    def test_cli_ingest_auto_detects_inputs_and_reports_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "plain.eml"
            archive_path = root / "mailbox.mbox"
            storage_root = root / "mailatlas-root"
            _write_message(eml_path, _plain_message())

            archive = mailbox.mbox(archive_path)
            archive.lock()
            try:
                archive_message = _plain_message("Archive One")
                archive_message.replace_header("Message-ID", "<archive-1@example.com>")
                archive.add(archive_message)
                archive.flush()
            finally:
                archive.unlock()
                archive.close()

            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = mailatlas_cli.main(["ingest", "--root", storage_root.as_posix(), eml_path.as_posix(), archive_path.as_posix()])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["ingested_count"], 2)
            self.assertEqual(payload["duplicate_count"], 0)
            self.assertEqual(len(payload["document_refs"]), 2)

    def test_cli_get_outputs_json_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "plain.eml"
            storage_root = root / "mailatlas-root"
            _write_message(eml_path, _plain_message())

            atlas = MailAtlas(db_path=storage_root / "store.db", workspace_path=storage_root)
            refs = atlas.ingest_eml([eml_path])

            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = mailatlas_cli.main(["get", "--root", storage_root.as_posix(), refs[0].id])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["id"], refs[0].id)
            self.assertEqual(payload["subject"], "Plain Subject")

    def test_cli_doctor_can_skip_pdf_check(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = mailatlas_cli.main(["doctor", "--skip-pdf"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pdf"]["status"], "skipped")
        self.assertTrue(payload["checks"]["export_json"])

    def test_cli_doctor_warns_when_pdf_is_unavailable(self) -> None:
        with mock.patch("mailatlas.cli.find_pdf_browser", side_effect=RuntimeError("No browser available")):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = mailatlas_cli.main(["doctor"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "warn")
        self.assertEqual(payload["pdf"]["status"], "unavailable")
        self.assertFalse(payload["checks"]["export_pdf"])

    def test_cli_doctor_requires_pdf_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            browser_path = Path(temp_dir) / "fake-browser.sh"
            _write_fake_pdf_browser(browser_path)

            previous_browser = os.environ.get("MAILATLAS_PDF_BROWSER")
            os.environ["MAILATLAS_PDF_BROWSER"] = browser_path.as_posix()
            try:
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(["doctor", "--require-pdf"])
            finally:
                if previous_browser is None:
                    os.environ.pop("MAILATLAS_PDF_BROWSER", None)
                else:
                    os.environ["MAILATLAS_PDF_BROWSER"] = previous_browser

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pdf"]["status"], "ok")
        self.assertTrue(payload["checks"]["export_pdf"])

    def test_resolve_root_uses_env_before_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            (project_root / "pyproject.toml").write_text(
                "[tool.mailatlas]\nroot = \".mailatlas-from-config\"\n",
                encoding="utf-8",
            )
            env_root = project_root / "env-root"
            current_dir = Path.cwd()
            try:
                os.chdir(project_root)
                with mock.patch.dict(os.environ, {"MAILATLAS_HOME": env_root.as_posix()}, clear=False):
                    resolved = mailatlas_cli._resolve_root(None)
            finally:
                os.chdir(current_dir)

            self.assertEqual(resolved, env_root.resolve())

    def test_export_json_is_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "plain.eml"
            _write_message(eml_path, _plain_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            exported = json.loads(atlas.export_document(refs[0].id, format="json"))

            self.assertEqual(exported["id"], refs[0].id)
            self.assertIn("metadata", exported)
            self.assertIn("raw_path", exported)

    def test_export_pdf_uses_browser_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline.eml"
            browser_path = root / "fake-browser.sh"
            _write_message(eml_path, _html_inline_message())
            _write_fake_pdf_browser(browser_path)

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])

            previous_browser = os.environ.get("MAILATLAS_PDF_BROWSER")
            os.environ["MAILATLAS_PDF_BROWSER"] = browser_path.as_posix()
            try:
                pdf_path = Path(atlas.export_document(refs[0].id, format="pdf"))
            finally:
                if previous_browser is None:
                    os.environ.pop("MAILATLAS_PDF_BROWSER", None)
                else:
                    os.environ["MAILATLAS_PDF_BROWSER"] = previous_browser

            self.assertTrue(pdf_path.exists())
            self.assertEqual(pdf_path.suffix, ".pdf")
            self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-1.4"))

    def test_export_pdf_falls_back_from_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "plain.eml"
            browser_path = root / "fake-browser.sh"
            _write_message(eml_path, _plain_message())
            _write_fake_pdf_browser(browser_path)

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])

            previous_browser = os.environ.get("MAILATLAS_PDF_BROWSER")
            os.environ["MAILATLAS_PDF_BROWSER"] = browser_path.as_posix()
            try:
                pdf_path = Path(atlas.export_document(refs[0].id, format="pdf"))
            finally:
                if previous_browser is None:
                    os.environ.pop("MAILATLAS_PDF_BROWSER", None)
                else:
                    os.environ["MAILATLAS_PDF_BROWSER"] = previous_browser

            self.assertTrue(pdf_path.exists())
            self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-1.4"))

    def test_export_html_rewrites_asset_paths_for_out_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline.eml"
            export_path = root / "exports" / "document.html"
            _write_message(eml_path, _html_inline_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            export_path.parent.mkdir(parents=True, exist_ok=True)

            html_path = Path(atlas.export_document(refs[0].id, format="html", out_path=export_path))
            html_content = html_path.read_text(encoding="utf-8")

            self.assertEqual(html_path, export_path.resolve())
            self.assertIn("../workspace/assets/", html_content)
            self.assertNotIn("../assets/", html_content)

    def test_pdf_renderer_uses_virtual_time_budget(self) -> None:
        class FakeCompletedProcess:
            def __init__(self, destination: Path):
                self.stdout = ""
                self.stderr = ""
                destination.write_bytes(b"%PDF-1.4\n% fake render\n")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html_path = root / "inline.html"
            pdf_path = root / "inline.pdf"
            html_path.write_text("<html><body><img src='chart.svg'></body></html>", encoding="utf-8")
            captured: dict[str, list[str]] = {}

            def fake_run(command, stdout=None, stderr=None, text=None, timeout=None):
                captured["command"] = command
                return FakeCompletedProcess(pdf_path)

            with mock.patch.object(pdf_module, "find_pdf_browser", return_value=Path("/fake/chrome")):
                with mock.patch.object(pdf_module.subprocess, "run", side_effect=fake_run):
                    rendered = pdf_module.render_pdf_from_html(html_path, pdf_path)

            self.assertEqual(rendered, pdf_path.resolve())
            self.assertIn("--virtual-time-budget=3000", captured["command"])
            self.assertTrue(pdf_path.exists())

    def test_boilerplate_lines_are_removed_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "boilerplate.eml"
            message = EmailMessage()
            message["Subject"] = "CTA test"
            message["From"] = "CTA Example <cta@example.com>"
            message["To"] = "team@example.com"
            message["Date"] = "Mon, 04 Mar 2024 11:00:00 +0000"
            message["Message-ID"] = "<cta-1@example.com>"
            message.set_content(
                "Main paragraph.\n\n"
                "READ IN APP\n"
                "<https://example.com/app>\n"
                "Keep reading with a 7-day free trial\n"
                "Unsubscribe\n"
                "Footer line."
            )
            _write_message(eml_path, message)

            parsed = parse_eml(eml_path)

            self.assertIn("Main paragraph.", parsed.body_text)
            self.assertNotIn("READ IN APP", parsed.body_text)
            self.assertNotIn("Keep reading", parsed.body_text)
            self.assertNotIn("Unsubscribe", parsed.body_text)

    def test_parser_config_can_disable_documented_cleaning_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "cleaning.eml"
            message = EmailMessage()
            message["Subject"] = "Cleaning controls"
            message["From"] = "Cleaner Example <cleaner@example.com>"
            message["To"] = "team@example.com"
            message["Date"] = "Tue, 05 Mar 2024 11:00:00 +0000"
            message["Message-ID"] = "<cleaning-1@example.com>"
            message.set_content(
                "Lead\u200b   line\n\n\n"
                "<https://example.com/only-link>\n"
                "Body before footer\n"
                "Unsubscribe\n"
                "Footer remains."
            )
            _write_message(eml_path, message)

            default = parse_eml(eml_path)
            uncleaned = parse_eml(
                eml_path,
                parser_config=ParserConfig(
                    strip_forwarded_headers=False,
                    strip_boilerplate=False,
                    strip_link_only_lines=False,
                    stop_at_footer=False,
                    strip_invisible_chars=False,
                    normalize_whitespace=False,
                ),
            )

            self.assertIn("Lead line", default.body_text)
            self.assertNotIn("\u200b", default.body_text)
            self.assertNotIn("<https://example.com/only-link>", default.body_text)
            self.assertNotIn("Unsubscribe", default.body_text)
            self.assertNotIn("Footer remains.", default.body_text)
            self.assertNotIn("\n\n\n", default.body_text)

            self.assertIn("Lead\u200b   line", uncleaned.body_text)
            self.assertIn("<https://example.com/only-link>", uncleaned.body_text)
            self.assertIn("Unsubscribe", uncleaned.body_text)
            self.assertIn("Footer remains.", uncleaned.body_text)
            self.assertIn("\n\n\n", uncleaned.body_text)

    def test_export_markdown_renders_inline_images_from_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline.eml"
            _write_message(eml_path, _html_inline_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            markdown = atlas.export_document(refs[0].id, format="markdown")

            self.assertIn("# Inline HTML", markdown)
            self.assertIn("Hello HTML world.", markdown)
            self.assertIn("![chart.svg](", markdown)
            self.assertIn((atlas.workspace_path / "assets").as_posix(), markdown)
            self.assertNotIn("Fallback body", markdown)
            self.assertNotIn("## Assets", markdown)

    def test_export_markdown_lists_non_image_attachments_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline-attachment.eml"
            _write_message(eml_path, _html_inline_attachment_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            markdown = atlas.export_document(refs[0].id, format="markdown")

            self.assertIn("![chart.svg](", markdown)
            self.assertIn("## Attachments", markdown)
            self.assertIn("[port-dwell.csv](", markdown)
            self.assertIn("(text/csv)", markdown)

    def test_export_markdown_fallback_lists_images_and_attachments_without_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "plain-attachments.eml"
            _write_message(eml_path, _plain_message_with_attachments())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            markdown = atlas.export_document(refs[0].id, format="markdown")

            self.assertIn("First paragraph.", markdown)
            self.assertIn("## Images", markdown)
            self.assertIn("![chart.svg](", markdown)
            self.assertIn("## Attachments", markdown)
            self.assertIn("[port-dwell.csv](", markdown)

    def test_export_markdown_bundle_writes_document_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline-attachment.eml"
            bundle_dir = root / "bundle"
            _write_message(eml_path, _html_inline_attachment_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            markdown_path = Path(atlas.export_document(refs[0].id, format="markdown", out_path=bundle_dir))
            markdown = markdown_path.read_text(encoding="utf-8")

            self.assertEqual(markdown_path, (bundle_dir / "document.md").resolve())
            self.assertIn("![chart.svg](assets/001-chart.svg)", markdown)
            self.assertIn("[port-dwell.csv](assets/002-port-dwell.csv)", markdown)
            self.assertTrue((bundle_dir / "assets" / "001-chart.svg").exists())
            self.assertTrue((bundle_dir / "assets" / "002-port-dwell.csv").exists())

    def test_export_markdown_stdout_uses_absolute_asset_paths_without_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline-attachment.eml"
            _write_message(eml_path, _html_inline_attachment_message())

            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])
            markdown = atlas.export_document(refs[0].id, format="markdown")

            self.assertIn((atlas.workspace_path / "assets").as_posix(), markdown)
            self.assertEqual(list((atlas.workspace_path / "exports").iterdir()), [])

    def test_resolve_root_reads_dot_mailatlas_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            (project_root / ".mailatlas.toml").write_text('root = "configured-root"\n', encoding="utf-8")
            current_dir = Path.cwd()
            try:
                os.chdir(project_root)
                with mock.patch.dict(os.environ, {}, clear=True):
                    resolved = mailatlas_cli._resolve_root(None)
            finally:
                os.chdir(current_dir)

            self.assertEqual(resolved, (project_root / "configured-root").resolve())

    def test_cli_get_pdf_without_out_writes_default_export_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "inline.eml"
            browser_path = root / "fake-browser.sh"
            storage_root = root / "mailatlas-root"
            _write_message(eml_path, _html_inline_message())
            _write_fake_pdf_browser(browser_path)

            atlas = MailAtlas(db_path=storage_root / "store.db", workspace_path=storage_root)
            refs = atlas.ingest_eml([eml_path])

            with mock.patch.dict(os.environ, {"MAILATLAS_PDF_BROWSER": browser_path.as_posix()}, clear=False):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    exit_code = mailatlas_cli.main(["get", "--root", storage_root.as_posix(), refs[0].id, "--format", "pdf"])

            rendered_path = Path(stdout.getvalue().strip())
            self.assertEqual(exit_code, 0)
            self.assertEqual(rendered_path, (storage_root / "exports" / f"{refs[0].id}.pdf").resolve())
            self.assertTrue(rendered_path.exists())
            self.assertTrue(rendered_path.read_bytes().startswith(b"%PDF-1.4"))

    def test_documented_cli_quickstart_flow_works_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            storage_root = project_root / ".mailatlas"
            browser_path = project_root / "fake-browser.sh"
            fixtures = Path(__file__).resolve().parent / "fixtures"
            _write_fake_pdf_browser(browser_path)

            fixture_paths = [
                fixtures / "atlas-market-map.eml",
                fixtures / "atlas-founder-forward.eml",
                fixtures / "atlas-inline-chart.eml",
            ]

            with mock.patch.dict(
                os.environ,
                {
                    "MAILATLAS_HOME": storage_root.as_posix(),
                    "MAILATLAS_PDF_BROWSER": browser_path.as_posix(),
                },
                clear=False,
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    ingest_code = mailatlas_cli.main(["ingest", *(path.as_posix() for path in fixture_paths)])
                ingest_payload = json.loads(stdout.getvalue())

                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    list_code = mailatlas_cli.main(["list"])
                listed_refs = json.loads(stdout.getvalue())

                inline_ref = next(ref for ref in ingest_payload["document_refs"] if ref["subject"] == "Port dwell times normalize after weather disruptions")

                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    get_code = mailatlas_cli.main(["get", inline_ref["id"]])
                stored_document = json.loads(stdout.getvalue())

                json_export_path = project_root / "port-dwell.json"
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    json_code = mailatlas_cli.main(["get", inline_ref["id"], "--format", "json", "--out", json_export_path.as_posix()])
                written_json_path = Path(stdout.getvalue().strip())

                markdown_export_dir = project_root / "port-dwell-markdown"
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    markdown_code = mailatlas_cli.main(
                        ["get", inline_ref["id"], "--format", "markdown", "--out", markdown_export_dir.as_posix()]
                    )
                written_markdown_path = Path(stdout.getvalue().strip())

                pdf_export_path = project_root / "port-dwell.pdf"
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    pdf_code = mailatlas_cli.main(["get", inline_ref["id"], "--format", "pdf", "--out", pdf_export_path.as_posix()])
                written_pdf_path = Path(stdout.getvalue().strip())

            self.assertEqual(ingest_code, 0)
            self.assertEqual(ingest_payload["status"], "ok")
            self.assertEqual(ingest_payload["ingested_count"], 3)
            self.assertEqual(ingest_payload["duplicate_count"], 0)
            self.assertEqual(len(listed_refs), 3)
            self.assertEqual(list_code, 0)
            self.assertEqual(get_code, 0)
            self.assertEqual(stored_document["id"], inline_ref["id"])
            self.assertEqual(stored_document["body_html_path"].split("/", 1)[0], "html")
            self.assertEqual(stored_document["raw_path"].split("/", 1)[0], "raw")
            self.assertEqual(stored_document["assets"][0]["kind"], "inline")
            self.assertEqual(stored_document["assets"][0]["file_path"].split("/", 1)[0], "assets")
            self.assertEqual(json_code, 0)
            self.assertEqual(written_json_path, json_export_path.resolve())
            self.assertEqual(json.loads(json_export_path.read_text(encoding="utf-8"))["id"], inline_ref["id"])
            self.assertEqual(markdown_code, 0)
            self.assertEqual(written_markdown_path, (markdown_export_dir / "document.md").resolve())
            self.assertIn("assets/001-route-heatmap.svg", written_markdown_path.read_text(encoding="utf-8"))
            self.assertTrue((markdown_export_dir / "assets" / "001-route-heatmap.svg").exists())
            self.assertEqual(pdf_code, 0)
            self.assertEqual(written_pdf_path, pdf_export_path.resolve())
            self.assertTrue(pdf_export_path.read_bytes().startswith(b"%PDF-1.4"))

            self.assertTrue((storage_root / "store.db").exists())
            self.assertTrue((storage_root / "raw").exists())
            self.assertTrue((storage_root / "html").exists())
            self.assertTrue((storage_root / "assets").exists())
            self.assertTrue((storage_root / "exports").exists())

    def test_cli_receive_imap_with_access_token_does_not_persist_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"
            connection = FakeImapConnection(
                {
                    "INBOX": {
                        "uidvalidity": 777,
                        "messages": {
                            4: _imap_message_bytes("Token Auth", "<imap-token@example.com>"),
                        },
                    }
                }
            )

            with mock.patch("mailatlas.adapters.imap.imaplib.IMAP4_SSL", return_value=connection):
                with mock.patch.dict(
                    os.environ,
                    {
                        "MAILATLAS_IMAP_HOST": "imap.example.com",
                        "MAILATLAS_IMAP_USERNAME": "oauth-user@example.com",
                        "MAILATLAS_IMAP_ACCESS_TOKEN": "access-token",
                    },
                    clear=False,
                ):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        exit_code = mailatlas_cli.main(["receive", "--root", root.as_posix(), "--provider", "imap"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["provider"], "imap")
            self.assertEqual(payload["details"]["auth"], "xoauth2")
            self.assertEqual(connection.login_calls, [])
            self.assertEqual(connection.authenticate_calls[0][0], "XOAUTH2")

            with sqlite3.connect(root / "store.db") as connection_db:
                schema_columns = {
                    row[1]
                    for row in connection_db.execute("PRAGMA table_info(imap_sync_state)").fetchall()
                }
                state_row = connection_db.execute(
                    "SELECT host, port, username, folder, uidvalidity, last_uid, status, error FROM imap_sync_state"
                ).fetchone()

            self.assertNotIn("password", schema_columns)
            self.assertNotIn("access_token", schema_columns)
            self.assertEqual(state_row, ("imap.example.com", 993, "oauth-user@example.com", "INBOX", "777", 4, "ok", None))

    def test_cli_receive_imap_rejects_missing_or_conflicting_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mailatlas-root"

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    missing_code = mailatlas_cli.main(
                        [
                            "receive",
                            "--root",
                            root.as_posix(),
                            "--provider",
                            "imap",
                            "--host",
                            "imap.example.com",
                            "--username",
                            "user@example.com",
                        ]
                    )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(missing_code, 1)
            self.assertEqual(payload["status"], "not_configured")
            self.assertIn("IMAP password is required for password auth.", payload["error"])

            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                conflicting_code = mailatlas_cli.main(
                    [
                        "receive",
                        "--root",
                        root.as_posix(),
                        "--provider",
                        "imap",
                        "--host",
                        "imap.example.com",
                        "--username",
                        "user@example.com",
                        "--password",
                        "secret",
                        "--access-token",
                        "token",
                    ]
                )
            self.assertEqual(conflicting_code, 1)
            self.assertIn("Choose either IMAP password auth or IMAP access-token auth, not both.", stderr.getvalue())

    def test_public_synthetic_fixtures_support_launch_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = Path(__file__).resolve().parent / "fixtures"
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")

            refs = atlas.ingest_eml(
                [
                    fixtures / "atlas-market-map.eml",
                    fixtures / "atlas-founder-forward.eml",
                    fixtures / "atlas-inline-chart.eml",
                ]
            )

            self.assertEqual(len(refs), 3)
            inline_doc = json.loads(atlas.export_document(refs[2].id, format="json"))
            self.assertEqual(inline_doc["subject"], "Port dwell times normalize after weather disruptions")
            self.assertEqual(len(inline_doc["assets"]), 1)
            inline_html = atlas.export_document(refs[2].id, format="html")
            self.assertIn("route-heatmap.svg", inline_html)
            inline_asset_path = atlas.workspace_path / inline_doc["assets"][0]["file_path"]
            self.assertIn("<svg", inline_asset_path.read_text(encoding="utf-8"))

            archive_refs = atlas.ingest_mbox(fixtures / "atlas-demo.mbox")
            self.assertEqual(len(archive_refs), 2)


if __name__ == "__main__":
    unittest.main()
