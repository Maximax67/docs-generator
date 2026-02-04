from datetime import datetime, timezone
from beanie import PydanticObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.schemas.auth import AuthorizedUser
from app.models import User
from app.enums import UserRole


async def update_user_bool_field(
    user_id: PydanticObjectId,
    authorized_user: AuthorizedUser,
    field: str,
    value: bool,
    conflict_detail: str,
) -> User:
    query = {"_id": user_id, field: not value}
    if authorized_user.role != UserRole.GOD:
        query["role"] = UserRole.USER.value

    now = datetime.now(timezone.utc)
    updated_user: User | None = await User.get_pymongo_collection().find_one_and_update(
        query,
        {"$set": {field: value, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )

    if updated_user:
        return updated_user

    user_exists = await User.find_one(User.id == user_id)

    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    if user_exists.role != UserRole.USER and authorized_user.role != UserRole.GOD:
        raise HTTPException(status_code=403, detail="Forbidden")

    raise HTTPException(status_code=409, detail=conflict_detail)
