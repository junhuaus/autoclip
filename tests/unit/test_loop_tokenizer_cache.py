from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from tools.loop_engineering import tokenizer_cache as cache


@pytest.fixture
def asset(monkeypatch: pytest.MonkeyPatch) -> tuple[str, bytes]:
    url, data = "https://example.invalid/static-tokenizer", b"tokenizer fixture\n"
    monkeypatch.setattr(cache, "ENCODING_ASSETS", ((url, hashlib.sha256(data).hexdigest()),))
    return url, data


def test_preparation_publishes_verified_asset_then_reuses_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asset: tuple[str, bytes]
) -> None:
    url, data = asset
    calls = []

    class Opener:
        def open(self, address: str, *, timeout: int) -> io.BytesIO:
            calls.append((address, timeout))
            return io.BytesIO(data)

    monkeypatch.setattr(cache.urllib.request, "build_opener", lambda *_: Opener())
    cache.prepare_cache(tmp_path)
    cache.prepare_cache(tmp_path)
    cache.validate_cache(tmp_path)
    assert calls == [(url, 30)]
    paths = list((tmp_path / cache.CACHE_PATH).iterdir())
    assert len(paths) == 1
    assert paths[0].name == hashlib.sha1(url.encode()).hexdigest()
    assert paths[0].read_bytes() == data


def test_readiness_does_not_create_or_repair_cache(
    tmp_path: Path, asset: tuple[str, bytes]
) -> None:
    url, _ = asset
    with pytest.raises(cache.TokenizerCacheError, match="directory"):
        cache.validate_cache(tmp_path)
    assert not (tmp_path / ".cache").exists()
    directory = tmp_path / cache.CACHE_PATH
    directory.mkdir(parents=True)
    path = directory / hashlib.sha1(url.encode()).hexdigest()
    path.write_bytes(b"corrupt original")
    for operation in (cache.validate_cache, cache.prepare_cache):
        with pytest.raises(cache.TokenizerCacheError, match="SHA-256"):
            operation(tmp_path)
        assert path.read_bytes() == b"corrupt original"


def test_cache_rejects_symlink_directory_and_asset(
    tmp_path: Path, asset: tuple[str, bytes]
) -> None:
    url, data = asset
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".cache").symlink_to(outside, target_is_directory=True)
    with pytest.raises(cache.TokenizerCacheError, match="directory"):
        cache.prepare_cache(tmp_path)
    assert list(outside.iterdir()) == []
    (tmp_path / ".cache").unlink()
    directory = tmp_path / cache.CACHE_PATH
    directory.mkdir(parents=True)
    source = outside / "data"
    source.write_bytes(data)
    (directory / hashlib.sha1(url.encode()).hexdigest()).symlink_to(source)
    with pytest.raises(OSError):
        cache.validate_cache(tmp_path)


def test_bad_download_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asset: tuple[str, bytes]
) -> None:
    class Opener:
        def open(self, address: str, *, timeout: int) -> io.BytesIO:
            return io.BytesIO(b"wrong content")

    monkeypatch.setattr(cache.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(cache.TokenizerCacheError, match="SHA-256"):
        cache.prepare_cache(tmp_path)
    assert list((tmp_path / cache.CACHE_PATH).iterdir()) == []


def test_cache_rejects_oversize_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "MAX_ASSET_BYTES", 3)
    path = tmp_path / "oversize"
    path.write_bytes(b"four")
    with pytest.raises(cache.TokenizerCacheError, match="bounded"):
        cache._read_asset(path, hashlib.sha256(b"four").hexdigest())


def test_setup_rejects_redirects() -> None:
    with pytest.raises(cache.TokenizerCacheError, match="redirect"):
        cache._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere")


@pytest.mark.parametrize("valid_winner", [True, False])
def test_concurrent_publication_preserves_winner_and_removes_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    asset: tuple[str, bytes],
    valid_winner: bool,
) -> None:
    url, data = asset
    winner = data if valid_winner else b"corrupt concurrent winner"

    class Opener:
        def open(self, address: str, *, timeout: int) -> io.BytesIO:
            return io.BytesIO(data)

    real_link = cache.os.link

    def race(source: str, destination: Path, *, follow_symlinks: bool) -> None:
        destination.write_bytes(winner)
        real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(cache.urllib.request, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(cache.os, "link", race)
    if valid_winner:
        cache.prepare_cache(tmp_path)
    else:
        with pytest.raises(cache.TokenizerCacheError, match="SHA-256"):
            cache.prepare_cache(tmp_path)
    directory = tmp_path / cache.CACHE_PATH
    destination = directory / hashlib.sha1(url.encode()).hexdigest()
    assert destination.read_bytes() == winner
    assert list(directory.iterdir()) == [destination]
