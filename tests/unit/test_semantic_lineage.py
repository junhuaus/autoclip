from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.pipeline.semantic_global import SemanticInputUnit, transcript_cues
from liveclip.pipeline.semantic_lineage import (
    BoundaryReviewV5,
    ChainCandidateV5,
    DiscoveryBatchOutputV5,
    FinalPartitionV5,
    LineageLedgerV5,
    TopicChainReviewV5,
    attribute_risks_v5,
    build_boundary_authority_v5,
    build_boundary_payload_v5,
    build_discovery_payload_v5,
    build_lineage_ledger_v5,
    build_topic_chain_payload_v5,
    collect_response_errors_v5,
    expected_routes_v5,
    namespace_discovery_batch_v5,
    parse_response_v5,
    validate_boundary_review_v5,
    validate_discovery_batch_v5,
    validate_graph_v5,
    validate_lineage_ledger_v5,
)
from liveclip.pipeline.semantic_profiles import TimeRangeV4, TopicChainV4


def wire(model, raw):
    return parse_response_v5(model, json.dumps(raw))


@pytest.mark.parametrize("kind", ["original", "unit", "path"])
@pytest.mark.parametrize("unknown_before", [False, True])
def test_redundant_record_comparisons_use_only_known_prefix(kind, unknown_before):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    if kind == "original":
        raw["originals"][0] = None
        raw["originals"][1]["original"]["central_question"] = "changed"
        raw["batches"].insert(0 if unknown_before else 1, {"batch_id": "incomplete"})
        location = ("originals", 1, "original", "central_question")
    elif kind == "unit":
        raw["outcomes"][0] = None
        raw["outcomes"][1]["unit"]["origin_reason"] = "changed"
        del raw["reviews"][0 if unknown_before else 3]["candidates"]
        location = ("outcomes", 1, "unit", "origin_reason")
    else:
        raw["originals"][0]["paths"][0] = None
        raw["originals"][0]["paths"][1]["topic_chain_id"] = "changed"
        del raw["reviews"][0 if unknown_before else 3]["source_dispositions"]
        location = ("originals", 0, "paths", 1, "topic_chain_id")
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert any(e.code == "schema" for e in errors)
    code = "terminal_path_mismatch" if kind == "path" else "provenance_mismatch"
    assert ((location, code) in {(e.location, e.code) for e in errors}) is not unknown_before


@pytest.mark.parametrize("container", ["standalone", "outcomes", "chain_new_outcomes"])
@pytest.mark.parametrize("schema_fault", [False, True])
@pytest.mark.parametrize(
    "fact,value,flag",
    [
        ("opening_complete", False, "context_dependent_opening"),
        ("ending_complete", False, "incomplete_ending"),
        ("central_objective_complete", False, "central_objective_incomplete"),
        ("contains_padding", True, "padded_to_min_duration"),
    ],
)
def test_boundary_quality_consistency_without_transcript(
    container, schema_fault, fact, value, flag
):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    field = "outcomes" if container == "standalone" else container
    boundary_raw = raw[field][0]["boundary"]
    boundary_raw[fact] = value
    assert boundary_raw["quality_flags"] == []
    if container == "chain_new_outcomes":
        raw["outcomes"][-1]["boundary"] = copy.deepcopy(boundary_raw)
    if container != "standalone":
        with pytest.raises(ValueError, match=flag):
            wire(LineageLedgerV5, raw)
    if schema_fault:
        del boundary_raw["review_reason"]
    model = BoundaryReviewV5 if container == "standalone" else LineageLedgerV5
    payload = boundary_raw if container == "standalone" else raw
    errors = collect_response_errors_v5(model, json.dumps(payload))
    location = () if container == "standalone" else (field, 0, "boundary")
    assert any(
        e.location == location and e.code == "current_quality" and flag in e.message for e in errors
    )
    if schema_fault:
        assert any(
            e.code == "schema" and e.location == (*location, "review_reason") for e in errors
        )
    assert not any(e.code == "unknown_cue" for e in errors)


@pytest.mark.parametrize(
    "path",
    [
        ("logical_windows", 0, "candidate_ids"),
        ("logical_windows", 0, "fragment_ids"),
        ("logical_windows", 0, "left_boundary", "related_candidate_ids"),
        ("logical_windows", 0, "left_boundary", "related_fragment_ids"),
        ("logical_windows", 0, "right_boundary", "related_candidate_ids"),
        ("logical_windows", 0, "right_boundary", "related_fragment_ids"),
        ("candidates", 0, "source_window_ids"),
    ],
)
@pytest.mark.parametrize("fault", ["unknown", "duplicate"])
def test_strict_ledger_checks_discovery_reference_collections(path, fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    value = raw["batches"][0]
    for part in path:
        value = value[part]
    assert value
    value.append("unknown_reference" if fault == "unknown" else value[0])
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert any(e.code == ("unknown_id" if fault == "unknown" else "duplicate_id") for e in errors)


@pytest.mark.parametrize(
    "fault", ["duplicate_window", "fragment_window", "candidate_batch", "fragment_batch"]
)
def test_strict_ledger_checks_discovery_record_identities(fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    batch = raw["batches"][0]
    if fault == "duplicate_window":
        batch["logical_windows"].append(copy.deepcopy(batch["logical_windows"][0]))
    elif fault == "fragment_window":
        batch["topic_fragments"][0]["logical_window_id"] = "missing_window"
    else:
        batch["candidates" if fault == "candidate_batch" else "topic_fragments"][0][
            "source_batch_id"
        ] = "wrong_batch"
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)


def test_strict_empty_batches_require_unique_batch_identity():
    batch = fixture()[0].model_dump(mode="json")
    batch["candidates"] = []
    batch["topic_fragments"] = []
    for window in batch["logical_windows"]:
        window["candidate_ids"] = window["fragment_ids"] = []
        for side in ("left_boundary", "right_boundary"):
            window[side]["related_candidate_ids"] = window[side]["related_fragment_ids"] = []
    first = wire(DiscoveryBatchOutputV5, batch)
    second = wire(DiscoveryBatchOutputV5, dict(batch, batch_id="other_batch"))
    ledger = build_lineage_ledger_v5(
        batches=(first, second),
        chains=(),
        reviews=(),
        boundaries=(),
        partition=wire(FinalPartitionV5, {name: [] for name in FinalPartitionV5.model_fields}),
        transcript=transcript(),
    )
    assert wire(LineageLedgerV5, ledger.model_dump(mode="json")) == ledger
    raw = ledger.model_dump(mode="json")
    raw["batches"][1]["batch_id"] = raw["batches"][0]["batch_id"]
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)


@pytest.mark.parametrize(
    "authority,bad_cue",
    [
        ("transcript", 999999),
        ("transcript", 31),
        ("explicit", 31),
        ("both", 5),
        ("chain_only", 31),
    ],
)
@pytest.mark.parametrize("schema_fault", [False, True])
def test_topic_chain_cue_authority_is_shared_and_scoped(authority, bad_cue, schema_fault):
    batch, chains, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    raw["evidence_cue_ids"] = [None, 1, bad_cue]
    raw["candidates"].insert(0, None)
    raw["candidates"][1]["evidence_cue_ids"] = [None, bad_cue]
    raw["source_dispositions"][0]["evidence_cue_ids"] = [None, bad_cue]
    if schema_fault:
        raw["central_question"] = []
    kwargs = {
        "chain": chains[0],
        "routes": expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
    }
    if authority in {"transcript", "both"}:
        kwargs["transcript"] = transcript()
    if authority in {"explicit", "both"}:
        kwargs["known_cue_ids"] = set(range(1, 61)) - ({5} if authority == "both" else set())
    errors = collect_response_errors_v5(TopicChainReviewV5, json.dumps(raw), **kwargs)
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("evidence_cue_ids", 2), "unknown_cue"),
        (("candidates", 1, "evidence_cue_ids", 1), "unknown_cue"),
        (("source_dispositions", 0, "evidence_cue_ids", 1), "unknown_cue"),
    } <= actual
    assert (("evidence_cue_ids", 1), "unknown_cue") not in actual


def test_topic_chain_without_any_cue_or_chain_authority_does_not_invent_existence():
    raw = fixture()[2][0].model_dump(mode="json")
    raw["evidence_cue_ids"] = [999999]
    errors = collect_response_errors_v5(TopicChainReviewV5, json.dumps(raw))
    assert not any(e.code == "unknown_cue" for e in errors)


@pytest.mark.parametrize("container", ["standalone", "ledger"])
@pytest.mark.parametrize("schema_fault", [False, True])
def test_discovery_references_do_not_require_transcript(container, schema_fault):
    batch, _, _ = fixture()
    raw = batch.model_dump(mode="json")
    raw["candidates"][0]["topic_fragment_ids"] = [None, "missing", "missing"]
    raw["candidates"][0]["source_batch_id"] = "wrong_batch"
    raw["candidates"][0]["start_cue_id"] = 99999
    raw["candidates"][0]["end_cue_id"] = 1
    raw["logical_windows"][0]["candidate_ids"].extend([None, "missing"])
    last_index = len(raw["logical_windows"][0]["candidate_ids"]) - 1
    if schema_fault:
        del raw["candidates"][0]["central_question"]
    model = DiscoveryBatchOutputV5
    prefix = ()
    if container == "ledger":
        ledger = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
        ledger["batches"][0] = raw
        if schema_fault:
            ledger["counts"]["originals"] = "invalid"
        raw = ledger
        model = LineageLedgerV5
        prefix = ("batches", 0)
    errors = collect_response_errors_v5(model, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert {
        ((*prefix, "candidates", 0, "topic_fragment_ids", 1), "unknown_id"),
        ((*prefix, "candidates", 0, "topic_fragment_ids", 2), "duplicate_id"),
        ((*prefix, "candidates", 0, "source_batch_id"), "batch_mismatch"),
        ((*prefix, "candidates", 0), "reversed_interval"),
        ((*prefix, "logical_windows", 0, "candidate_ids", last_index), "unknown_id"),
    } <= actual
    assert not any(e.code == "unknown_cue" for e in errors)


@pytest.mark.parametrize("container", ["standalone", "ledger"])
@pytest.mark.parametrize("boundary", ["before", "exclusive_end"])
@pytest.mark.parametrize("schema_fault", [False, True])
@pytest.mark.parametrize("malformed_sibling", [False, True])
def test_discovery_ownership_uses_transcript_and_preserves_wire_index(
    container, boundary, schema_fault, malformed_sibling
):
    batch, _, _ = fixture()
    raw = batch.model_dump(mode="json")
    candidate_index = 1 if malformed_sibling else 0
    if malformed_sibling:
        raw["candidates"].insert(0, None)
    if boundary == "exclusive_end":
        raw["candidates"][candidate_index]["start_cue_id"] = 2
    start_id = raw["candidates"][candidate_index]["start_cue_id"]
    start_ms = next(c.start_ms for c in transcript_cues(transcript()) if c.cue_id == start_id)
    if boundary == "before":
        raw["ownership_interval"]["start_ms"] = start_ms + 1
    else:
        raw["ownership_interval"]["end_ms"] = start_ms
    model = DiscoveryBatchOutputV5
    prefix = ()
    if schema_fault:
        raw["candidates"][candidate_index]["central_question"] = []
    if container == "ledger":
        ledger = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
        ledger["batches"][0] = raw
        ledger["counts"]["originals"] = "bad"
        raw = ledger
        model = LineageLedgerV5
        prefix = ("batches", 0)
    errors = collect_response_errors_v5(model, json.dumps(raw), transcript=transcript())
    assert (
        (*prefix, "candidates", candidate_index, "start_cue_id"),
        "outside_batch_ownership",
    ) in {(e.location, e.code) for e in errors}
    if schema_fault or malformed_sibling or container == "ledger":
        assert any(e.code == "schema" for e in errors)


def test_discovery_ownership_is_unknown_without_transcript():
    batch, _, _ = fixture()
    raw = batch.model_dump(mode="json")
    raw["ownership_interval"]["start_ms"] = 10_000
    errors = collect_response_errors_v5(DiscoveryBatchOutputV5, json.dumps(raw))
    assert not any(e.code == "outside_batch_ownership" for e in errors)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("candidate_id", "wrong", "candidate_mismatch"),
        ("clip_profile", "short_highlight", "profile_mismatch"),
    ],
)
@pytest.mark.parametrize("schema_fault", ["none", "invalid_count", "missing_unit"])
def test_boundary_identity_is_independent_of_transcript(field, value, code, schema_fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["outcomes"][0]["boundary"][field] = value
    if schema_fault == "invalid_count":
        raw["counts"]["originals"] = "invalid"
    elif schema_fault == "missing_unit":
        del raw["outcomes"][0]["unit"]
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert (("outcomes", 0, "boundary", field), code) in {(e.location, e.code) for e in errors}


@pytest.mark.parametrize("include_authority", [False, True])
def test_standalone_boundary_identity_needs_only_unit(include_authority):
    inputs = ledger_inputs()
    ledger = build_lineage_ledger_v5(**inputs)
    outcome = ledger.outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw["clip_profile"] = "short_highlight"
    errors = collect_response_errors_v5(
        BoundaryReviewV5,
        json.dumps(raw),
        unit=outcome.unit,
        authority=outcome.authority if include_authority else None,
    )
    assert (("clip_profile",), "profile_mismatch") in {(e.location, e.code) for e in errors}


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "malformed",
        "empty",
        "truncated_first",
        "truncated_last",
        "malformed_first",
        "malformed_last",
    ],
)
def test_chain_new_count_uses_canonical_units_despite_outcome_carrier_faults(fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["chain_new_outcomes"] = []
    if fault == "missing":
        del raw["outcomes"]
    elif fault == "malformed":
        raw["outcomes"] = {}
    elif fault == "empty":
        raw["outcomes"] = []
    elif fault == "truncated_first":
        raw["outcomes"].pop(0)
    elif fault == "truncated_last":
        raw["outcomes"].pop()
    elif fault == "malformed_first":
        raw["outcomes"][0] = None
    else:
        raw["outcomes"][-1] = None
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert (("chain_new_outcomes",), "record_count_mismatch") in {
        (e.location, e.code) for e in errors
    }


def test_chain_new_known_unit_copy_survives_missing_all_outcomes():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["outcomes"]
    raw["chain_new_outcomes"][0]["unit"]["candidate_id"] = "wrong"
    raw["chain_new_outcomes"][0]["boundary"]["candidate_id"] = "wrong"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert (("chain_new_outcomes", 0, "unit", "candidate_id"), "provenance_mismatch") in actual
    assert (("chain_new_outcomes", 0, "boundary", "candidate_id"), "candidate_mismatch") in actual


def test_chain_new_unknown_classification_does_not_invent_count():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["reviews"][0]["candidates"][0]["origin_kind"]
    del raw["outcomes"]
    raw["chain_new_outcomes"] = []
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert not any(e.location == ("chain_new_outcomes",) for e in errors)


@pytest.mark.parametrize("with_transcript", [False, True])
def test_chain_new_risk_claims_remain_checkable_without_outcomes(with_transcript):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    record = raw["chain_new_outcomes"][0]
    missing = {r["risk_id"] for r in record["authority"]["risks"]}
    assert missing
    del raw["outcomes"]
    raw["counts"]["originals"] = "invalid"
    record["authority"]["risks"] = []
    record["boundary"]["risk_treatments"] = []
    record["boundary"]["clip_profile"] = "short_highlight"
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("chain_new_outcomes", 0, "authority", "risks", r), "missing_risk_authority")
        for r in missing
    } <= actual
    assert {
        (("chain_new_outcomes", 0, "boundary", "risk_treatments", r), "missing_risk_treatment")
        for r in missing
    } <= actual
    assert (("chain_new_outcomes", 0, "boundary", "clip_profile"), "profile_mismatch") in actual


