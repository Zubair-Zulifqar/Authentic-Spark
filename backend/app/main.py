from __future__ import annotations

import time
import uuid

from quart import Quart, g, jsonify, request
from quart_cors import cors

from app.core import db
from app.core.config import get_settings
from app.core.errors import ApiError, RateLimited
from app.core.logging import configure_logging, log
from app.core.ratelimit import RateLimiter

API = "/api/v1"


def create_app() -> Quart:
    settings = get_settings()
    configure_logging()
    app = Quart(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    app = cors(app, allow_origin=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
               allow_headers=["Authorization", "Content-Type", "Idempotency-Key"], allow_methods=["GET", "POST", "PATCH", "DELETE"])
    limiter = RateLimiter(settings.rate_limit_per_minute)

    from app.blueprints import ads, ai, billing, compliance, contacts, core, email, platform, sms
    from app.jobs import handlers  # noqa: F401  (register job handlers)

    for mod in (core, email, contacts, sms, ads, billing, compliance, ai, platform):
        app.register_blueprint(mod.bp, url_prefix=API)

    @app.before_serving
    async def startup() -> None:
        db.init_engine(get_settings().database_url)
        await db.create_all()
        log.info("startup complete", extra={"ctx": {"env": settings.env}})

    @app.after_serving
    async def shutdown() -> None:  # graceful shutdown on SIGTERM (Cloud Run)
        await db.dispose()

    @app.before_request
    async def before() -> None:
        g.request_id = request.headers.get("X-Cloud-Trace-Context", uuid.uuid4().hex).split("/")[0]
        g.started = time.perf_counter()
        key = request.headers.get("Authorization", "") or (request.remote_addr or "anon")
        if request.path.startswith(API) and not limiter.allow(key[-40:]):
            raise RateLimited("Too many requests")

    @app.after_request
    async def after(resp):
        resp.headers["X-Request-ID"] = g.get("request_id", "")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if settings.is_production:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        log.info("request", extra={"ctx": {"method": request.method, "path": request.path, "status": resp.status_code,
                                            "ms": int((time.perf_counter() - g.get("started", time.perf_counter())) * 1000),
                                            "request_id": g.get("request_id")}})
        return resp

    @app.errorhandler(ApiError)
    async def api_error(e: ApiError):
        return jsonify(e.to_dict()), e.status

    @app.errorhandler(404)
    async def not_found(_):
        return jsonify({"error": {"code": "not_found", "message": "Route not found"}}), 404

    @app.errorhandler(413)
    async def too_large(_):
        return jsonify({"error": {"code": "payload_too_large", "message": "Upload exceeds limit"}}), 413

    @app.errorhandler(Exception)
    async def unhandled(e: Exception):
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException):
            return jsonify({"error": {"code": e.name.lower().replace(" ", "_"), "message": e.description}}), e.code
        log.exception("unhandled error", extra={"ctx": {"request_id": g.get("request_id")}})
        return jsonify({"error": {"code": "internal_error", "message": "Internal server error",
                                  "request_id": g.get("request_id")}}), 500

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        from sqlalchemy import text

        from app.core.db import session_scope

        async with session_scope() as s:
            await s.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get(f"{API}/openapi.json")
    async def openapi():
        from app.openapi import build_spec

        return build_spec(app)

    return app


app = create_app()
