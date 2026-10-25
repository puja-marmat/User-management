"""
Shared response shapes (plan §7).

- camelCase on the wire: models inherit `CamelModel`.
- One pagination shape: {data, totalElements, totalPages, page, size}.
- One error shape: {errorCode, message, errors?}.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for request/response schemas: snake_case in Python, camelCase in JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ErrorResponse(BaseModel):
    errorCode: str = Field(..., examples=["NOT_FOUND"])
    message: str = Field(..., examples=["Resource not found"])
    errors: list[Any] | None = None


class Page[T](CamelModel):
    data: list[T]
    total_elements: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    size: int = Field(..., ge=1)

    @classmethod
    def build(cls, data: list[T], total: int, page: int, size: int) -> "Page[T]":
        pages = (total + size - 1) // size if size else 0
        return cls(data=data, total_elements=total, total_pages=pages, page=page, size=size)
