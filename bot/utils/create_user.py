from aiogram.types import User as TG_USER

from app.models.database import User


async def create_user(user: TG_USER) -> User:
    if user.is_bot:
        raise ValueError("Can not create a bot user")

    return await User.find_one(User.telegram_id == user.id).upsert(
        {
            "$set": {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
            }
        },
        on_insert=User(
            telegram_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        ),
    )
