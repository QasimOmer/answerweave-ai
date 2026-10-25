"""
Team alerts: email (Resend API or SMTP) and the assistant's webhook.

Email is configured with environment variables:
  RESEND_API_KEY + ALERT_EMAIL_FROM            (https://resend.com), or
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM [, SMTP_SSL=1]
Recipients come from each assistant's "Alert email" setting (comma-separated).
Nothing here raises: alerts are best-effort and must never break a chat.
"""
import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List, Tuple

import requests

from app.netsafe import is_public_url


def email_provider() -> str:
    if os.environ.get("RESEND_API_KEY"):
        return "resend"
    if os.environ.get("SMTP_HOST"):
        return "smtp"
    return ""


def _recipients(raw: str) -> List[str]:
    return [e.strip() for e in (raw or "").replace(";", ",").split(",") if "@" in e]


def send_email(to: List[str], subject: str, text: str, html_body: str = "") -> Tuple[bool, str]:
    if not to:
        return False, "No alert email address is set for this assistant."
    provider = email_provider()
    try:
        if provider == "resend":
            sender = os.environ.get("ALERT_EMAIL_FROM") or "AnswerWeave <onboarding@resend.dev>"
            payload = {"from": sender, "to": to, "subject": subject, "text": text}
            if html_body:
                payload["html"] = html_body
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                json=payload,
                timeout=6,
            )
            if resp.ok:
                return True, "sent"
            return False, f"Resend error {resp.status_code}: {resp.text[:200]}"
        if provider == "smtp":
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER", "")
            msg["To"] = ", ".join(to)
            msg.set_content(text)
            if html_body:
                msg.add_alternative(html_body, subtype="html")
            host = os.environ["SMTP_HOST"]
            port = int(os.environ.get("SMTP_PORT") or (465 if os.environ.get("SMTP_SSL") == "1" else 587))
            if os.environ.get("SMTP_SSL") == "1":
                server = smtplib.SMTP_SSL(host, port, timeout=8, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(host, port, timeout=8)
                server.starttls(context=ssl.create_default_context())
            with server:
                if os.environ.get("SMTP_USER"):
                    server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                server.send_message(msg)
            return True, "sent"
        return False, "Email isn't configured on the server (set RESEND_API_KEY or SMTP_HOST)."
    except Exception as e:
        return False, f"Email failed: {e}"


def notify_human_requested(asst: Dict[str, Any], conversation_id: str, visitor_message: str, base_url: str) -> Dict[str, Any]:
    """Tell the team a visitor wants a person: email + webhook. Returns what happened."""
    name = asst.get("name") or "your assistant"
    inbox_url = base_url.rstrip("/") + "/dashboard#inbox"
    subject = f"A visitor wants to talk to a person — {name}"
    text = (
        f"A visitor on {name} asked to talk to someone:\n\n"
        f"  \"{visitor_message.strip()[:500]}\"\n\n"
        f"Open the inbox to take over the chat: {inbox_url}\n"
        f"Conversation: {conversation_id}\n"
    )
    html_body = (
        f"<p>A visitor on <strong>{html.escape(name)}</strong> asked to talk to someone:</p>"
        f"<blockquote style=\"border-left:3px solid #2f5cf6;margin:0;padding:4px 12px;color:#333\">{html.escape(visitor_message.strip()[:500])}</blockquote>"
        f"<p><a href=\"{html.escape(inbox_url)}\" style=\"display:inline-block;background:#2f5cf6;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none\">Open the inbox</a></p>"
        f"<p style=\"color:#888;font-size:12px\">Conversation {html.escape(conversation_id)}</p>"
    )
    email_ok, email_detail = send_email(_recipients(asst.get("notification_email") or ""), subject, text, html_body)

    webhook_ok = None
    if asst.get("webhook_url") and is_public_url(asst["webhook_url"]):
        try:
            r = requests.post(asst["webhook_url"], json={
                "event": "human_requested",
                "assistant_id": asst.get("id"),
                "assistant_name": name,
                "conversation_id": conversation_id,
                "message": visitor_message,
                "inbox_url": inbox_url,
            }, timeout=5)
            webhook_ok = r.ok
        except Exception:
            webhook_ok = False

    return {"email_sent": email_ok, "email_detail": email_detail, "webhook_sent": webhook_ok}
