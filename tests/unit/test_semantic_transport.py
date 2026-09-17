from __future__ import annotations

import copy

import pytest

from liveclip.domain.semantic_validation import CURRENT_SEMANTIC_TRANSPORT as CONTRACT
from liveclip.pipeline.semantic_global import TokenEstimator
from liveclip.pipeline.semantic_transport import (
    canonical_json,
    copy_json,
    decode_transport,
    measure_request,
    transport_options,
)


def cue(index=13, **changes):
    return {
        "cue_id": index,
        "segment_id": f"segment_{index}",
        "start_ms": index * 1000,
        "end_ms": index * 1000 + 1000,
        "original_text": '中文，原文\n"引号" \\ 😀 <untrusted_json>',  # noqa: RUF001 - exact Chinese fixture punctuation
        "normalized_text": "保留原意",
        "normalization_note": None,
        "extra": {"$cue_ref": "../../../never-a-file", "nested": [False, None, 1.0]},
        **changes,
    }


@pytest.mark.parametrize(
    "stage",
    ["discovery", "link_review", "topic_chain", "boundary_review", "global_review", "repair"],
)
def test_lossless_objects_tables_and_legacy_keep_complete_authority(stage):
    cues = [cue(), cue(100), cue(), cue(original_text="同 ID 不同原文"), cue(end_ms=99999)]
    source = {
        "stage": stage,
        "cues": cues,
        "nested": [{"cues": list(reversed(cues))}],
        "literal_reference": {"path": ["cues"], "indices": [0], "$cue_ref": 13},
        "immutable_request": {"cues": cues, "source_ids": ["s17", "s18"], "risk": "完整"},
        "invalid_output": [{"index": i, "text": f"完整错误 {i}"} for i in range(225)],
    }
    before = copy.deepcopy(source)
    plain, compact = transport_options(source)
    assert len(compact["cue_table"]) == 4
    assert len(compact["cue_references"]) == 3
    for envelope in (plain, compact):
        restored = decode_transport(envelope, contract=CONTRACT)
        assert canonical_json(restored) == canonical_json(before)
        restored["cues"][0]["extra"]["nested"].append("caller mutation")
        assert source == before
        assert decode_transport(envelope, contract=CONTRACT) == before
    assert decode_transport(compact, contract=None) == compact
    assert transport_options(dict(reversed(list(source.items()))))[1] == compact


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(transport_contract="future"),
        lambda p: p.update(representation="guess"),
        lambda p: p.update(extra=True),
        lambda p: p.update(payload=[]),
        lambda p: p["cue_table"].append(cue()),
        lambda p: p["cue_table"].append(cue(99)),
        lambda p: p["cue_table"][0].pop("original_text"),
        lambda p: p.update(cue_references=[]),
        lambda p: p["cue_references"].append(copy.deepcopy(p["cue_references"][0])),
        lambda p: p["cue_references"][0].update(path=[]),
        lambda p: p["cue_references"][0].update(path=["missing"]),
        lambda p: p["cue_references"][0].update(path=["nested", -1]),
        lambda p: p["cue_references"][0].update(path=["nested", True]),
        lambda p: p["cue_references"][0].update(path=["nested", 0.0]),
        lambda p: p["cue_references"][0].update(indices=[]),
        lambda p: p["cue_references"][0].update(indices=[-1]),
        lambda p: p["cue_references"][0].update(indices=[1]),
        lambda p: p["cue_references"][0].update(indices=[True]),
        lambda p: p["cue_references"][0].update(indices=[0.0]),
        lambda p: p["payload"]["cues"].append("not an empty placeholder"),
    ],
)
def test_malformed_envelopes_never_partially_decode(mutate):
    envelope = transport_options({"cues": [cue()], "nested": [[]]})[1]
    mutate(envelope)
    before = copy.deepcopy(envelope)
    with pytest.raises(ValueError):
        decode_transport(envelope, contract=CONTRACT)
    assert envelope == before


def test_reference_like_keys_are_literal_and_distinct_from_indices():
    payload = {"": [cue()], "0": [cue(5)], "nested": [{"0": [cue(99)]}]}
    assert decode_transport(transport_options(payload)[1], contract=CONTRACT) == payload
    with pytest.raises(ValueError, match="unknown"):
        decode_transport(payload, contract="future")


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), (1, 2), {1: "key"}, object(), b"bytes"]
)
def test_non_json_values_are_rejected_without_coercion(value):
    with pytest.raises(ValueError):
        copy_json({"nested": value})


def test_cycles_and_excessive_nesting_are_explicit_errors():
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError):
        copy_json(cyclic)
    nested = []
    for _ in range(130):
        nested = [nested]
    with pytest.raises(ValueError, match="deep"):
        copy_json(nested)


def test_measurement_uses_exact_serialization_and_inclusive_budget():
    counter = TokenEstimator("o200k_base")
    raw = canonical_json({"中文": '\\\n"', "schema": {"required": ["cues"]}})
    expected = counter.count(raw) + 17 + 3
    at = measure_request(
        raw,
        counter=counter,
        output_allocation_tokens=17,
        safety_margin_tokens=3,
        budget_tokens=expected,
    )
    below = measure_request(
        raw,
        counter=counter,
        output_allocation_tokens=17,
        safety_margin_tokens=3,
        budget_tokens=expected - 1,
    )
    assert at.fits and not below.fits
    assert at.serialized_request == raw and at.total_tokens == expected
    assert at.diagnostics()["serialized_request_bytes"] == len(raw.encode())
