from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine

from liveclip.application.media_assets import MediaAssetNotFound, MediaAssetRecord
from liveclip.db.models import AssetRow
from liveclip.domain.state_transitions import AssetStatus


class SqlAlchemyMediaAssetRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_committed_asset(self, asset_id: str) -> MediaAssetRecord:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    AssetRow.id,
                    AssetRow.project_id,
                    AssetRow.kind,
                    AssetRow.relative_path,
                    AssetRow.mime_type,
                    AssetRow.sha256,
                    AssetRow.size_bytes,
                ).where(
                    AssetRow.id == asset_id,
                    AssetRow.status == AssetStatus.COMMITTED.value,
                )
            ).one_or_none()
        if row is None or row.sha256 is None or row.size_bytes is None:
            raise MediaAssetNotFound("asset does not exist")
        return MediaAssetRecord(
            asset_id=str(row.id),
            project_id=str(row.project_id),
            kind=str(row.kind),
            relative_path=str(row.relative_path),
            mime_type=str(row.mime_type),
            sha256=str(row.sha256),
            size_bytes=int(row.size_bytes),
        )
