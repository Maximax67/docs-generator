from math import ceil
from typing import Any

from app.schemas.common_responses import PaginationMeta


async def paginate(
    query: Any,
    page: int,
    page_size: int,
):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10

    total_items = await query.count()

    skip = (page - 1) * page_size
    items = await query.skip(skip).limit(page_size).to_list()

    total_pages = ceil(total_items / page_size) if total_items else 1

    return items, PaginationMeta(
        total_items=total_items,
        total_pages=total_pages,
        current_page=page,
        page_size=page_size,
    )
