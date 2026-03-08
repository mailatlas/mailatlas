from __future__ import annotations

import imaplib
import io
import mailbox
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mailatlas.cli as mailatlas_cli
from mailatlas.ai import generate_brief
from mailatlas.core import ImapFolderSyncResult, ImapSyncConfig, ImapSyncResult, MailAtlas, ParserConfig, parse_eml
from mailatlas.core import pdf as pdf_module


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


def _imap_message_bytes(subject: str, message_id: str) -> bytes:
    message = _plain_message(subject)
    message.replace_header("Message-ID", message_id)
    return message.as_bytes()


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

    def test_sync_imap_password_ingests_multiple_folders_and_tracks_duplicates(self) -> None:
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
                result = atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="user@example.com",
                        password="app-password",
                        folders=("INBOX", "Archive"),
                    )
                )

            self.assertEqual(result.status, "ok")
            self.assertEqual(connection.login_calls, [("user@example.com", "app-password")])
            self.assertEqual(len(result.folders), 2)
            self.assertEqual(result.folders[0].ingested_count, 2)
            self.assertEqual(result.folders[1].duplicate_count, 1)
            self.assertEqual(len(atlas.list_documents()), 2)

            exported = json.loads(atlas.export_document(result.folders[0].document_refs[0].id, format="json"))
            self.assertEqual(exported["source_kind"], "imap")
            self.assertEqual(exported["metadata"]["source"]["kind"], "imap")
            self.assertEqual(exported["metadata"]["source"]["host"], "imap.example.com")
            self.assertEqual(exported["metadata"]["source"]["folder"], "INBOX")
            self.assertEqual(exported["metadata"]["source"]["uid"], 1)
            self.assertEqual(exported["metadata"]["source"]["uidvalidity"], "101")
            self.assertTrue(exported["raw_path"].endswith(".eml"))

            inbox_state = atlas.store.get_imap_sync_state("imap.example.com", 993, "user@example.com", "INBOX")
            archive_state = atlas.store.get_imap_sync_state("imap.example.com", 993, "user@example.com", "Archive")
            self.assertEqual(inbox_state.uidvalidity, "101")
            self.assertEqual(inbox_state.last_uid, 2)
            self.assertEqual(archive_state.uidvalidity, "202")
            self.assertEqual(archive_state.last_uid, 8)

    def test_sync_imap_incremental_runs_fetch_only_new_uids(self) -> None:
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
                first = atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="user@example.com",
                        password="app-password",
                    )
                )
                connection.mailboxes["INBOX"]["messages"][3] = _imap_message_bytes("Three", "<imap-3@example.com>")
                second = atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="user@example.com",
                        password="app-password",
                    )
                )

            self.assertEqual(first.folders[0].fetched_count, 2)
            self.assertEqual(second.folders[0].fetched_count, 1)
            self.assertEqual(second.folders[0].ingested_count, 1)
            self.assertEqual(connection.fetch_calls, [("INBOX", 1), ("INBOX", 2), ("INBOX", 3)])
            state = atlas.store.get_imap_sync_state("imap.example.com", 993, "user@example.com", "INBOX")
            self.assertEqual(state.last_uid, 3)

    def test_sync_imap_uidvalidity_reset_rescans_and_dedupes(self) -> None:
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
                atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="user@example.com",
                        password="app-password",
                    )
                )
                connection.mailboxes["INBOX"]["uidvalidity"] = 303
                second = atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="user@example.com",
                        password="app-password",
                    )
                )

            self.assertEqual(second.folders[0].fetched_count, 2)
            self.assertEqual(second.folders[0].duplicate_count, 2)
            self.assertEqual(len(atlas.list_documents()), 2)
            self.assertEqual(connection.fetch_calls[-2:], [("INBOX", 1), ("INBOX", 2)])
            state = atlas.store.get_imap_sync_state("imap.example.com", 993, "user@example.com", "INBOX")
            self.assertEqual(state.uidvalidity, "303")
            self.assertEqual(state.last_uid, 2)

    def test_sync_imap_xoauth2_uses_access_token_authentication(self) -> None:
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
                atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="oauth-user@example.com",
                        auth="xoauth2",
                        access_token="access-token",
                    )
                )

            self.assertEqual(connection.login_calls, [])
            self.assertEqual(connection.authenticate_calls[0][0], "XOAUTH2")
            self.assertIn(b"user=oauth-user@example.com", connection.authenticate_calls[0][1])
            self.assertIn(b"auth=Bearer access-token", connection.authenticate_calls[0][1])

    def test_sync_imap_folder_error_does_not_stop_other_folders(self) -> None:
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
                result = atlas.sync_imap(
                    ImapSyncConfig(
                        host="imap.example.com",
                        username="user@example.com",
                        password="app-password",
                        folders=("INBOX", "Broken"),
                    )
                )

            self.assertTrue(result.has_errors())
            self.assertEqual(result.folders[0].status, "ok")
            self.assertEqual(result.folders[1].status, "error")
            self.assertEqual(len(atlas.list_documents()), 1)
            broken_state = atlas.store.get_imap_sync_state("imap.example.com", 993, "user@example.com", "Broken")
            self.assertEqual(broken_state.status, "error")
            self.assertEqual(broken_state.last_uid, 0)

    def test_cli_sync_imap_uses_env_defaults_and_cli_precedence(self) -> None:
        result = ImapSyncResult(host="imap.example.com", port=993, username="user@example.com", auth="password")

        with mock.patch.object(mailatlas_cli.MailAtlas, "sync_imap", return_value=result) as sync_mock:
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
                    exit_code = mailatlas_cli.main(["sync", "imap", "--db", ".mailatlas/store.db", "--workspace", ".mailatlas/workspace"])
                    env_config = sync_mock.call_args.args[0]

                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    override_code = mailatlas_cli.main(
                        [
                            "sync",
                            "imap",
                            "--db",
                            ".mailatlas/store.db",
                            "--workspace",
                            ".mailatlas/workspace",
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
                    cli_config = sync_mock.call_args.args[0]

        self.assertEqual(exit_code, 0)
        self.assertEqual(env_config.host, "env.example.com")
        self.assertEqual(env_config.port, 1993)
        self.assertEqual(env_config.username, "env-user@example.com")
        self.assertEqual(env_config.password, "env-secret")
        self.assertEqual(env_config.folders, ("INBOX",))
        self.assertEqual(override_code, 0)
        self.assertEqual(cli_config.host, "cli.example.com")
        self.assertEqual(cli_config.username, "cli-user@example.com")
        self.assertEqual(cli_config.password, "cli-secret")
        self.assertEqual(cli_config.folders, ("Inbox/Subfolder",))

    def test_cli_sync_imap_returns_nonzero_when_any_folder_fails(self) -> None:
        result = ImapSyncResult(
            host="imap.example.com",
            port=993,
            username="user@example.com",
            auth="password",
            folders=[
                ImapFolderSyncResult(
                    folder="INBOX",
                    status="error",
                    uidvalidity="101",
                    last_uid=0,
                    fetched_count=0,
                    ingested_count=0,
                    duplicate_count=0,
                    error="cannot select mailbox",
                )
            ],
        )

        with mock.patch.object(mailatlas_cli.MailAtlas, "sync_imap", return_value=result):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                exit_code = mailatlas_cli.main(
                    [
                        "sync",
                        "imap",
                        "--db",
                        ".mailatlas/store.db",
                        "--workspace",
                        ".mailatlas/workspace",
                        "--host",
                        "imap.example.com",
                        "--username",
                        "user@example.com",
                        "--password",
                        "secret",
                    ]
                )

        self.assertEqual(exit_code, 1)

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

    def test_generate_brief_without_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eml_path = root / "plain.eml"
            _write_message(eml_path, _plain_message())
            atlas = MailAtlas(db_path=root / "store.db", workspace_path=root / "workspace")
            refs = atlas.ingest_eml([eml_path])

            output_path = generate_brief(
                document_ids=[refs[0].id],
                db_path=atlas.db_path,
                workspace_path=atlas.workspace_path,
                model_config={"provider": "fallback"},
            )

            self.assertTrue(Path(output_path).exists())
            self.assertIn("Generated Brief", Path(output_path).read_text(encoding="utf-8"))

    def test_public_synthetic_fixtures_support_launch_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = Path(__file__).resolve().parents[1] / "data" / "fixtures"
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
