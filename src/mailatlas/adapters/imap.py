from __future__ import annotations

import imaplib

from mailatlas.core.models import _ImapReceiveConfig


class ImapReceiveError(RuntimeError):
    pass


def _quote_mailbox(mailbox: str) -> str:
    escaped = mailbox.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _ensure_ok(response_type: str, data: list[bytes] | list[object] | None, action: str) -> list[bytes] | list[object]:
    if response_type == "OK":
        return data or []

    details: list[str] = []
    for item in data or []:
        if isinstance(item, tuple):
            for nested in item:
                if isinstance(nested, bytes):
                    details.append(_decode_bytes(nested))
        elif isinstance(item, bytes):
            details.append(_decode_bytes(item))
        elif item is not None:
            details.append(str(item))

    suffix = f": {' | '.join(details)}" if details else ""
    raise ImapReceiveError(f"IMAP {action} failed{suffix}")


def _xoauth2_payload(username: str, access_token: str) -> bytes:
    return f"user={username}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")


class ImapSession:
    def __init__(self, connection: imaplib.IMAP4_SSL):
        self._connection = connection

    def __enter__(self) -> "ImapSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def select_folder(self, folder: str) -> str:
        try:
            response_type, data = self._connection.select(_quote_mailbox(folder), readonly=True)
            _ensure_ok(response_type, data, f"select mailbox {folder}")
            _, uidvalidity_response = self._connection.response("UIDVALIDITY")
        except (imaplib.IMAP4.error, OSError) as error:
            raise ImapReceiveError(str(error)) from error

        uidvalidity = ""
        for item in uidvalidity_response or []:
            if isinstance(item, bytes):
                uidvalidity = _decode_bytes(item).strip()
                break
        if not uidvalidity:
            raise ImapReceiveError(f"IMAP mailbox {folder} did not report UIDVALIDITY")
        return uidvalidity

    def list_uids(self) -> list[int]:
        try:
            response_type, data = self._connection.uid("SEARCH", None, "ALL")
        except (imaplib.IMAP4.error, OSError) as error:
            raise ImapReceiveError(str(error)) from error

        payload = _ensure_ok(response_type, data, "search")
        if not payload or not payload[0]:
            return []
        return [int(value) for value in _decode_bytes(payload[0]).split() if value]

    def fetch_message(self, uid: int) -> bytes:
        try:
            response_type, data = self._connection.uid("FETCH", str(uid), "(RFC822)")
        except (imaplib.IMAP4.error, OSError) as error:
            raise ImapReceiveError(str(error)) from error

        payload = _ensure_ok(response_type, data, f"fetch UID {uid}")
        for item in payload:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        raise ImapReceiveError(f"IMAP fetch for UID {uid} returned no RFC822 bytes")

    def close(self) -> None:
        try:
            self._connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def open_imap_session(config: _ImapReceiveConfig) -> ImapSession:
    connection: imaplib.IMAP4_SSL | None = None
    try:
        connection = imaplib.IMAP4_SSL(config.host, config.port)
        if config.auth == "password":
            connection.login(config.username, config.password or "")
        else:
            connection.authenticate("XOAUTH2", lambda _: _xoauth2_payload(config.username, config.access_token or ""))
    except (imaplib.IMAP4.error, OSError) as error:
        if connection is not None:
            try:
                connection.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        raise ImapReceiveError(str(error)) from error

    return ImapSession(connection)
