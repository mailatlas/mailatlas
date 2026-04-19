from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from mailatlas.core.models import OutboundMessage, ReceiveConfig, SendConfig
from mailatlas.core.outbound import build_outbound_mime

from .outbound import ProviderSendResult


GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


@dataclass(frozen=True)
class GmailMessageCandidate:
    id: str
    thread_id: str | None = None


@dataclass(frozen=True)
class GmailReceivedMessage:
    id: str
    thread_id: str | None
    label_ids: tuple[str, ...]
    history_id: str | None
    internal_date: str | None
    raw_bytes: bytes


class GmailReceiveError(RuntimeError):
    def __init__(self, message: str, *, status: str = "error"):
        super().__init__(message)
        self.status = status


def _gmail_error(payload: Any, fallback: str = "Gmail API send failed.") -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            status = error.get("status")
            code = error.get("code")
            if message:
                prefix = f"{code} {status}: " if code is not None and status else ""
                return f"{prefix}{message}"
        if isinstance(error, str):
            return error
    return fallback


def _gmail_api_error(payload: Any, fallback: str = "Gmail API receive failed.") -> str:
    return _gmail_error(payload, fallback=fallback)


def _metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = {"gmail_response": payload}
    thread_id = payload.get("threadId")
    label_ids = payload.get("labelIds")
    if thread_id:
        metadata["gmail_thread_id"] = thread_id
    if label_ids:
        metadata["gmail_label_ids"] = label_ids
    return metadata


def _api_base(config: ReceiveConfig | SendConfig) -> str:
    return (config.gmail_api_base or GMAIL_API_BASE).rstrip("/")


def _user_id(config: ReceiveConfig | SendConfig) -> str:
    return urllib.parse.quote(config.gmail_user_id or "me", safe="")


