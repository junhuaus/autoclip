"""Run the read-only customer share server (``make share``; Stage 19d).

Loopback by default (``127.0.0.1:8766``). Sharing on the local network needs
``LIVECLIP_SHARE_ALLOW_LAN=true``, a non-loopback ``LIVECLIP_SHARE_HOST`` and
``LIVECLIP_SHARE_BASE_URL``; see ``ShareSettings``. There is no TLS: do not use
share links on public Wi-Fi, and never expose this port to the internet.
"""

from __future__ import annotations

import sys

from pydantic import ValidationError


def main() -> int:
    import uvicorn

    from liveclip.api.share import create_share_app
    from liveclip.config import get_settings
    from liveclip.customer_delivery_settings import ShareSettings
    from liveclip.observability import configure_logging

    try:
        sharing = ShareSettings()
    except ValidationError as exc:
        messages = "; ".join(str(error.get("msg", "invalid setting")) for error in exc.errors())
        print(f"LiveClip share server refused to start: {messages}", file=sys.stderr)
        return 2
    settings = get_settings()
    configure_logging(settings.log_level)
    app = create_share_app(settings, share_settings=sharing)
    print(
        f"LiveClip share server on http://{sharing.host}:{sharing.port} "
        f"(links use {sharing.public_base_url}); do not use on public Wi-Fi",
        file=sys.stderr,
    )
    uvicorn.run(
        app,
        host=sharing.host,
        port=sharing.port,
        access_log=False,
        log_config=None,
        server_header=False,
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