def test_partial_ledger_malformed_scalar_identities_return_diagnostics():
    valid = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    paths = []

    def visit(value, path=()):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_id") and isinstance(item, str):
                    paths.append((*path, key))
                visit(item, (*path, key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, (*path, i))

    visit(valid)
    checked = 0
    for path in paths:
        for bad in ([], {}, None, True, 7):
            raw = copy.deepcopy(valid)
            parent = raw
            for part in path[:-1]:
                parent = parent[part]
            parent[path[-1]] = bad
            errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
            assert any(e.code == "schema" for e in errors), (path, bad)
            checked += 1
    assert checked > 500


def transcript():
    return TranscriptDocument(
        source_duration_ms=600_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            TranscriptSegment(
                segment_id=f"s{i}",
                start_ms=(i - 1) * 10_000,
                end_ms=i * 10_000,
                text=f"教学证据{i}",
            )
            for i in range(1, 61)
        ),
    )


def fixture():
    def fragment(name):
        return dict(
            topic_fragment_id=name,
            logical_window_id="w",
            topic_summary="练习",
            central_question="怎样练习",
            learning_outcome="掌握练习",
            start_cue_id=1,
            end_cue_id=60,
            touches_left_boundary=False,
            touches_right_boundary=False,
            left_complete=True,
            right_complete=True,
            evidence_cue_ids=[1, 60],
            possible_profiles=["mini_lesson"],
            source_batch_id="batch",
        )

    def original(name, fragments, cue):
        return dict(
            candidate_id=name,
            source_topic_id=f"t_{name}",
            topic_fragment_ids=fragments,
            topic_summary="练习",
            central_question="怎样练习",
            learning_outcome="掌握练习",
            start_cue_id=1,
            end_cue_id=60,
            evidence_cue_ids=[1, 60],
            possible_profiles=["short_highlight"] if name == "C" else ["mini_lesson"],
            risks=[
                dict(risk_id="r", flag="absolute_claim", reason="源风险", evidence_cue_ids=[cue]),
                dict(
                    risk_id="r2", flag="absolute_claim", reason="独立源风险", evidence_cue_ids=[cue]
                ),
            ],
            source_window_ids=["w"],
            source_batch_id="batch",
        )

    batch = wire(
        DiscoveryBatchOutputV5,
        dict(
            batch_id="batch",
            batch_context=dict(start_ms=0, end_ms=600_000),
            ownership_interval=dict(start_ms=0, end_ms=600_000),
            logical_windows=[
                dict(
                    logical_window_id="w",
                    window_start_ms=0,
                    window_end_ms=600_000,
                    candidate_ids=["A", "B", "C"],
                    fragment_ids=["f1", "f2", "f3", "f4"],
                    left_boundary=dict(related_candidate_ids=["A"], related_fragment_ids=["f1"]),
                    right_boundary=dict(related_candidate_ids=["C"], related_fragment_ids=["f3"]),
                )
            ],
            candidates=[
                original("A", ["f1", "f2"], 35),
                original("B", ["f1"], 25),
                original("C", ["f3"], 5),
            ],
            topic_fragments=[fragment(f"f{i}") for i in range(1, 5)],
        ),
    )
    chains = tuple(
        wire(
            TopicChainV4,
            dict(
                topic_chain_id=f"c{i}",
                fragment_ids=[f"f{i}"],
                central_question="怎样练习",
                learning_outcome="掌握练习",
                topic_outline=["说明", "实践"],
                source_start_cue_id=31 if i == 2 else 1,
                source_end_cue_id=60 if i == 2 else 30,
                left_closed=True,
                right_closed=True,
                chain_status="closed",
            ),
        )
        for i in range(1, 5)
    )

    def unit(name, chain, origins, start):
        return dict(
            candidate_id=name,
            clip_profile="mini_lesson",
            source_topic_id=f"t_{chain}",
            topic_chain_id=f"c{chain}",
            source_fragment_ids=[f"f{chain}"],
            start_cue_id=start,
            end_cue_id=start + 9,
            central_question="怎样练习",
            learning_outcome="掌握练习",
            title="练习",
            summary="完成练习",
            evidence_cue_ids=[start],
            origin_kind="derived" if origins else "chain_new",
            original_candidate_ids=origins,
            origin_reason="模型依据",
            natural_subunit=False,
        )

    def disposition(source, chain, units):
        return dict(
            original_candidate_id=source,
            topic_chain_id=f"c{chain}",
            derived_unit_ids=units,
            rejection_reason=None if units else "目标不完整",
            evidence_cue_ids=[31 if chain == 2 else 1],
        )

    units = [
        [unit("u1", 1, ["A", "B"], 1), unit("u2", 1, ["A"], 11), unit("u5", 1, ["B"], 21)],
        [unit("u3", 2, ["A"], 31)],
        [],
        [unit("u4", 4, [], 1)],
    ]
    sources = [
        [disposition("A", 1, ["u1", "u2"]), disposition("B", 1, ["u1", "u5"])],
        [disposition("A", 2, ["u3"])],
        [disposition("C", 3, [])],
        [],
    ]
    reviews = tuple(
        wire(
            TopicChainReviewV5,
            dict(
                topic_chain_id=c.topic_chain_id,
                central_question=c.central_question,
                learning_outcome=c.learning_outcome,
                topic_outline=list(c.topic_outline),
                left_closed=True,
                right_closed=True,
                chain_status="closed",
                candidates=units[i],
                rejection_reason=None if units[i] else "no_complete_profile_candidate",
                evidence_cue_ids=[c.source_start_cue_id],
                source_dispositions=sources[i],
            ),
        )
        for i, c in enumerate(chains)
    )
    return batch, chains, reviews


def boundary(unit, authority, *, drop=False):
    cue = unit.start_cue_id
    return wire(
        BoundaryReviewV5,
        dict(
            candidate_id=unit.candidate_id,
            clip_profile="mini_lesson",
            content_decision="drop" if drop else "keep",
            proposed_start_cue_id=None if drop else cue,
            proposed_end_cue_id=None if drop else unit.end_cue_id,
            opening_complete=True,
            ending_complete=True,
            central_objective_complete=True,
            boundary_compactness="shortest_complete",
            opening_relevance="direct",
            ending_relevance="necessary_conclusion",
            internal_topic_switch=False,
            contains_padding=False,
            quality_flags=[],
            risk_flags=[],
            evidence=dict(
                opening_cue_ids=[cue], core_cue_ids=[cue], ending_cue_ids=[unit.end_cue_id]
            ),
            review_reason="模型审查依据",
            risk_treatments=[
                dict(
                    risk_id=r.risk_id,
                    treatment="dropped_candidate" if drop else "resolved_in_context",
                    reason="模型在最终内容中解释",
                    evidence_cue_ids=[cue],
                )
                for r in authority.risks
            ],
        ),
    )


def authority_for(unit, chain, originals):
    return build_boundary_authority_v5(
        unit,
        chain=chain,
        originals=originals,
        context_cue_ids=tuple(
            range(max(1, unit.start_cue_id - 3), min(60, unit.end_cue_id + 3) + 1)
        ),
    )


def ledger_inputs():
    batch, chains, reviews = fixture()
    boundaries = tuple(
        boundary(u, authority_for(u, c, batch.candidates), drop=u.candidate_id == "u4")
        for c, r in zip(chains, reviews, strict=True)
        for u in r.candidates
    )
    partition = wire(
        FinalPartitionV5,
        dict(
            selected=["u1"], manual=["u2"], blocked=["u3"], rejected=["u4"], top_n_excluded=["u5"]
        ),
    )
    return dict(
        batches=(batch,),
        chains=chains,
        reviews=reviews,
        boundaries=boundaries,
        partition=partition,
        transcript=transcript(),
    )


def test_partial_partition_preserves_original_indices_after_invalid_siblings():
    raw = dict(
        selected=[7, 8, "missing", "unit_a", "unit_a"],
        manual=[],
        blocked=[],
        rejected=[],
        top_n_excluded=[],
    )
    errors = collect_response_errors_v5(FinalPartitionV5, json.dumps(raw), unit_ids={"unit_a"})
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("selected", 2), "unknown_unit"),
        (("selected", 4), "duplicate_final_disposition"),
    }


@pytest.mark.parametrize("container", ["partition", "ledger"])
@pytest.mark.parametrize("fault", ["missing_candidates", "malformed_candidate", "missing_id"])
def test_partition_duplicates_survive_incomplete_unit_authority(container, fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    review = raw["reviews"][0]
    if fault == "missing_candidates":
        del review["candidates"]
    elif fault == "malformed_candidate":
        review["candidates"].insert(0, None)
    else:
        del review["candidates"][0]["candidate_id"]
    partition = raw["partition"]
    partition["selected"] = [None, "unproven_unit", *(["unproven_unit"] * 251)]
    partition["manual"].append("unproven_unit")
    model = LineageLedgerV5 if container == "ledger" else FinalPartitionV5
    payload = raw if container == "ledger" else partition
    prefix = ("partition",) if container == "ledger" else ()
    with pytest.raises(ValueError):
        wire(model, payload)
    errors = collect_response_errors_v5(model, json.dumps(payload))
    assert any(e.code == "schema" for e in errors)
    assert {e.location for e in errors if e.code == "duplicate_final_disposition"} == {
        (*prefix, "selected", i) for i in range(2, 253)
    } | {(*prefix, "manual", 1)}
    assert not any(e.code in {"unknown_unit", "missing_final_disposition"} for e in errors)


@pytest.mark.parametrize("direction", ["forward", "reverse"])
def test_partial_chain_preserves_original_edge_indices(direction):
    batch, chains, reviews = fixture()
    routes = expected_routes_v5(batch.candidates, chains, batch.topic_fragments)
    raw = reviews[0].model_dump(mode="json")
    if direction == "forward":
        raw["source_dispositions"][0]["derived_unit_ids"] = [7, 8, "u5"]
        expected = (("source_dispositions", 0, "derived_unit_ids", 2), "missing_reverse_origin")
    else:
        raw["candidates"][2]["original_candidate_ids"] = [7, 8, "A"]
        expected = (("candidates", 2, "original_candidate_ids", 2), "missing_forward_edge")
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chains[0],
        routes=routes,
        known_cue_ids=set(range(1, 31)),
    )
    assert expected in {(e.location, e.code) for e in errors}
    assert any(e.code == "schema" for e in errors)


def test_ledger_cross_review_duplicate_uses_actual_nested_wire_location():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["reviews"][1]["candidates"] = [7, 8, copy.deepcopy(raw["reviews"][0]["candidates"][0])]
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert (("reviews", 1, "candidates", 2, "candidate_id"), "duplicate_id") in {
        (e.location, e.code) for e in errors
    }
    assert not any(e.location and e.location[0] == "units" for e in errors)


@pytest.mark.parametrize("with_transcript", [False, True])
@pytest.mark.parametrize("malformed_siblings", [False, True])
@pytest.mark.parametrize("repetitions", [1, 251])
def test_partial_ledger_cross_batch_original_duplicates(
    with_transcript, malformed_siblings, repetitions
):
    siblings = [None, {"candidate_id": []}] if malformed_siblings else []
    batches = [
        {"batch_id": "b1", "candidates": [*siblings, {"candidate_id": "same"}]},
    ]
    if malformed_siblings:
        batches.extend([None, {"batch_id": "unknown_candidates"}])
    repeated_batch_index = len(batches)
    batches.append(
        {
            "batch_id": "b2",
            "candidates": [
                *siblings,
                {"candidate_id": "distinct"},
                *[{"candidate_id": "same"} for _ in range(repetitions)],
            ],
        }
    )
    raw = {"batches": batches, "counts": {"originals": "invalid"}}
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    duplicates = [e.location for e in errors if e.code == "duplicate_id"]
    assert len(duplicates) == repetitions
    assert set(duplicates) == {
        ("batches", repeated_batch_index, "candidates", len(siblings) + 1 + i, "candidate_id")
        for i in range(repetitions)
    }
    assert any(e.location == ("counts", "originals") and e.code == "schema" for e in errors)


def test_strict_ledger_rejects_cross_batch_original_duplicates():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    duplicate_batch = copy.deepcopy(raw["batches"][0])
    duplicate_batch["batch_id"] = "b2"
    for record in (*duplicate_batch["candidates"], *duplicate_batch["topic_fragments"]):
        record["source_batch_id"] = "b2"
    raw["batches"].append(duplicate_batch)
    with pytest.raises(ValueError, match="duplicate original ID"):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert {
        ("batches", 1, "candidates", i, "candidate_id")
        for i in range(len(duplicate_batch["candidates"]))
    } <= {e.location for e in errors if e.code == "duplicate_id"}


def many_risk_ledger():
    inputs = ledger_inputs()
    raw = inputs["batches"][0].model_dump(mode="json")
    risk = raw["candidates"][0]["risks"][0]
    raw["candidates"][0]["risks"] = [dict(risk, risk_id=f"risk_{i}") for i in range(211)]
    batch = wire(DiscoveryBatchOutputV5, raw)
    inputs["batches"] = (batch,)
    inputs["boundaries"] = tuple(
        boundary(u, authority_for(u, c, batch.candidates), drop=u.candidate_id == "u4")
        for c, r in zip(inputs["chains"], inputs["reviews"], strict=True)
        for u in r.candidates
    )
    return build_lineage_ledger_v5(**inputs)


@pytest.mark.parametrize("with_transcript", [False, True])
def test_partial_ledger_checks_chain_fragment_authority_at_wire_indices(with_transcript):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    offset = len(raw["chains"][0]["fragment_ids"])
    raw["chains"][0]["fragment_ids"].extend([7, "invented_fragment", "invented_fragment"])
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    assert {(e.location, e.code) for e in errors if e.location[:1] == ("chains",)} == {
        (("chains", 0, "fragment_ids", offset), "schema"),
        (("chains", 0, "fragment_ids", offset + 1), "unknown_id"),
        (("chains", 0, "fragment_ids", offset + 2), "unknown_id"),
        (("chains", 0, "fragment_ids", offset + 2), "duplicate_id"),
    }
    assert (("counts", "originals"), "schema") in {(e.location, e.code) for e in errors}


