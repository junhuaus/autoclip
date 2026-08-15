from __future__ import annotations

import logging
import os
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from liveclip.application.clips import ClipQueryService
from liveclip.application.deliveries import DeliveryService
from liveclip.application.delivery_runner import DeliveryTaskRunner
from liveclip.application.edit_packages import EditPackageService
from liveclip.application.identity import AuthenticationService, UserAdministrationService
from liveclip.application.media_assets import MediaAssetService
from liveclip.application.offline_review import OfflineReviewPackageService
from liveclip.application.pipeline import PipelineRunConfig, PipelineService
from liveclip.application.projects import ProjectManagementService
from liveclip.application.render_runner import RenderTaskRunner
from liveclip.application.rendering import RenderProfile, RenderService
from liveclip.application.reviewing import ReviewService
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.application.workspace import WorkspaceService
from liveclip.config import Settings
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.clip_repository import SqlAlchemyClipQueryRepository
from liveclip.db.delivery_repository import SqlAlchemyDeliveryRepository
from liveclip.db.edit_package_repository import SqlAlchemyEditPackageRepository
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.identity_repository import SqlAlchemyIdentityRepository
from liveclip.db.media_repository import SqlAlchemyMediaAssetRepository
from liveclip.db.offline_review_repository import SqlAlchemyOfflineReviewFenceRepository
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.project_repository import SqlAlchemyProjectManagementRepository
from liveclip.db.render_repository import SqlAlchemyRenderRepository
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.db.workspace_repository import SqlAlchemyWorkspaceRepository
from liveclip.delivery.edit_package_task_handler import EditPackageTaskHandler
from liveclip.delivery.task_handler import DeliveryTaskHandler
from liveclip.domain.edit_plan import EDIT_PLAN_PIPELINE_CONTRACT_VERSION
from liveclip.observability import configure_logging
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.prompts import load_editing_prompts
from liveclip.providers.asr.mock import MOCK_ASR_CONTRACT_VERSION
from liveclip.providers.asr.openai import OPENAI_ASR_CONTRACT_VERSION
from liveclip.providers.asr.openrouter import OPENROUTER_ASR_CONTRACT_VERSION
from liveclip.providers.llm.base import (
    EDITORIAL_SUGGESTION_SCHEMA_VERSION,
    MOCK_LLM_CONTRACT_VERSION,
    mock_prompt_sha256,
)
from liveclip.providers.llm.codex import (
    CODEX_LLM_UNPROBED_CONTRACT,
    codex_cli_contract_version,
)
from liveclip.providers.llm.openai import OPENAI_LLM_CONTRACT_VERSION
from liveclip.renderer.task_handler import RenderTaskHandler
from liveclip.services.janitor import cleanup_terminal_attempt_worktrees

_LOGGER = logging.getLogger(__name__)


class BootstrapError(RuntimeError):
    pass


