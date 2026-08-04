from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path


class FingerprintCancelled(RuntimeError):
    """A streamed fingerprint stopped before it could become an identity fact."""


def stream_sha256(
    path: Path,
    *,
    block_size: int = 1024 * 1024,
    cancel_requested: Callable[[], bool] | None = None,
) -> str:
    if block_size <= 0:
        raise ValueError("fingerprint block size must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            if cancel_requested is not None and cancel_requested():
                raise FingerprintCancelled("streamed fingerprint was cancelled")
            block = source.read(block_size)
            if not block:
                break
            digest.update(block)
    if cancel_requested is not None and cancel_requested():
        raise FingerprintCancelled("streamed fingerprint was cancelled")
    return digest.hexdigest()