def test_partial_ledger_checks_exact_chain_review_membership():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    missing_chain = raw["reviews"].pop(2)["topic_chain_id"]
    duplicate_index = len(raw["reviews"])
    raw["reviews"].append(copy.deepcopy(raw["reviews"][0]))
    raw["reviews"].append(dict(raw["reviews"][0], topic_chain_id="invented_chain"))
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("reviews", missing_chain), "missing_chain_review"),
        (("reviews", duplicate_index, "topic_chain_id"), "duplicate_id"),
        (("reviews", duplicate_index + 1, "topic_chain_id"), "unknown_id"),
        (("counts", "originals"), "schema"),
    } <= actual


@pytest.mark.parametrize("incomplete", ["fragments", "reviews"])
def test_partial_graph_does_not_invent_exclusions_from_incomplete_authority(incomplete):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    if incomplete == "fragments":
        del raw["batches"][0]["topic_fragments"]
        raw["chains"][0]["fragment_ids"].append("unresolved_fragment")
    else:
        raw["reviews"][2] = 7
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert any(e.code == "schema" for e in errors)
    assert not any(e.code == "missing_chain_review" for e in errors)
    assert not any(e.location[:1] == ("chains",) and e.code == "unknown_id" for e in errors)


@pytest.mark.parametrize("boundary_state", ["missing", "malformed"])
@pytest.mark.parametrize("with_transcript", [False, True])
def test_missing_boundary_does_not_hide_215_risk_authority_omissions(
    boundary_state, with_transcript
):
    raw = many_risk_ledger().model_dump(mode="json")
    outcome = raw["outcomes"][0]
    risk_ids = {risk["risk_id"] for risk in outcome["authority"]["risks"]}
    assert len(risk_ids) == 215
    outcome["authority"]["risks"] = []
    if boundary_state == "missing":
        del outcome["boundary"]
    else:
        outcome["boundary"] = 7
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    assert {(e.location, e.code) for e in errors} == {
        (("outcomes", 0, "authority", "risks", rid), "missing_risk_authority") for rid in risk_ids
    } | {(("outcomes", 0, "boundary"), "schema")}


def test_boundary_partial_diagnostics_need_authority_but_not_transcript_or_unit():
    outcome = many_risk_ledger().outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw["risk_treatments"] = []
    del raw["candidate_id"]
    errors = collect_response_errors_v5(
        BoundaryReviewV5, json.dumps(raw), authority=outcome.authority
    )
    expected = {
        (("risk_treatments", risk.risk_id), "missing_risk_treatment")
        for risk in outcome.authority.risks
    }
    assert {(e.location, e.code) for e in errors} == expected | {(("candidate_id",), "schema")}
    assert len(outcome.authority.risks) == 215


def test_chain_partial_structure_and_inverse_edges_need_no_external_context():
    _, _, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    del raw["central_question"]
    raw["rejection_reason"] = "topic_not_closed"
    raw["source_dispositions"][0]["derived_unit_ids"] = [7, 8, "u5"]
    errors = collect_response_errors_v5(TopicChainReviewV5, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert (("central_question",), "schema") in actual
    assert (("rejection_reason",), "candidates_with_rejection") in actual
    expected_edge = (("source_dispositions", 0, "derived_unit_ids", 2), "missing_reverse_origin")
    assert expected_edge in actual
    assert not any(e.code in {"unknown_cue", "unexpected_source"} for e in errors)


@pytest.mark.parametrize("with_transcript", [False, True])
@pytest.mark.parametrize("missing_context", [False, True])
def test_partial_ledger_reports_every_omitted_authority_and_treatment(
    with_transcript, missing_context
):
    raw = many_risk_ledger().model_dump(mode="json")
    outcome = raw["outcomes"][0]
    expected_ids = {r["risk_id"] for r in outcome["authority"]["risks"]}
    assert len(expected_ids) == 215
    outcome["authority"]["risks"] = []
    outcome["boundary"]["risk_treatments"] = []
    raw["counts"]["originals"] = "invalid"
    if missing_context:
        del outcome["authority"]["context_cue_ids"]
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    # Without either transcript or context, C's two context-only risks are unknowable.
    if missing_context and not with_transcript:
        expected_ids -= {r["risk_id"] for r in raw["originals"][2]["risks"]}
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("outcomes", 0, "authority", "risks", rid), "missing_risk_authority")
        for rid in expected_ids
    } <= actual
    assert {
        (("outcomes", 0, "boundary", "risk_treatments", rid), "missing_risk_treatment")
        for rid in expected_ids
    } <= actual
    assert (("counts", "originals"), "schema") in actual


def test_partial_ledger_risk_id_omissions_do_not_depend_on_source_prose():
    raw = many_risk_ledger().model_dump(mode="json")
    expected_ids = {r["risk_id"] for r in raw["outcomes"][0]["authority"]["risks"]}
    for risk in raw["batches"][0]["candidates"][0]["risks"]:
        del risk["reason"]
    raw["outcomes"][0]["authority"]["risks"] = []
    raw["outcomes"][0]["authority"]["context_cue_ids"] = []
    raw["outcomes"][0]["boundary"]["risk_treatments"] = []
    raw["originals"][0]["risks"] = []
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("outcomes", 0, "boundary", "risk_treatments", rid), "missing_risk_treatment")
        for rid in expected_ids
    } <= actual
    assert len([e for e in errors if e.code == "missing_original_risk"]) == 211
    assert {e.location for e in errors if e.code == "schema"} == {
        ("batches", 0, "candidates", 0, "risks", i, "reason") for i in range(211)
    } | {("outcomes", 0, "authority", "context_cue_ids")}


@pytest.mark.parametrize("invalid_source_prose", [False, True])
def test_partial_ledger_reports_all_invented_risks_and_treatments(invalid_source_prose):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes"][0]
    offset = len(outcome["authority"]["risks"])
    for i in range(211):
        risk = dict(outcome["authority"]["risks"][0], risk_id=f"invented_{i}")
        outcome["authority"]["risks"].append(risk)
        treatment = dict(outcome["boundary"]["risk_treatments"][0], risk_id=risk["risk_id"])
        outcome["boundary"]["risk_treatments"].append(treatment)
    raw["counts"]["originals"] = "invalid"
    if invalid_source_prose:
        del raw["batches"][0]["candidates"][0]["risks"][0]["reason"]
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("outcomes", 0, "authority", "risks", offset + i, "risk_id"), "unknown_source_risk")
        for i in range(211)
    } <= actual
    assert {
        (("outcomes", 0, "boundary", "risk_treatments", offset + i, "risk_id"), "unknown_risk")
        for i in range(211)
    } <= actual


def test_partial_ledger_rejects_known_risk_outside_unit_authority():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes"][1]  # u2, context8..23; C belongs to c3, cue5.
    risk = copy.deepcopy(raw["originals"][2]["risks"][0])
    offset = len(outcome["authority"]["risks"])
    assert risk["risk_id"] not in {r["risk_id"] for r in outcome["authority"]["risks"]}
    outcome["authority"]["risks"].append(risk)
    outcome["boundary"]["risk_treatments"].append(
        dict(outcome["boundary"]["risk_treatments"][0], risk_id=risk["risk_id"])
    )
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {
        (("outcomes", 1, "authority", "risks", offset, "risk_id"), "unexpected_risk_authority"),
        (("outcomes", 1, "boundary", "risk_treatments", offset, "risk_id"), "unknown_risk"),
    } <= {(e.location, e.code) for e in errors}


def test_missing_source_risk_list_does_not_invent_unknown_membership():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["batches"][0]["candidates"][0]["risks"]
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert any(e.code == "schema" for e in errors)
    assert not any(e.code in {"unknown_source_risk", "unknown_risk"} for e in errors)


@pytest.mark.parametrize("invented", [False, True])
def test_partial_original_risk_membership_is_exact(invented):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    risk = copy.deepcopy(raw["originals"][1]["risks"][0])
    if invented:
        risk["risk_id"] = "invented"
    offset = len(raw["originals"][0]["risks"])
    raw["originals"][0]["risks"].append(risk)
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert (("originals", 0, "risks", offset, "risk_id"), "unexpected_original_risk") in {
        (e.location, e.code) for e in errors
    }


def test_partition_gate_is_checkable_without_duplicate_outcome_disposition():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes"][1]
    outcome["boundary"]["risk_flags"] = ["medical_claim"]
    del outcome["disposition"]
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert (("partition", "manual", 0), "medical_risk_requires_blocked_or_rejected") in {
        (e.location, e.code) for e in errors
    }


@pytest.mark.parametrize("fault", ["absent", "malformed", "duplicate_id"])
def test_partition_gate_uses_canonical_unit_when_outcome_copies_are_invalid(fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes"][1]
    outcome["boundary"]["risk_flags"] = ["medical_claim"]
    del outcome["disposition"]
    if fault == "absent":
        del outcome["unit"]
    elif fault == "malformed":
        outcome["unit"] = None
    else:
        outcome["unit"]["candidate_id"] = raw["outcomes"][0]["unit"]["candidate_id"]
    raw["counts"]["originals"] = "invalid"
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert (("partition", "manual", 0), "medical_risk_requires_blocked_or_rejected") in {
        (e.location, e.code) for e in errors
    }


@pytest.mark.parametrize("stage", ["discovery", "topic_chain"])
@pytest.mark.parametrize("endpoint", ["start_cue_id", "end_cue_id"])
def test_unknown_scalar_cues_report_scalar_wire_locations(stage, endpoint):
    inputs = ledger_inputs()
    if stage == "discovery":
        model = DiscoveryBatchOutputV5
        raw = inputs["batches"][0].model_dump(mode="json")
    else:
        model = TopicChainReviewV5
        raw = inputs["reviews"][0].model_dump(mode="json")
    raw["candidates"][0][endpoint] = 999
    del raw["candidates"][0]["central_question"]
    with pytest.raises(ValueError):
        wire(model, raw)
    errors = collect_response_errors_v5(model, json.dumps(raw), known_cue_ids=set(range(1, 61)))
    assert {e.location for e in errors if e.code == "unknown_cue"} == {("candidates", 0, endpoint)}


@pytest.mark.parametrize(
    "gate,code",
    [
        ("drop", "dropped_unit_must_be_rejected"),
        ("medical_claim", "medical_risk_requires_blocked_or_rejected"),
        ("quality", "blocking_quality_requires_rejected"),
    ],
)
def test_partial_and_strict_ledger_reject_mandatory_boundary_gate_contradictions(gate, code):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    if gate == "drop":
        outcome = next(o for o in raw["outcomes"] if o["unit"]["candidate_id"] == "u4")
        raw["partition"]["rejected"].remove("u4")
        raw["partition"]["selected"].append("u4")
        raw["counts"]["rejected"] -= 1
        raw["counts"]["selected"] += 1
        outcome["disposition"] = "selected"
        raw["chain_new_outcomes"] = [copy.deepcopy(outcome)]
    else:
        outcome = next(o for o in raw["outcomes"] if o["unit"]["candidate_id"] == "u2")
        if gate == "quality":
            outcome["boundary"]["quality_flags"] = ["title_source_mismatch"]
        else:
            outcome["boundary"]["risk_flags"] = [gate]
    index = raw["outcomes"].index(outcome)
    with pytest.raises(ValueError, match=code):
        wire(LineageLedgerV5, raw)
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert (("outcomes", index, "disposition"), code) in {(e.location, e.code) for e in errors}


@pytest.mark.parametrize("disposition", ["blocked", "rejected"])
def test_medical_risk_allows_only_blocked_or_earlier_rejection(disposition):
    inputs = ledger_inputs()
    raw = inputs["boundaries"][1].model_dump(mode="json")
    raw["risk_flags"] = ["medical_claim"]
    inputs["boundaries"] = (
        inputs["boundaries"][0],
        wire(BoundaryReviewV5, raw),
        *inputs["boundaries"][2:],
    )
    with pytest.raises(ValueError, match="medical_risk_requires_blocked_or_rejected"):
        build_lineage_ledger_v5(**inputs)
    partition = inputs["partition"].model_dump(mode="json")
    partition["manual"] = []
    partition[disposition].append("u2")
    inputs["partition"] = wire(FinalPartitionV5, partition)
    ledger = build_lineage_ledger_v5(**inputs)
    assert (
        validate_lineage_ledger_v5(
            wire(LineageLedgerV5, ledger.model_dump(mode="json")), transcript=transcript()
        )
        == ledger
    )


def test_exact_many_to_many_terminal_paths_and_v5_roundtrip():
    inputs = ledger_inputs()
    ledger = build_lineage_ledger_v5(**inputs)
    assert {
        (r.original_candidate_id, r.topic_chain_id)
        for r in expected_routes_v5(
            inputs["batches"][0].candidates, inputs["chains"], inputs["batches"][0].topic_fragments
        )
    } == {("A", "c1"), ("A", "c2"), ("B", "c1"), ("C", "c3")}
    paths = {
        o.original.candidate_id: {(p.topic_chain_id, p.unit_id, p.disposition) for p in o.paths}
        for o in ledger.originals
    }
    assert paths == {
        "A": {("c1", "u1", "selected"), ("c1", "u2", "manual"), ("c2", "u3", "blocked")},
        "B": {("c1", "u1", "selected"), ("c1", "u5", "top_n_excluded")},
        "C": {("c3", None, "rejected")},
    }
    assert [(o.unit.candidate_id, o.disposition) for o in ledger.chain_new_outcomes] == [
        ("u4", "rejected")
    ]
    assert ledger.counts.model_dump() == dict(
        originals=3,
        units=5,
        derived_units=4,
        chain_new_units=1,
        terminal_paths=6,
        rejected_source_paths=1,
        selected=1,
        manual=1,
        blocked=1,
        rejected=1,
        top_n_excluded=1,
    )
    restored = parse_response_v5(LineageLedgerV5, ledger.model_dump_json())
    assert restored == ledger
    assert restored.originals[0].original.risks == inputs["batches"][0].candidates[0].risks
    assert restored.outcomes[0].unit.original_candidate_ids == ("A", "B")
    with pytest.raises(ValueError):
        restored.originals[0].risks[0].reason = "mutated"
    assert isinstance(restored.originals[0].risks[0].source_fragment_ids, tuple)


def test_one_original_rejected_in_one_chain_and_advancing_in_another():
    inputs = ledger_inputs()
    raw = inputs["reviews"][1].model_dump(mode="json")
    raw.update(candidates=[], rejection_reason="no_complete_profile_candidate")
    raw["source_dispositions"][0].update(derived_unit_ids=[], rejection_reason="此链不成立")
    inputs["reviews"] = (
        inputs["reviews"][0],
        wire(TopicChainReviewV5, raw),
        *inputs["reviews"][2:],
    )
    inputs["boundaries"] = tuple(b for b in inputs["boundaries"] if b.candidate_id != "u3")
    raw_partition = inputs["partition"].model_dump(mode="json")
    raw_partition["blocked"] = []
    inputs["partition"] = wire(FinalPartitionV5, raw_partition)
    ledger = build_lineage_ledger_v5(**inputs)
    assert {(p.topic_chain_id, p.unit_id, p.disposition) for p in ledger.originals[0].paths} == {
        ("c1", "u1", "selected"),
        ("c1", "u2", "manual"),
        ("c2", None, "rejected"),
    }


def test_empty_ledger_has_explicit_zeros():
    partition = wire(FinalPartitionV5, {k: [] for k in FinalPartitionV5.model_fields})
    ledger = build_lineage_ledger_v5(
        batches=(),
        chains=(),
        reviews=(),
        boundaries=(),
        partition=partition,
        transcript=transcript(),
    )
    assert all(v == 0 for v in ledger.counts.model_dump().values())
    assert parse_response_v5(LineageLedgerV5, ledger.model_dump_json()) == ledger


@pytest.mark.parametrize("invalid_chain_prose", [False, True])
@pytest.mark.parametrize("with_transcript", [False, True])
def test_partial_ledger_reports_all_201_chain_errors_despite_invalid_risk_reason(
    invalid_chain_prose,
    with_transcript,
):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["batches"][0]["candidates"][0]["risks"][0]["reason"]
    if invalid_chain_prose:
        del raw["chains"][0]["central_question"]
    review = raw["reviews"][0]
    offset = len(review["candidates"])
    for i in range(201):
        unit = copy.deepcopy(review["candidates"][0])
        unit.update(
            candidate_id=f"new_{i}",
            topic_chain_id="wrong",
            origin_kind="chain_new",
            original_candidate_ids=[],
        )
        review["candidates"].append(unit)
        raw["partition"]["selected"].append(unit["candidate_id"])
        outcome = copy.deepcopy(raw["outcomes"][0])
        outcome["unit"] = unit
        outcome["boundary"]["candidate_id"] = unit["candidate_id"]
        outcome["authority"]["candidate_id"] = unit["candidate_id"]
        raw["outcomes"].insert(offset + i, outcome)
    raw["chain_new_outcomes"] = [
        o for o in raw["outcomes"] if o["unit"]["origin_kind"] == "chain_new"
    ]
    for field in ("units", "chain_new_units", "selected"):
        raw["counts"][field] += 201
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("reviews", 0, "candidates", offset + i, "topic_chain_id"), "chain_mismatch")
        for i in range(201)
    }
    schema_locations = {("batches", 0, "candidates", 0, "risks", 0, "reason")}
    if invalid_chain_prose:
        schema_locations.add(("chains", 0, "central_question"))
    assert {e.location for e in errors if e.code == "schema"} == schema_locations


