from pydantic import BaseModel

from app.schemas.common_responses import PaginationMeta
from app.db.database import Result


class PaginatedResults(BaseModel):
    data: list[Result]
    meta: PaginationMeta