@dataclass(slots=True)
class LiveClipRuntime:
    settings: Settings
    data_dir: Path
    database_path: Path
    engine: Engine
    pipeline_repository: SqlAlchemyPipelineRepository
    pipeline_service: PipelineService
    project_management_service: ProjectManagementService
    task_queue: SQLiteTaskQueue
    stage_runner: StageTaskRunner
    clip_query_service: ClipQueryService
    review_service: ReviewService
    render_service: RenderService
    render_runner: RenderTaskRunner
    delivery_service: DeliveryService
    edit_package_service: EditPackageService
    delivery_runner: DeliveryTaskRunner
    media_asset_service: MediaAssetService
    offline_review_package_service: OfflineReviewPackageService
    workspace_service: WorkspaceService
    authentication_service: AuthenticationService
    user_administration_service: UserAdministrationService

    @classmethod
    def open(
        cls,
        settings: Settings,
        *,
        project_root: Path | None = None,
    ) -> LiveClipRuntime:
        configure_logging(settings.log_level)
        data_dir = settings.resolved_data_dir(project_root or Path.cwd())
        data_dir.mkdir(parents=True, exist_ok=True)
        database_path = data_dir / "liveclip.sqlite3"
        engine = create_sqlite_engine(database_path)
        try:
            upgrade_database(
                engine,
                project_root=project_root or _installed_project_root(),
            )
            cleanup_report = cleanup_terminal_attempt_worktrees(engine, data_dir=data_dir)
            if cleanup_report.failed:
                _LOGGER.warning(
                    "attempt_janitor incomplete inspected=%s cleaned=%s failed=%s",
                    cleanup_report.inspected,
                    cleanup_report.cleaned,
                    cleanup_report.failed,
                )
            repository = SqlAlchemyPipelineRepository(engine)
            service = PipelineService(repository)
            project_management_service = ProjectManagementService(
                SqlAlchemyProjectManagementRepository(engine)
            )
            workspace_service = WorkspaceService(SqlAlchemyWorkspaceRepository(engine))
            workspace_service.ensure_configured_users(
                tuple(dict.fromkeys((settings.workspace_username, *settings.workspace_tokens)))
            )
            identity_repository = SqlAlchemyIdentityRepository(engine)
            user_administration_service = UserAdministrationService(identity_repository)
            bootstrap_secret = (
                settings.bootstrap_admin_password.get_secret_value().strip()
                if settings.bootstrap_admin_password is not None
                else ""
            )
            user_administration_service.bootstrap(
                username=settings.workspace_username,
                password=bootstrap_secret or None,
            )
            authentication_service = AuthenticationService(
                identity_repository,
                session_ttl=timedelta(hours=settings.session_ttl_hours),
            )
            queue = SQLiteTaskQueue(
                engine,
                lease_seconds=settings.worker_lease_seconds,
            )
            asset_store = SqlAlchemyAssetStore(engine)
            stage_state_store = SqlAlchemyStageStateStore(engine)
            handlers = PipelineStageHandlers(
                data_dir=data_dir,
                allowed_media_roots=tuple(settings.allowed_media_roots),
                assets=asset_store,
                state=stage_state_store,
                openai_api_key=(
                    settings.openai_api_key.get_secret_value().strip()
                    if settings.ai_provider in {"openai", "openai-codex"}
                    and settings.openai_api_key is not None
                    else None
                ),
                openrouter_api_key=(
                    settings.openrouter_api_key.get_secret_value().strip()
                    if settings.ai_provider == "openrouter-codex"
                    and settings.openrouter_api_key is not None
                    else None
                ),
                openrouter_base_url=settings.openrouter_base_url,
                codex_executable=settings.codex_executable,
                runtime_provider=settings.ai_provider,
            )
            runner = StageTaskRunner(
                queue=queue,
                repository=repository,
                pipeline_service=service,
                handler=handlers,
                heartbeat_seconds=settings.worker_heartbeat_seconds,
            )
            clip_query_service = ClipQueryService(SqlAlchemyClipQueryRepository(engine))
            review_service = ReviewService(SqlAlchemyReviewRepository(engine))
            render_repository = SqlAlchemyRenderRepository(engine)
            render_service = RenderService(
                render_repository,
                RenderProfile(
                    preview_width=settings.preview_render_width,
                    preview_height=settings.preview_render_height,
                    final_width=settings.final_render_width,
                    final_height=settings.final_render_height,
                    encoder=settings.video_encoder,
                    max_retries=settings.max_stage_retries,
                ),
            )
            render_runner = RenderTaskRunner(
                queue=queue,
                repository=render_repository,
                handler=RenderTaskHandler(data_dir=data_dir, assets=asset_store),
                heartbeat_seconds=settings.worker_heartbeat_seconds,
            )
            delivery_repository = SqlAlchemyDeliveryRepository(engine)
            delivery_service = DeliveryService(
                delivery_repository,
                max_retries=settings.max_stage_retries,
            )
            edit_package_repository = SqlAlchemyEditPackageRepository(engine)
            edit_package_service = EditPackageService(
                edit_package_repository,
                clip_query_service,
                max_retries=settings.max_stage_retries,
            )
            delivery_runner = DeliveryTaskRunner(
                queue=queue,
                repository=delivery_repository,
                handler=DeliveryTaskHandler(data_dir=data_dir, assets=asset_store),
                heartbeat_seconds=settings.worker_heartbeat_seconds,
                edit_package_repository=edit_package_repository,
                edit_package_handler=EditPackageTaskHandler(
                    data_dir=data_dir,
                    assets=asset_store,
                    publication_fence=edit_package_repository.assert_edit_package_current,
                ),
            )
            media_asset_service = MediaAssetService(
                SqlAlchemyMediaAssetRepository(engine),
                data_dir=data_dir,
            )
            offline_review_package_service = OfflineReviewPackageService(
                pipeline=service,
                clips=clip_query_service,
                source_media=stage_state_store,
                media_assets=media_asset_service,
                fence_repository=SqlAlchemyOfflineReviewFenceRepository(engine),
                data_dir=data_dir,
            )
            return cls(
                settings=settings,
                data_dir=data_dir,
                database_path=database_path,
                engine=engine,
                pipeline_repository=repository,
                pipeline_service=service,
                project_management_service=project_management_service,
                task_queue=queue,
                stage_runner=runner,
                clip_query_service=clip_query_service,
                review_service=review_service,
                render_service=render_service,
                render_runner=render_runner,
                delivery_service=delivery_service,
                edit_package_service=edit_package_service,
                delivery_runner=delivery_runner,
                media_asset_service=media_asset_service,
                offline_review_package_service=offline_review_package_service,
                workspace_service=workspace_service,
                authentication_service=authentication_service,
                user_administration_service=user_administration_service,
            )
        except Exception:
            engine.dispose(close=True)
            raise

    def close(self) -> None:
        self.engine.dispose(close=True)

    def __enter__(self) -> LiveClipRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def upgrade_database(engine: Engine, *, project_root: Path | None = None) -> None:
    root = (project_root or _installed_project_root()).resolve(strict=True)
    alembic_path = root / "alembic.ini"
    if not alembic_path.is_file():
        raise BootstrapError("alembic.ini is not available for database initialization")
    config = Config(str(alembic_path))
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def pipeline_config_from_settings(
    settings: Settings,
    *,
    run_scope: Literal["full", "import"] = "full",
    top_n: int | None = None,
    minimum_clip_seconds: int | None = None,
    maximum_clip_seconds: int | None = None,
) -> PipelineRunConfig:
    provider = settings.ai_provider
    mock_asr = provider in {"mock", "mock-codex"}
    openrouter_asr = provider == "openrouter-codex"
    codex_llm = provider in {"mock-codex", "openai-codex", "openrouter-codex"}
    mock_llm = provider == "mock"
    transcription_model = (
        "mock-asr-v1"
        if mock_asr
        else settings.openrouter_asr_model
        if openrouter_asr
        else settings.transcription_model
    )
    llm_model = "mock-llm-v1" if mock_llm else settings.llm_model
    asr_contract_version = (
        MOCK_ASR_CONTRACT_VERSION
        if mock_asr
        else OPENROUTER_ASR_CONTRACT_VERSION
        if openrouter_asr
        else OPENAI_ASR_CONTRACT_VERSION
    )
    if mock_llm:
        llm_contract_version = MOCK_LLM_CONTRACT_VERSION
        editing_prompt_version = "editing_v1"
        editing_prompt_sha256 = mock_prompt_sha256(editing_prompt_version)
    else:
        prompts = load_editing_prompts()
        llm_contract_version = (
            (
                CODEX_LLM_UNPROBED_CONTRACT
                if run_scope == "import"
                else codex_cli_contract_version(settings.codex_executable)
            )
            if codex_llm
            else OPENAI_LLM_CONTRACT_VERSION
        )
        editing_prompt_version = prompts.version
        editing_prompt_sha256 = prompts.sha256
    return PipelineRunConfig(
        run_scope=run_scope,
        provider=provider,
        top_n=top_n if top_n is not None else settings.default_top_n,
        minimum_clip_ms=(
            minimum_clip_seconds if minimum_clip_seconds is not None else settings.min_clip_seconds
        )
        * 1_000,
        maximum_clip_ms=(
            maximum_clip_seconds if maximum_clip_seconds is not None else settings.max_clip_seconds
        )
        * 1_000,
        chunk_duration_ms=settings.asr_chunk_seconds * 1_000,
        chunk_overlap_ms=settings.asr_chunk_overlap_seconds * 1_000,
        max_chunk_bytes=settings.asr_max_chunk_bytes,
        transcription_model=transcription_model,
        llm_model=llm_model,
        preview_width=settings.preview_render_width,
        preview_height=settings.preview_render_height,
        video_encoder=settings.video_encoder,
        asr_concurrency=settings.asr_concurrency,
        asr_vocabulary_prompt=settings.asr_vocabulary_prompt,
        openai_request_timeout_seconds=settings.openai_request_timeout_seconds,
        openai_max_request_retries=settings.openai_max_request_retries,
        openai_retry_base_seconds=settings.openai_retry_base_seconds,
        openai_retry_max_seconds=settings.openai_retry_max_seconds,
        llm_input_price_per_million=(
            settings.llm_input_price_per_million if provider == "openai" else None
        ),
        llm_output_price_per_million=(
            settings.llm_output_price_per_million if provider == "openai" else None
        ),
        asr_contract_version=asr_contract_version,
        llm_contract_version=llm_contract_version,
        editing_prompt_version=editing_prompt_version,
        editing_prompt_sha256=editing_prompt_sha256,
        editorial_schema_version=EDITORIAL_SUGGESTION_SCHEMA_VERSION,
        edit_plan_schema_version=EDIT_PLAN_PIPELINE_CONTRACT_VERSION,
    )


def local_worker_id(prefix: str = "worker") -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_.:-]", "-", prefix)[:30] or "worker"
    host = re.sub(r"[^A-Za-z0-9_.:-]", "-", socket.gethostname())[:30] or "local"
    return f"{safe_prefix}:{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"[:100]


def _installed_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
