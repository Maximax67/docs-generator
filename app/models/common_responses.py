from pydantic import BaseModel


class DetailResponse(BaseModel):
    detail: str


class PaginationMeta(BaseModel):
    total_items: int
    total_pages: int
    current_page: int
    page_size: int
