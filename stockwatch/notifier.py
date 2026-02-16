from __future__ import annotations

import smtplib
from email.message import EmailMessage


class MailAuthenticationError(RuntimeError):
    """Raised when SMTP login fails due to credential/auth policy issues."""


def _normalize_app_password(app_password: str) -> str:
    # Gmail app passwords are often displayed with spaces; remove them safely.
    return app_password.replace(" ", "").strip()


def send_email(
    *,
    smtp_host: str,
    smtp_port: int,
    use_starttls: bool,
    user: str,
    app_password: str,
    to_addr: str,
    subject: str,
    body: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    normalized_password = _normalize_app_password(app_password)

    try:
        if use_starttls:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, normalized_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                server.login(user, normalized_password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailAuthenticationError(
            "Gmail SMTP authentication failed. Check GMAIL_USER and GMAIL_APP_PASSWORD. "
            "Use a 16-character Google App Password (2-Step Verification required), "
            "not your normal account password."
        ) from exc