def test_partial_ledger_keeps_references_and_inverse_edges_without_complete_routing():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["batches"][0]["candidates"][0]["topic_fragment_ids"]
    review = raw["reviews"][0]
    review["candidates"][0]["original_candidate_ids"] = ["B"]
    review["candidates"][1]["source_fragment_ids"] = ["unknown_fragment"]
    review["source_dispositions"][1]["derived_unit_ids"] = ["u5"]
    raw["outcomes"][0]["unit"]["original_candidate_ids"] = ["B"]
    raw["outcomes"][1]["unit"]["source_fragment_ids"] = ["unknown_fragment"]
    raw["originals"][1]["paths"].pop(0)
    raw["counts"]["terminal_paths"] -= 1
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("reviews", 0, "source_dispositions", 0, "derived_unit_ids", 0), "missing_reverse_origin"),
        (("reviews", 0, "candidates", 0, "original_candidate_ids", 0), "missing_forward_edge"),
        (("reviews", 0, "candidates", 1, "source_fragment_ids", 0), "unknown_id"),
    }


@pytest.mark.parametrize(
    "case,code",
    [
        ("applies", "missing_source_flag"),
        ("uncertain", "missing_source_flag"),
        ("uncertain_without_sensitivity", "missing_sensitivity_review"),
        ("retained_drop", "retained_forbids_dropped_candidate"),
        ("drop_retained", "drop_requires_dropped_candidate"),
        ("drop_span", "drop_forbids_final_span"),
    ],
)
def test_strict_ledger_loading_rejects_treatment_contradictions(case, code):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes"][0]  # selected u1, including the reviewer's exact case
    if case.startswith("drop_"):
        outcome = next(o for o in raw["outcomes"] if o["unit"]["candidate_id"] == "u4")
    boundary_raw = outcome["boundary"]
    if case in ("applies", "uncertain"):
        boundary_raw["risk_treatments"][0]["treatment"] = case
    elif case == "uncertain_without_sensitivity":
        boundary_raw["risk_treatments"][0]["treatment"] = "uncertain"
        boundary_raw["risk_flags"] = ["absolute_claim"]
    elif case == "retained_drop":
        boundary_raw["risk_treatments"][0]["treatment"] = "dropped_candidate"
    elif case == "drop_retained":
        boundary_raw["risk_treatments"][0]["treatment"] = "resolved_in_context"
    else:
        boundary_raw.update(proposed_start_cue_id=1, proposed_end_cue_id=10)
    with pytest.raises(ValueError, match=code):
        parse_response_v5(LineageLedgerV5, json.dumps(raw))


def test_loaded_ledger_requires_contextual_revalidation_of_actual_span_claims():
    ledger = build_lineage_ledger_v5(**ledger_inputs())
    assert validate_lineage_ledger_v5(ledger, transcript=transcript()) == ledger
    raw = ledger.model_dump(mode="json")
    # C's evidence at cue 5 lies inside selected u1. This requires transcript times.
    raw["outcomes"][0]["boundary"]["risk_treatments"][-1]["treatment"] = "outside_final_span"
    loaded = parse_response_v5(LineageLedgerV5, json.dumps(raw))
    with pytest.raises(ValueError, match="source_evidence_inside_final_span"):
        validate_lineage_ledger_v5(loaded, transcript=transcript())


def test_strict_ledger_preserves_valid_manual_uncertain_treatments():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = next(o for o in raw["outcomes"] if o["unit"]["candidate_id"] == "u2")
    outcome["boundary"]["risk_treatments"][0]["treatment"] = "uncertain"
    outcome["boundary"]["risk_flags"] = ["absolute_claim", "sensitivity_review"]
    loaded = parse_response_v5(LineageLedgerV5, json.dumps(raw))
    assert validate_lineage_ledger_v5(loaded, transcript=transcript()) == loaded


def test_partial_ledger_treatment_checks_do_not_require_unit_prose_or_transcript():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["outcomes"][0]["unit"]["title"]
    raw["outcomes"][0]["boundary"]["risk_treatments"][0]["treatment"] = "applies"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("outcomes", 0, "boundary", "risk_treatments", 0, "treatment"), "missing_source_flag")
    }
    assert {e.location for e in errors if e.code == "schema"} == {("outcomes", 0, "unit", "title")}


@pytest.mark.parametrize("with_transcript", [False, True])
def test_invalid_authority_reason_does_not_hide_uncertain_flag_requirements(with_transcript):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["outcomes"][0]["authority"]["risks"][0]["reason"]
    raw["outcomes"][0]["boundary"]["risk_treatments"][0]["treatment"] = "uncertain"
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("outcomes", 0, "boundary", "risk_treatments", 0, "treatment"), "missing_source_flag"),
        (
            ("outcomes", 0, "boundary", "risk_treatments", 0, "treatment"),
            "missing_sensitivity_review",
        ),
    }
    assert {e.location for e in errors if e.code == "schema"} == {
        ("outcomes", 0, "authority", "risks", 0, "reason")
    }


def test_invalid_discovery_reason_does_not_hide_terminal_path_and_count_corruption():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["batches"][0]["candidates"][0]["risks"][0]["reason"]
    raw["originals"][0]["paths"][0]["unit_id"] = "unknown_unit"
    raw["counts"]["units"] = 999
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("originals", 0, "paths", 0, "unit_id"), "terminal_path_mismatch"),
        (("counts", "units"), "count_mismatch"),
    }
    assert {e.location for e in errors if e.code == "schema"} == {
        ("batches", 0, "candidates", 0, "risks", 0, "reason")
    }


def test_missing_context_does_not_invent_unknown_cues_or_hide_known_flag_claims():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["outcomes"][0]["authority"]["context_cue_ids"]
    raw["outcomes"][0]["boundary"]["risk_treatments"][0]["treatment"] = "uncertain"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("outcomes", 0, "boundary", "risk_treatments", 0, "treatment"), "missing_source_flag"),
        (
            ("outcomes", 0, "boundary", "risk_treatments", 0, "treatment"),
            "missing_sensitivity_review",
        ),
    }


def test_partial_ledger_provenance_checks_every_available_risk_field():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["outcomes"][0]["authority"]["risks"][0]["reason"]
    raw["outcomes"][0]["authority"]["risks"][0]["source_window_ids"] = ["forged_window"]
    raw["originals"][0]["original"]["source_batch_id"] = "forged_batch"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("outcomes", 0, "authority", "risks", 0, "source_window_ids", 0), "provenance_mismatch"),
        (("originals", 0, "original", "source_batch_id"), "provenance_mismatch"),
    }


def test_all_422_treatment_errors_survive_211_invalid_authority_reasons():
    inputs = ledger_inputs()
    batch_raw = inputs["batches"][0].model_dump(mode="json")
    original = batch_raw["candidates"][0]
    original["risks"] = [dict(original["risks"][0], risk_id=f"risk_{i}") for i in range(211)]
    batch = wire(DiscoveryBatchOutputV5, batch_raw)
    inputs["batches"] = (batch,)
    inputs["boundaries"] = tuple(
        boundary(u, authority_for(u, c, batch.candidates), drop=u.candidate_id == "u4")
        for c, review in zip(inputs["chains"], inputs["reviews"], strict=True)
        for u in review.candidates
    )
    raw = build_lineage_ledger_v5(**inputs).model_dump(mode="json")
    for i in range(211):
        del raw["outcomes"][0]["authority"]["risks"][i]["reason"]
        raw["outcomes"][0]["boundary"]["risk_treatments"][i]["treatment"] = "uncertain"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("outcomes", 0, "boundary", "risk_treatments", i, "treatment"), code)
        for i in range(211)
        for code in ("missing_source_flag", "missing_sensitivity_review")
    }
    assert {e.location for e in errors if e.code == "schema"} == {
        ("outcomes", 0, "authority", "risks", i, "reason") for i in range(211)
    }
    assert errors == collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript()
    )


@pytest.mark.parametrize(
    "case,field,code",
    [
        ("nonempty", "rejection_reason", "candidates_with_rejection"),
        ("empty", "rejection_reason", "empty_chain_without_rejection"),
        ("closed", "chain_status", "closed_chain_requires_closed_sides"),
    ],
)
@pytest.mark.parametrize("invalid_prose", [False, True])
def test_chain_structure_agrees_in_wire_preflight_and_context(case, field, code, invalid_prose):
    batch, chains, reviews = fixture()
    index = 2 if case == "empty" else 0
    raw = reviews[index].model_dump(mode="json")
    if case == "nonempty":
        raw["rejection_reason"] = "no_complete_profile_candidate"
    elif case == "empty":
        raw["rejection_reason"] = None
    else:
        raw["left_closed"] = False
    if invalid_prose:
        raw["central_question"] = 17
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chains[index],
        routes=expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
        known_cue_ids=set(range(1, 31)),
    )
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {((field,), code)}
    with pytest.raises(ValueError):
        changed = list(reviews)
        changed[index] = parse_response_v5(TopicChainReviewV5, json.dumps(raw))
        validate_graph_v5(
            batch.candidates, chains, batch.topic_fragments, changed, transcript=transcript()
        )
    if invalid_prose:
        assert {e.location for e in errors if e.code == "schema"} == {("central_question",)}
    else:
        assert any(e.code == "schema" and code in e.message for e in errors)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "cross_category"])
def test_actual_partition_must_be_complete_unique_and_known(change):
    inputs = ledger_inputs()
    raw = inputs["partition"].model_dump(mode="json")
    if change == "missing":
        raw["selected"] = []
    elif change == "duplicate":
        raw["selected"].append("u1")
    elif change == "unknown":
        raw["selected"].append("unknown")
    else:
        raw["manual"].append("u1")
    inputs["partition"] = wire(FinalPartitionV5, raw)
    with pytest.raises(ValueError):
        build_lineage_ledger_v5(**inputs)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_origin",
        "missing_reverse",
        "missing_forward",
        "duplicate_edge",
        "missing_disposition",
        "duplicate_disposition",
        "cross_chain",
        "unsafe",
        "missing_reason",
        "derived_empty",
        "chain_new_origins",
        "unknown_evidence",
    ],
)
def test_invalid_wire_or_contextual_graph_rejected(change):
    batch, chains, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    first = raw["candidates"][0]
    source = raw["source_dispositions"][0]
    if change == "unknown_origin":
        first["original_candidate_ids"].append("unknown")
    elif change == "missing_reverse":
        first["original_candidate_ids"] = ["B"]
    elif change == "missing_forward":
        source["derived_unit_ids"] = ["u2"]
    elif change == "duplicate_edge":
        source["derived_unit_ids"].append("u1")
    elif change == "missing_disposition":
        raw["source_dispositions"].pop()
    elif change == "duplicate_disposition":
        raw["source_dispositions"].append(copy.deepcopy(source))
    elif change == "cross_chain":
        first["topic_chain_id"] = "c2"
    elif change == "unsafe":
        first["candidate_id"] = "../execute"
    elif change == "missing_reason":
        first.pop("origin_reason")
    elif change == "derived_empty":
        first["original_candidate_ids"] = []
    elif change == "chain_new_origins":
        first["origin_kind"] = "chain_new"
    elif change == "unknown_evidence":
        first["evidence_cue_ids"] = [999]
    with pytest.raises(ValueError):
        changed = wire(TopicChainReviewV5, raw)
        validate_graph_v5(
            batch.candidates,
            chains,
            batch.topic_fragments,
            (changed, *reviews[1:]),
            transcript=transcript(),
        )


def test_unrouted_original_and_duplicate_authorities_fail():
    batch, chains, reviews = fixture()
    with pytest.raises(ValueError, match="unrouted"):
        expected_routes_v5(batch.candidates, chains[:2], batch.topic_fragments)
    with pytest.raises(ValueError, match="duplicate"):
        expected_routes_v5((*batch.candidates, batch.candidates[0]), chains, batch.topic_fragments)
    with pytest.raises(ValueError, match="duplicate"):
        validate_graph_v5(
            batch.candidates,
            chains,
            batch.topic_fragments,
            (*reviews, reviews[0]),
            transcript=transcript(),
        )


