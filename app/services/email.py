import httpx
from typing import Literal

from app.settings import settings


async def send_email(
    to_email: str,
    subject: str,
    template: Literal["confirm", "reset"],
    username: str,
    url: str,
) -> None:
    headers = {"x-api-token": settings.MAILER_TOKEN.get_secret_value()}
    payload = {
        "to_email": to_email,
        "subject": subject,
        "template": template,
        "username": username,
        "url": url,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(settings.MAILER_URL, json=payload, headers=headers)
        response.raise_for_status()
