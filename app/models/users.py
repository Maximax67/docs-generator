from typing import List
from pydantic import BaseModel

from app.models.database import Result, User


class AllUsersResponse(BaseModel):
    users: List[User]


class UserDocumentsResponse(BaseModel):
    documents: List[Result]
