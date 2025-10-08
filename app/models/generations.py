from typing import List
from pydantic import BaseModel

from app.models.common_responses import PaginationMeta
from app.models.database import Result


class PaginatedResults(BaseModel):
    data: List[Result]
    meta: PaginationMeta
