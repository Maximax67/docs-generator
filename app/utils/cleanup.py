import asyncio
from datetime import datetime, timedelta, timezone

from app.settings import settings
from app.models import Session


async def cleanup_old_sessions() -> None:
    seven_days_ago = datetime.now(timezone.utc) - timedelta(
        days=settings.REFRESH_TOKEN_EXPIRES_DAYS
    )
    await Session.find(Session.updated_at < seven_days_ago).delete()


async def periodic_cleanup(interval_seconds: int = 3600) -> None:
    while True:
        await cleanup_old_sessions()
        await asyncio.sleep(interval_seconds)
