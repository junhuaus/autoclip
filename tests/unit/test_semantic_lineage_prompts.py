import hashlib
import json
from importlib.resources import files

import pytest

from liveclip.clipping_skills.semantic_topic_chain_v2 import load_semantic_topic_chain_prompt
from liveclip.domain.clip_profile import ClipProfile


@pytest.mark.parametrize("profile", ["general", "vocal_coach_live"])
def test_composed_v1_link_review_relationship_contract(profile):
    from liveclip.clipping_skills.semantic_topic_chain_v1 import (
        load_semantic_topic_chain_prompt as load_v1,
    )

    bundle = load_v1("link_review", profile, ClipProfile.MINI_LESSON)
    linking_clause = (
        "当 `same_topic=true` 且 `same_central_objective=true` 时\uff0c`relationship` 必须且只能是 "
        "`continuation`、`supporting_example`、`next_step_same_lesson`、"
        "`summary_same_lesson` 之一。"
    )
    non_linking_clause = (
        "当任一布尔值为 false\uff08`same_topic=true` 且 `same_central_objective=false`、 "
        "`same_topic=false` 且 `same_central_objective=true`、或 "
        "`same_topic=false` 且 `same_central_objective=false`\uff09时\uff0c"
        "`relationship` 必须且只能是 "
        "`adjacent_but_independent`、`topic_switch`、`uncertain` 之一。"
    )
    for prompt in (bundle.instructions, bundle.repair):
        composed = " ".join(prompt.split())
        assert linking_clause in composed
        assert non_linking_clause in composed

    repair = " ".join(bundle.repair.split())
    assert (
        "仅当错误为 `link relationship contradicts same-topic/objective decision` 时\uff1a"
        in repair
    )
    assert "保留原始 `same_topic` 和 `same_central_objective` 两个布尔语义判断及其值" in repair
    assert "只修改报错对象的 `relationship` 字段这一冗余关系分类" in repair
    assert "不得重新判断语义、重跑整个阶段或修改无关对象及其他字段" in repair
    assert "其他错误仍遵守上述通用修复约束" in repair
    assert bundle.sha256 != "12881e9817b1fe45d86607b81d629966a0e948bf8f4d3d0d701355db9b48085d"


@pytest.mark.parametrize("profile", ["general", "vocal_coach_live"])
def test_composed_v1_mini_global_review_final_decision_contract(profile):
    from liveclip.clipping_skills.semantic_topic_chain_v1 import (
        load_semantic_topic_chain_prompt as load_v1,
    )

    bundle = load_v1("global_review", profile, ClipProfile.MINI_LESSON)
    composed = " ".join(bundle.instructions.split())
    required_clauses = (
        "当前 Global Review 中\uff0c`boundary_reviews` 提供的是已经解决边界问题的"
        "最终 Boundary 区间。",
        "必须独立判断该给定的精确区间\uff0c不得照抄上游历史 `repair_boundary` 决定。",
        "该精确区间可接受时\uff0c`content_decision` 返回 `keep`\uff0c否则返回 `drop`。",
        "即使其他通用或 Profile 指导讨论边界调整\uff0c"
        "当前 Global Review 也不得返回 `repair_boundary`\uff0c "
        "不得提出第二次边界修复。",
    )
    for clause in required_clauses:
        assert clause in composed


@pytest.mark.parametrize("stage", ["discovery", "topic_chain", "boundary_review"])
@pytest.mark.parametrize("profile", ["general", "vocal_coach_live"])
def test_every_resource_and_identity_participates_in_hash(stage, profile):
    bundle = load_semantic_topic_chain_prompt(stage, profile, ClipProfile.MINI_LESSON)
    resources = tuple(
        (name, files("liveclip.clipping_skills").joinpath(name).read_text(encoding="utf-8"))
        for name in bundle.loaded_files
    )
    identity = (bundle.version, stage, profile, "mini_lesson", resources)

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()

    assert bundle.sha256 == digest(identity)
    assert len(resources) == 5
    assert resources[3][1].strip() == bundle.repair
    assert resources[4][1].strip() in bundle.instructions
    for i in range(len(resources)):
        changed = list(resources)
        changed[i] = (resources[i][0], resources[i][1] + "\n")
        assert digest((*identity[:4], tuple(changed))) != bundle.sha256
    for i in range(4):
        changed = list(identity)
        changed[i] = "changed"
        assert digest(changed) != bundle.sha256


@pytest.mark.parametrize(
    "stage,profile,clip",
    [
        ("link_review", "general", ClipProfile.MINI_LESSON),
        ("global_review", "general", ClipProfile.MINI_LESSON),
        ("../main", "general", ClipProfile.MINI_LESSON),
        ("discovery", "../../secret", ClipProfile.MINI_LESSON),
        ("discovery", "general", ClipProfile.SHORT_HIGHLIGHT),
        ("discovery", "general", "../../secret"),
    ],
)
def test_unsupported_selectors_fail_before_resource_lookup(monkeypatch, stage, profile, clip):
    def forbidden(*args):
        pytest.fail("resource lookup before selector validation")

    monkeypatch.setattr("liveclip.clipping_skills.semantic_topic_chain_v2.files", forbidden)
    with pytest.raises(ValueError):
        load_semantic_topic_chain_prompt(stage, profile, clip)


@pytest.mark.parametrize("profile", ["general", "vocal_coach_live"])
def test_composed_discovery_does_not_expose_global_score_policy(profile):
    from liveclip.clipping_skills.semantic_topic_chain_v1 import (
        load_semantic_topic_chain_prompt as load_v1,
    )

    discovery = load_semantic_topic_chain_prompt("discovery", profile, ClipProfile.MINI_LESSON)
    assert "75" not in discovery.instructions
    assert "20/20/15/15/10/10/10" not in discovery.instructions
    global_review = load_v1("global_review", profile, ClipProfile.MINI_LESSON)
    assert "75 分不能通过" in global_review.instructions
    assert "中心目标20、完整闭合20" in global_review.instructions
    assert "教学推进15、独立理解15" in global_review.instructions