def test_namespacing_all_references_and_distinct_owning_risks():
    batch, _, _ = fixture()
    original_json = batch.model_dump_json()
    namespaced = namespace_discovery_batch_v5(batch)
    assert batch.model_dump_json() == original_json
    assert namespaced == namespace_discovery_batch_v5(batch)
    ids = {o.candidate_id for o in namespaced.candidates}
    fragments = {f.topic_fragment_id for f in namespaced.topic_fragments}
    window = namespaced.logical_windows[0]
    assert set(window.candidate_ids) == ids
    assert set(window.fragment_ids) == fragments
    assert window.left_boundary.related_candidate_ids == (namespaced.candidates[0].candidate_id,)
    assert window.right_boundary.related_fragment_ids == (
        namespaced.topic_fragments[2].topic_fragment_id,
    )
    assert all(o.source_window_ids == (window.logical_window_id,) for o in namespaced.candidates)
    assert all(f.logical_window_id == window.logical_window_id for f in namespaced.topic_fragments)
    risks = attribute_risks_v5(namespaced.candidates)
    assert len({r.risk_id for r in risks}) == 6
    assert len({r.flag for r in risks}) == 1
    for before, after in zip(batch.candidates, namespaced.candidates, strict=True):
        assert before.risks == after.risks
        assert before.source_topic_id != after.source_topic_id
        owned = tuple(r for r in risks if r.original_candidate_id == after.candidate_id)
        assert {r.local_risk_id for r in owned} == {"r", "r2"}
        assert all(
            r.source_batch_id == batch.batch_id
            and r.source_window_ids == after.source_window_ids
            and r.source_fragment_ids == after.topic_fragment_ids
            for r in owned
        )
    validate_discovery_batch_v5(
        namespaced,
        expected_batch_id="batch",
        expected_context=batch.batch_context,
        expected_ownership=batch.ownership_interval,
        expected_windows=(TimeRangeV4(start_ms=0, end_ms=600_000),),
        transcript=transcript(),
    )
    assert wire(DiscoveryBatchOutputV5, namespaced.model_dump(mode="json")) == namespaced


def test_namespace_framing_distinguishes_old_prefix_collision_and_maximum_ids():
    batch, _, _ = fixture()
    raw = batch.model_dump(mode="json")
    raw["candidates"][0]["candidate_id"] = "batch_B"
    raw["logical_windows"][0]["candidate_ids"][0] = "batch_B"
    raw["logical_windows"][0]["left_boundary"]["related_candidate_ids"] = ["batch_B"]
    normalized = namespace_discovery_batch_v5(wire(DiscoveryBatchOutputV5, raw))
    assert normalized.candidates[0].candidate_id != normalized.candidates[1].candidate_id
    raw["candidates"][0]["source_topic_id"] = "x" * 96
    assert (
        len(
            namespace_discovery_batch_v5(wire(DiscoveryBatchOutputV5, raw))
            .candidates[0]
            .source_topic_id
        )
        <= 96
    )


def test_boundary_authority_includes_chain_and_expansion_risks():
    batch, chains, reviews = fixture()
    unit = reviews[0].candidates[1]  # A origin, but B shares this Chain.
    authority = authority_for(unit, chains[0], batch.candidates)
    assert {r.original_candidate_id for r in authority.risks} == {"A", "B"}
    new = reviews[3].candidates[0]  # C risk at cue 5 intersects allowed context.
    new_authority = authority_for(new, chains[3], batch.candidates)
    assert {r.original_candidate_id for r in new_authority.risks} == {"C"}
    risk = batch.candidates[2].model_dump(mode="json")
    for r in risk["risks"]:
        r["evidence_cue_ids"] = [12]  # outside initial unit, inside expansion context
    altered = (*batch.candidates[:2], wire(type(batch.candidates[2]), risk))
    expanded = authority_for(new, chains[3], altered)
    assert {r.original_candidate_id for r in expanded.risks} == {"C"}


@pytest.mark.parametrize("kind", ["applies", "uncertain"])
def test_boundary_requires_model_flags_per_risk_identity(kind):
    batch, chains, reviews = fixture()
    unit = reviews[0].candidates[0]
    authority = authority_for(unit, chains[0], batch.candidates)
    raw = boundary(unit, authority).model_dump(mode="json")
    for treatment in raw["risk_treatments"]:
        treatment["treatment"] = kind
    with pytest.raises(ValueError, match="missing_source_flag"):
        validate_boundary_review_v5(
            wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=transcript()
        )
    raw["risk_flags"] = ["absolute_claim"]
    if kind == "uncertain":
        with pytest.raises(ValueError, match="missing_sensitivity_review"):
            validate_boundary_review_v5(
                wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=transcript()
            )
        raw["risk_flags"].append("sensitivity_review")
    raw["risk_flags"].append("music_rights_review")  # Additional model findings remain valid.
    review = wire(BoundaryReviewV5, raw)
    assert (
        validate_boundary_review_v5(review, authority=authority, unit=unit, transcript=transcript())
        == review
    )
    assert len(review.risk_treatments) == len(authority.risks)


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "missing",
        "duplicate",
        "outside",
        "resolved",
        "drop_span",
        "drop_treatment",
        "retained_drop",
        "quality",
    ],
)
def test_boundary_risk_and_current_quality_failures(change):
    batch, chains, reviews = fixture()
    unit = reviews[0].candidates[0]
    authority = authority_for(unit, chains[0], batch.candidates)
    raw = boundary(unit, authority).model_dump(mode="json")
    if change == "unknown":
        raw["risk_treatments"][0]["risk_id"] = "unknown"
    elif change == "missing":
        raw["risk_treatments"].pop()
    elif change == "duplicate":
        raw["risk_treatments"].append(copy.deepcopy(raw["risk_treatments"][0]))
    elif change == "outside":
        # C's source evidence at 5 is inside the final span.
        raw["risk_treatments"][-1]["treatment"] = "outside_final_span"
    elif change == "resolved":
        raw["risk_treatments"][0]["evidence_cue_ids"] = [12]
    elif change == "drop_span":
        raw["content_decision"] = "drop"
    elif change == "drop_treatment":
        raw.update(content_decision="drop", proposed_start_cue_id=None, proposed_end_cue_id=None)
    elif change == "retained_drop":
        raw["risk_treatments"][0]["treatment"] = "dropped_candidate"
    elif change == "quality":
        raw["opening_complete"] = False
    with pytest.raises(ValueError):
        validate_boundary_review_v5(
            wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=transcript()
        )


def test_repaired_final_span_invalidates_prior_outside_and_resolved_claims():
    batch, chains, reviews = fixture()
    unit = reviews[3].candidates[0]
    raw_original = batch.candidates[2].model_dump(mode="json")
    for risk in raw_original["risks"]:
        risk["evidence_cue_ids"] = [12]
    originals = (*batch.candidates[:2], wire(type(batch.candidates[2]), raw_original))
    authority = authority_for(unit, chains[3], originals)
    raw = boundary(unit, authority).model_dump(mode="json")
    for treatment in raw["risk_treatments"]:
        treatment["treatment"] = "outside_final_span"
    validate_boundary_review_v5(
        wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=transcript()
    )
    raw.update(content_decision="repair_boundary", proposed_end_cue_id=12)
    with pytest.raises(ValueError, match="source_evidence_inside_final_span"):
        validate_boundary_review_v5(
            wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=transcript()
        )
    raw = boundary(unit, authority).model_dump(mode="json")
    raw.update(content_decision="repair_boundary", proposed_start_cue_id=2, proposed_end_cue_id=11)
    with pytest.raises(ValueError, match="resolution_outside_final_span"):
        validate_boundary_review_v5(
            wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=transcript()
        )


def test_outside_risk_uses_actual_time_overlap_not_only_cue_number():
    batch, chains, reviews = fixture()
    unit = reviews[0].candidates[1]  # starts at cue 11 / 100 seconds
    raw_original = batch.candidates[0].model_dump(mode="json")
    raw_original["risks"][0]["evidence_cue_ids"] = [10]
    originals = (wire(type(batch.candidates[0]), raw_original), *batch.candidates[1:])
    raw_transcript = transcript().model_dump(mode="json")
    raw_transcript["segments"][9]["end_ms"] = 105_000
    overlapping = wire(TranscriptDocument, raw_transcript)
    authority = authority_for(unit, chains[0], originals)
    raw = boundary(unit, authority).model_dump(mode="json")
    raw["risk_treatments"][0]["treatment"] = "outside_final_span"
    with pytest.raises(ValueError, match="source_evidence_inside_final_span"):
        validate_boundary_review_v5(
            wire(BoundaryReviewV5, raw), authority=authority, unit=unit, transcript=overlapping
        )


def test_complete_partial_schema_errors_over_two_hundred_with_exact_indices():
    batch, chains, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    raw["central_question"] = 17  # independent schema error does not suppress edge checks
    raw["source_dispositions"][0]["derived_unit_ids"] = [f"missing_{i}" for i in range(241)]
    raw["candidates"][0]["origin_reason"] = []
    routes = expected_routes_v5(batch.candidates, chains, batch.topic_fragments)
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chains[0],
        routes=routes,
        known_cue_ids=set(range(1, 31)),
    )
    expected = {
        (("source_dispositions", 0, "derived_unit_ids", i), "unknown_id") for i in range(241)
    }
    expected |= {
        (("candidates", i, "original_candidate_ids", 0), "missing_forward_edge") for i in (0, 1)
    }
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == expected
    assert {e.location for e in errors if e.code == "schema"} == {
        ("central_question",),
        ("candidates", 0, "origin_reason"),
    }
    assert errors == collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chains[0],
        routes=routes,
        known_cue_ids=set(range(1, 31)),
    )


def test_strict_json_no_duplicate_member_nonfinite_or_coercion():
    for text in ('{"selected":[],"selected":["u"]}', '{"selected":NaN}', "{"):
        with pytest.raises(ValueError):
            parse_response_v5(FinalPartitionV5, text)
        assert collect_response_errors_v5(FinalPartitionV5, text)
    batch, _, _ = fixture()
    raw = batch.model_dump(mode="json")
    raw["candidates"][0]["start_cue_id"] = "1"
    with pytest.raises(ValueError):
        wire(DiscoveryBatchOutputV5, raw)
    raw = batch.model_dump(mode="json")
    raw["logical_windows"][0]["logical_window_id"] = " unsafe "
    with pytest.raises(ValueError):
        wire(DiscoveryBatchOutputV5, raw)


def test_payloads_preserve_explicit_v5_fields_and_source_authority():
    batch, chains, reviews = fixture()
    identity = dict(
        source_id="source",
        source_hash="sourcehash",
        prompt_hash="prompthash",
        semantic_profile="general",
    )
    topic = build_topic_chain_payload_v5(
        chains[0], batches=(batch,), chains=chains, transcript=transcript(), **identity
    )
    assert wire(DiscoveryBatchOutputV5, topic["batches"][0]) == batch
    assert topic["expected_routes"] == [
        dict(original_candidate_id="A", topic_chain_id="c1"),
        dict(original_candidate_id="B", topic_chain_id="c1"),
    ]
    payload = build_boundary_payload_v5(
        reviews[0].candidates[0],
        chain=chains[0],
        originals=batch.candidates,
        transcript=transcript(),
        **identity,
    )
    restored = json.loads(json.dumps(payload))
    assert wire(ChainCandidateV5, restored["candidate"]) == reviews[0].candidates[0]
    assert restored["authority"]["risks"] == payload["authority"]["risks"]
    assert payload["contract_version"] == "semantic-v5-lineage-v1"
    assert payload["validation_contract"] == "semantic-v4-quality-v2"


def test_discovery_payload_identity_and_transcript_remain_unchanged():
    cues = transcript_cues(transcript())
    raw = dict(
        unit_id="batch",
        source_range=dict(start_cue_id=1, end_cue_id=60),
        cues=[c.model_dump(mode="json") for c in cues],
        estimated_tokens=100,
        context_range_ms=dict(start_ms=0, end_ms=600_000),
        ownership_range_ms=dict(start_ms=0, end_ms=600_000),
        logical_windows_ms=[dict(start_ms=0, end_ms=600_000)],
    )
    unit = wire(SemanticInputUnit, raw)
    before = unit.model_dump_json()
    payload = build_discovery_payload_v5(
        unit, source_id="s", source_hash="h", prompt_hash="p", semantic_profile="vocal_coach_live"
    )
    assert payload["cues"] == raw["cues"]
    assert payload["schema_version"] == "5"
    assert payload["stage"] == "discovery"
    assert payload["semantic_profile"] == "vocal_coach_live"
    assert unit.model_dump_json() == before


@pytest.mark.parametrize("target", ["counts", "risk", "unit", "path", "chain_new", "treatment"])
def test_serialized_ledger_rejects_changed_provenance_or_partition(target):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    if target == "counts":
        raw["counts"]["originals"] += 1
    elif target == "risk":
        raw["originals"][0]["risks"][0]["source_batch_id"] = "forged"
    elif target == "unit":
        raw["outcomes"][0]["unit"]["original_candidate_ids"] = ["A"]
    elif target == "path":
        raw["originals"][0]["paths"].pop()
    elif target == "chain_new":
        raw["chain_new_outcomes"] = []
    elif target == "treatment":
        raw["outcomes"][0]["boundary"]["risk_treatments"].pop()
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)


def test_discovery_partial_fields_remain_independently_checkable_without_guessing():
    batch, _, _ = fixture()
    raw = batch.model_dump(mode="json")
    raw.pop("logical_windows")
    raw["candidates"][0]["risks"][0]["reason"] = 99
    raw["candidates"][0]["risks"][0]["evidence_cue_ids"] = [999]
    errors = collect_response_errors_v5(
        DiscoveryBatchOutputV5, json.dumps(raw), known_cue_ids=set(range(1, 61))
    )
    assert (("candidates", 0, "risks", 0, "evidence_cue_ids", 0), "unknown_cue") in {
        (e.location, e.code) for e in errors
    }
    assert not any(e.code == "unknown_id" and "source_window_ids" in e.location for e in errors)


def test_partial_boundary_reports_every_unknown_risk_alongside_schema_error():
    batch, chains, reviews = fixture()
    unit = reviews[0].candidates[0]
    authority = authority_for(unit, chains[0], batch.candidates)
    raw = boundary(unit, authority).model_dump(mode="json")
    raw["review_reason"] = []
    offset = len(raw["risk_treatments"])
    raw["risk_treatments"].extend(
        dict(risk_id=f"missing_{i}", treatment="applies", reason="独立证据", evidence_cue_ids=[1])
        for i in range(251)
    )
    errors = collect_response_errors_v5(
        BoundaryReviewV5, json.dumps(raw), authority=authority, unit=unit, transcript=transcript()
    )
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("risk_treatments", offset + i, "risk_id"), "unknown_risk") for i in range(251)
    }
    assert {e.location for e in errors if e.code == "schema"} == {("review_reason",)}


def test_ledger_partial_schema_error_keeps_every_partition_error():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["counts"]["originals"] = "invalid"
    raw["partition"]["selected"].extend(f"missing_{i}" for i in range(211))
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("partition", "selected", i + 1), "unknown_unit") for i in range(211)
    } | {(("counts", "selected"), "count_mismatch")}
    assert any(e.location == ("counts", "originals") and e.code == "schema" for e in errors)


@pytest.mark.parametrize("invalid_prose", [False, True])
@pytest.mark.parametrize(
    "variant,code",
    [
        ("nonexistent", "unknown_variant_reference"),
        ("u1", "self_variant_reference"),
    ],
)
def test_variant_references_fail_strict_ledger_and_partial_collection(variant, code, invalid_prose):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    for unit in (raw["reviews"][0]["candidates"][0], raw["outcomes"][0]["unit"]):
        unit.update(variant_of=variant, variant_relationship="long_version_of")
    with pytest.raises(ValueError, match=code):
        wire(LineageLedgerV5, raw)
    if invalid_prose:
        raw["counts"]["originals"] = "bad"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("reviews", 0, "candidates", 0, "variant_of"), code)
    }
    assert any(e.code == "schema" for e in errors)


