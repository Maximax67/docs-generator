from typing import Any, Dict

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pybars import Compiler # type: ignore[import-untyped]

from app.settings import settings

_compiler = Compiler()


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def render_handlebars(template_path: str, context: Dict[str, Any]) -> str:
    source = _load_template(template_path)
    template = _compiler.compile(source)
    rendered: str = template(context)

    return rendered


async def send_email(to_email: str, subject: str, html: str) -> None:
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    if settings.SMTP_USE_TLS:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)

    try:
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(
                settings.SMTP_USERNAME, settings.SMTP_PASSWORD.get_secret_value()
            )
        server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())
    finally:
        server.quit()


def render_confirm_email(username: str, url: str) -> str:
    return render_handlebars(
        settings.EMAIL_VERIFICATION_TEMPLATE,
        {"username": username, "url": url, "app_name": settings.APP_TITLE},
    )


def render_reset_password_email(username: str, url: str) -> str:
    return render_handlebars(
        settings.PASSWORD_RESET_TEMPLATE,
        {"username": username, "url": url, "app_name": settings.APP_TITLE},
    )

