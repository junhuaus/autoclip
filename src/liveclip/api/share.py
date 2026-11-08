# ruff: noqa: RUF001
"""Separate read-only share server for customer deliveries (Stage 19d).

Routes (and nothing else): ``GET /s/{token}``,
``GET /s/{token}/clips/{ordinal}/video``, ``GET /s/{token}/clips/{ordinal}/subtitle``
and ``GET /s/{token}/download``. The app never reads cookies or an
``Authorization`` header, sets no cookie, has no CORS, no OpenAPI/docs routes
and none of the internal API. An unknown, expired or revoked token, an unknown
ordinal, a malformed path and any other route all get one identical 404.
Request paths are logged with the token redacted; the token is never stored
or audited.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from liveclip.api.media import MediaRangeNotSatisfiable, stream_asset_response
from liveclip.application.customer_share_links import ShareTarget
from liveclip.application.media_assets import MediaAssetInvalid, MediaAssetNotFound
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings, get_settings
from liveclip.customer_delivery_settings import ShareSettings
from liveclip.delivery.customer_package import (
    CONTENT_SECURITY_POLICY,
    CustomerDeliveryManifest,
    customer_download_filename,
    customer_filename_component,
    customer_index_html,
)
from liveclip.domain.customer_delivery import CustomerClipView
from liveclip.media.secure_files import SecureFileError, read_regular_file_no_follow
from liveclip.observability import configure_logging

logger = logging.getLogger("liveclip.share")
_TOKEN_PATH = re.compile(r"^/s/[^/]+")
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": f"{CONTENT_SECURITY_POLICY}; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_NOT_FOUND_HTML = (
    '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>链接不可用</title></head><body><main><h1>链接不可用</h1>"
    "<p>该分享链接无效、已过期或已被撤销，请联系发送者获取新的链接。</p>"
    "</main></body></html>\n"
)


def redact_share_path(path: str) -> str:
    return _TOKEN_PATH.sub("/s/<redacted>", path)


class ShareRateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("share rate limit exceeded")
        self.retry_after = max(1, retry_after)


class ShareRateLimiter:
    """In-process sliding windows: misses per client IP and requests per link."""

    def __init__(
        self,
        *,
        miss_limit: int = 20,
        miss_window_seconds: float = 600,
        link_limit: int = 600,
        link_window_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._miss_limit = miss_limit
        self._miss_window = miss_window_seconds
        self._link_limit = link_limit
        self._link_window = link_window_seconds
        self._clock = clock
        self._misses: dict[str, deque[float]] = defaultdict(deque)
        self._links: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, values: deque[float], window: float, now: float) -> None:
        while values and values[0] <= now - window:
            values.popleft()

    def check_client(self, client: str) -> None:
        now = self._clock()
        with self._lock:
            values = self._misses[client]
            self._trim(values, self._miss_window, now)
            if len(values) >= self._miss_limit:
                raise ShareRateLimited(int(values[0] + self._miss_window - now) + 1)

    def record_miss(self, client: str) -> None:
        with self._lock:
            self._misses[client].append(self._clock())

    def hit_link(self, link_id: str) -> None:
        now = self._clock()
        with self._lock:
            values = self._links[link_id]
            self._trim(values, self._link_window, now)
            if len(values) >= self._link_limit:
                raise ShareRateLimited(int(values[0] + self._link_window - now) + 1)
            values.append(now)


def _not_found() -> HTMLResponse:
    return HTMLResponse(_NOT_FOUND_HTML, status_code=404, headers=dict(SECURITY_HEADERS))


def _expiry_text(value: datetime) -> str:
    local = value.astimezone()
    return (
        f"此分享链接将于 {local.year}年{local.month}月{local.day}日 "
        f"{local.hour:02d}:{local.minute:02d} 失效。仅限同一局域网内访问。"
    )


def create_share_app(
    settings: Settings | None = None,
    *,
    share_settings: ShareSettings | None = None,
    runtime: LiveClipRuntime | None = None,
    project_root: Path | None = None,
    rate_limiter: ShareRateLimiter | None = None,
) -> FastAPI:
    configured = settings or get_settings()
    sharing = share_settings or ShareSettings()
    limiter = rate_limiter or ShareRateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = runtime is None
        active = runtime or LiveClipRuntime.open(
            configured, project_root=project_root, share_settings=sharing
        )
        app.state.runtime = active
        # Opening the runtime runs Alembic, whose logging fileConfig replaces the
        # root handlers and disables existing loggers; restore the redacting JSON
        # logging so the (token-redacted) request log stays on.
        configure_logging(configured.log_level)
        logger.disabled = False
        try:
            yield
        finally:
            if owned:
                active.close()

    app = FastAPI(
        title="LiveClip share",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        client = request.client.host if request.client is not None else "unknown"
        try:
            limiter.check_client(client)
            response = await call_next(request)
        except ShareRateLimited as exc:
            response = HTMLResponse(
                "<!doctype html><title>请求过多</title><p>请求过多，请稍后再试。</p>",
                status_code=429,
                headers={**SECURITY_HEADERS, "Retry-After": str(exc.retry_after)},
            )
        if response.status_code == 404:
            limiter.record_miss(client)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if "set-cookie" in response.headers:  # pragma: no cover - nothing sets cookies
            del response.headers["set-cookie"]
        logger.info(
            "share_request method=%s path=%s status=%s",
            request.method,
            redact_share_path(request.url.path),
            response.status_code,
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code in {404, 405}:
            return _not_found()
        return HTMLResponse("", status_code=exc.status_code, headers=dict(SECURITY_HEADERS))

    @app.exception_handler(RequestValidationError)
    async def invalid_path(_request: Request, _exc: RequestValidationError) -> Response:
        return _not_found()

    @app.exception_handler(ShareRateLimited)
    async def limited(_request: Request, exc: ShareRateLimited) -> Response:
        return HTMLResponse(
            "<!doctype html><title>请求过多</title><p>请求过多，请稍后再试。</p>",
            status_code=429,
            headers={**SECURITY_HEADERS, "Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(MediaRangeNotSatisfiable)
    async def bad_range(_request: Request, exc: MediaRangeNotSatisfiable) -> Response:
        return Response(
            status_code=416,
            headers={**SECURITY_HEADERS, "Content-Range": f"bytes */{exc.size_bytes}"},
        )

    @app.exception_handler(MediaAssetNotFound)
    @app.exception_handler(MediaAssetInvalid)
    async def missing_asset(_request: Request, _exc: Exception) -> Response:
        return _not_found()

    def _runtime(request: Request) -> LiveClipRuntime:
        value = request.app.state.runtime
        if not isinstance(value, LiveClipRuntime):  # pragma: no cover - lifespan sets it
            raise RuntimeError("share runtime is not initialized")
        return value

    def _target(request: Request, token: str) -> ShareTarget | None:
        target = _runtime(request).share_link_service.resolve(token)
        if target is not None:
            limiter.hit_link(target.link_id)
        return target

    def _manifest(active: LiveClipRuntime, target: ShareTarget) -> CustomerDeliveryManifest:
        asset = active.media_asset_service.resolve(
            target.manifest_asset_id, required_kind="customer_delivery_manifest"
        )
        try:
            payload = read_regular_file_no_follow(asset.path, max_bytes=8_000_000)
        except SecureFileError as exc:
            raise MediaAssetInvalid("customer manifest could not be read") from exc
        if hashlib.sha256(payload).hexdigest() != asset.sha256:
            raise MediaAssetInvalid("customer manifest differs from its committed hash")
        return CustomerDeliveryManifest.model_validate_json(payload)

    @app.get("/s/{token}", response_class=HTMLResponse)
    def share_page(token: str, request: Request) -> Response:
        target = _target(request, token)
        if target is None:
            return _not_found()
        active = _runtime(request)
        manifest = _manifest(active, target)
        shared = manifest.model_copy(
            update={
                "clips": tuple(
                    CustomerClipView(
                        **{
                            **clip.model_dump(),
                            "video_href": f"/s/{token}/clips/{clip.ordinal}/video",
                            "subtitle_href": f"/s/{token}/clips/{clip.ordinal}/subtitle",
                        }
                    )
                    for clip in manifest.clips
                )
            }
        )
        page = customer_index_html(
            shared,
            download_href=f"/s/{token}/download",
            notice=_expiry_text(target.expires_at),
        )
        active.share_link_service.record_access(target, "viewed", "page")
        return HTMLResponse(page)

    def _clip_file(
        request: Request,
        token: str,
        ordinal: int,
        *,
        kind: str,
        suffix: str,
        range_header: str | None,
    ) -> Response:
        target = _target(request, token)
        if target is None or ordinal not in target.clip_assets:
            return _not_found()
        video_id, subtitle_id, title = target.clip_assets[ordinal]
        active = _runtime(request)
        asset = active.media_asset_service.resolve(
            video_id if kind == "dual_profile_video" else subtitle_id, required_kind=kind
        )
        response = stream_asset_response(
            asset,
            range_header=range_header,
            download_filename=f"{ordinal:02d}-{customer_filename_component(title)}{suffix}",
            unicode_filename=True,
        )
        if range_header is None:
            active.share_link_service.record_access(target, "downloaded", f"{suffix[1:]}:{ordinal}")
        return response

    @app.get("/s/{token}/clips/{ordinal}/video")
    def share_video(
        token: str,
        ordinal: int,
        request: Request,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> Response:
        return _clip_file(
            request,
            token,
            ordinal,
            kind="dual_profile_video",
            suffix=".mp4",
            range_header=range_header,
        )

    @app.get("/s/{token}/clips/{ordinal}/subtitle")
    def share_subtitle(
        token: str,
        ordinal: int,
        request: Request,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> Response:
        return _clip_file(
            request,
            token,
            ordinal,
            kind="dual_profile_subtitle",
            suffix=".srt",
            range_header=range_header,
        )

    @app.get("/s/{token}/download")
    def share_download(
        token: str,
        request: Request,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> Response:
        target = _target(request, token)
        if target is None:
            return _not_found()
        active = _runtime(request)
        asset = active.media_asset_service.resolve(
            target.zip_asset_id, required_kind="customer_delivery_zip"
        )
        response = stream_asset_response(
            asset,
            range_header=range_header,
            download_filename=customer_download_filename(target.title, target.delivery_version),
            unicode_filename=True,
        )
        if range_header is None:
            active.share_link_service.record_access(target, "downloaded", "zip")
        return response

    return app


__all__ = [
    "SECURITY_HEADERS",
    "ShareRateLimited",
    "ShareRateLimiter",
    "create_share_app",
    "redact_share_path",
]
