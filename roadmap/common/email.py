from __future__ import annotations

import base64
from typing import Any

import httpx
from django.conf import settings


def send_email_via_resend(
    *,
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None = None,
    cc_emails: list[str] | None = None,
    attachments: list[dict[str, str]] | None = None,
    timeout_seconds: float = 20.0,
) -> None:
    api_key = getattr(settings, "RESEND_API_KEY", "")
    from_email = getattr(settings, "RESEND_FROM_EMAIL", "")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured.")
    if not from_email:
        raise RuntimeError("RESEND_FROM_EMAIL is not configured.")

    payload: dict[str, Any] = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }
    if text_content:
        payload["text"] = text_content
    if cc_emails:
        payload["cc"] = cc_emails
    if attachments:
        payload["attachments"] = attachments

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()


def build_base64_attachment(*, filename: str, content_bytes: bytes) -> dict[str, str]:
    return {
        "filename": filename,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
    }
