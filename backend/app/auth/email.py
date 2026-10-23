"""Transactional email for verification, password resets and security notices."""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Optional
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger("app.auth.email")
dev_logger = logging.getLogger("app.auth.email.dev")


def app_base_url() -> str:
    configured = (settings.app_base_url or settings.public_base_url or "").strip()
    if configured:
        return configured.rstrip("/")
    if settings.environment == "production":
        logger.error(
            "APP_BASE_URL is not set; confirmation and reset links cannot be built correctly"
        )
    else:
        logger.warning(
            "APP_BASE_URL is not set; account links will point at http://localhost:5173"
        )
    return "http://localhost:5173"


def app_link(path: str) -> str:
    return urljoin(app_base_url() + "/", path.lstrip("/"))


def verification_link(token: str) -> str:
    return app_link(f"verify-email?token={token}")


def reset_link(token: str) -> str:
    return app_link(f"reset-password?token={token}")


def _layout(title: str, body: str) -> str:
    return f"""\
<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#ece5d8;color:#1c1b18;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="background:#ece5d8;padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
          style="max-width:560px;background:#faf6ed;border:1px solid #d8cfbf;">
          <tr><td style="border-top:3px solid #8d3c34;padding:28px 32px 10px;">
            <div style="font-family:Georgia,'Times New Roman',serif;font-size:13px;
              letter-spacing:0.16em;text-transform:uppercase;color:#8d3c34;">
              Globe News Atlas
            </div>
            <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:26px;
              line-height:1.2;margin:14px 0 0;font-weight:600;color:#1c1b18;">
              {html.escape(title)}
            </h1>
          </td></tr>
          <tr><td style="padding:14px 32px 30px;font-family:Arial,Helvetica,sans-serif;
            font-size:15px;line-height:1.65;color:#3b362e;">
            {body}
          </td></tr>
          <tr><td style="padding:18px 32px;border-top:1px solid #d8cfbf;
            font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.05em;
            color:#6f695e;">
            You are receiving this because someone used this address at Globe News Atlas.
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""


def _button(label: str, url: str) -> str:
    safe_url = html.escape(url, quote=True)
    return (
        f'<p style="margin:24px 0;">'
        f'<a href="{safe_url}" style="display:inline-block;background:#1c1b18;'
        f'color:#f7f1e6;text-decoration:none;padding:12px 20px;font-family:Arial,'
        f'sans-serif;font-size:13px;font-weight:bold;letter-spacing:0.06em;'
        f'text-transform:uppercase;">{html.escape(label)}</a></p>'
        f'<p style="font-size:12px;line-height:1.5;color:#6f695e;word-break:break-all;">'
        f'Or paste this link into your browser:<br>{safe_url}</p>'
    )


class EmailDelivery:
    def __init__(self) -> None:
        self.provider = settings.email_delivery

    def send(
        self, to_email: str, subject: str, text: str, html_body: str
    ) -> str:
        provider = settings.email_delivery
        if provider == "unconfigured":
            logger.error(
                "Email was not sent: configure RESEND_API_KEY or SMTP_HOST in production"
            )
            return "unconfigured"
        if provider == "dev":
            if settings.environment == "production":
                logger.error(
                    "Email was not sent: the dev email provider is disabled in production"
                )
                return "unconfigured"
            dev_logger.info(
                "\n%s\nTo: %s\nSubject: %s\n%s\n%s",
                "-" * 68,
                to_email,
                subject,
                "-" * 68,
                text,
            )
            return "dev"
        try:
            if provider == "resend":
                self._send_resend(to_email, subject, text, html_body)
            elif provider == "brevo":
                self._send_brevo(to_email, subject, text, html_body)
            else:
                self._send_smtp(to_email, subject, text, html_body)
            return provider
        except Exception as exc:
            logger.error("Email delivery via %s failed: %s", provider, exc)
            return "failed"

    def _send_resend(
        self, to_email: str, subject: str, text: str, html_body: str
    ) -> None:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "GlobeNewsAtlas/1.0",
            },
            json={
                "from": settings.email_from,
                "to": [to_email],
                "subject": subject,
                "text": text,
                "html": html_body,
                **(
                    {"reply_to": settings.email_reply_to}
                    if settings.email_reply_to
                    else {}
                ),
            },
            timeout=settings.email_timeout_seconds,
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Resend returned {response.status_code}: {response.text[:200]}")

    def _send_brevo(
        self, to_email: str, subject: str, text: str, html_body: str
    ) -> None:
        sender_name, sender_address = _split_address(settings.email_from)
        payload = {
            "sender": {"name": sender_name, "email": sender_address},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_body,
            "textContent": text,
        }
        if settings.email_reply_to:
            payload["replyTo"] = {"email": settings.email_reply_to}
        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": settings.brevo_api_key or "",
                "Content-Type": "application/json",
                "User-Agent": "GlobeNewsAtlas/1.0",
            },
            json=payload,
            timeout=settings.email_timeout_seconds,
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"Brevo returned {response.status_code}: {response.text[:200]}"
            )

    def _send_smtp(
        self, to_email: str, subject: str, text: str, html_body: str
    ) -> None:
        sender_name, sender_address = _split_address(settings.email_from)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((sender_name, sender_address))
        message["To"] = to_email
        message["Reply-To"] = settings.email_reply_to or sender_address
        message["Date"] = formatdate(usegmt=True)
        message["Message-ID"] = make_msgid(
            domain=sender_address.rsplit("@", 1)[-1] if "@" in sender_address else None
        )
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(text)
        message.add_alternative(html_body, subtype="html")

        if (
            not settings.smtp_ssl
            and not settings.smtp_starttls
            and settings.smtp_username
            and settings.smtp_password
        ):
            raise RuntimeError(
                "Refusing to send SMTP credentials over an unencrypted connection"
            )
        context = ssl.create_default_context(cafile=settings.smtp_ca_file or None)
        if settings.smtp_ssl:
            client = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.email_timeout_seconds,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.email_timeout_seconds,
            )
        try:
            if settings.smtp_starttls and not settings.smtp_ssl:
                client.starttls(context=context)
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:
                client.close()


def _split_address(value: str) -> tuple[str, str]:
    if "<" in value and value.rstrip().endswith(">"):
        name, _, rest = value.partition("<")
        return name.strip().strip('"'), rest[:-1].strip()
    return "", value.strip()


email_delivery = EmailDelivery()


def send_verification(email: str, display_name: str, token: str, ttl_hours: int) -> str:
    url = verification_link(token)
    title = "Confirm your Globe News Atlas email"
    body = f"""\
      <p style="margin:0 0 12px;">Hello {html.escape(display_name)},</p>
      <p style="margin:0 0 12px;">Confirm this address to finish setting up your
      reader account and receive security notices.</p>
      {_button("Confirm email", url)}
      <p style="margin:0;font-size:13px;color:#6f695e;">This link expires in
      {ttl_hours} hours. If you did not create an account, you can ignore this message.</p>
    """
    text = (
        f"Hello {display_name},\n\n"
        f"Confirm your email address for Globe News Atlas:\n{url}\n\n"
        f"This link expires in {ttl_hours} hours. If you did not create an account, "
        "you can ignore this message.\n"
    )
    return email_delivery.send(email, title, text, _layout(title, body))


def send_password_reset(email: str, display_name: str, token: str, ttl_minutes: int) -> str:
    url = reset_link(token)
    title = "Reset your Globe News Atlas password"
    body = f"""\
      <p style="margin:0 0 12px;">Hello {html.escape(display_name)},</p>
      <p style="margin:0 0 12px;">A password reset was requested for your account.
      Choose a new password using the link below.</p>
      {_button("Choose a new password", url)}
      <p style="margin:0;font-size:13px;color:#6f695e;">This link expires in
      {ttl_minutes} minutes and can be used once. If you did not request it, no action
      is needed; your current password still works.</p>
    """
    text = (
        f"Hello {display_name},\n\n"
        f"Reset your Globe News Atlas password:\n{url}\n\n"
        f"This link expires in {ttl_minutes} minutes and can be used once. If you did "
        "not request it, no action is needed.\n"
    )
    return email_delivery.send(email, title, text, _layout(title, body))


def send_security_notice(email: str, display_name: str, what_changed: str, detail: str) -> str:
    title = what_changed
    body = f"""\
      <p style="margin:0 0 12px;">Hello {html.escape(display_name)},</p>
      <p style="margin:0 0 12px;">{html.escape(detail)}</p>
      <p style="margin:0;font-size:13px;color:#6f695e;">If this was not you, reset your
      password immediately and revoke any sessions you do not recognise.</p>
    """
    text = (
        f"Hello {display_name},\n\n{detail}\n\n"
        "If this was not you, reset your password immediately and revoke any sessions "
        "you do not recognise.\n"
    )
    return email_delivery.send(email, title, text, _layout(title, body))
