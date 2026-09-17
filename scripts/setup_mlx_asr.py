from __future__ import annotations

import argparse
import importlib
import os
import stat
from pathlib import Path

from liveclip.providers.asr.mlx import (
    MLX_ASR_REPOSITORY,
    MLX_ASR_REVISION,
    inspect_mlx_model,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install and verify LiveClip's pinned local Whisper large-v3 snapshot."
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("data/models/whisper-large-v3-mlx"),
    )
    args = parser.parse_args()
    model_dir = args.model_dir.expanduser()
    if not model_dir.is_absolute():
        model_dir = (Path.cwd() / model_dir).resolve(strict=False)
    _assert_safe_destination(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    project_cache = Path.cwd() / ".cache" / "huggingface"
    os.environ.setdefault("HF_HOME", str(project_cache))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    huggingface_hub = importlib.import_module("huggingface_hub")
    snapshot_download = getattr(huggingface_hub, "snapshot_download", None)
    if not callable(snapshot_download):
        raise RuntimeError("huggingface-hub download API is unavailable")
    snapshot_download(
        repo_id=MLX_ASR_REPOSITORY,
        revision=MLX_ASR_REVISION,
        allow_patterns=("config.json", "weights.npz"),
        local_dir=model_dir,
    )
    snapshot = inspect_mlx_model(model_dir)
    print(
        "MLX ASR ready: "
        f"contract={snapshot.contract_version} "
        f"weights_bytes={snapshot.weights_size_bytes}"
    )


def _assert_safe_destination(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("model destination must be absolute")
    if path == Path(path.anchor) or len(path.parts) < 4:
        raise ValueError("model destination is too broad")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("model destination must be a non-symlink directory")


if __name__ == "__main__":
    main()
