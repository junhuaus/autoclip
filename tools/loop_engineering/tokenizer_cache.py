"""Prepare public, hash-pinned tokenizer data before entering the offline Runner."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import urllib.request
from pathlib import Path

CACHE_PATH = Path(".cache/tiktoken")
MAX_ASSET_BYTES = 8 * 1024 * 1024
# Matches tiktoken_ext.openai_public in the locked tiktoken distribution.
ENCODING_ASSETS = (
    (
        "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
        "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
    ),
    (
        "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
        "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
    ),
)


class TokenizerCacheError(OSError):
    pass


def _cache_directory(root: Path, *, create: bool = False) -> Path:
    directory = root
    for part in CACHE_PATH.parts:
        directory = directory / part
        if create and not directory.exists() and not directory.is_symlink():
            directory.mkdir(mode=0o700)
        if directory.is_symlink() or not directory.is_dir():
            raise TokenizerCacheError(
                "tokenizer cache directory is missing or unsafe; run make setup"
            )
    return directory


def _asset_path(directory: Path, url: str) -> Path:
    # This is tiktoken's cache-key convention; integrity uses SHA-256 below.
    return directory / hashlib.sha1(url.encode()).hexdigest()


def _verify(data: bytes, expected: str) -> None:
    if len(data) > MAX_ASSET_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise TokenizerCacheError("tokenizer asset size or SHA-256 mismatch")


def _read_asset(path: Path, expected: str) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_ASSET_BYTES:
            raise TokenizerCacheError("tokenizer asset is not a bounded regular file")
        _verify(stream.read(MAX_ASSET_BYTES + 1), expected)


def validate_cache(root: Path) -> None:
    """Read-only readiness check: no SDK loader, network, repair or cache mutation."""
    directory = _cache_directory(root)
    for url, expected in ENCODING_ASSETS:
        _read_asset(_asset_path(directory, url), expected)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise TokenizerCacheError("tokenizer asset redirect is not allowed")


def prepare_cache(root: Path) -> None:
    """Trusted setup only; preserve invalid existing data and fail for manual repair."""
    directory = _cache_directory(root, create=True)
    for url, expected in ENCODING_ASSETS:
        path = _asset_path(directory, url)
        if path.exists() or path.is_symlink():
            _read_asset(path, expected)
            continue
        with urllib.request.build_opener(_NoRedirect).open(url, timeout=30) as response:
            data = response.read(MAX_ASSET_BYTES + 1)
        _verify(data, expected)
        fd, temporary = tempfile.mkstemp(prefix=".download-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Publish without replacing an existing path, including concurrent setup.
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                _read_asset(path, expected)
        finally:
            os.unlink(temporary)
    validate_cache(root)


if __name__ == "__main__":
    prepare_cache(Path.cwd().resolve())
    print("Tokenizer cache: verified cl100k_base and o200k_base")
