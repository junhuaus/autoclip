from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineConfigInvalid,
    PipelineRunConfig,
    PipelineRunConfigV9,
    PipelineRunConfigV12,
    PipelineService,
    StageWork,
    load_persisted_pipeline_config,
)
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import PipelineRunRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.clip_profile import ClipProfile


def mini_config():
    current = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=ClipProfile.MINI_LESSON,
    )

    raw = current.model_dump(mode="json")
    raw.pop("semantic_transport_contract")
    raw.pop("semantic_execution_contract")
    raw["schema_version"] = "9"
    return PipelineRunConfigV9.model_validate_json(json.dumps(raw))


def test_historical_mini_config_has_exact_versioned_lineage_identity():
    config = mini_config()
    assert config.schema_version == "9"
    assert config.semantic_result_schema_version == "5"
    assert config.semantic_lineage_contract == "semantic-v5-lineage-v1"
    assert config.semantic_validation_contract == "semantic-v4-quality-v2"
    assert (config.minimum_clip_ms, config.semantic_target_clip_ms, config.maximum_clip_ms) == (
        90_000,
        180_000,
        300_000,
    )
    assert [
        getattr(config, f"semantic_{name}_skill_version")
        for name in ("discovery", "link_review", "topic_chain", "boundary_review", "global_review")
    ] == [
        "semantic_topic_chain_v2.discovery",
        "semantic_topic_chain_v1.link_review",
        "semantic_topic_chain_v2.topic_chain",
        "semantic_topic_chain_v2.boundary_review",
        "semantic_topic_chain_v1.global_review",
    ]
    raw = config.model_dump(mode="json")
    assert set(raw) == set(PipelineRunConfig.model_fields) | {"semantic_lineage_contract"}
    assert load_persisted_pipeline_config(raw, config.fingerprint) == config


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "8"),
        ("semantic_result_schema_version", "4"),
        ("semantic_lineage_contract", "unrecognized"),
        ("semantic_validation_contract", "semantic-v4-validation-v1"),
        ("semantic_discovery_skill_version", "semantic_topic_chain_v1.discovery"),
        ("clip_profile", "short_highlight"),
        ("maximum_clip_ms", 301_000),
    ],
)
def test_persisted_v9_rejects_changed_identity(field, value):
    config = mini_config()
    raw = copy.deepcopy(config.model_dump(mode="json"))
    raw[field] = value
    with pytest.raises(PipelineConfigInvalid):
        load_persisted_pipeline_config(raw, config.fingerprint)


def test_new_nonmini_runs_bind_execution_with_v12():
    config = pipeline_config_from_settings(Settings(_env_file=None, ai_provider="mock"))
    assert type(config) is PipelineRunConfigV12 and config.schema_version == "12"
    assert "semantic_lineage_contract" not in config.model_dump(mode="json")
    assert (
        load_persisted_pipeline_config(config.model_dump(mode="json"), config.fingerprint) == config
    )


@pytest.mark.parametrize("import_only", [False, True])
def test_v9_survives_real_sqlite_lease_and_stagework_json(tmp_path: Path, import_only):
    engine = create_sqlite_engine(tmp_path / "lineage.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    config = mini_config()
    try:
        method = service.import_project if import_only else service.create_project_and_run
        created = method(source_path=tmp_path / "input.mp4", config=config, max_stage_retries=1)
        with engine.connect() as connection:
            row = connection.execute(
                select(PipelineRunRow.config_json, PipelineRunRow.config_fingerprint).where(
                    PipelineRunRow.id == created.run_id
                )
            ).one()
        persisted = load_persisted_pipeline_config(row.config_json, row.config_fingerprint)
        assert (
            persisted.schema_version == "9"
            and persisted.semantic_lineage_contract == config.semantic_lineage_contract
        )
        assert persisted.run_scope == ("import" if import_only else "full")
        expected = config.model_dump(mode="json")
        expected["run_scope"] = persisted.run_scope
        assert row.config_json == expected
        queue = SQLiteTaskQueue(engine, lease_seconds=30)
        lease = queue.claim(worker_id="lineage-config", pipeline_run_id=created.run_id)
        assert lease is not None
        work = repository.start_or_resume_stage(
            LeaseIdentity(
                task_id=lease.task_id, worker_id=lease.worker_id, lease_token=lease.lease_token
            )
        )
        raw = work.model_dump_json()
        assert json.loads(raw)["config"] == expected
        restored = StageWork.model_validate_json(raw)
        assert restored.config == persisted and restored.config.fingerprint == persisted.fingerprint
    finally:
        engine.dispose()