@pytest.mark.parametrize("invalid_prose", [False, True])
def test_chain_duration_diagnostics_use_transcript_and_preserve_indices(invalid_prose):
    batch, chains, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    raw["candidates"][0]["end_cue_id"] = 1
    if invalid_prose:
        del raw["central_question"]
        raw["candidates"].insert(0, 7)
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chains[0],
        routes=expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
        known_cue_ids=set(range(1, 31)),
        transcript=transcript(),
    )
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("candidates", int(invalid_prose), "end_cue_id"), "profile_duration_violation")
    }
    assert any(e.code == "schema" for e in errors) == invalid_prose


@pytest.mark.parametrize("invalid_prose", [False, True])
def test_partial_ledger_reports_duration_even_with_invalid_count(invalid_prose):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["reviews"][0]["candidates"][0]["end_cue_id"] = 1
    raw["outcomes"][0]["unit"]["end_cue_id"] = 1
    if invalid_prose:
        raw["counts"]["originals"] = "bad"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {e.location for e in errors if e.code == "profile_duration_violation"} == {
        ("reviews", 0, "candidates", 0, "end_cue_id")
    }


@pytest.mark.parametrize("invalid_prose", [False, True])
@pytest.mark.parametrize("fault", ["unsplit", "evidence", "rejection"])
def test_partial_chain_reports_determinable_natural_split_faults(fault, invalid_prose):
    batch, chains, reviews = fixture()
    chain_raw = chains[0].model_dump(mode="json")
    chain_raw["source_end_cue_id"] = 60
    chain = wire(TopicChainV4, chain_raw)
    raw = reviews[0].model_dump(mode="json")
    if fault == "evidence":
        for unit in raw["candidates"]:
            unit["natural_subunit"] = True
            unit["natural_split_evidence_cue_ids"] = []
        expected = {
            (("candidates", i, "natural_split_evidence_cue_ids"), "missing_natural_split_evidence")
            for i in range(3)
        }
    elif fault == "rejection":
        raw["candidates"] = []
        raw["source_dispositions"] = []
        raw["rejection_reason"] = "no_complete_profile_candidate"
        expected = {(("rejection_reason",), "unsplit_long_chain_requires_rejection")}
    else:
        expected = {
            (("candidates", i, "natural_subunit"), "requires_natural_teaching_subunits")
            for i in range(3)
        }
    if invalid_prose:
        del raw["central_question"]
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chain,
        routes=expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
        known_cue_ids=set(range(1, 61)),
        transcript=transcript(),
    )
    codes = {
        "missing_natural_split_evidence",
        "unsplit_long_chain_requires_rejection",
        "requires_natural_teaching_subunits",
    }
    assert {(e.location, e.code) for e in errors if e.code in codes} == expected


def test_variant_membership_requires_complete_authority_but_self_reference_does_not():
    _, _, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    raw["candidates"][0].update(variant_of="u3", variant_relationship="long_version_of")
    assert not collect_response_errors_v5(TopicChainReviewV5, json.dumps(raw))
    assert not collect_response_errors_v5(
        TopicChainReviewV5, json.dumps(raw), unit_ids={"u1", "u2", "u3", "u5"}
    )
    errors = collect_response_errors_v5(
        TopicChainReviewV5, json.dumps(raw), unit_ids={"u1", "u2", "u5"}
    )
    assert {(e.location, e.code) for e in errors} == {
        (("candidates", 0, "variant_of"), "unknown_variant_reference")
    }
    raw["candidates"].insert(0, 7)
    raw["candidates"][1]["variant_of"] = "u1"
    errors = collect_response_errors_v5(TopicChainReviewV5, json.dumps(raw))
    assert {(e.location, e.code) for e in errors if e.code != "schema"} == {
        (("candidates", 1, "variant_of"), "self_variant_reference")
    }


def test_chain_natural_split_duration_and_boundary_context_are_enforced():
    batch, chains, reviews = fixture()
    raw_chain = chains[0].model_dump(mode="json")
    raw_chain["source_end_cue_id"] = 60
    longer = wire(TopicChainV4, raw_chain)
    with pytest.raises(ValueError, match="natural teaching subunits"):
        validate_graph_v5(
            batch.candidates,
            (longer, *chains[1:]),
            batch.topic_fragments,
            reviews,
            transcript=transcript(),
        )
    unit = reviews[0].candidates[0]
    raw_unit = unit.model_dump(mode="json")
    raw_unit["end_cue_id"] = 8
    invalid_duration = wire(ChainCandidateV5, raw_unit)
    raw_review = reviews[0].model_dump(mode="json")
    raw_review["candidates"][0] = invalid_duration.model_dump(mode="json")
    with pytest.raises(ValueError, match="duration"):
        validate_graph_v5(
            batch.candidates,
            chains,
            batch.topic_fragments,
            (wire(TopicChainReviewV5, raw_review), *reviews[1:]),
            transcript=transcript(),
        )
    authority = build_boundary_authority_v5(
        unit, chain=chains[0], originals=batch.candidates, context_cue_ids=tuple(range(1, 11))
    )
    with pytest.raises(ValueError, match="complete allowed context"):
        validate_boundary_review_v5(
            boundary(unit, authority), authority=authority, unit=unit, transcript=transcript()
        )


@pytest.mark.parametrize(
    "filename,model",
    [
        ("discovery-batch-v5.schema.json", DiscoveryBatchOutputV5),
        ("topic-chain-review-v5.schema.json", TopicChainReviewV5),
        ("boundary-review-v5.schema.json", BoundaryReviewV5),
        ("lineage-ledger-v5.schema.json", LineageLedgerV5),
    ],
)
def test_schema_drift_and_explicit_v5_nested_fields(filename, model):
    path = Path(__file__).parents[2] / "src/liveclip/schemas/semantic_v5" / filename
    schema = json.loads(path.read_text())
    assert schema == model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "5"
    if model is LineageLedgerV5:
        assert "risks" in schema["$defs"]["DiscoveryCandidateV5"]["properties"]
        assert "original_candidate_ids" in schema["$defs"]["ChainCandidateV5"]["required"]
        assert "risk_treatments" in schema["$defs"]["BoundaryReviewV5"]["required"]


@pytest.mark.parametrize(
    "path,operation",
    [
        *((("originals", i, "risks"), op) for i in range(3) for op in ("duplicate", "reverse")),
        *((("outcomes", i, "authority", "risks"), "reverse") for i in range(4)),
    ],
)
def test_partial_ledger_preserves_risk_sequence_errors(path, operation):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    value = raw
    for part in path:
        value = value[part]
    if operation == "duplicate":
        value.append(copy.deepcopy(value[0]))
        expected = {((*path, len(value) - 1, "risk_id"), "duplicate_id")}
    else:
        value.reverse()
        expected = {
            ((*path, i, "risk_id"), "risk_order_mismatch")
            for i in range(len(value))
            if i != len(value) - i - 1
        }
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert expected <= {(e.location, e.code) for e in errors}
    assert any(e.location == ("counts", "originals") and e.code == "schema" for e in errors)


def test_partial_ledger_reports_all_duplicate_original_risks_at_wire_indices():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    risks = raw["originals"][0]["risks"]
    risk = copy.deepcopy(risks[0])
    offset = len(risks)
    risks.extend([None, *[copy.deepcopy(risk) for _ in range(251)]])
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {e.location for e in errors if e.code == "duplicate_id"} == {
        ("originals", 0, "risks", offset + i + 1, "risk_id") for i in range(251)
    }
    assert not any(e.code == "risk_order_mismatch" for e in errors)


@pytest.mark.parametrize("fault", ["absent", "malformed", "wrong_id"])
@pytest.mark.parametrize("earlier_invalid", [False, True])
def test_canonical_original_preserves_risks_and_paths_without_valid_copy(fault, earlier_invalid):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    index = 1 if earlier_invalid else 0
    record = raw["originals"][index]
    missing = {r["risk_id"] for r in record["risks"]}
    if earlier_invalid:
        raw["batches"][0]["candidates"][0] = None
        raw["originals"][0] = None
    if fault == "absent":
        del record["original"]
    elif fault == "malformed":
        record["original"] = []
    else:
        record["original"]["candidate_id"] = "wrong_original"
    record["risks"] = []
    record["paths"] = []
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert {(("originals", index, "risks", r), "missing_original_risk") for r in missing} <= actual
    assert (("originals", index, "paths"), "record_count_mismatch") in actual


@pytest.mark.parametrize("fault", ["absent", "malformed"])
@pytest.mark.parametrize("missing_authority", [False, True])
def test_duplicate_original_risks_do_not_require_original_authority(fault, missing_authority):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    record = raw["originals"][0]
    risks = record["risks"]
    offset = len(risks)
    risks.extend([None, *[copy.deepcopy(risks[0]) for _ in range(251)]])
    if fault == "absent":
        del record["original"]
    else:
        record["original"] = None
    if missing_authority:
        del raw["batches"][0]["candidates"]
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert {e.location for e in errors if e.code == "duplicate_id"} == {
        ("originals", 0, "risks", offset + i + 1, "risk_id") for i in range(251)
    }


@pytest.mark.parametrize("fault", ["order", "foreign_risk"])
def test_known_original_risk_checks_survive_missing_copy_and_later_unknown_batch(fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    record = raw["originals"][0]
    del record["original"]
    raw["batches"].append(dict(batch_id="missing_candidates"))
    if fault == "order":
        record["risks"].reverse()
        expected = {
            (("originals", 0, "risks", i, "risk_id"), "risk_order_mismatch") for i in range(2)
        }
    else:
        record["risks"].append(copy.deepcopy(raw["originals"][1]["risks"][0]))
        expected = {(("originals", 0, "risks", 2, "risk_id"), "unexpected_original_risk")}
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert expected <= {(e.location, e.code) for e in errors}


@pytest.mark.parametrize("fault", ["absent", "malformed", "missing_id", "empty"])
@pytest.mark.parametrize("earlier_invalid", [False, True])
def test_canonical_outcome_keeps_identity_disposition_and_new_membership(fault, earlier_invalid):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    index = 1 if earlier_invalid else 0
    outcome = raw["outcomes"][index]
    outcome["disposition"] = "rejected"
    outcome["authority"]["candidate_id"] = "wrong"
    outcome["boundary"]["candidate_id"] = "wrong"
    if earlier_invalid:
        raw["outcomes"][0] = None
    if fault == "absent":
        del outcome["unit"]
    elif fault == "malformed":
        outcome["unit"] = []
    elif fault == "missing_id":
        del outcome["unit"]["candidate_id"]
    else:
        outcome["unit"] = {}
    raw["chain_new_outcomes"] = []
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert {
        (("outcomes", index, "disposition"), "disposition_mismatch"),
        (("outcomes", index, "authority", "candidate_id"), "candidate_mismatch"),
        (("outcomes", index, "boundary", "candidate_id"), "candidate_mismatch"),
        (("chain_new_outcomes",), "record_count_mismatch"),
    } <= {(e.location, e.code) for e in errors}


def test_outcome_identity_does_not_guess_unknown_review_offsets():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["reviews"].insert(0, dict(topic_chain_id="unknown_length"))
    for outcome in raw["outcomes"]:
        del outcome["unit"]
        outcome["disposition"] = "rejected"
        outcome["authority"]["candidate_id"] = "wrong"
    raw["chain_new_outcomes"] = []
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert not any(e.code in ("disposition_mismatch", "candidate_mismatch") for e in errors)
    assert not any(e.location == ("chain_new_outcomes",) for e in errors)


def test_original_authority_stops_at_unknown_batch_offsets():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    batch = copy.deepcopy(raw["batches"][0])
    raw["batches"].insert(0, dict(batch_id="missing_candidates"))
    del raw["originals"][0]["original"]
    raw["originals"][0]["risks"] = []
    raw["originals"][0]["paths"] = []
    assert raw["batches"][1] == batch
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert not any(
        e.location[:3] in (("originals", 0, "risks"), ("originals", 0, "paths"))
        and e.code in ("missing_original_risk", "record_count_mismatch", "terminal_path_mismatch")
        for e in errors
    )


def test_partial_known_risk_order_survives_missing_boundary_and_source_prose():
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["batches"][0]["candidates"][0]["risks"][0]["reason"]
    del raw["outcomes"][0]["boundary"]
    risks = raw["outcomes"][0]["authority"]["risks"]
    risks.reverse()
    risks.insert(0, None)
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    assert {e.location for e in errors if e.code == "risk_order_mismatch"} == {
        ("outcomes", 0, "authority", "risks", i + 1, "risk_id")
        for i in range(len(risks) - 1)
        if i != len(risks) - i - 2
    }


def test_partial_ledger_keeps_diagnostics_for_structural_list_mutations():
    from pydantic import ValidationError

    valid = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    lists = []

    def visit(value, path=()):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, (*path, key))
        elif isinstance(value, list):
            if value:
                lists.append((path, value))
            for i, item in enumerate(value):
                visit(item, (*path, i))

    visit(valid)
    checked = rejected = 0
    omissions = []
    for path, values in lists:
        mutations = [values[1:], [*values, values[0]]]
        if len(values) > 1:
            mutations.append(list(reversed(values)))
        for replacement in mutations:
            raw = copy.deepcopy(valid)
            parent = raw
            for part in path[:-1]:
                parent = parent[part]
            parent[path[-1]] = copy.deepcopy(replacement)
            checked += 1
            try:
                LineageLedgerV5.model_validate_json(json.dumps(raw))
            except ValidationError as exc:
                details = exc.errors(include_input=False, include_url=False)
                if not details or any(e["loc"] for e in details):
                    continue
                rejected += 1
            else:
                continue
            raw["counts"]["originals"] = "invalid"
            errors = collect_response_errors_v5(
                LineageLedgerV5, json.dumps(raw), transcript=transcript()
            )
            if not any(e.location != ("counts", "originals") for e in errors):
                omissions.append(path)
    assert checked >= 600 and rejected >= 300
    assert not omissions, omissions


@pytest.mark.parametrize("fault", ["absent", "malformed", "missing_id", "unknown_id"])
@pytest.mark.parametrize("invalid_earlier_unit", [False, True])
def test_canonical_unit_keeps_risk_authority_when_outcome_copy_is_invalid(
    fault, invalid_earlier_unit
):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    index = 1 if invalid_earlier_unit else 0
    if invalid_earlier_unit:
        raw["reviews"][0]["candidates"][0] = None
    outcome = raw["outcomes"][index]
    missing = {
        r["risk_id"]
        for r in outcome["authority"]["risks"]
        if r["original_candidate_id"] in {"A", "B"}
    }
    if fault == "absent":
        del outcome["unit"]
    elif fault == "malformed":
        outcome["unit"] = []
    elif fault == "missing_id":
        del outcome["unit"]["candidate_id"]
    else:
        outcome["unit"]["candidate_id"] = "unknown_unit"
    outcome["authority"]["risks"] = [
        r for r in outcome["authority"]["risks"] if r["risk_id"] not in missing
    ]
    outcome["boundary"]["risk_treatments"] = [
        r for r in outcome["boundary"]["risk_treatments"] if r["risk_id"] not in missing
    ]
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    actual = {(e.location, e.code) for e in errors}
    assert {
        (("outcomes", index, "authority", "risks", r), "missing_risk_authority") for r in missing
    } <= actual
    assert {
        (("outcomes", index, "boundary", "risk_treatments", r), "missing_risk_treatment")
        for r in missing
    } <= actual


