"""Generates an OpenAPI 3.1 document from the registered routes and pydantic request models."""
from __future__ import annotations

import inspect
import re
from typing import Any

from pydantic import BaseModel


def build_spec(app: Any) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    schemas: dict[str, Any] = {}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1"):
            continue
        view = app.view_functions[rule.endpoint]
        fn = inspect.unwrap(view)
        path = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule.rule)
        src = inspect.getsource(fn) if hasattr(fn, "__code__") else ""
        m = re.search(r"await body\((\w+)\)", src)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            op: dict[str, Any] = {
                "operationId": rule.endpoint.replace(".", "_") + f"_{method.lower()}",
                "tags": [rule.endpoint.split(".")[0]],
                "summary": (fn.__doc__ or fn.__name__.replace("_", " ")).strip().split("\n")[0],
                "parameters": [{"name": a, "in": "path", "required": True, "schema": {"type": "string"}} for a in rule.arguments],
                "responses": {"200": {"description": "OK"}, "401": {"description": "Unauthorized"},
                              "403": {"description": "Forbidden"}, "422": {"description": "Validation failed"}},
            }
            if "webhooks" not in rule.rule and rule.rule not in ("/api/v1/jobs/tick",) and "callback" not in rule.rule:
                op["security"] = [{"firebase": []}]
            if m:
                model = fn.__globals__.get(m.group(1))
                if isinstance(model, type) and issubclass(model, BaseModel):
                    schemas[model.__name__] = model.model_json_schema(ref_template="#/components/schemas/{model}")
                    op["requestBody"] = {"required": True, "content": {"application/json": {
                        "schema": {"$ref": f"#/components/schemas/{model.__name__}"}}}}
            paths.setdefault(path, {})[method.lower()] = op
    for s in list(schemas.values()):
        for name, sub in s.pop("$defs", {}).items():
            schemas.setdefault(name, sub)
    return {
        "openapi": "3.1.0",
        "info": {"title": "Authentic Spark API", "version": "1.0.0"},
        "servers": [{"url": "/"}],
        "paths": paths,
        "components": {"schemas": schemas, "securitySchemes": {"firebase": {"type": "http", "scheme": "bearer",
                                                                            "bearerFormat": "Firebase ID token"}}},
    }