def _gmail_get_json(access_token: str, url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            payload = json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            payload = {"error": {"message": response_body or str(error), "code": error.code}}
        message = _gmail_api_error(payload)
        if error.code == 404:
            raise GmailReceiveError(message, status="cursor_reset_required") from error
        raise GmailReceiveError(message) from error
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise GmailReceiveError(str(error)) from error

    if not isinstance(payload, dict):
        raise GmailReceiveError("Gmail API response was not a JSON object.")
    return payload


def _gmail_url(config: ReceiveConfig, path: str, params: dict[str, str | int | bool | None] | None = None) -> str:
    query_params = {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in (params or {}).items()
        if value is not None
    }
    query = urllib.parse.urlencode(query_params)
    base_url = f"{_api_base(config)}/users/{_user_id(config)}/{path.lstrip('/')}"
    return f"{base_url}?{query}" if query else base_url


def get_gmail_profile(config: ReceiveConfig, access_token: str) -> dict[str, str | None]:
    payload = _gmail_get_json(access_token, _gmail_url(config, "profile"))
    return {
        "email": str(payload["emailAddress"]) if payload.get("emailAddress") else None,
        "history_id": str(payload["historyId"]) if payload.get("historyId") else None,
    }


def _message_candidates_from_list(payload: dict[str, Any]) -> list[GmailMessageCandidate]:
    candidates: list[GmailMessageCandidate] = []
    for item in payload.get("messages") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        candidates.append(
            GmailMessageCandidate(
                id=str(item["id"]),
                thread_id=str(item["threadId"]) if item.get("threadId") else None,
            )
        )
    return candidates


def _message_candidates_from_history(payload: dict[str, Any]) -> list[GmailMessageCandidate]:
    candidates: list[GmailMessageCandidate] = []
    for history in payload.get("history") or []:
        if not isinstance(history, dict):
            continue
        for added in history.get("messagesAdded") or []:
            if not isinstance(added, dict):
                continue
            message = added.get("message")
            if not isinstance(message, dict) or not message.get("id"):
                continue
            candidates.append(
                GmailMessageCandidate(
                    id=str(message["id"]),
                    thread_id=str(message["threadId"]) if message.get("threadId") else None,
                )
            )
    return candidates


def list_gmail_message_candidates(
    config: ReceiveConfig,
    access_token: str,
    *,
    cursor: dict[str, object] | None = None,
) -> list[GmailMessageCandidate]:
    history_id = str(cursor["history_id"]) if cursor and cursor.get("history_id") else None
    use_history = bool(history_id and not config.full_sync and not config.gmail_query)
    candidates: list[GmailMessageCandidate] = []
    seen_ids: set[str] = set()
    page_token: str | None = None

    while len(candidates) < config.limit:
        page_size = min(500, config.limit - len(candidates))
        if use_history:
            params: dict[str, str | int | bool | None] = {
                "startHistoryId": history_id,
                "historyTypes": "messageAdded",
                "maxResults": page_size,
                "pageToken": page_token,
                "labelId": config.gmail_label or None,
            }
            payload = _gmail_get_json(access_token, _gmail_url(config, "history", params))
            page_candidates = _message_candidates_from_history(payload)
        else:
            params = {
                "maxResults": page_size,
                "pageToken": page_token,
                "includeSpamTrash": config.gmail_include_spam_trash,
                "labelIds": config.gmail_label or None,
                "q": config.gmail_query,
            }
            payload = _gmail_get_json(access_token, _gmail_url(config, "messages", params))
            page_candidates = _message_candidates_from_list(payload)

        for candidate in page_candidates:
            if candidate.id in seen_ids:
                continue
            candidates.append(candidate)
            seen_ids.add(candidate.id)
            if len(candidates) >= config.limit:
                break

        page_token = str(payload["nextPageToken"]) if payload.get("nextPageToken") else None
        if not page_token:
            break

    return candidates


def _decode_gmail_raw(raw_value: str) -> bytes:
    padding = "=" * (-len(raw_value) % 4)
    try:
        return base64.urlsafe_b64decode(raw_value + padding)
    except (TypeError, ValueError) as error:
        raise GmailReceiveError("Gmail message raw payload was not valid base64url.") from error


def fetch_gmail_message(config: ReceiveConfig, access_token: str, message_id: str) -> GmailReceivedMessage:
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    payload = _gmail_get_json(access_token, _gmail_url(config, f"messages/{encoded_message_id}", {"format": "raw"}))
    raw_value = payload.get("raw")
    if not isinstance(raw_value, str) or not raw_value:
        raise GmailReceiveError(f"Gmail message {message_id} did not include a raw RFC 2822 payload.")

    label_ids = payload.get("labelIds")
    return GmailReceivedMessage(
        id=str(payload.get("id") or message_id),
        thread_id=str(payload["threadId"]) if payload.get("threadId") else None,
        label_ids=tuple(str(label_id) for label_id in label_ids) if isinstance(label_ids, list) else (),
        history_id=str(payload["historyId"]) if payload.get("historyId") else None,
        internal_date=str(payload["internalDate"]) if payload.get("internalDate") else None,
        raw_bytes=_decode_gmail_raw(raw_value),
    )


def gmail_source_uri(config: ReceiveConfig, message_id: str) -> str:
    return f"gmail://{config.gmail_user_id or 'me'}/messages/{message_id}"


def build_gmail_cursor(
    messages: list[GmailReceivedMessage],
    *,
    profile_history_id: str | None = None,
    existing_cursor: dict[str, object] | None = None,
) -> dict[str, object]:
    cursor = dict(existing_cursor or {})

    history_ids = [int(message.history_id) for message in messages if message.history_id and message.history_id.isdigit()]
    if profile_history_id and profile_history_id.isdigit():
        history_ids.append(int(profile_history_id))
    if history_ids:
        cursor["history_id"] = str(max(history_ids))

    internal_dates = [int(message.internal_date) for message in messages if message.internal_date and message.internal_date.isdigit()]
    if internal_dates:
        cursor["last_message_internal_date"] = str(max(internal_dates))

    return cursor


def send_gmail_message(
    message: OutboundMessage,
    mime_message: EmailMessage,
    config: SendConfig,
) -> ProviderSendResult:
    if not config.gmail_access_token:
        return ProviderSendResult(
            status="error",
            error="Gmail access token is required. Run 'mailatlas auth gmail' or set MAILATLAS_GMAIL_ACCESS_TOKEN.",
        )
    provider_mime_message = build_outbound_mime(message, include_bcc=True) if message.bcc else mime_message

    endpoint = f"{_api_base(config)}/users/{_user_id(config)}/messages/send"
    payload = {
        "raw": base64.urlsafe_b64encode(provider_mime_message.as_bytes()).decode("ascii"),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.gmail_access_token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            response_payload = json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            response_payload = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            response_payload = {"error": {"message": response_body or str(error), "code": error.code}}
        return ProviderSendResult(
            status="error",
            metadata={"gmail_response": response_payload, "http_status": error.code},
            error=_gmail_error(response_payload),
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return ProviderSendResult(status="error", error=str(error))

    if not isinstance(response_payload, dict):
        return ProviderSendResult(status="error", error="Gmail API response was not a JSON object.")

    return ProviderSendResult(
        status="sent",
        provider_message_id=str(response_payload["id"]) if response_payload.get("id") else None,
        metadata=_metadata_from_payload(response_payload),
    )
