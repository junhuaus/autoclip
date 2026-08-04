from __future__ import annotations

import os
import re
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from liveclip.application.clips import ClipQueryService
from liveclip.application.deliveries import DeliveryService
from liveclip.application.delivery_runner import DeliveryTaskRunner
from liveclip.application.media_assets import MediaAssetService
from liveclip.application.pipeline import PipelineRunConfig, PipelineService
from liveclip.application.render_runner import RenderTaskRunner
from liveclip.application.rendering import RenderProfile, RenderService
from liveclip.application.reviewing import ReviewService
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.config import Settings
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.clip_repository import SqlAlchemyClipQueryRepository
from liveclip.db.delivery_repository import SqlAlchemyDeliveryRepository
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.media_repository import SqlAlchemyMediaAssetRepository
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.render_repository import SqlAlchemyRenderRepository
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.delivery.task_handler import DeliveryTaskHandler
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.renderer.task_handler import RenderTaskHandler


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
    task_queue: SQLiteTaskQueue
    stage_runner: StageTaskRunner
    clip_query_service: ClipQueryService
    review_service: ReviewService
    render_service: RenderService
    render_runner: RenderTaskRunner
    delivery_service: DeliveryService
    delivery_runner: DeliveryTaskRunner
    media_asset_service: MediaAssetService

    @classmethod
    def open(
        cls,
        settings: Settings,
        *,
        project_root: Path | None = None,
    ) -> LiveClipRuntime:
        data_dir = settings.resolved_data_dir(project_root or Path.cwd())
        data_dir.mkdir(parents=True, exist_ok=True)
        database_path = data_dir / "liveclip.sqlite3"
        engine = create_sqlite_engine(database_path)
        try:
            upgrade_database(
                engine,
                project_root=project_root or _installed_project_root(),
            )
            repository = SqlAlchemyPipelineRepository(engine)
            service = PipelineService(repository)
            queue = SQLiteTaskQueue(
                engine,
                lease_seconds=settings.worker_lease_seconds,
            )
            asset_store = SqlAlchemyAssetStore(engine)
            handlers = PipelineStageHandlers(
                data_dir=data_dir,
                allowed_media_roots=tuple(settings.allowed_media_roots),
                assets=asset_store,
                state=SqlAlchemyStageStateStore(engine),
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
            delivery_runner = DeliveryTaskRunner(
                queue=queue,
                repository=delivery_repository,
                handler=DeliveryTaskHandler(data_dir=data_dir, assets=asset_store),
                heartbeat_seconds=settings.worker_heartbeat_seconds,
            )
            media_asset_service = MediaAssetService(
                SqlAlchemyMediaAssetRepository(engine),
                data_dir=data_dir,
            )
            return cls(
                settings=settings,
                data_dir=data_dir,
                database_path=database_path,
                engine=engine,
                pipeline_repository=repository,
                pipeline_service=service,
                task_queue=queue,
                stage_runner=runner,
                clip_query_service=clip_query_service,
                review_service=review_service,
                render_service=render_service,
                render_runner=render_runner,
                delivery_service=delivery_service,
                delivery_runner=delivery_runner,
                media_asset_service=media_asset_service,
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
    top_n: int | None = None,
    minimum_clip_seconds: int | None = None,
    maximum_clip_seconds: int | None = None,
) -> PipelineRunConfig:
    provider = settings.ai_provider
    transcription_model = "mock-asr-v1" if provider == "mock" else settings.transcription_model
    llm_model = "mock-llm-v1" if provider == "mock" else settings.llm_model
    return PipelineRunConfig(
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
    )


def local_worker_id(prefix: str = "worker") -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_.:-]", "-", prefix)[:30] or "worker"
    host = re.sub(r"[^A-Za-z0-9_.:-]", "-", socket.gethostname())[:30] or "local"
    return f"{safe_prefix}:{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"[:100]


def _installed_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
