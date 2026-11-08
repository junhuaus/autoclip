"""Prepare the configured SQLite runtime before development processes fan out."""

import sys
from pathlib import Path

from pydantic import ValidationError

from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import get_settings
from liveclip.customer_delivery_settings import ShareSettings, share_settings_error_message


def main() -> int:
    # Stage 19e: the console builds share-link URLs from LIVECLIP_SHARE_*; refuse a
    # misconfiguration with one clean line before any process starts (make dev
    # runs this first and stops on a non-zero exit).
    try:
        ShareSettings()
    except ValidationError as exc:
        print(
            f"LiveClip console refused to start: {share_settings_error_message(exc)}",
            file=sys.stderr,
        )
        return 2
    with LiveClipRuntime.open(get_settings(), project_root=Path.cwd()):
        pass
    print("LiveClip SQLite schema ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
