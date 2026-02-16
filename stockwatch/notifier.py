from __future__ import annotations

import smtplib
from email.message import EmailMessage


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

    if use_starttls:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, app_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(user, app_password)
            server.send_message(msg)
