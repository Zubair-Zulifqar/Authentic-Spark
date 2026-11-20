from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from quart import request

from app.core.errors import ValidationFailed

T = TypeVar("T", bound=BaseModel)


async def body(model: type[T]) -> T:
    data = await request.get_json(silent=True)
    if data is None:
        data = {}
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed(
            "Request validation failed",
            details=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        ) from exc


def ok(data: Any, status: int = 200) -> tuple[dict[str, Any], int]:
    return {"data": data}, status


def page_args() -> tuple[int, int]:
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError as exc:
        raise ValidationFailed("limit/offset must be integers") from exc
    return limit, offset
