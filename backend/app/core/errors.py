from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if status:
            self.status = status
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return body


class Unauthorized(ApiError):
    status, code = 401, "unauthorized"


class Forbidden(ApiError):
    status, code = 403, "forbidden"


class NotFound(ApiError):
    status, code = 404, "not_found"


class Conflict(ApiError):
    status, code = 409, "conflict"


class ValidationFailed(ApiError):
    status, code = 422, "validation_failed"


class RateLimited(ApiError):
    status, code = 429, "rate_limited"


class IntegrationError(ApiError):
    status, code = 502, "integration_error"
