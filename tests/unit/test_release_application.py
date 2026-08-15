from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from liveclip.application.releases import (
    MAX_RELEASE_CLOCK_SKEW,
    MAX_RELEASE_METRIC_VALUE,
    ReleaseItemUpdate,
    ReleaseMetricCreate,
    ReleasePackageRequest,
    ReleaseStatusCommand,
)
from liveclip.domain.releases import (
    ReleaseCaptionMode,
    ReleaseChecklist,
    ReleaseItemStatus,
)


def _update(**changes: object) -> ReleaseItemUpdate:
    values: dict[str, object] = {
        "expected_management_version": 1,
        "edit_plan_revision": 2,
        "title": " 发布标题 ",
        "title_variants": ("版本一", "版本二"),
        "description": " 描述 ",
        "hashtags": ("#直播", "高光"),
        "cta": " 关注下一场 ",
        "caption_mode": ReleaseCaptionMode.CLEAN_SEPARATE,
        "cover_time_ms": 1_000,
        "assignee_user_id": None,
        "planned_publish_at": datetime(2026, 8, 16, 12, tzinfo=UTC),
        "checklist": ReleaseChecklist(),
    }
    values.update(changes)
    return ReleaseItemUpdate.model_validate(values)


def test_release_update_normalizes_editable_copy() -> None:
    value = _update()

    assert value.title == "发布标题"
    assert value.description == "描述"
    assert value.cta == "关注下一场"
    assert value.hashtags == ("直播", "高光")


def test_release_update_rejects_duplicate_or_naive_schedule() -> None:
    with pytest.raises(ValidationError):
        _update(title_variants=("相同", "相同"))
    with pytest.raises(ValidationError):
        _update(planned_publish_at=datetime(2026, 8, 16, 12))


def test_published_result_requires_https_identity_and_aware_time() -> None:
    observed_at = datetime.now(UTC) - timedelta(minutes=1)
    with pytest.raises(ValidationError):
        ReleaseStatusCommand(
            expected_management_version=1,
            target=ReleaseItemStatus.PUBLISHED,
            release_package_id="package_1",
            external_url="http://example.test/watch/1",
            published_at=observed_at,
        )
    with pytest.raises(ValidationError):
        ReleaseStatusCommand(
            expected_management_version=1,
            target=ReleaseItemStatus.PUBLISHED,
            release_package_id="package_1",
            published_at=observed_at,
        )
    with pytest.raises(ValidationError, match="exact platform package"):
        ReleaseStatusCommand(
            expected_management_version=1,
            target=ReleaseItemStatus.PUBLISHED,
            external_id="external-1",
            published_at=observed_at,
        )

    value = ReleaseStatusCommand(
        expected_management_version=1,
        target=ReleaseItemStatus.PUBLISHED,
        release_package_id="package_1",
        external_url="https://example.test/watch/1",
        published_at=observed_at,
    )
    assert value.external_url == "https://example.test/watch/1"
    assert value.release_package_id == "package_1"


def test_observed_release_times_and_metric_values_are_bounded() -> None:
    too_far_ahead = datetime.now(UTC) + MAX_RELEASE_CLOCK_SKEW + timedelta(minutes=1)
    with pytest.raises(ValidationError, match="cannot be in the future"):
        ReleaseStatusCommand(
            expected_management_version=1,
            target=ReleaseItemStatus.PUBLISHED,
            release_package_id="package_1",
            external_id="external-1",
            published_at=too_far_ahead,
        )
    with pytest.raises(ValidationError, match="cannot be in the future"):
        ReleaseMetricCreate(captured_at=too_far_ahead)
    with pytest.raises(ValidationError):
        ReleaseMetricCreate(
            captured_at=datetime.now(UTC),
            views=MAX_RELEASE_METRIC_VALUE + 1,
        )

    maximum = ReleaseMetricCreate(
        captured_at=datetime.now(UTC),
        views=MAX_RELEASE_METRIC_VALUE,
    )
    assert maximum.views == MAX_RELEASE_METRIC_VALUE


@pytest.mark.parametrize(
    "outside_range",
    [
        datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(-timedelta(hours=23))),
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=23))),
    ],
)
def test_release_datetimes_reject_utc_conversion_overflow(outside_range: datetime) -> None:
    with pytest.raises(ValidationError, match="outside the supported datetime range"):
        ReleaseMetricCreate(captured_at=outside_range)
    with pytest.raises(ValidationError, match="outside the supported datetime range"):
        _update(planned_publish_at=outside_range)


def test_platform_release_package_is_always_a_complete_zip() -> None:
    request = ReleasePackageRequest(expected_release_item_version=3)
    assert request.include_zip is True

    with pytest.raises(ValidationError):
        ReleasePackageRequest(
            expected_release_item_version=3,
            include_zip=False,  # type: ignore[arg-type]
        )
