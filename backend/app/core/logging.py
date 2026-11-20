"""Structured JSON logging compatible with Cloud Logging. Redacts secret-looking keys."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

SENSITIVE = ("token", "secret", "password", "authorization", "api_key", "apikey", "phone", "email")


def redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: ("[REDACTED]" if any(s in k.lower() for s in SENSITIVE) else redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


log = logging.getLogger("authentic_spark")
