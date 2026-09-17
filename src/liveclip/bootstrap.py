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
from liveclip.application.comments import ClipCommentService
from liveclip.application.completion_runner import CompletionRunner
from liveclip.application.completion_service import CompletionService
from liveclip.application.deliveries import DeliveryService
from liveclip.application.delivery_runner import DeliveryTaskRunner
from liveclip.application.edit_packages import EditPackageService
from liveclip.application.governance import ProjectGovernanceService
from liveclip.application.identity import AuthenticationService, UserAdministrationService
from liveclip.application.media_assets import MediaAssetService
from liveclip.application.offline_review import OfflineReviewPackageService
from liveclip.application.pipeline import (
    ActionReadiness,
    PipelineCapability,
    PipelineConfig,
    PipelineRunConfigV12,
    PipelineRunConfigV13,
    PipelineService,
)
from liveclip.application.project_discovery import ProjectDiscoveryService
from liveclip.application.projects import ProjectManagementService
from liveclip.application.releases import ReleaseService
from liveclip.application.render_runner import RenderTaskRunner
from liveclip.application.rendering import RenderProfile, RenderService
from liveclip.application.reviewing import ReviewService
from liveclip.application.selection import SelectionService
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.application.storage import StorageAdministrationService
from liveclip.application.workspace import WorkspaceService
from liveclip.clipping_skills import (
    load_semantic_continuous_skill,
    load_semantic_discovery_skill,
)
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_global_v3 import (
    load_semantic_global_v3_boundary_prompt,
    load_semantic_global_v3_review_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v1 import (
    load_semantic_topic_chain_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v2 import (
    load_semantic_topic_chain_prompt as load_lineage_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v2 import (
    load_semantic_windowed_v2_discovery_prompt,
)
from liveclip.config import Settings
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.clip_repository import SqlAlchemyClipQueryRepository
from liveclip.db.comment_repository import SqlAlchemyClipCommentRepository
from liveclip.db.completion_repository import SqlAlchemyCompletionRepository
from liveclip.db.delivery_repository import SqlAlchemyDeliveryRepository
from liveclip.db.edit_package_repository import SqlAlchemyEditPackageRepository
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.governance_repository import SqlAlchemyProjectGovernanceRepository
from liveclip.db.identity_repository import SqlAlchemyIdentityRepository
from liveclip.db.media_repository import SqlAlchemyMediaAssetRepository
from liveclip.db.offline_review_repository import SqlAlchemyOfflineReviewFenceRepository
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.project_discovery_repository import SqlAlchemyProjectDiscoveryRepository
from liveclip.db.project_repository import SqlAlchemyProjectManagementRepository
from liveclip.db.release_repository import SqlAlchemyReleaseRepository
from liveclip.db.render_repository import SqlAlchemyRenderRepository
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.storage_repository import (
    SqlAlchemyStorageAdministrationRepository,
    recover_interrupted_project_purges,
)
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.db.workspace_repository import SqlAlchemyWorkspaceRepository
from liveclip.delivery.edit_package_task_handler import EditPackageTaskHandler
from liveclip.delivery.release_package_task_handler import ReleasePackageTaskHandler
from liveclip.delivery.task_handler import DeliveryTaskHandler
from liveclip.domain.clip_profile import ClipProfile, clip_profile_spec
from liveclip.domain.edit_plan import EDIT_PLAN_PIPELINE_CONTRACT_VERSION
from liveclip.observability import configure_logging
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.prompts import load_editing_prompts
from liveclip.providers.asr.mlx import (
    MLX_ASR_MODEL,
    MLX_ASR_UNPROBED_CONTRACT,
    inspect_mlx_model,
)
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
from liveclip.providers.readiness import require_action_readiness
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
    project_discovery_service: ProjectDiscoveryService
    project_management_service: ProjectManagementService
    task_queue: SQLiteTaskQueue
    stage_runner: StageTaskRunner
    clip_query_service: ClipQueryService
    clip_comment_service: ClipCommentService
    review_service: ReviewService
    selection_service: SelectionService
    render_service: RenderService
    render_runner: RenderTaskRunner
    delivery_service: DeliveryService
    edit_package_service: EditPackageService
    release_service: ReleaseService
    delivery_runner: DeliveryTaskRunner
    completion_runner: CompletionRunner
    completion_service: CompletionService
    media_asset_service: MediaAssetService
    offline_review_package_service: OfflineReviewPackageService
    workspace_service: WorkspaceService
    authentication_service: AuthenticationService
    user_administration_service: UserAdministrationService
    project_governance_service: ProjectGovernanceService
    storage_administration_service: StorageAdministrationService

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
            purge_recovery = recover_interrupted_project_purges(engine, data_dir=data_dir)
            if purge_recovery[2]:
                _LOGGER.warning(
                    "project_purge_recovery incomplete inspected=%s recovered=%s failed=%s",
                    *purge_recovery,
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

            def check_actions(
                config: PipelineConfig, required: tuple[PipelineCapability, ...]
            ) -> ActionReadiness:
                return require_action_readiness(settings, config, required)

            service = PipelineService(
                repository,
                forbidden_source_roots=(data_dir,),
                readiness_check=check_actions,
            )
            project_management_service = ProjectManagementService(
                SqlAlchemyProjectManagementRepository(engine)
            )
            project_discovery_service = ProjectDiscoveryService(
                SqlAlchemyProjectDiscoveryRepository(engine),
                service,
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
            project_governance_service = ProjectGovernanceService(
                SqlAlchemyProjectGovernanceRepository(engine)
            )
            queue = SQLiteTaskQueue(
                engine,
                lease_seconds=settings.worker_lease_seconds,
                data_dir=data_dir,
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
                mlx_asr_model_path=settings.resolved_mlx_asr_model_path(
                    project_root or _installed_project_root()
                ),
                codex_executable=settings.codex_executable,
                runtime_provider=settings.ai_provider,
                readiness_check=check_actions,
            )
            runner = StageTaskRunner(
                queue=queue,
                repository=repository,
                pipeline_service=service,
                handler=handlers,
                heartbeat_seconds=settings.worker_heartbeat_seconds,
            )
            clip_query_service = ClipQueryService(SqlAlchemyClipQueryRepository(engine))
            clip_comment_service = ClipCommentService(SqlAlchemyClipCommentRepository(engine))
            review_service = ReviewService(SqlAlchemyReviewRepository(engine))
            selection_service = SelectionService(clip_query_service, review_service)
            render_repository = SqlAlchemyRenderRepository(engine)
            render_service = RenderService(
                render_repository,
                RenderProfile(
                    preview_width=settings.final_render_width,
                    preview_height=settings.final_render_height,
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
            release_repository = SqlAlchemyReleaseRepository(engine, data_dir=data_dir)
            release_service = ReleaseService(
                release_repository,
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
                release_repository=release_repository,
                release_package_handler=ReleasePackageTaskHandler(
                    data_dir=data_dir,
                    assets=asset_store,
                    publication_fence=release_repository.assert_release_package_current,
                ),
            )
            completion_repository = SqlAlchemyCompletionRepository(
                engine,
                data_dir=data_dir,
                delivery_max_retries=settings.max_stage_retries,
            )
            completion_runner = CompletionRunner(queue, completion_repository)
            completion_service = CompletionService(
                completion_repository,
                allowed_source_roots=settings.allowed_media_roots,
                forbidden_source_roots=(data_dir,),
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
            storage_administration_service = StorageAdministrationService(
                SqlAlchemyStorageAdministrationRepository(engine, data_dir=data_dir)
            )
            return cls(
                settings=settings,
                data_dir=data_dir,
                database_path=database_path,
                engine=engine,
                pipeline_repository=repository,
                pipeline_service=service,
                project_discovery_service=project_discovery_service,
                project_management_service=project_management_service,
                task_queue=queue,
                stage_runner=runner,
                clip_query_service=clip_query_service,
                clip_comment_service=clip_comment_service,
                review_service=review_service,
                selection_service=selection_service,
                render_service=render_service,
                render_runner=render_runner,
                delivery_service=delivery_service,
                edit_package_service=edit_package_service,
                release_service=release_service,
                delivery_runner=delivery_runner,
                completion_runner=completion_runner,
                completion_service=completion_service,
                media_asset_service=media_asset_service,
                offline_review_package_service=offline_review_package_service,
                workspace_service=workspace_service,
                authentication_service=authentication_service,
                user_administration_service=user_administration_service,
                project_governance_service=project_governance_service,
                storage_administration_service=storage_administration_service,
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
    clipping_algorithm: Literal[
        "a", "b", "b_v2_experimental", "semantic_global", "semantic_windowed"
    ] = "a",
    semantic_target_clip_seconds: int | None = None,
    semantic_score_threshold: float | None = None,
    semantic_profile: Literal["general", "vocal_coach_live"] = "general",
    clip_profile: ClipProfile = ClipProfile.SHORT_HIGHLIGHT,
    semantic_full_context_budget_ratio: float = 0.58,
    semantic_model_context_tokens: int = 128_000,
    semantic_no_render: bool = False,
    semantic_prompt_debug: bool = False,
) -> PipelineConfig:
    provider = settings.ai_provider
    mock_asr = provider in {"mock", "mock-codex"}
    openrouter_asr = provider == "openrouter-codex"
    mlx_asr = provider == "mlx-codex"
    codex_llm = provider in {
        "mock-codex",
        "openai-codex",
        "openrouter-codex",
        "mlx-codex",
    }
    mock_llm = provider == "mock"
    transcription_model = (
        "mock-asr-v1"
        if mock_asr
        else settings.openrouter_asr_model
        if openrouter_asr
        else MLX_ASR_MODEL
        if mlx_asr
        else settings.transcription_model
    )
    llm_model = "mock-llm-v1" if mock_llm else settings.llm_model
    asr_contract_version = (
        MOCK_ASR_CONTRACT_VERSION
        if mock_asr
        else OPENROUTER_ASR_CONTRACT_VERSION
        if openrouter_asr
        else (
            MLX_ASR_UNPROBED_CONTRACT
            if run_scope == "import"
            else inspect_mlx_model(settings.resolved_mlx_asr_model_path()).contract_version
        )
        if mlx_asr
        else OPENAI_ASR_CONTRACT_VERSION
    )
    if mock_llm:
        llm_contract_version = MOCK_LLM_CONTRACT_VERSION
    else:
        llm_contract_version = (
            (
                CODEX_LLM_UNPROBED_CONTRACT
                if run_scope == "import"
                else codex_cli_contract_version(settings.codex_executable)
            )
            if codex_llm
            else OPENAI_LLM_CONTRACT_VERSION
        )
    semantic_v1_skill = load_semantic_discovery_skill("semantic_window_v1")
    semantic_v2_skill = load_semantic_discovery_skill("semantic_window_v2")
    consolidation_skill = load_semantic_continuous_skill()
    topic_chain_prompts = {
        stage: load_semantic_topic_chain_prompt(stage, semantic_profile, clip_profile)
        for stage in (
            "discovery",
            "link_review",
            "topic_chain",
            "boundary_review",
            "global_review",
        )
    }
    if clip_profile == ClipProfile.MINI_LESSON:
        topic_chain_prompts.update(
            {
                "discovery": load_lineage_prompt("discovery", semantic_profile, clip_profile),
                "topic_chain": load_lineage_prompt("topic_chain", semantic_profile, clip_profile),
                "boundary_review": load_lineage_prompt(
                    "boundary_review", semantic_profile, clip_profile
                ),
            }
        )
    global_discovery = load_semantic_global_prompt("discovery", semantic_profile)
    global_review = (
        topic_chain_prompts["global_review"]
        if clip_profile == ClipProfile.MINI_LESSON
        else load_semantic_global_v3_review_prompt(semantic_profile)
    )
    boundary_review = (
        topic_chain_prompts["boundary_review"]
        if clip_profile == ClipProfile.MINI_LESSON
        else load_semantic_global_v3_boundary_prompt(semantic_profile)
    )
    windowed_discovery = (
        topic_chain_prompts["discovery"]
        if clip_profile == ClipProfile.MINI_LESSON
        else load_semantic_windowed_v2_discovery_prompt(semantic_profile)
    )
    if clipping_algorithm == "b":
        semantic_skill = semantic_v1_skill
        editing_prompt_version = semantic_skill.version
        editing_prompt_sha256 = semantic_skill.sha256
    elif clipping_algorithm == "b_v2_experimental":
        semantic_skill = semantic_v2_skill
        editing_prompt_version = semantic_skill.version
        editing_prompt_sha256 = semantic_skill.sha256
    elif clipping_algorithm == "semantic_global":
        semantic_skill = semantic_v1_skill
        editing_prompt_version = f"{global_discovery.version}.discovery"
        editing_prompt_sha256 = global_discovery.sha256
    elif clipping_algorithm == "semantic_windowed":
        semantic_skill = semantic_v1_skill
        editing_prompt_version = f"{windowed_discovery.version}.discovery"
        editing_prompt_sha256 = windowed_discovery.sha256
    elif mock_llm:
        semantic_skill = semantic_v1_skill
        editing_prompt_version = "editing_v1"
        editing_prompt_sha256 = mock_prompt_sha256(editing_prompt_version)
    else:
        semantic_skill = semantic_v1_skill
        prompts = load_editing_prompts()
        editing_prompt_version = prompts.version
        editing_prompt_sha256 = prompts.sha256
    profile_spec = clip_profile_spec(clip_profile)
    if clip_profile == ClipProfile.MINI_LESSON and (
        (minimum_clip_seconds is not None and minimum_clip_seconds != 90)
        or (maximum_clip_seconds is not None and maximum_clip_seconds != 300)
        or (semantic_target_clip_seconds is not None and semantic_target_clip_seconds != 180)
    ):
        raise ValueError("mini_lesson uses fixed 90/180/300 second duration bounds")
    resolved_minimum_clip_seconds = (
        minimum_clip_seconds
        if minimum_clip_seconds is not None
        else profile_spec.minimum_duration_ms // 1_000
        if clip_profile == ClipProfile.MINI_LESSON
        else 45
        if clipping_algorithm in {"semantic_global", "semantic_windowed"}
        else 8
        if clipping_algorithm in {"b", "b_v2_experimental"}
        else settings.min_clip_seconds
    )
    resolved_maximum_clip_seconds = (
        maximum_clip_seconds
        if maximum_clip_seconds is not None
        else profile_spec.maximum_duration_ms // 1_000
        if clip_profile == ClipProfile.MINI_LESSON
        else 90
        if clipping_algorithm in {"b_v2_experimental", "semantic_global", "semantic_windowed"}
        else 60
        if clipping_algorithm == "b"
        else settings.max_clip_seconds
    )
    resolved_semantic_target_seconds = (
        semantic_target_clip_seconds
        if semantic_target_clip_seconds is not None
        else profile_spec.target_duration_ms // 1_000
        if clip_profile == ClipProfile.MINI_LESSON
        else min(max(60, resolved_minimum_clip_seconds), resolved_maximum_clip_seconds)
    )
    config_model = (
        PipelineRunConfigV13 if clip_profile == ClipProfile.MINI_LESSON else PipelineRunConfigV12
    )
    return config_model(
        run_scope=run_scope,
        provider=provider,
        top_n=top_n if top_n is not None else settings.default_top_n,
        minimum_clip_ms=resolved_minimum_clip_seconds * 1_000,
        maximum_clip_ms=resolved_maximum_clip_seconds * 1_000,
        chunk_duration_ms=settings.asr_chunk_seconds * 1_000,
        chunk_overlap_ms=settings.asr_chunk_overlap_seconds * 1_000,
        max_chunk_bytes=settings.asr_max_chunk_bytes,
        transcription_model=transcription_model,
        llm_model=llm_model,
        preview_width=settings.final_render_width,
        preview_height=settings.final_render_height,
        video_encoder=settings.video_encoder,
        asr_concurrency=1 if mlx_asr else settings.asr_concurrency,
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
        clipping_algorithm=clipping_algorithm,
        semantic_skill_version=semantic_skill.version,
        semantic_skill_sha256=semantic_skill.sha256,
        semantic_target_clip_ms=resolved_semantic_target_seconds * 1_000,
        semantic_continuous_merge_enabled=clipping_algorithm == "b_v2_experimental",
        semantic_consolidation_skill_version=consolidation_skill.version,
        semantic_consolidation_skill_sha256=consolidation_skill.sha256,
        semantic_score_threshold=(
            semantic_score_threshold if semantic_score_threshold is not None else 75.0
        ),
        semantic_profile=semantic_profile,
        semantic_discovery_skill_version=(
            f"{windowed_discovery.version}.discovery"
            if clipping_algorithm == "semantic_windowed"
            else f"{global_discovery.version}.discovery"
        ),
        semantic_discovery_skill_sha256=(
            windowed_discovery.sha256
            if clipping_algorithm == "semantic_windowed"
            else global_discovery.sha256
        ),
        semantic_global_review_skill_version=f"{global_review.version}.global_review",
        semantic_global_review_skill_sha256=global_review.sha256,
        semantic_boundary_review_skill_version=(f"{boundary_review.version}.boundary_review"),
        semantic_boundary_review_skill_sha256=boundary_review.sha256,
        clip_profile=clip_profile,
        semantic_link_review_skill_version=(
            f"{topic_chain_prompts['link_review'].version}.link_review"
        ),
        semantic_link_review_skill_sha256=topic_chain_prompts["link_review"].sha256,
        semantic_topic_chain_skill_version=(
            f"{topic_chain_prompts['topic_chain'].version}.topic_chain"
        ),
        semantic_topic_chain_skill_sha256=topic_chain_prompts["topic_chain"].sha256,
        semantic_full_context_budget_ratio=semantic_full_context_budget_ratio,
        semantic_model_context_tokens=semantic_model_context_tokens,
        semantic_no_render=semantic_no_render,
        semantic_prompt_debug=semantic_prompt_debug,
    )


def local_worker_id(prefix: str = "worker") -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_.:-]", "-", prefix)[:30] or "worker"
    host = re.sub(r"[^A-Za-z0-9_.:-]", "-", socket.gethostname())[:30] or "local"
    return f"{safe_prefix}:{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"[:100]


def _installed_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
