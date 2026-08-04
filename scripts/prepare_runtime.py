"""Prepare the configured SQLite runtime before development processes fan out."""

from pathlib import Path

from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import get_settings


def main() -> None:
    with LiveClipRuntime.open(get_settings(), project_root=Path.cwd()):
        pass
    print("LiveClip SQLite schema ready")


if __name__ == "__main__":
    main()
