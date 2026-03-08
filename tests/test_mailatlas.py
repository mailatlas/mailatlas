from __future__ import annotations

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

from mailatlas.ai import generate_brief
from mailatlas.core import MailAtlas, ParserConfig, parse_eml
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