@pytest.mark.parametrize(
    "decision,changed,code",
    [
        ("keep", True, "keep_changed_span"),
        ("repair_boundary", False, "repair_unchanged_span"),
    ],
)
@pytest.mark.parametrize("context", ["unit", "authority", "transcript"])
@pytest.mark.parametrize("schema_fault", [False, True])
def test_boundary_known_span_comparison_uses_available_unit(
    decision, changed, code, context, schema_fault
):
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw["content_decision"] = decision
    raw["proposed_start_cue_id"] = outcome.unit.start_cue_id + int(changed)
    if schema_fault:
        del raw["review_reason"]
    kwargs = {"unit": outcome.unit}
    if context != "unit":
        kwargs["authority"] = outcome.authority
    if context == "transcript":
        kwargs["transcript"] = transcript()
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw), **kwargs)
    assert any(e.code == code for e in errors)
    assert any(e.code == "schema" for e in errors) == schema_fault


@pytest.mark.parametrize("edge", ["start", "end"])
def test_boundary_keep_reports_known_changed_endpoint_despite_missing_sibling(edge):
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw[f"proposed_{edge}_cue_id"] += 1
    del raw[f"proposed_{'end' if edge == 'start' else 'start'}_cue_id"]
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw), unit=outcome.unit)
    assert any(e.code == "keep_changed_span" for e in errors)
    raw["content_decision"] = "repair_boundary"
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw), unit=outcome.unit)
    assert not any(e.code == "repair_unchanged_span" for e in errors)


@pytest.mark.parametrize(
    "case", ["keep_span", "repair_span", "risk_reference", "boundary_reference", "discontinuous"]
)
def test_strict_ledger_rejects_boundary_contradictions_without_transcript(case):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    boundary = raw["outcomes"][0]["boundary"]
    if case == "keep_span":
        boundary["proposed_start_cue_id"] += 1
    elif case == "repair_span":
        boundary["content_decision"] = "repair_boundary"
    elif case == "risk_reference":
        boundary["risk_treatments"][0]["evidence_cue_ids"] = [99999]
    elif case == "boundary_reference":
        boundary["evidence"]["core_cue_ids"] = [99999]
    else:
        boundary["continuous_source_interval"] = False
        boundary["quality_flags"] = ["multi_interval_edit"]
    with pytest.raises(ValueError):
        parse_response_v5(LineageLedgerV5, json.dumps(raw))


@pytest.mark.parametrize("container", ["standalone", "outcomes", "chain_new_outcomes"])
@pytest.mark.parametrize(
    "field", ["risk", "opening_cue_ids", "core_cue_ids", "ending_cue_ids", "interruption"]
)
@pytest.mark.parametrize("missing_unit", [False, True])
def test_boundary_reference_scope_survives_partial_siblings(container, field, missing_unit):
    ledger = build_lineage_ledger_v5(**ledger_inputs())
    raw = ledger.model_dump(mode="json")
    index = 0
    if container == "standalone":
        outcome = raw["outcomes"][0]
        kwargs = {"authority": ledger.outcomes[0].authority}
        if not missing_unit:
            kwargs["unit"] = ledger.outcomes[0].unit
        prefix = ()
    else:
        outcome = raw[container][index]
        kwargs = {}
        prefix = (container, index, "boundary")
        raw["counts"]["originals"] = "unrelated-invalid-count"
        if missing_unit:
            del outcome["unit"]
    boundary = outcome["boundary"]
    if field == "risk":
        boundary["risk_treatments"].insert(0, None)
        boundary["risk_treatments"][1]["evidence_cue_ids"] = [None, 99999]
        expected = (*prefix, "risk_treatments", 1, "evidence_cue_ids", 1)
    elif field == "interruption":
        boundary["interruption_review"] = [None, {"evidence_cue_ids": [None, 99999]}]
        expected = (*prefix, "interruption_review", 1, "evidence_cue_ids", 1)
    else:
        boundary["evidence"][field] = [None, 99999]
        expected = (*prefix, "evidence", field, 1)
    errors = collect_response_errors_v5(
        BoundaryReviewV5 if container == "standalone" else LineageLedgerV5,
        json.dumps(boundary if container == "standalone" else raw),
        **kwargs,
    )
    assert any(e.code == "schema" for e in errors)
    assert any(e.location == expected and e.code == "unknown_cue" for e in errors)


@pytest.mark.parametrize("context", ["none", "authority", "explicit_ids", "transcript"])
def test_boundary_scope_keeps_unknown_authority_distinct_from_empty(context):
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw["risk_treatments"][0]["evidence_cue_ids"] = [99999]
    kwargs = {}
    if context == "authority":
        kwargs["authority"] = outcome.authority
    elif context == "explicit_ids":
        kwargs["known_cue_ids"] = {1, 2, 3}
    elif context == "transcript":
        kwargs["transcript"] = transcript()
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw), **kwargs)
    assert any(e.code == "unknown_cue" for e in errors) == (context != "none")


@pytest.mark.parametrize("with_unit", [False, True])
def test_boundary_retained_continuous_interval_fact_needs_no_transcript(with_unit):
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw["continuous_source_interval"] = False
    raw["quality_flags"] = ["multi_interval_edit"]
    errors = collect_response_errors_v5(
        BoundaryReviewV5,
        json.dumps(raw),
        unit=outcome.unit if with_unit else None,
    )
    assert any(
        e.code == "current_quality" and "one continuous interval" in e.message for e in errors
    )


def test_boundary_scope_reports_more_than_two_hundred_treatment_references():
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    treatment = {**raw["risk_treatments"][0], "evidence_cue_ids": [None, 99999]}
    raw["risk_treatments"] = [None, *[dict(treatment) for _ in range(251)]]
    errors = collect_response_errors_v5(
        BoundaryReviewV5, json.dumps(raw), authority=outcome.authority
    )
    assert {e.location for e in errors if e.code == "unknown_cue"} == {
        ("risk_treatments", i, "evidence_cue_ids", 1) for i in range(1, 252)
    }


@pytest.mark.parametrize("context", ["absent", "malformed", "empty"])
@pytest.mark.parametrize("with_transcript", [False, True])
def test_boundary_incomplete_context_does_not_invent_exclusion(context, with_transcript):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes"][0]
    if context == "absent":
        del outcome["authority"]["context_cue_ids"]
    else:
        outcome["authority"]["context_cue_ids"] = [1, None] if context == "malformed" else []
    outcome["boundary"]["risk_treatments"][0]["evidence_cue_ids"] = [99999]
    errors = collect_response_errors_v5(
        LineageLedgerV5,
        json.dumps(raw),
        transcript=transcript() if with_transcript else None,
    )
    location = ("outcomes", 0, "boundary", "risk_treatments", 0, "evidence_cue_ids", 0)
    assert any(e.code == "unknown_cue" and e.location == location for e in errors) == (
        with_transcript or context == "empty"
    )


@pytest.mark.parametrize(
    "authority,known,with_transcript,unknown",
    [
        (True, {99999}, False, True),
        (False, {99999}, False, False),
        (False, {99999}, True, True),
        (True, None, False, True),
        (False, None, False, False),
    ],
)
def test_boundary_intersects_each_available_cue_authority(
    authority, known, with_transcript, unknown
):
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw["risk_treatments"][0]["evidence_cue_ids"] = [99999]
    errors = collect_response_errors_v5(
        BoundaryReviewV5,
        json.dumps(raw),
        known_cue_ids=known,
        authority=outcome.authority if authority else None,
        transcript=transcript() if with_transcript else None,
    )
    location = ("risk_treatments", 0, "evidence_cue_ids", 0)
    assert any(e.code == "unknown_cue" and e.location == location for e in errors) == unknown


@pytest.mark.parametrize("with_transcript", [False, True])
def test_boundary_does_not_invent_duration_from_cue_numbers(with_transcript):
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0]
    raw = outcome.boundary.model_dump(mode="json")
    raw.update(content_decision="repair_boundary", proposed_start_cue_id=2, proposed_end_cue_id=3)
    errors = collect_response_errors_v5(
        BoundaryReviewV5,
        json.dumps(raw),
        unit=outcome.unit,
        authority=outcome.authority,
        transcript=transcript() if with_transcript else None,
    )
    assert any("duration is outside its Profile" in e.message for e in errors) == with_transcript


@pytest.mark.parametrize("container", ["outcomes", "chain_new_outcomes"])
@pytest.mark.parametrize("scope", ["empty", "restricted"])
@pytest.mark.parametrize("with_transcript", [False, True])
def test_ledger_supplied_scope_remains_constraining_with_transcript(
    container, scope, with_transcript
):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw[container][0]
    context = outcome["authority"]["context_cue_ids"]
    assert 2 in context
    outcome["authority"]["context_cue_ids"] = (
        [] if scope == "empty" else [cue for cue in context if cue != 2]
    )
    boundary = outcome["boundary"]
    del boundary["review_reason"]
    boundary["risk_treatments"][0]["evidence_cue_ids"] = [None, 2]
    boundary["evidence"]["core_cue_ids"] = [None, 2]
    boundary["interruption_review"] = [None, {"evidence_cue_ids": [None, 2]}]
    errors = collect_response_errors_v5(
        LineageLedgerV5, json.dumps(raw), transcript=transcript() if with_transcript else None
    )
    assert any(e.code == "schema" for e in errors)
    assert {
        (container, 0, "boundary", "risk_treatments", 0, "evidence_cue_ids", 1),
        (container, 0, "boundary", "evidence", "core_cue_ids", 1),
        (container, 0, "boundary", "interruption_review", 1, "evidence_cue_ids", 1),
    } <= {e.location for e in errors if e.code == "unknown_cue"}
    if with_transcript:
        assert any(
            e.location[:4] == (container, 0, "authority", "context_cue_ids")
            and e.code in {"boundary_context_mismatch", "record_count_mismatch"}
            for e in errors
        )


@pytest.mark.parametrize("container", ["standalone", "outcomes", "chain_new_outcomes"])
@pytest.mark.parametrize("authority_fault", ["absent", "malformed"])
@pytest.mark.parametrize("sensitivity", [False, True])
@pytest.mark.parametrize("schema_fault", [False, True])
def test_uncertain_sensitivity_does_not_depend_on_risk_authority(
    container, authority_fault, sensitivity, schema_fault
):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw["outcomes" if container == "standalone" else container][0]
    boundary = outcome["boundary"]
    boundary["risk_treatments"][0]["treatment"] = "uncertain"
    boundary["risk_flags"] = ["sensitivity_review"] if sensitivity else []
    if schema_fault:
        del boundary["review_reason"]
        boundary["risk_treatments"].insert(0, None)
    index = int(schema_fault)
    if authority_fault == "absent":
        del outcome["authority"]
    else:
        outcome["authority"]["risks"] = [None]
    if container == "standalone":
        model, wire_raw, prefix = BoundaryReviewV5, boundary, ()
    else:
        # No Discovery risk universe is available to reconstruct the missing authority.
        del raw["batches"]
        model, wire_raw, prefix = LineageLedgerV5, raw, (container, 0, "boundary")
    errors = collect_response_errors_v5(model, json.dumps(wire_raw))
    assert any(
        e.location == (*prefix, "risk_treatments", index, "treatment")
        and e.code == "missing_sensitivity_review"
        for e in errors
    ) == (not sensitivity)
    if schema_fault:
        assert any(e.code == "schema" for e in errors)


@pytest.mark.parametrize("container", ["standalone", "outcomes", "chain_new_outcomes"])
@pytest.mark.parametrize("omitted", [False, True])
def test_optional_risk_flags_default_is_known_despite_invalid_siblings(container, omitted):
    ledger = build_lineage_ledger_v5(**ledger_inputs())
    raw = ledger.model_dump(mode="json")
    outcome = raw["outcomes" if container == "standalone" else container][0]
    boundary_raw = outcome["boundary"]
    boundary_raw["risk_treatments"][0]["treatment"] = "uncertain"
    boundary_raw["risk_flags"] = []
    if omitted:
        del boundary_raw["risk_flags"]
    del boundary_raw["review_reason"]
    if container == "standalone":
        errors = collect_response_errors_v5(
            BoundaryReviewV5, json.dumps(boundary_raw), authority=ledger.outcomes[0].authority
        )
        prefix = ()
    else:
        raw["counts"]["originals"] = "invalid"
        errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
        prefix = (container, 0, "boundary")
    codes = {e.code for e in errors if e.location == (*prefix, "risk_treatments", 0, "treatment")}
    assert {"missing_sensitivity_review", "missing_source_flag"} <= codes
    assert any(e.code == "schema" for e in errors)


@pytest.mark.parametrize("container", ["standalone", "outcomes"])
@pytest.mark.parametrize("missing", ["start", "both"])
def test_optional_boundary_endpoints_default_to_none_in_partial_wire(container, missing):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    boundary_raw = raw["outcomes"][0]["boundary"]
    del boundary_raw["proposed_start_cue_id"]
    if missing == "both":
        del boundary_raw["proposed_end_cue_id"]
    del boundary_raw["review_reason"]
    expected = (
        "boundary proposal requires both cue IDs"
        if missing == "start"
        else "kept or repaired boundary requires one concrete interval"
    )
    errors = collect_response_errors_v5(
        BoundaryReviewV5 if container == "standalone" else LineageLedgerV5,
        json.dumps(boundary_raw if container == "standalone" else raw),
    )
    assert any(expected in e.message for e in errors)


@pytest.mark.parametrize(
    "case", ["variant_of", "variant_relationship", "natural_split", "long_chain"]
)
@pytest.mark.parametrize("omitted", [False, True])
def test_chain_optional_defaults_preserve_independent_constraints(case, omitted):
    batch, chains, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    candidate = raw["candidates"][0]
    del candidate["summary"]
    chain = chains[0]
    if case == "variant_of":
        field, default, code = "variant_of", None, "incomplete_variant_relationship"
        candidate["variant_relationship"] = "long_version_of"
    elif case == "variant_relationship":
        field, default, code = "variant_relationship", None, "incomplete_variant_relationship"
        candidate["variant_of"] = "u2"
    elif case == "natural_split":
        field, default, code = (
            "natural_split_evidence_cue_ids",
            [],
            "missing_natural_split_evidence",
        )
        candidate["natural_subunit"] = True
    else:
        field, default, code = "natural_subunit", False, "requires_natural_teaching_subunits"
        chain_raw = chain.model_dump(mode="json")
        chain_raw["source_end_cue_id"] = 40
        chain = wire(type(chain), chain_raw)
    candidate[field] = default
    if omitted:
        del candidate[field]
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chain,
        routes=expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
        unit_ids={"u1", "u2", "u5"},
        transcript=transcript(),
    )
    assert any(e.code == code and e.location[:2] == ("candidates", 0) for e in errors)


