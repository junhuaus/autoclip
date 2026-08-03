from __future__ import annotations

import hashlib
from pathlib import Path


def stream_sha256(path: Path, *, block_size: int = 1024 * 1024) -> str:
    if block_size <= 0:
        raise ValueError("fingerprint block size must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(block_size):
            digest.update(block)
    return digest.hexdigest()
