from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mailatlas.core.models import OutboundMessage, SendConfig

from .outbound import ProviderSendResult


def _one_or_many(values: tuple[str, ...]) -> str | list[str] | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return list(values)


def _cloudflare_payload(message: OutboundMessage) -> dict[str, Any]:
    headers = dict(message.headers)
    if message.in_reply_to:
        headers["In-Reply-To"] = message.in_reply_to
    if message.references:
        headers["References"] = " ".join(message.references)

    payload: dict[str, Any] = {
        "to": _one_or_many(message.to),
        "from": {"address": message.from_email, "name": message.from_name} if message.from_name else message.from_email,
        "subject": message.subject,
    }
    if message.text is not None:
        payload["text"] = message.text
    if message.html is not None:
        payload["html"] = message.html
    if message.cc:
        payload["cc"] = _one_or_many(message.cc)
    if message.bcc:
        payload["bcc"] = _one_or_many(message.bcc)
    if message.reply_to:
        payload["reply_to"] = _one_or_many(message.reply_to)
    if headers:
        payload["headers"] = headers
    if message.attachments:
        payload["attachments"] = [
            {
                "content": base64.b64encode(Path(attachment.path).read_bytes()).decode("ascii"),
                "filename": attachment.filename,
                "type": attachment.mime_type,
                "disposition": "attachment",
            }
            for attachment in message.attachments
        ]
    return payload


def _error_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            messages = []
            for error in errors:
                if isinstance(error, dict):
                    code = error.get("code")
                    message = error.get("message") or "Cloudflare API error"
                    messages.append(f"{code}: {message}" if code is not None else str(message))
                else:
                    messages.append(str(error))
            return "; ".join(messages)
    return "Cloudflare send failed."


def _status_from_result(result: Any) -> str:
    if not isinstance(result, dict):
        return "sent"
    delivered = result.get("delivered") or []
    queued = result.get("queued") or []
    permanent_bounces = result.get("permanent_bounces") or []
    if permanent_bounces:
        return "error"
    if queued and not delivered:
        return "queued"
    return "sent"


def _provider_message_id(payload: dict[str, Any]) -> str | None:
    result = payload.get("result")
    if isinstance(result, dict):
        value = result.get("message_id") or result.get("messageId") or result.get("id")
        if value:
            return str(value)
    value = payload.get("message_id") or payload.get("messageId") or payload.get("id")
    return str(value) if value else None


def send_cloudflare_message(message: OutboundMessage, config: SendConfig) -> ProviderSendResult:
    if not config.cloudflare_account_id:
        return ProviderSendResult(status="error", error="Cloudflare account id is required.")
    if not config.cloudflare_api_token:
        return ProviderSendResult(status="error", error="Cloudflare API token is required.")

    api_base = config.cloudflare_api_base or "https://api.cloudflare.com/client/v4"
    endpoint = f"{api_base}/accounts/{config.cloudflare_account_id}/email/sending/send"
    body = json.dumps(_cloudflare_payload(message)).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.cloudflare_api_token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            payload = json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            payload = {"errors": [{"message": response_body or str(error)}]}
        return ProviderSendResult(
            status="error",
            metadata={"cloudflare_response": payload, "http_status": error.code},
            error=_error_from_payload(payload),
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return ProviderSendResult(status="error", error=str(error))

    if not isinstance(payload, dict):
        return ProviderSendResult(status="error", error="Cloudflare response was not a JSON object.")
    if payload.get("success") is False:
        return ProviderSendResult(
            status="error",
            metadata={"cloudflare_response": payload},
            error=_error_from_payload(payload),
        )

    status = _status_from_result(payload.get("result"))
    error = None
    if status == "error":
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        error = f"Cloudflare reported permanent bounces: {', '.join(result.get('permanent_bounces') or [])}"

    return ProviderSendResult(
        status=status,
        provider_message_id=_provider_message_id(payload),
        metadata={"cloudflare_response": payload},
        error=error,
    )