@pytest.mark.parametrize("container", ["outcomes", "chain_new_outcomes"])
def test_omitted_unit_default_does_not_hide_changed_canonical_copy(container):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    review_index, outcome_index = (0, 0) if container == "outcomes" else (3, 4)
    canonical = raw["reviews"][review_index]["candidates"][0]
    canonical.update(natural_subunit=True, natural_split_evidence_cue_ids=[5])
    raw["outcomes"][outcome_index]["unit"].update(canonical)
    if container == "chain_new_outcomes":
        raw[container][0]["unit"].update(canonical)
    del raw[container][0]["unit"]["natural_subunit"]
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert any(
        e.code == "provenance_mismatch" and e.location == (container, 0, "unit", "natural_subunit")
        for e in errors
    )


@pytest.mark.parametrize("duplicate_kind", ["original", "chain"])
@pytest.mark.parametrize("scope", ["included", "unknown", "excluded"])
@pytest.mark.parametrize("supplied", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_authority_preserves_all_membership_claims(
    duplicate_kind, scope, supplied, reverse
):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    if duplicate_kind == "original":
        rows = raw["batches"][0]["candidates"]
        duplicate = copy.deepcopy(rows[2])
        field = "topic_fragment_ids"
        fragments = ["f1", None] if scope == "included" else ["f3"]
    else:
        rows = raw["chains"]
        duplicate = copy.deepcopy(rows[0])
        field = "fragment_ids"
        fragments = ["f3", None] if scope == "included" else ["f1"]
    if scope == "unknown":
        del duplicate[field]
    else:
        duplicate[field] = fragments
    rows.insert(0, duplicate) if reverse else rows.append(duplicate)
    outcome = raw["outcomes"][1]
    outcome["authority"]["context_cue_ids"] = [8]
    risk = copy.deepcopy(raw["originals"][2]["risks"][0])
    review = raw["reviews"][0]
    risk_index = len(outcome["authority"]["risks"])
    route_index = len(review["source_dispositions"])
    if supplied:
        outcome["authority"]["risks"].append(risk)
        outcome["boundary"]["risk_treatments"].append(
            dict(
                risk_id=risk["risk_id"],
                treatment="outside_final_span",
                reason="声明",
                evidence_cue_ids=[],
            )
        )
        review["source_dispositions"].append(
            dict(
                original_candidate_id="C",
                topic_chain_id="c1",
                derived_unit_ids=[],
                rejection_reason="不构成独立主题",
                evidence_cue_ids=[1],
            )
        )
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert any(e.code == "duplicate_id" for e in errors)
    assert (
        (("reviews", 0, "source_dispositions", "C"), "missing_source_disposition") in actual
    ) == (scope == "included" and not supplied)
    assert (
        (("outcomes", 1, "authority", "risks", risk["risk_id"]), "missing_risk_authority") in actual
    ) == (scope == "included" and not supplied)
    assert (
        (("outcomes", 1, "boundary", "risk_treatments", risk["risk_id"]), "missing_risk_treatment")
        in actual
    ) == (scope == "included" and not supplied)
    if supplied:
        assert (
            (
                ("reviews", 0, "source_dispositions", route_index, "original_candidate_id"),
                "unexpected_source",
            )
            in actual
        ) == (scope == "excluded")
        assert (
            (
                ("outcomes", 1, "authority", "risks", risk_index, "risk_id"),
                "unexpected_risk_authority",
            )
            in actual
        ) == (scope == "excluded")
        assert (
            (("outcomes", 1, "boundary", "risk_treatments", risk_index, "risk_id"), "unknown_risk")
            in actual
        ) == (scope == "excluded")
    with pytest.raises(ValueError):
        wire(LineageLedgerV5, raw)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("duplicate_kind", ["unit", "disposition"])
@pytest.mark.parametrize("scope", ["included", "unknown", "excluded"])
def test_duplicate_graph_claims_do_not_manufacture_missing_inverse_edges(
    reverse, duplicate_kind, scope
):
    batch, chains, reviews = fixture()
    raw = reviews[0].model_dump(mode="json")
    if duplicate_kind == "unit":
        rows, field = raw["candidates"], "original_candidate_ids"
        target = rows[0]
        target[field] = ["B"]
        duplicate = copy.deepcopy(target)
        values = ["A", None] if scope == "included" else ["B"]
        code, location = "missing_reverse_origin", ("source_dispositions", 0, "derived_unit_ids", 0)
    else:
        rows, field = raw["source_dispositions"], "derived_unit_ids"
        target = rows[0]
        target[field] = ["u2"]
        duplicate = copy.deepcopy(target)
        values = ["u1", None] if scope == "included" else ["u2"]
        code, location = "missing_forward_edge", ("candidates", 0, "original_candidate_ids", 0)
    if scope == "unknown":
        del duplicate[field]
    else:
        duplicate[field] = values
    rows.insert(0, duplicate) if reverse else rows.append(duplicate)
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(raw),
        chain=chains[0],
        routes=expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
    )
    assert any(e.code == "duplicate_id" for e in errors)
    assert any(e.code == code and e.location == location for e in errors) == (scope == "excluded")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("claim", ["flag", "evidence"])
def test_conflicting_duplicate_risk_claims_keep_every_known_constraint(reverse, claim):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    risks = raw["batches"][0]["candidates"][0]["risks"]
    duplicate = copy.deepcopy(risks[0])
    if claim == "flag":
        duplicate["flag"] = "medical_claim"
    else:
        duplicate["evidence_cue_ids"] = [8]
    risks.insert(0, duplicate) if reverse else risks.append(duplicate)
    boundary = raw["outcomes"][0]["boundary"]
    boundary["risk_treatments"][0]["treatment"] = (
        "applies" if claim == "flag" else "outside_final_span"
    )
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw), transcript=transcript())
    actual = {(e.location, e.code) for e in errors}
    expected = "missing_source_flag" if claim == "flag" else "source_evidence_inside_final_span"
    assert (("outcomes", 0, "boundary", "risk_treatments", 0, "treatment"), expected) in actual
    assert any(e.code == "duplicate_id" for e in errors)
    assert any(e.code == "provenance_mismatch" for e in errors)


def test_provider_local_cues_keep_absolute_boundary_timing_and_ids():
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[1]
    cues = tuple(c for c in transcript_cues(transcript()) if 8 <= c.cue_id <= 23)
    assert cues[0].cue_id == 8 and cues[0].start_ms == 70_000
    kwargs = dict(authority=outcome.authority, unit=outcome.unit, cues=cues)
    assert not collect_response_errors_v5(
        BoundaryReviewV5, outcome.boundary.model_dump_json(), **kwargs
    )
    raw = outcome.boundary.model_dump(mode="json")
    raw.update(content_decision="repair_boundary", proposed_start_cue_id=20, proposed_end_cue_id=23)
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw), **kwargs)
    assert any(e.code == "current_quality" and "duration" in e.message for e in errors)
    raw["proposed_end_cue_id"] = 24
    assert any(
        e.code == "unknown_cue"
        for e in collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw), **kwargs)
    )


def test_provider_local_cues_enforce_discovery_ownership_and_chain_duration():
    batch, chains, reviews = fixture()
    all_cues = transcript_cues(transcript())
    raw = batch.model_dump(mode="json")
    raw["ownership_interval"] = dict(start_ms=300_000, end_ms=400_000)
    raw["candidates"][0]["start_cue_id"] = 11
    errors = collect_response_errors_v5(
        DiscoveryBatchOutputV5, json.dumps(raw), cues=tuple(c for c in all_cues if c.cue_id >= 8)
    )
    assert any(
        e.code == "outside_batch_ownership" and e.location == ("candidates", 0, "start_cue_id")
        for e in errors
    )
    chain_raw = reviews[1].model_dump(mode="json")
    chain_raw["candidates"][0]["end_cue_id"] = 35
    errors = collect_response_errors_v5(
        TopicChainReviewV5,
        json.dumps(chain_raw),
        chain=chains[1],
        routes=expected_routes_v5(batch.candidates, chains, batch.topic_fragments),
        cues=tuple(c for c in all_cues if 31 <= c.cue_id <= 40),
    )
    assert any(e.code == "profile_duration_violation" for e in errors)


@pytest.mark.parametrize("fault", ["duplicate", "conflicting_time", "unknown_id"])
def test_local_cue_authority_rejects_conflicting_full_transcript(fault):
    cues = list(transcript_cues(transcript()))
    if fault == "duplicate":
        cues.append(cues[0])
    else:
        raw = cues[0].model_dump(mode="json")
        raw["start_ms" if fault == "conflicting_time" else "cue_id"] = (
            1 if fault == "conflicting_time" else 999
        )
        cues[0] = type(cues[0]).model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError, match="cue authority"):
        collect_response_errors_v5(
            DiscoveryBatchOutputV5,
            fixture()[0].model_dump_json(),
            transcript=transcript(),
            cues=cues,
        )


def test_omitting_every_actual_default_preserves_valid_ledger():
    ledger = build_lineage_ledger_v5(**ledger_inputs())
    text = ledger.model_dump_json(exclude_defaults=True)
    assert parse_response_v5(LineageLedgerV5, text) == ledger
    assert not collect_response_errors_v5(LineageLedgerV5, text, transcript=transcript())


@pytest.mark.parametrize("container", ["outcomes", "chain_new_outcomes"])
@pytest.mark.parametrize("context", [[], [8], [None], None])
def test_complete_empty_context_proves_unrelated_risk_exclusion(container, context):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    outcome = raw[container][1 if container == "outcomes" else 0]
    extra = copy.deepcopy(raw["originals"][2]["risks"][0])
    index = len(outcome["authority"]["risks"])
    outcome["authority"]["risks"].append(extra)
    if context is None:
        del outcome["authority"]["context_cue_ids"]
    else:
        outcome["authority"]["context_cue_ids"] = context
    outcome["boundary"]["risk_treatments"].append(
        {
            "risk_id": extra["risk_id"],
            "treatment": "outside_final_span",
            "reason": "模型声明",
            "evidence_cue_ids": [],
        }
    )
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    outcome_index = 1 if container == "outcomes" else 0
    expected = context == [] or context == [8]
    assert (
        any(
            e.code == "unexpected_risk_authority"
            and e.location == (container, outcome_index, "authority", "risks", index, "risk_id")
            for e in errors
        )
        == expected
    )
    assert (
        any(
            e.code == "unknown_risk"
            and e.location
            == (container, outcome_index, "boundary", "risk_treatments", index, "risk_id")
            for e in errors
        )
        == expected
    )


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "missing_fragments",
        "partial_fragments",
        "missing_original",
        "missing_chain_fragment",
    ],
)
def test_known_positive_routes_survive_incomplete_other_authority(fault):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    raw["reviews"][0]["source_dispositions"] = [
        row
        for row in raw["reviews"][0]["source_dispositions"]
        if row["original_candidate_id"] != "A"
    ]
    if fault == "missing_fragments":
        del raw["batches"][0]["candidates"][1]["topic_fragment_ids"]
    elif fault == "partial_fragments":
        raw["batches"][0]["candidates"][0]["topic_fragment_ids"].append(None)
    elif fault == "missing_original":
        raw["batches"][0]["candidates"].insert(0, None)
    elif fault == "missing_chain_fragment":
        raw["chains"][0]["fragment_ids"].append(None)
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    assert any(
        e.code == "missing_source_disposition"
        and e.location == ("reviews", 0, "source_dispositions", "A")
        for e in errors
    )
    if fault != "none":
        assert not any(e.code == "unexpected_source" for e in errors)


@pytest.mark.parametrize("source", ["C", "unknown_original"])
def test_known_route_exclusions_survive_unrelated_missing_fragment_authority(source):
    raw = build_lineage_ledger_v5(**ledger_inputs()).model_dump(mode="json")
    del raw["batches"][0]["candidates"][1]["topic_fragment_ids"]
    review = raw["reviews"][0]
    disposition_index = len(review["source_dispositions"])
    review["source_dispositions"].append(
        {
            "original_candidate_id": source,
            "topic_chain_id": "c1",
            "derived_unit_ids": ["u1"],
            "rejection_reason": None,
            "evidence_cue_ids": [1],
        }
    )
    origin_index = len(review["candidates"][0]["original_candidate_ids"])
    review["candidates"][0]["original_candidate_ids"].append(source)
    raw["counts"]["originals"] = "invalid"
    errors = collect_response_errors_v5(LineageLedgerV5, json.dumps(raw))
    actual = {(e.location, e.code) for e in errors}
    assert {
        (
            ("reviews", 0, "source_dispositions", disposition_index, "original_candidate_id"),
            "unexpected_source",
        ),
        (("reviews", 0, "candidates", 0, "original_candidate_ids", origin_index), "unknown_id"),
    } <= actual


@pytest.mark.parametrize("value", [None, "invalid", {"sensitivity_review": True}])
def test_present_invalid_optional_flags_are_not_replaced_with_defaults(value):
    raw = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0].boundary.model_dump(mode="json")
    raw["risk_flags"] = value
    raw["risk_treatments"][0]["treatment"] = "uncertain"
    before = copy.deepcopy(raw)
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw))
    assert any(e.location == ("risk_flags",) and e.code == "schema" for e in errors)
    assert not any(e.code == "missing_sensitivity_review" for e in errors)
    assert raw == before


def test_required_semantic_fields_remain_unknown_while_optional_defaults_apply():
    raw = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0].boundary.model_dump(mode="json")
    for field in ("content_decision", "proposed_start_cue_id", "proposed_end_cue_id"):
        del raw[field]
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw))
    assert any(e.location == ("content_decision",) and e.code == "schema" for e in errors)
    assert not any("requires one concrete interval" in e.message for e in errors)


def test_valid_drop_with_omitted_optional_endpoints_needs_no_invented_span():
    ledger = build_lineage_ledger_v5(**ledger_inputs())
    outcome = ledger.outcomes[-1]
    raw = outcome.boundary.model_dump(mode="json")
    assert raw["content_decision"] == "drop"
    del raw["proposed_start_cue_id"], raw["proposed_end_cue_id"]
    assert not collect_response_errors_v5(
        BoundaryReviewV5,
        json.dumps(raw),
        authority=outcome.authority,
        unit=outcome.unit,
        transcript=transcript(),
    )


def test_defaulted_flags_preserve_more_than_two_hundred_original_treatment_indices():
    raw = build_lineage_ledger_v5(**ledger_inputs()).outcomes[0].boundary.model_dump(mode="json")
    treatment = dict(raw["risk_treatments"][0], treatment="uncertain")
    raw["risk_treatments"] = [None, *[dict(treatment) for _ in range(251)]]
    del raw["risk_flags"], raw["review_reason"]
    errors = collect_response_errors_v5(BoundaryReviewV5, json.dumps(raw))
    assert {e.location for e in errors if e.code == "missing_sensitivity_review"} == {
        ("risk_treatments", i, "treatment") for i in range(1, 252)
    }
