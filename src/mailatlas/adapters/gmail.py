from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any

from mailatlas.core.models import OutboundMessage, SendConfig
from mailatlas.core.outbound import build_outbound_mime

from .outbound import ProviderSendResult


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


def _metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = {"gmail_response": payload}
    thread_id = payload.get("threadId")
    label_ids = payload.get("labelIds")
    if thread_id:
        metadata["gmail_thread_id"] = thread_id
    if label_ids:
        metadata["gmail_label_ids"] = label_ids
    return metadata


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

    api_base = config.gmail_api_base or "https://gmail.googleapis.com/gmail/v1"
    user_id = urllib.parse.quote(config.gmail_user_id or "me", safe="")
    endpoint = f"{api_base}/users/{user_id}/messages/send"
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
