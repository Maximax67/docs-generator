from typing import Generic, TypeVar
from pydantic import BaseModel


class DetailResponse(BaseModel):
    detail: str


class PaginationMeta(BaseModel):
    total_items: int
    total_pages: int
    current_page: int
    page_size: int


T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    data: list[T]
    meta: PaginationMeta
