from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from mailatlas.core.models import OutboundMessage, SendConfig
from mailatlas.core.outbound import outbound_envelope_recipients

from .outbound import ProviderSendResult


def send_smtp_message(message: OutboundMessage, mime_message: EmailMessage, config: SendConfig) -> ProviderSendResult:
    if not config.smtp_host:
        return ProviderSendResult(status="error", error="SMTP host is required.")
    if bool(config.smtp_username) != bool(config.smtp_password):
        return ProviderSendResult(status="error", error="SMTP username and password must be provided together.")

    context = ssl.create_default_context()
    envelope_recipients = list(outbound_envelope_recipients(message))
    try:
        if config.smtp_ssl:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30, context=context) as server:
                if config.smtp_username and config.smtp_password:
                    server.login(config.smtp_username, config.smtp_password)
                server.send_message(mime_message, from_addr=message.from_email, to_addrs=envelope_recipients)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as server:
                if config.smtp_starttls:
                    server.starttls(context=context)
                if config.smtp_username and config.smtp_password:
                    server.login(config.smtp_username, config.smtp_password)
                server.send_message(mime_message, from_addr=message.from_email, to_addrs=envelope_recipients)
    except (OSError, smtplib.SMTPException) as error:
        return ProviderSendResult(status="error", error=str(error))

    return ProviderSendResult(
        status="sent",
        provider_message_id=mime_message.get("Message-ID"),
        metadata={"envelope_recipients": envelope_recipients},
    )
