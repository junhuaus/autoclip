from __future__ import annotations

from collections.abc import Mapping

RENDER_SPEC_SCHEMA_VERSION = "4"
FFMPEG_RENDERER_CONTRACT_VERSION = "ffmpeg-renderer-v4.av-sync-preroll"
LEGACY_CLEAN_PROXY_PIPELINE_CONTRACT_VERSION = "edit-plan-v1.caption-v2.clean-proxy-v2.no-blur-v1"
CLEAN_DELIVERY_MASTER_PIPELINE_CONTRACT_VERSION = (
    "edit-plan-v1.caption-v2.clean-delivery-master-v1.no-blur-v1"
)
# Compatibility export used by existing review/edit-package callers and tests.
CLEAN_PROXY_PIPELINE_CONTRACT_VERSION = CLEAN_DELIVERY_MASTER_PIPELINE_CONTRACT_VERSION


def text_mode_for_render_kind(kind: str) -> str:
    if kind == "proxy":
        return "none"
    if kind == "final":
        return "title_and_captions"
    raise ValueError("render kind is not supported")


def has_current_manual_render_contract(kind: str, spec: object) -> bool:
    """Return whether a manual render spec has the current trusted text contract."""

    if not isinstance(spec, Mapping):
        return False
    try:
        expected_text_mode = text_mode_for_render_kind(kind)
    except ValueError:
        return False
    return (
        spec.get("schema_version") == RENDER_SPEC_SCHEMA_VERSION
        and spec.get("renderer") == FFMPEG_RENDERER_CONTRACT_VERSION
        and spec.get("text_mode") == expected_text_mode
    )


def is_clean_review_proxy(
    *,
    spec: object,
    pipeline_config: object,
) -> bool:
    """Recognize only proxies proven to have no LiveClip-generated text pixels.

    Pipeline-stage proxies historically stored no manual ``spec_json``; their
    immutable Pipeline config contract is therefore the authority. Manual proxy
    jobs carry their complete render spec. Any ambiguous legacy row fails closed.
    """

    if spec is not None:
        return has_current_manual_render_contract("proxy", spec)
    return isinstance(pipeline_config, Mapping) and pipeline_config.get(
        "edit_plan_schema_version"
    ) in {
        LEGACY_CLEAN_PROXY_PIPELINE_CONTRACT_VERSION,
        CLEAN_DELIVERY_MASTER_PIPELINE_CONTRACT_VERSION,
    }


def is_clean_delivery_master(
    *,
    spec: object,
    pipeline_config: object,
) -> bool:
    """Recognize a clean render produced by the single-render delivery contract."""

    if spec is not None:
        return has_current_manual_render_contract("proxy", spec)
    return isinstance(pipeline_config, Mapping) and (
        pipeline_config.get("edit_plan_schema_version")
        == CLEAN_DELIVERY_MASTER_PIPELINE_CONTRACT_VERSION
    )
