import base64
from io import BytesIO
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from goal.models import Goal


def build_goal_snapshots(user) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    goals = (
        Goal.objects.filter(user=user)
        .exclude(status__in=["cancelled"])
        .order_by("target_date", "created_at")
    )

    goals_snapshot: list[dict[str, Any]] = []
    deadlines_snapshot: list[dict[str, Any]] = []

    for goal in goals:
        deadline = goal.target_date.isoformat() if goal.target_date else None
        goals_snapshot.append(
            {
                "goal_id": str(goal.id),
                "title": goal.title,
                "description": goal.description,
                "category": goal.primary_category,
                "priority": goal.priority,
                "deadline": deadline,
            }
        )
        deadlines_snapshot.append(
            {
                "goal_id": str(goal.id),
                "title": goal.title,
                "deadline": deadline,
            }
        )

    return goals_snapshot, deadlines_snapshot


def generate_contract_pdf_bytes(*, user_name: str, signed_at: str, identity_statement: str, signature_name: str, goals_snapshot: list[dict[str, Any]]) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except Exception:
        return _generate_basic_pdf_bytes(
            user_name=user_name,
            signed_at=signed_at,
            identity_statement=identity_statement,
            signature_name=signature_name,
            goals_snapshot=goals_snapshot,
        )

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 24 * mm
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(22 * mm, y, "Roadmap Smart Planner")
    y -= 9 * mm
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(22 * mm, y, "Commitment Contract")
    y -= 8 * mm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(22 * mm, y, f"Signed by: {user_name}")
    y -= 5 * mm
    pdf.drawString(22 * mm, y, f"Date: {signed_at}")
    y -= 9 * mm

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(22 * mm, y, "Identity Statement")
    y -= 6 * mm
    pdf.setFont("Helvetica", 10)
    for line in _split_text(identity_statement, 105):
        pdf.drawString(24 * mm, y, line)
        y -= 5 * mm
        if y < 26 * mm:
            pdf.showPage()
            y = height - 24 * mm

    y -= 2 * mm
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(22 * mm, y, "Goal Commitments")
    y -= 7 * mm
    pdf.setFont("Helvetica", 10)

    for index, goal in enumerate(goals_snapshot, start=1):
        deadline = goal.get("deadline") or "No deadline"
        title = goal.get("title") or "Untitled goal"
        line = f"{index}. {title}  |  Deadline: {deadline}"
        for wrapped in _split_text(line, 108):
            pdf.drawString(24 * mm, y, wrapped)
            y -= 5 * mm
            if y < 22 * mm:
                pdf.showPage()
                y = height - 24 * mm

    y -= 2 * mm
    declaration = (
        "I commit to honoring these goals with discipline and integrity. "
        "I understand this contract is permanent and cannot be changed once signed."
    )
    for line in _split_text(declaration, 108):
        pdf.drawString(22 * mm, y, line)
        y -= 5 * mm
        if y < 20 * mm:
            pdf.showPage()
            y = height - 24 * mm

    y -= 8 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(22 * mm, y, f"Signature: {signature_name}")

    pdf.save()
    buffer.seek(0)
    return buffer.read()


def send_contract_email_via_resend(
    *,
    to_email: str,
    cc_email: str | None,
    subject: str,
    html_content: str,
    attachment_filename: str,
    attachment_bytes: bytes,
) -> None:
    api_key = getattr(settings, "RESEND_API_KEY", "")
    from_email = getattr(settings, "RESEND_FROM_EMAIL", "")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured.")
    if not from_email:
        raise RuntimeError("RESEND_FROM_EMAIL is not configured.")

    encoded_pdf = base64.b64encode(attachment_bytes).decode("utf-8")

    payload: dict[str, Any] = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "attachments": [
            {
                "filename": attachment_filename,
                "content": encoded_pdf,
            }
        ],
    }

    if cc_email:
        payload["cc"] = [cc_email]

    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()


def build_contract_email_html(user_name: str, signed_at_display: str, goals_snapshot: list[dict[str, Any]]) -> str:
    list_items = "".join(
        f"<li><strong>{goal.get('title', 'Untitled')}</strong> — Deadline: {goal.get('deadline') or 'N/A'}</li>"
        for goal in goals_snapshot
    )
    return f"""
    <div style="font-family: Georgia, serif; max-width: 680px; margin: 0 auto; color: #0f172a;">
      <h1 style="margin-bottom: 0;">Commitment Contract Signed</h1>
      <p style="margin-top: 8px; color: #475569;">{user_name} signed on {signed_at_display}</p>
      <p>Your roadmap commitment contract is attached as a PDF.</p>
      <h3>Committed Goals</h3>
      <ul>{list_items}</ul>
      <p style="margin-top: 20px;">Keep going — disciplined consistency compounds over time.</p>
    </div>
    """


def _split_text(text: str, max_chars: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines or [""]


def _generate_basic_pdf_bytes(
    *,
    user_name: str,
    signed_at: str,
    identity_statement: str,
    signature_name: str,
    goals_snapshot: list[dict[str, Any]],
) -> bytes:
    lines = [
        "Roadmap Smart Planner - Commitment Contract",
        f"Signed by: {user_name}",
        f"Date: {signed_at}",
        "",
        "Identity Statement:",
        *(_split_text(identity_statement, 90)),
        "",
        "Goal Commitments:",
    ]

    for index, goal in enumerate(goals_snapshot, start=1):
        lines.append(f"{index}. {goal.get('title', 'Untitled')} | Deadline: {goal.get('deadline') or 'N/A'}")

    lines.extend(
        [
            "",
            "I commit to honoring these goals with discipline and integrity.",
            f"Signature: {signature_name}",
        ]
    )

    text_commands: list[str] = []
    y = 800
    for line in lines:
        escaped = (
            line.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        text_commands.append(f"1 0 0 1 40 {y} Tm ({escaped}) Tj")
        y -= 14
        if y < 40:
            break

    stream_text = "BT\n/F1 10 Tf\n" + "\n".join(text_commands) + "\nET"
    stream_bytes = stream_text.encode("latin-1", errors="ignore")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"\nendstream",
    ]

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n")
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    pdf.extend(b"trailer\n")
    pdf.extend(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("ascii"))
    pdf.extend(b"startxref\n")
    pdf.extend(f"{xref_pos}\n".encode("ascii"))
    pdf.extend(b"%%EOF")

    return bytes(pdf)
