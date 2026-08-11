from liveclip.renderer.contracts import (
    CLEAN_PROXY_PIPELINE_CONTRACT_VERSION,
    has_current_manual_render_contract,
    is_clean_review_proxy,
)


def test_clean_pipeline_proxy_requires_versioned_pipeline_contract() -> None:
    assert is_clean_review_proxy(
        spec=None,
        pipeline_config={
            "edit_plan_schema_version": CLEAN_PROXY_PIPELINE_CONTRACT_VERSION,
        },
    )
    assert not is_clean_review_proxy(
        spec=None,
        pipeline_config={"edit_plan_schema_version": "edit-plan-v1.caption-v2"},
    )
    assert not is_clean_review_proxy(spec=None, pipeline_config=None)


def test_clean_manual_proxy_requires_exact_current_text_contract() -> None:
    clean = {
        "schema_version": "4",
        "renderer": "ffmpeg-renderer-v3.no-blur",
        "text_mode": "none",
    }
    assert has_current_manual_render_contract("proxy", clean)
    assert is_clean_review_proxy(spec=clean, pipeline_config={})
    assert not is_clean_review_proxy(
        spec={**clean, "renderer": "ffmpeg-renderer-v1"},
        pipeline_config={
            "edit_plan_schema_version": CLEAN_PROXY_PIPELINE_CONTRACT_VERSION,
        },
    )
    assert not is_clean_review_proxy(
        spec={"schema_version": "2", "renderer": "ffmpeg-renderer-v1"},
        pipeline_config={},
    )
