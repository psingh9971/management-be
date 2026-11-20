from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    skip: int
    limit: int


def mask(value: str, visible: int = 4) -> str:
    """Hide all but the last `visible` characters, e.g. XXXXXXXX1234."""
    if not value:
        return value
    return "X" * max(len(value) - visible, 0) + value[-visible:]
