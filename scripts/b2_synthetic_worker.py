"""Disposable, Mock-only B2 browser instrumentation; never an installed Worker mode."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from liveclip.application.delivery_progress import DeliveryProgressEvent, DeliveryProgressLostLease
from liveclip.config import Settings
from liveclip.db.delivery_repository import (
    _DeliveryProgressSink,
    current_delivery_progress_authority,
)
from liveclip.db.models import DeliveryProgressRow
from liveclip.providers.asr.mock import DEFAULT_MOCK_SCRIPT, MockASRProvider
from liveclip.worker import run_worker

# Separate test data: the installed default and its contract remain untouched.
LONG_SCRIPT = tuple(
    segment.model_copy(
        update={
            "source_start_ms": segment.source_start_ms * 2,
            "source_end_ms": segment.source_end_ms * 2,
        }
    )
    for segment in DEFAULT_MOCK_SCRIPT
)


def validate_fixture(settings: Settings, root: Path, identity: tuple[int, int]) -> Path:
    resolved = root.resolve(strict=True)
    metadata = root.lstat()
    if (
        root.is_symlink()
        or resolved.parent != Path(tempfile.gettempdir()).resolve()
        or not re.fullmatch(r"liveclip-browser-e2e\.[A-Za-z0-9_-]{6,32}", root.name)
        or (metadata.st_dev, metadata.st_ino) != identity
        or settings.ai_provider != "mock"
        or settings.resolved_data_dir() != resolved / "projects"
        or tuple(p.resolve() for p in settings.allowed_media_roots) != (resolved / "media",)
        or any(
            key and key.get_secret_value()
            for key in (
                settings.openai_api_key,
                settings.openrouter_api_key,
            )
        )
    ):
        raise ValueError("B2 Worker requires an owned disposable Mock fixture")
    return resolved


class PackagingPause:
    """Hold only an owned directory descriptor; no caller-provided marker paths."""

    def __init__(self, root: Path | int, *, timeout: float, lease_seconds: int):
        if not 0 < timeout < lease_seconds / 2:
            raise ValueError("B2 pause must be shorter than half the lease")
        self.timeout = timeout
        self.directory = (
            os.dup(root)
            if isinstance(root, int)
            else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        )
        self.seen: set[int] = set()

    def close(self) -> None:
        os.close(self.directory)

    def write(self, name: str, value: dict[str, object]) -> None:
        descriptor = os.open(
            f".{name}.pending",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directory,
        )
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(f".{name}.pending", name, src_dir_fd=self.directory, dst_dir_fd=self.directory)

    def after_commit(self, sink: _DeliveryProgressSink, event: DeliveryProgressEvent) -> None:
        if event.phase != "writing_metadata" or event.completed not in (1, 2):
            return
        count = event.completed
        if event.total != 4 or count in self.seen:
            raise ValueError("B2 requires one clip and one Delivery attempt")
        self.seen.add(count)
        from datetime import UTC, datetime

        def snapshot() -> dict[str, object]:
            with sink._engine.connect() as connection:
                authority = current_delivery_progress_authority(
                    connection, sink._work.delivery_id, now=datetime.now(UTC)
                )
                if authority is None:
                    raise DeliveryProgressLostLease("B2 paused authority expired")
                _, task, attempt = authority
                row = (
                    connection.execute(
                        select(DeliveryProgressRow).where(
                            DeliveryProgressRow.delivery_id == sink._work.delivery_id,
                            DeliveryProgressRow.task_attempt_id == attempt["id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    task["id"] != sink._lease.task_id
                    or task["lease_token"] != sink._lease.lease_token
                    or row["phase"] != "writing_metadata"
                    or row["completed"] != count
                    or row["total"] != 4
                ):
                    raise DeliveryProgressLostLease("B2 paused progress changed")
                return {
                    "project_id": sink._work.project_id,
                    "run_id": sink._work.run_id,
                    "generation": sink._work.generation,
                    "delivery_id": sink._work.delivery_id,
                    "task_id": task["id"],
                    "attempt_id": attempt["id"],
                    "phase": row["phase"],
                    "unit": row["unit"],
                    "completed": row["completed"],
                    "total": row["total"],
                    "business_advanced_at": row["business_advanced_at"].isoformat(),
                    "observed_unix_ms": int(time.time() * 1000),
                }

        receipt = snapshot()
        release = f"release-{count}.json"
        self.write(f"pause-{count}.json", receipt)
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                snapshot()  # read-only authority check; the normal LeaseMonitor keeps heartbeating
                try:
                    descriptor = os.open(
                        release, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory
                    )
                except FileNotFoundError:
                    time.sleep(0.05)
                    continue
                with os.fdopen(descriptor, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("B2 release marker must be a regular file")
                    value = json.loads(stream.read(8193))
                if value != {"attempt_id": receipt["attempt_id"], "completed": count}:
                    raise ValueError("B2 release does not match the paused attempt")
                self.write(
                    f"released-{count}.json",
                    {
                        **receipt,
                        "released_unix_ms": int(time.time() * 1000),
                    },
                )
                return
            raise TimeoutError("B2 browser did not release packaging before its bounded deadline")
        finally:
            with suppress(FileNotFoundError):
                os.unlink(release, dir_fd=self.directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-device", type=int, required=True)
    parser.add_argument("--expected-inode", type=int, required=True)
    args = parser.parse_args()
    settings = Settings()
    root = validate_fixture(settings, args.root, (args.expected_device, args.expected_inode))
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(directory)
        if (metadata.st_dev, metadata.st_ino) != (args.expected_device, args.expected_inode):
            raise ValueError("B2 fixture identity changed before marker allocation")
        os.mkdir("b2-pauses", mode=0o700, dir_fd=directory)
        child = os.open("b2-pauses", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            pause = PackagingPause(child, timeout=40, lease_seconds=settings.worker_lease_seconds)
        finally:
            os.close(child)
    finally:
        os.close(directory)
    original = _DeliveryProgressSink.advance

    def advance(sink: _DeliveryProgressSink, event: DeliveryProgressEvent) -> None:
        original(sink, event)  # genuine fenced persistence always precedes instrumentation
        pause.after_commit(sink, event)

    try:
        with (
            patch(
                "liveclip.pipeline.stage_handlers.MockASRProvider",
                side_effect=lambda **kwargs: MockASRProvider(LONG_SCRIPT, **kwargs),
            ),
            patch.object(_DeliveryProgressSink, "advance", advance),
        ):
            raise SystemExit(run_worker(settings))
    finally:
        pause.close()


if __name__ == "__main__":
    main()
