from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from liveclip import __version__
from liveclip.api.media import MediaRangeNotSatisfiable, stream_asset_response
from liveclip.api.schemas import (
    AcceptedPipelineResponse,
    AcceptedTaskResponse,
    ApiErrorDetail,
    ApiErrorEnvelope,
    ApiErrorItem,
    BatchReviewRequest,
    BatchReviewResponse,
    ClipDetailResponse,
    ClipPatchRequest,
    ClipSummaryResponse,
    DeliveryCreateRequest,
    DeliveryDetailResponse,
    HealthResponse,
    JobCreateRequest,
    ProjectMemberCreateRequest,
    ProjectMembersResponse,
    ProviderHealthResponse,
    RenderCreateRequest,
    ReviewActionRequest,
    RunCreateRequest,
    SessionResponse,
)
from liveclip.api.security import ApiAuthenticationError, ApiSecurity, AuthenticatedCaller
from liveclip.application.deliveries import (
    DeliveryConflict,
    DeliveryRequest,
    DeliverySnapshot,
)
from liveclip.application.idempotency import (
    IdempotencyConflict,
    IdempotencyContext,
    build_idempotency_context,
)
from liveclip.application.media_assets import MediaAssetInvalid
from liveclip.application.pipeline import (
    PipelineConflict,
    PipelineRunConfig,
    ProjectSnapshot,
    RunSnapshot,
)
from liveclip.application.rendering import QueuedRender, RenderConflict
from liveclip.application.reviewing import (
    ClipDetail,
    ClipPatch,
    RenderRequest,
    ReviewCommand,
    ReviewConflict,
    TranscriptSnapshot,
)
from liveclip.application.workspace import WorkspaceUser
from liveclip.bootstrap import LiveClipRuntime, pipeline_config_from_settings
from liveclip.config import Settings, get_settings
from liveclip.db.workspace_repository import WorkspacePermissionDenied
from liveclip.domain.state_transitions import ReviewStatus
from liveclip.media.ingest import MediaIngestError, resolve_allowed_source
from liveclip.providers.readiness import (
    ProviderNotReady,
    assess_provider_readiness,
    ensure_processing_ready,
)

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    runtime: LiveClipRuntime | None = None,
    project_root: Path | None = None,
) -> FastAPI:
    configured = settings or get_settings()
    security = ApiSecurity(configured)
    provider_readiness = assess_provider_readiness(configured)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned_runtime = runtime is None
        active_runtime = runtime or LiveClipRuntime.open(configured, project_root=project_root)
        app.state.runtime = active_runtime
        try:
            yield
        finally:
            if owned_runtime:
                active_runtime.close()

    app = FastAPI(
        title="LiveClip API",
        version=__version__,
        lifespan=lifespan,
        responses={
            401: {"model": ApiErrorEnvelope, "description": "Authentication failed"},
            403: {"model": ApiErrorEnvelope, "description": "Permission denied"},
            404: {"model": ApiErrorEnvelope, "description": "Resource not found"},
            409: {"model": ApiErrorEnvelope, "description": "State conflict"},
            416: {"model": ApiErrorEnvelope, "description": "Range not satisfiable"},
            422: {"model": ApiErrorEnvelope, "description": "Request validation failed"},
            500: {"model": ApiErrorEnvelope, "description": "Safe internal error"},
            503: {
                "model": ApiErrorEnvelope,
                "description": "Provider or local storage temporarily unavailable",
            },
        },
    )
    app.state.settings = configured
    app.state.security = security
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Range"],
        expose_headers=[
            "Accept-Ranges",
            "Content-Length",
            "Content-Range",
            "ETag",
            "Location",
            "Retry-After",
            "X-Request-ID",
        ],
    )

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        if (
            request.method == "OPTIONS"
            and request.headers.get("origin") is not None
            and request.headers.get("access-control-request-method") is not None
            and response.status_code >= 400
        ):
            cors_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() == "vary" or key.lower().startswith("access-control-")
            }
            response = _error_response(
                request,
                status_code=response.status_code,
                code="CORS_PREFLIGHT_REJECTED",
                message="The browser cross-origin request is not allowed",
                headers=cors_headers,
            )
        response.headers["X-Request-ID"] = correlation_id
        return response

    _install_exception_handlers(app)

    def require_api_auth(
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> AuthenticatedCaller:
        caller = security.authenticate(authorization)
        request.state.authenticated_caller = caller
        return caller

    protected = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_auth)])

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        active = _runtime(request)
        with active.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        return HealthResponse(
            version=__version__,
            providers=ProviderHealthResponse(
                mode=provider_readiness.mode,
                asr_provider=provider_readiness.asr_provider,
                llm_provider=provider_readiness.llm_provider,
                asr_ready=provider_readiness.asr_ready,
                llm_ready=provider_readiness.llm_ready,
                processing_ready=provider_readiness.processing_ready,
                blocking_issues=provider_readiness.blocking_issues,
                warnings=provider_readiness.warnings,
            ),
        )

    @protected.get("/session", response_model=SessionResponse)
    def get_session(request: Request) -> SessionResponse:
        user = _runtime(request).workspace_service.get_user_by_username(_caller(request).username)
        return SessionResponse(user=user)

    @protected.post(
        "/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AcceptedPipelineResponse,
    )
    def create_job(
        body: JobCreateRequest,
        response: Response,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AcceptedPipelineResponse:
        active = _runtime(request)
        caller = _caller(request)
        workspace_user = active.workspace_service.get_user_by_username(caller.username)
        idempotency = _idempotency(
            caller,
            idempotency_key,
            operation="POST:/api/v1/jobs",
            payload=body.model_dump(mode="json"),
        )
        created = active.pipeline_service.replay_pipeline(idempotency)
        if created is None:
            ensure_processing_ready(provider_readiness)
            source_path = resolve_allowed_source(body.input_path, configured.allowed_media_roots)
            config = _pipeline_config(configured, body)
            created = active.pipeline_service.create_project_and_run(
                source_path=source_path,
                config=config,
                max_stage_retries=configured.max_stage_retries,
                owner_id=workspace_user.user_id,
                idempotency=idempotency,
            )
        location = f"/api/v1/jobs/{created.run_id}"
        response.headers["Location"] = location
        response.headers["Retry-After"] = "1"
        return AcceptedPipelineResponse(
            project_id=created.project_id,
            run_id=created.run_id,
            status=active.pipeline_service.get_run(created.run_id).status.value,
            status_url=location,
        )

    @protected.get("/jobs/{run_id}", response_model=RunSnapshot)
    def get_job(run_id: str, request: Request) -> RunSnapshot:
        return _require_run_access(_runtime(request), _caller(request), run_id)

    @protected.get("/projects", response_model=list[ProjectSnapshot])
    def list_projects(request: Request) -> list[ProjectSnapshot]:
        active = _runtime(request)
        workspace_user = active.workspace_service.get_user_by_username(_caller(request).username)
        return list(active.pipeline_service.list_projects_for_user(workspace_user.user_id))

    @protected.post(
        "/projects/import",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AcceptedPipelineResponse,
    )
    def import_project(
        body: JobCreateRequest,
        response: Response,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AcceptedPipelineResponse:
        active = _runtime(request)
        caller = _caller(request)
        source_path = resolve_allowed_source(body.input_path, configured.allowed_media_roots)
        created = active.pipeline_service.import_project(
            source_path=source_path,
            config=_pipeline_config(configured, body, run_scope="import"),
            max_stage_retries=configured.max_stage_retries,
            owner_id=active.workspace_service.get_user_by_username(caller.username).user_id,
            idempotency=_idempotency(
                caller,
                idempotency_key,
                operation="POST:/api/v1/projects/import",
                payload=body.model_dump(mode="json"),
            ),
        )
        location = f"/api/v1/runs/{created.run_id}"
        response.headers["Location"] = location
        response.headers["Retry-After"] = "1"
        return AcceptedPipelineResponse(
            project_id=created.project_id,
            run_id=created.run_id,
            status=active.pipeline_service.get_run(created.run_id).status.value,
            status_url=location,
        )

    @protected.get("/projects/{project_id}", response_model=ProjectSnapshot)
    def get_project(project_id: str, request: Request) -> ProjectSnapshot:
        active = _runtime(request)
        workspace_user = active.workspace_service.get_user_by_username(_caller(request).username)
        return active.pipeline_service.get_project(project_id, user_id=workspace_user.user_id)

    @protected.get(
        "/projects/{project_id}/members",
        response_model=ProjectMembersResponse,
    )
    def list_project_members(project_id: str, request: Request) -> ProjectMembersResponse:
        active = _runtime(request)
        _require_project_access(active, _caller(request), project_id)
        return ProjectMembersResponse(
            project_id=project_id,
            members=active.workspace_service.list_project_members(project_id),
        )

    @protected.post(
        "/projects/{project_id}/members",
        response_model=ProjectMembersResponse,
    )
    def add_project_member(
        project_id: str,
        body: ProjectMemberCreateRequest,
        request: Request,
    ) -> ProjectMembersResponse:
        active = _runtime(request)
        caller_user = _require_project_access(active, _caller(request), project_id)
        active.workspace_service.add_project_member(
            project_id=project_id,
            acting_user_id=caller_user.user_id,
            username=body.username,
            display_name=body.display_name,
            role=body.role,
        )
        return ProjectMembersResponse(
            project_id=project_id,
            members=active.workspace_service.list_project_members(project_id),
        )

    @protected.delete(
        "/projects/{project_id}/members/{member_user_id}",
        response_model=ProjectMembersResponse,
    )
    def remove_project_member(
        project_id: str,
        member_user_id: str,
        request: Request,
    ) -> ProjectMembersResponse:
        active = _runtime(request)
        caller_user = _require_project_access(active, _caller(request), project_id)
        active.workspace_service.remove_project_member(
            project_id=project_id,
            acting_user_id=caller_user.user_id,
            member_user_id=member_user_id,
        )
        return ProjectMembersResponse(
            project_id=project_id,
            members=active.workspace_service.list_project_members(project_id),
        )

    @protected.post(
        "/projects/{project_id}/runs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AcceptedPipelineResponse,
    )
    def create_project_run(
        project_id: str,
        body: RunCreateRequest,
        response: Response,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AcceptedPipelineResponse:
        active = _runtime(request)
        caller = _caller(request)
        _require_project_access(active, caller, project_id)
        idempotency = _idempotency(
            caller,
            idempotency_key,
            operation="POST:/api/v1/projects/:project_id/runs",
            payload={"project_id": project_id, **body.model_dump(mode="json")},
        )
        created = active.pipeline_service.replay_pipeline(
            idempotency,
            expected_project_id=project_id,
        )
        if created is None:
            ensure_processing_ready(provider_readiness)
            created = active.pipeline_service.create_run(
                project_id=project_id,
                config=_pipeline_config(configured, body),
                max_stage_retries=configured.max_stage_retries,
                idempotency=idempotency,
            )
        location = f"/api/v1/runs/{created.run_id}"
        response.headers["Location"] = location
        response.headers["Retry-After"] = "1"
        return AcceptedPipelineResponse(
            project_id=created.project_id,
            run_id=created.run_id,
            status=active.pipeline_service.get_run(created.run_id).status.value,
            status_url=location,
        )

    @protected.get("/runs/{run_id}", response_model=RunSnapshot)
    def get_run(run_id: str, request: Request) -> RunSnapshot:
        return _require_run_access(_runtime(request), _caller(request), run_id)

    @protected.post(
        "/runs/{run_id}/cancel",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=RunSnapshot,
    )
    def cancel_run(
        run_id: str,
        response: Response,
        request: Request,
    ) -> RunSnapshot:
        active = _runtime(request)
        _require_run_access(active, _caller(request), run_id)
        response.headers["Location"] = f"/api/v1/runs/{run_id}"
        response.headers["Retry-After"] = "1"
        return active.pipeline_service.cancel(run_id)

    @protected.post(
        "/runs/{run_id}/retry",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=RunSnapshot,
    )
    def retry_run(
        run_id: str,
        response: Response,
        request: Request,
    ) -> RunSnapshot:
        active = _runtime(request)
        _require_run_access(active, _caller(request), run_id)
        response.headers["Location"] = f"/api/v1/runs/{run_id}"
        response.headers["Retry-After"] = "1"
        return active.pipeline_service.retry(run_id)

    @protected.get(
        "/projects/{project_id}/transcript",
        response_model=TranscriptSnapshot,
    )
    def get_transcript(
        project_id: str,
        request: Request,
    ) -> TranscriptSnapshot:
        active = _runtime(request)
        _require_project_access(active, _caller(request), project_id)
        return active.review_service.get_transcript(project_id)

    @protected.get(
        "/projects/{project_id}/clips",
        response_model=list[ClipSummaryResponse],
    )
    def list_clips(
        project_id: str,
        request: Request,
    ) -> list[ClipSummaryResponse]:
        active = _runtime(request)
        _require_project_access(active, _caller(request), project_id)
        values = active.clip_query_service.list_project_clips(project_id)
        return [
            ClipSummaryResponse(
                clip=value,
                proxy_media_url=(
                    _asset_url(security, value.proxy_asset_id) if value.proxy_asset_id else None
                ),
            )
            for value in values
        ]

    @protected.get("/clips/{clip_id}", response_model=ClipDetailResponse)
    def get_clip(
        clip_id: str,
        request: Request,
    ) -> ClipDetailResponse:
        return _clip_response(
            security,
            _require_clip_access(_runtime(request), _caller(request), clip_id),
        )

    @protected.patch("/clips/{clip_id}", response_model=ClipDetailResponse)
    def patch_clip(
        clip_id: str,
        body: ClipPatchRequest,
        request: Request,
    ) -> ClipDetailResponse:
        active = _runtime(request)
        _require_clip_access(active, _caller(request), clip_id)
        detail = active.review_service.revise_clip(clip_id, _clip_patch(body))
        return _clip_response(security, detail)

    @protected.post("/clips/{clip_id}/review", response_model=ClipDetailResponse)
    def review_clip(
        clip_id: str,
        body: ReviewActionRequest,
        request: Request,
    ) -> ClipDetailResponse:
        active = _runtime(request)
        _require_clip_access(active, _caller(request), clip_id)
        command = ReviewCommand(
            expected_revision=body.expected_revision,
            status=ReviewStatus(body.status),
            reason=body.reason,
        )
        if _review_contains_patch(body):
            detail = active.review_service.revise_and_review(
                clip_id,
                _review_patch(body),
                command,
            )
        else:
            detail = active.review_service.review_clip(clip_id, command)
        return _clip_response(security, detail)

    @protected.post(
        "/projects/{project_id}/reviews/batch",
        response_model=BatchReviewResponse,
    )
    def review_clips_batch(
        project_id: str,
        body: BatchReviewRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> BatchReviewResponse:
        caller = _caller(request)
        active = _runtime(request)
        _require_project_access(active, caller, project_id)
        canonical_items = sorted(
            (item.model_dump(mode="json") for item in body.items),
            key=lambda item: str(item["clip_id"]),
        )
        details = active.review_service.review_clips_batch(
            project_id,
            body.to_command(),
            idempotency=_idempotency(
                caller,
                idempotency_key,
                operation="POST:/api/v1/projects/:project_id/reviews/batch",
                payload={"project_id": project_id, "items": canonical_items},
            ),
        )
        return BatchReviewResponse(
            project_id=project_id,
            clips=tuple(_clip_response(security, detail) for detail in details),
        )

    @protected.post(
        "/clips/{clip_id}/render",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AcceptedTaskResponse,
    )
    def create_render(
        clip_id: str,
        body: RenderCreateRequest,
        response: Response,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AcceptedTaskResponse:
        caller = _caller(request)
        active = _runtime(request)
        _require_clip_access(active, caller, clip_id)
        queued = active.render_service.enqueue(
            clip_id,
            RenderRequest(expected_revision=body.expected_revision, kind=body.kind),
            idempotency=_idempotency(
                caller,
                idempotency_key,
                operation="POST:/api/v1/clips/:clip_id/render",
                payload={"clip_id": clip_id, **body.model_dump(mode="json")},
            ),
        )
        location = f"/api/v1/renders/{queued.render_id}"
        response.headers["Location"] = location
        response.headers["Retry-After"] = "1"
        return AcceptedTaskResponse(
            resource_type="render",
            resource_id=queued.render_id,
            task_id=queued.task_id,
            status=queued.status.value,
            status_url=location,
        )

    @protected.get("/renders/{render_id}", response_model=QueuedRender)
    def get_render(
        render_id: str,
        request: Request,
    ) -> QueuedRender:
        return _require_render_access(_runtime(request), _caller(request), render_id)

    @protected.post(
        "/projects/{project_id}/deliveries",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AcceptedTaskResponse,
    )
    def create_delivery(
        project_id: str,
        body: DeliveryCreateRequest,
        response: Response,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AcceptedTaskResponse:
        caller = _caller(request)
        active = _runtime(request)
        _require_project_access(active, caller, project_id)
        queued = active.delivery_service.enqueue(
            project_id,
            DeliveryRequest(include_zip=body.include_zip),
            idempotency=_idempotency(
                caller,
                idempotency_key,
                operation="POST:/api/v1/projects/:project_id/deliveries",
                payload={"project_id": project_id, **body.model_dump(mode="json")},
            ),
        )
        location = f"/api/v1/deliveries/{queued.delivery_id}"
        response.headers["Location"] = location
        response.headers["Retry-After"] = "1"
        return AcceptedTaskResponse(
            resource_type="delivery",
            resource_id=queued.delivery_id,
            task_id=queued.task_id,
            status=queued.status.value,
            status_url=location,
        )

    @protected.get(
        "/projects/{project_id}/deliveries",
        response_model=list[DeliveryDetailResponse],
    )
    def list_deliveries(
        project_id: str,
        request: Request,
    ) -> list[DeliveryDetailResponse]:
        active = _runtime(request)
        _require_project_access(active, _caller(request), project_id)
        return [
            _delivery_response(security, item) for item in active.delivery_service.list(project_id)
        ]

    @protected.get("/deliveries/{delivery_id}", response_model=DeliveryDetailResponse)
    def get_delivery(
        delivery_id: str,
        request: Request,
    ) -> DeliveryDetailResponse:
        return _delivery_response(
            security,
            _require_delivery_access(_runtime(request), _caller(request), delivery_id),
        )

    app.include_router(protected)

    @app.get("/api/v1/media/{asset_id}")
    def get_media(
        asset_id: str,
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
        expires: Annotated[int | None, Query(ge=0)] = None,
        signature: Annotated[str | None, Query(min_length=64, max_length=64)] = None,
    ) -> Response:
        security.authorize_resource(
            path=f"/api/v1/media/{asset_id}",
            resource=f"asset:{asset_id}",
            authorization=authorization,
            expires=expires,
            signature=signature,
        )
        asset = _runtime(request).media_asset_service.resolve(asset_id)
        return stream_asset_response(asset, range_header=range_header)

    @app.get("/api/v1/deliveries/{delivery_id}/download")
    def download_delivery(
        delivery_id: str,
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
        expires: Annotated[int | None, Query(ge=0)] = None,
        signature: Annotated[str | None, Query(min_length=64, max_length=64)] = None,
    ) -> Response:
        security.authorize_resource(
            path=f"/api/v1/deliveries/{delivery_id}/download",
            resource=f"delivery:{delivery_id}",
            authorization=authorization,
            expires=expires,
            signature=signature,
        )
        active = _runtime(request)
        delivery = active.delivery_service.get(delivery_id)
        if delivery.zip_asset_id is None or delivery.status.value != "succeeded":
            raise DeliveryConflict("delivery ZIP is not available")
        asset = active.media_asset_service.resolve(
            delivery.zip_asset_id,
            required_kind="delivery_zip",
        )
        return stream_asset_response(
            asset,
            range_header=range_header,
            download_filename=f"liveclip-{delivery.delivery_version}.zip",
        )

    return app


def _runtime(request: Request) -> LiveClipRuntime:
    value = getattr(request.app.state, "runtime", None)
    if not isinstance(value, LiveClipRuntime):
        raise RuntimeError("LiveClip runtime is not initialized")
    return value


def _caller(request: Request) -> AuthenticatedCaller:
    value = getattr(request.state, "authenticated_caller", None)
    if not isinstance(value, AuthenticatedCaller):
        raise ApiAuthenticationError("authenticated caller is unavailable")
    return value


def _pipeline_config(
    settings: Settings,
    body: JobCreateRequest | RunCreateRequest,
    *,
    run_scope: Literal["full", "import"] = "full",
) -> PipelineRunConfig:
    return pipeline_config_from_settings(
        settings,
        run_scope=run_scope,
        top_n=body.top_n,
        minimum_clip_seconds=body.minimum_clip_seconds,
        maximum_clip_seconds=body.maximum_clip_seconds,
    )


def _idempotency(
    caller: AuthenticatedCaller,
    raw_key: str | None,
    *,
    operation: str,
    payload: object,
) -> IdempotencyContext | None:
    if raw_key is None:
        return None
    return build_idempotency_context(
        raw_key=raw_key,
        caller_scope=caller.caller_scope,
        operation_scope=operation,
        request_payload=payload,
    )


def _require_project_access(
    runtime: LiveClipRuntime,
    caller: AuthenticatedCaller,
    project_id: str,
) -> WorkspaceUser:
    user = runtime.workspace_service.get_user_by_username(caller.username)
    runtime.pipeline_service.get_project(project_id, user_id=user.user_id)
    return user


def _require_run_access(
    runtime: LiveClipRuntime,
    caller: AuthenticatedCaller,
    run_id: str,
) -> RunSnapshot:
    run = runtime.pipeline_service.get_run(run_id)
    _require_project_access(runtime, caller, run.project_id)
    return run


def _require_clip_access(
    runtime: LiveClipRuntime,
    caller: AuthenticatedCaller,
    clip_id: str,
) -> ClipDetail:
    clip = runtime.review_service.get_clip(clip_id)
    _require_project_access(runtime, caller, clip.project_id)
    return clip


def _require_render_access(
    runtime: LiveClipRuntime,
    caller: AuthenticatedCaller,
    render_id: str,
) -> QueuedRender:
    render = runtime.render_service.get(render_id)
    clip = runtime.review_service.get_clip(render.clip_id)
    _require_project_access(runtime, caller, clip.project_id)
    return render


def _require_delivery_access(
    runtime: LiveClipRuntime,
    caller: AuthenticatedCaller,
    delivery_id: str,
) -> DeliverySnapshot:
    delivery = runtime.delivery_service.get(delivery_id)
    _require_project_access(runtime, caller, delivery.project_id)
    return delivery


def _clip_patch(body: ClipPatchRequest) -> ClipPatch:
    return ClipPatch(
        expected_revision=body.expected_revision,
        source_start_ms=body.source_start_ms,
        source_end_ms=body.source_end_ms,
        title=body.title,
        layout=body.layout,
        captions=(
            tuple(caption.to_domain() for caption in body.captions)
            if body.captions is not None
            else None
        ),
    )


def _review_contains_patch(body: ReviewActionRequest) -> bool:
    return any(
        value is not None
        for value in (
            body.source_start_ms,
            body.source_end_ms,
            body.title,
            body.layout,
            body.captions,
        )
    )


def _review_patch(body: ReviewActionRequest) -> ClipPatch:
    return ClipPatch(
        expected_revision=body.expected_revision,
        source_start_ms=body.source_start_ms,
        source_end_ms=body.source_end_ms,
        title=body.title,
        layout=body.layout,
        captions=(
            tuple(caption.to_domain() for caption in body.captions)
            if body.captions is not None
            else None
        ),
    )


def _asset_url(security: ApiSecurity, asset_id: str) -> str:
    return security.signed_url(
        path=f"/api/v1/media/{asset_id}",
        resource=f"asset:{asset_id}",
    )


def _clip_response(security: ApiSecurity, detail: ClipDetail) -> ClipDetailResponse:
    asset_ids = {
        asset_id
        for render in detail.renders
        for asset_id in (
            render.video_asset_id,
            render.subtitle_asset_id,
            render.contact_sheet_asset_id,
        )
        if asset_id is not None
    }
    return ClipDetailResponse(
        clip=detail,
        asset_urls={asset_id: _asset_url(security, asset_id) for asset_id in sorted(asset_ids)},
    )


def _delivery_response(
    security: ApiSecurity,
    delivery: DeliverySnapshot,
) -> DeliveryDetailResponse:
    download_url = None
    if delivery.status.value == "succeeded" and delivery.zip_asset_id is not None:
        download_url = security.signed_url(
            path=f"/api/v1/deliveries/{delivery.delivery_id}/download",
            resource=f"delivery:{delivery.delivery_id}",
        )
    return DeliveryDetailResponse(delivery=delivery, download_url=download_url)


def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def framework_http_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if exc.status_code == 404:
            code = "RESOURCE_NOT_FOUND"
            message = "The requested LiveClip resource does not exist"
        elif exc.status_code == 405:
            code = "METHOD_NOT_ALLOWED"
            message = "The HTTP method is not allowed for this LiveClip resource"
        else:
            code = "HTTP_REQUEST_REJECTED"
            message = "The HTTP request could not be completed"
        safe_headers = {
            key: value
            for key, value in (exc.headers or {}).items()
            if key.lower() in {"allow", "retry-after", "www-authenticate"}
        }
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            headers=safe_headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = tuple(
            ApiErrorItem(
                location=tuple(
                    value if isinstance(value, (str, int)) else str(value)
                    for value in item.get("loc", ())
                ),
                type=str(item.get("type", "validation_error")),
            )
            for item in exc.errors()
        )
        return _error_response(
            request,
            status_code=422,
            code="INVALID_REQUEST",
            message="Request validation failed",
            details=details,
        )

    @app.exception_handler(ApiAuthenticationError)
    async def authentication_handler(
        request: Request,
        _exc: ApiAuthenticationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="Valid Bearer authorization or signed media access is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(WorkspacePermissionDenied)
    async def workspace_permission_handler(
        request: Request,
        _exc: WorkspacePermissionDenied,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=403,
            code="PROJECT_PERMISSION_DENIED",
            message="Only the project owner can manage project members",
        )

    @app.exception_handler(MediaRangeNotSatisfiable)
    async def media_range_handler(
        request: Request,
        exc: MediaRangeNotSatisfiable,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=416,
            code="RANGE_NOT_SATISFIABLE",
            message="The requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{exc.size_bytes}"},
        )

    @app.exception_handler(LookupError)
    async def not_found_handler(request: Request, _exc: LookupError) -> JSONResponse:
        return _error_response(
            request,
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message="The requested LiveClip resource does not exist",
        )

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict_handler(
        request: Request,
        _exc: IdempotencyConflict,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="Idempotency-Key was already used for a different request",
        )

    @app.exception_handler(PipelineConflict)
    @app.exception_handler(ReviewConflict)
    @app.exception_handler(RenderConflict)
    @app.exception_handler(DeliveryConflict)
    async def state_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
        message = str(exc).strip()
        return _error_response(
            request,
            status_code=409,
            code="STATE_CONFLICT",
            message=message if 0 < len(message) <= 500 else "Resource state conflicts with request",
        )

    @app.exception_handler(MediaAssetInvalid)
    async def invalid_asset_handler(request: Request, _exc: MediaAssetInvalid) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            code="ASSET_INTEGRITY_FAILED",
            message="The generated asset failed local integrity verification",
        )

    @app.exception_handler(OperationalError)
    async def operational_error_handler(
        request: Request,
        exc: OperationalError,
    ) -> JSONResponse:
        category = str(exc.orig).lower()
        if "locked" in category or "busy" in category:
            return _error_response(
                request,
                status_code=503,
                code="LOCAL_STORAGE_BUSY",
                message="LiveClip local storage is busy; retry shortly",
                retryable=True,
                headers={"Retry-After": "1"},
            )
        return _error_response(
            request,
            status_code=500,
            code="LOCAL_STORAGE_ERROR",
            message="LiveClip local storage could not complete the request",
        )

    @app.exception_handler(MediaIngestError)
    async def ingest_handler(request: Request, exc: MediaIngestError) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="INVALID_SOURCE_MEDIA",
            message=str(exc),
        )

    @app.exception_handler(ProviderNotReady)
    async def provider_not_ready_handler(
        request: Request,
        _exc: ProviderNotReady,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=503,
            code="PROVIDER_NOT_READY",
            message=(
                "Required ASR/LLM providers are not ready; inspect /api/v1/health "
                "and run liveclip doctor"
            ),
        )

    @app.exception_handler(ValidationError)
    @app.exception_handler(ValueError)
    async def domain_validation_handler(request: Request, _exc: Exception) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="DOMAIN_VALIDATION_FAILED",
            message="The request violates LiveClip validation rules",
        )

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled API error class=%s correlation_id=%s",
            exc.__class__.__name__,
            _correlation_id(request),
        )
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="LiveClip could not complete the request",
        )


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    resource_id: str | None = None,
    details: tuple[ApiErrorItem, ...] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    envelope = ApiErrorEnvelope(
        error=ApiErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            resource_id=resource_id,
            correlation_id=_correlation_id(request),
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


def _correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", None)
    return str(value) if value else uuid.uuid4().hex
