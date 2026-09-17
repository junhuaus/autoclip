from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_semantic_lineage import fixture, ledger_inputs, transcript

from liveclip.clipping_skills.semantic_topic_chain_v2 import load_semantic_topic_chain_prompt
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.semantic_cache import (
    load_semantic_stage_cache,
    semantic_stage_cache_key,
    write_semantic_stage_cache,
)
from liveclip.pipeline.semantic_global import (
    CueRange,
    SemanticInputUnit,
    SemanticTimeRange,
    transcript_cues,
)
from liveclip.pipeline.semantic_lineage import (
    build_boundary_payload_v5,
    build_discovery_payload_v5,
    build_lineage_ledger_v5,
    build_topic_chain_payload_v5,
)
from liveclip.providers.llm.semantic_lineage import prepare_lineage_context
from liveclip.providers.llm.structured import (
    MockStructuredLLMProvider,
    OpenAIStructuredLLMProvider,
    StructuredProviderError,
)
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import ProviderConfigurationError


@pytest.mark.parametrize(
    "fault", ["risk_copy", "route_copy", "duplicate_cue", "prompt_hash", "profile"]
)
def test_mutated_immutable_authority_is_rejected_before_io(fault):
    stage = "topic_chain" if fault in {"risk_copy", "route_copy"} else "boundary_review"
    payload, output, prompts = case(stage)
    if fault == "risk_copy":
        payload["source_risks"][0]["flag"] = "medical_claim"
    elif fault == "route_copy":
        payload["expected_routes"] = []
    elif fault == "duplicate_cue":
        payload["cues"].append(copy.deepcopy(payload["cues"][0]))
    elif fault == "prompt_hash":
        payload["prompt_hash"] = "b" * 64
    else:
        payload["semantic_profile"] = "vocal_coach_live"
    responses = Responses([])
    with pytest.raises(ProviderConfigurationError):
        provider(prompts, responses).generate(
            subject_id="subject", payload=payload, response_model=type(output)
        )
    assert not responses.calls


def test_lineage_payload_cannot_silently_use_a_legacy_response_model():
    from liveclip.pipeline.semantic_profiles import BoundaryReviewV4

    payload, _output, prompts = case("boundary_review")
    responses = Responses([])
    with pytest.raises(ProviderConfigurationError):
        provider(prompts, responses).generate(
            subject_id="subject", payload=payload, response_model=BoundaryReviewV4
        )
    assert not responses.calls


@pytest.mark.parametrize("fault", ["missing", "empty", "invalid", "duplicate"])
def test_request_window_identity_is_checked_before_io(fault):
    payload, output, prompts = case("discovery")
    windows = payload["logical_windows"]
    if fault == "missing":
        windows[0].pop("logical_window_id")
    elif fault == "empty":
        windows[0]["logical_window_id"] = ""
    elif fault == "invalid":
        windows[0]["logical_window_id"] = "../arbitrary"
    else:
        windows.append(copy.deepcopy(windows[0]))
    responses = Responses([])
    with pytest.raises(ProviderConfigurationError):
        provider(prompts, responses).generate(
            subject_id="subject", payload=payload, response_model=type(output)
        )
    assert not responses.calls


def test_plausible_sdk_object_without_captured_business_text_is_not_success():
    payload, output, prompts = case("boundary_review")
    responses = Responses([output.model_dump_json()] * 2, parsed_override=output)
    original_parse = responses.parse

    def no_business_text(**kwargs):
        response = original_parse(**kwargs)
        response.text = json.dumps(dict(status="completed", output=[]))
        return response

    responses.parse = no_business_text
    with pytest.raises(StructuredProviderError) as caught:
        provider(prompts, responses).generate(
            subject_id="subject", payload=payload, response_model=type(output)
        )
    assert caught.value.code == "STRUCTURED_OUTPUT_MISSING" and len(responses.calls) == 2


def replace_fixture_ids(value, mapping):
    if isinstance(value, dict):
        return {key: replace_fixture_ids(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_fixture_ids(item, mapping) for item in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def case(stage):
    batch, chains, reviews = fixture()
    prompts = load_semantic_topic_chain_prompt(stage, "general", ClipProfile.MINI_LESSON)
    identity = dict(
        source_id="source_fixture",
        source_hash="a" * 64,
        prompt_hash=prompts.sha256,
        semantic_profile="general",
    )
    if stage == "discovery":
        unit = SemanticInputUnit(
            unit_id=batch.batch_id,
            source_range=CueRange(start_cue_id=1, end_cue_id=60),
            cues=transcript_cues(transcript()),
            estimated_tokens=1,
            context_range_ms=SemanticTimeRange(start_ms=0, end_ms=600_000),
            ownership_range_ms=SemanticTimeRange(start_ms=0, end_ms=600_000),
            logical_windows_ms=(SemanticTimeRange(start_ms=0, end_ms=600_000),),
        )
        payload = build_discovery_payload_v5(unit, **identity)
        names = {
            window.logical_window_id: requested["logical_window_id"]
            for window, requested in zip(
                batch.logical_windows, payload["logical_windows"], strict=True
            )
        }
        batch = type(batch).model_validate_json(
            json.dumps(replace_fixture_ids(batch.model_dump(mode="json"), names))
        )
        return payload, batch, prompts
    if stage == "topic_chain":
        payload = build_topic_chain_payload_v5(
            chains[0], batches=(batch,), chains=chains, transcript=transcript(), **identity
        )
        return payload, reviews[0], prompts
    outcome = build_lineage_ledger_v5(**ledger_inputs()).outcomes[1]
    payload = build_boundary_payload_v5(
        outcome.unit,
        chain=chains[0],
        originals=batch.candidates,
        transcript=transcript(),
        **identity,
    )
    return payload, outcome.boundary, prompts


class Responses:
    def __init__(self, texts, *, parsed_override=None, status="completed", extra_parts=()):
        self.texts = list(texts)
        self.calls = []
        self.parsed_override = parsed_override
        self.status = status
        self.extra_parts = extra_parts

    @property
    def with_raw_response(self):
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert self.texts, "unexpected additional provider request"
        text = self.texts.pop(0)
        parts = [{"type": "output_text", "text": text}, *self.extra_parts]

        def parse_body():
            parsed = self.parsed_override or kwargs["text_format"].model_validate_json(text)
            return SimpleNamespace(
                status=self.status,
                output_parsed=parsed,
                output=(
                    SimpleNamespace(
                        type="message", content=tuple(SimpleNamespace(**p) for p in parts)
                    ),
                ),
                usage=None,
                _request_id="synthetic-only",
                model="fixture",
            )

        return SimpleNamespace(
            text=json.dumps(
                {"status": self.status, "output": [{"type": "message", "content": parts}]}
            ),
            parse=parse_body,
        )


def provider(prompts, responses):
    return OpenAIStructuredLLMProvider(
        prompts=prompts,
        model_name="fixture",
        api_key=None,
        timeout_seconds=1,
        retry_policy=OpenAIRetryPolicy(max_retries=0),
        client=SimpleNamespace(responses=responses),
    )


@pytest.mark.parametrize("backend", ["openai", "codex"])
@pytest.mark.parametrize("repair_matches_original", [False, True])
def test_caller_mutation_during_io_cannot_replace_repair_authority(
    monkeypatch, backend, repair_matches_original
):
    """Synthetic transport evidence: a repair remains bound to the initial source."""
    from liveclip.providers.llm import codex as codex_module
    from liveclip.providers.llm import structured as structured_module

    payload, output, prompts = case("boundary_review")
    original = copy.deepcopy(payload)
    changed = output.model_dump(mode="json")
    changed["candidate_id"] = "changed_during_io"
    invalid = json.dumps(changed)
    texts = [invalid, output.model_dump_json() if repair_matches_original else invalid]
    sent = []

    def mutate_caller():
        payload["candidate"]["candidate_id"] = "changed_during_io"
        payload["authority"]["candidate_id"] = "changed_during_io"

    if backend == "openai":
        responses = Responses(texts, parsed_override=output)
        parse = responses.parse

        def fake_parse(**kwargs):
            sent.append(kwargs["input"][0]["content"][0]["text"])
            mutate_caller()
            return parse(**kwargs)

        responses.parse = fake_parse
        llm = provider(prompts, responses)
    else:
        contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
        monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
        monkeypatch.setattr(structured_module, "codex_cli_contract_version", lambda _: contract)

        def fake_run(argv, **kwargs):
            sent.append(kwargs["stdin_stream"].read().decode())
            mutate_caller()
            Path(argv[argv.index("--output-last-message") + 1]).write_text(texts.pop(0))
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(structured_module, "run_cancellable_process", fake_run)
        llm = structured_module.CodexStructuredLLMProvider(
            prompts=prompts,
            model_name="fixture",
            codex_executable="/usr/bin/true",
            timeout_seconds=30,
            contract_version=contract,
        )

    if repair_matches_original:
        result = llm.generate(subject_id="subject", payload=payload, response_model=type(output))
        assert result.output == output and result.repaired
        attempts = result.repair_attempts
    else:
        with pytest.raises(StructuredProviderError) as caught:
            llm.generate(subject_id="subject", payload=payload, response_model=type(output))
        assert caught.value.code == "STRUCTURED_OUTPUT_INVALID"
        attempts = caught.value.repair_attempts
        assert len(attempts) == 2
    assert len(sent) == 2 and "immutable_request" in sent[1]
    assert all(
        any("candidate_mismatch" in error for error in attempt["validation_errors"])
        for attempt in attempts
    )
    context = prepare_lineage_context(original, type(output), prompts=prompts)
    assert context is not None and context.errors(invalid)


@pytest.mark.parametrize("stage", ["discovery", "topic_chain", "boundary_review"])
def test_lineage_immutable_context_matches_real_builder(stage):
    payload, output, prompts = case(stage)
    context = prepare_lineage_context(payload, type(output), prompts=prompts)
    assert context is not None and not context.errors(output.model_dump_json())
    if stage == "boundary_review":
        assert context.cues[0].cue_id == 8 and context.cues[0].start_ms == 70_000


@pytest.mark.parametrize("stage", ["discovery", "topic_chain", "boundary_review"])
def test_openai_and_cache_preserve_all_typed_lineage_fields(stage, tmp_path):
    payload, output, prompts = case(stage)
    responses = Responses([output.model_dump_json()])
    llm = provider(prompts, responses)
    result = llm.generate(subject_id="subject", payload=payload, response_model=type(output))
    assert result.output == output and len(responses.calls) == 1 and not result.repaired
    settings = {"validation_contract": "quality-v2"}
    key = semantic_stage_cache_key(
        stage=stage,
        payload=payload,
        provider=llm,
        model_settings=settings,
        output_model=type(output),
    )
    write_semantic_stage_cache(
        cache_dir=tmp_path,
        cache_key=key,
        stage=stage,
        payload=payload,
        provider=llm,
        model_settings=settings,
        output=result.output,
    )
    loaded = load_semantic_stage_cache(
        cache_dirs=[tmp_path],
        cache_key=key,
        stage=stage,
        payload=payload,
        provider=llm,
        model_settings=settings,
        output_model=type(output),
    )
    assert loaded == output and loaded.model_dump(mode="json") == output.model_dump(mode="json")
    with pytest.raises(ValueError, match="identity"):
        load_semantic_stage_cache(
            cache_dirs=[tmp_path],
            cache_key=key,
            stage=stage,
            payload={**payload, "source_hash": "b" * 64},
            provider=llm,
            model_settings=settings,
            output_model=type(output),
        )


@pytest.mark.parametrize("stage", ["discovery", "topic_chain", "boundary_review"])
def test_mock_lineage_outputs_pass_shared_real_context(stage):
    payload, output, prompts = case(stage)
    llm = MockStructuredLLMProvider(prompts=prompts, model_name="fixture")
    result = llm.generate(subject_id="subject", payload=payload, response_model=type(output))
    context = prepare_lineage_context(payload, type(output), prompts=prompts)
    assert not context.errors(result.output.model_dump_json())
    if stage == "topic_chain":
        assert {d.original_candidate_id for d in result.output.source_dispositions} == {"A", "B"}
        assert all(set(u.original_candidate_ids) == {"A", "B"} for u in result.output.candidates)
    if stage == "boundary_review":
        assert {r.risk_id for r in result.output.risk_treatments} == {
            r.risk_id for r in context.authority.risks
        }
        assert "sensitivity_review" in result.output.risk_flags


@pytest.mark.parametrize(
    "fault", ["duplicate_json", "nonfinite", "missing_flag", "immutable_batch", "immutable_window"]
)
@pytest.mark.parametrize("repair_valid", [False, True])
@pytest.mark.parametrize("sdk_parses_actual", [False, True])
def test_openai_validates_original_business_json_and_repairs_once(
    fault, repair_valid, sdk_parses_actual
):
    stage = "discovery" if fault in {"immutable_batch", "immutable_window"} else "boundary_review"
    payload, output, prompts = case(stage)
    valid = output.model_dump_json()
    raw = output.model_dump(mode="json")
    if fault == "duplicate_json":
        invalid = '{"candidate_id":"wrong",' + valid[1:]
    elif fault == "nonfinite":
        invalid = valid[:-1] + ',"unexpected":NaN}'
    elif fault == "missing_flag":
        raw.pop("risk_flags", None)
        raw.pop("review_reason")
        raw["risk_treatments"][0]["treatment"] = "uncertain"
        invalid = json.dumps(raw)
    elif fault == "immutable_window":
        raw = replace_fixture_ids(raw, {raw["logical_windows"][0]["logical_window_id"]: "renamed"})
        invalid = json.dumps(raw)
    else:
        raw["batch_id"] = "model_changed_batch"
        invalid = json.dumps(raw)
    responses = Responses(
        [invalid, valid if repair_valid else invalid],
        parsed_override=None if sdk_parses_actual else output,
    )
    llm = provider(prompts, responses)
    if repair_valid:
        result = llm.generate(subject_id="subject", payload=payload, response_model=type(output))
        assert result.output == output and result.repaired
        attempts = result.repair_attempts
    else:
        with pytest.raises(StructuredProviderError) as caught:
            llm.generate(subject_id="subject", payload=payload, response_model=type(output))
        attempts = caught.value.repair_attempts
        assert len(attempts) == 2
    assert len(responses.calls) == 2 and attempts[0]["validation_errors"]
    if fault in {"duplicate_json", "nonfinite"}:
        assert isinstance(attempts[0]["invalid_output"], str)
    if fault == "missing_flag":
        assert any("missing_sensitivity_review" in e for e in attempts[0]["validation_errors"])
        assert any("review_reason" in e for e in attempts[0]["validation_errors"])


@pytest.mark.parametrize(
    "stage,field",
    [
        ("discovery", "ownership_interval"),
        ("topic_chain", "expected_routes"),
        ("boundary_review", "authority"),
        ("boundary_review", "cues"),
    ],
)
def test_malformed_required_context_rejects_before_provider_io(stage, field):
    payload, output, prompts = case(stage)
    payload = copy.deepcopy(payload)
    payload.pop(field)
    responses = Responses([])
    with pytest.raises(ProviderConfigurationError, match="immutable lineage request context"):
        provider(prompts, responses).generate(
            subject_id="subject", payload=payload, response_model=type(output)
        )
    assert not responses.calls


@pytest.mark.parametrize(
    "stage,fault",
    [
        (stage, fault)
        for stage in ("discovery", "topic_chain", "boundary_review")
        for fault in ("schema_and_context", "duplicate_json")
    ]
    + [("discovery", "immutable_window")],
)
@pytest.mark.parametrize("repair_valid", [False, True])
def test_codex_uses_raw_lineage_context_for_initial_and_sole_repair(
    monkeypatch, stage, repair_valid, fault
):
    from liveclip.providers.llm import codex as codex_module
    from liveclip.providers.llm import structured as structured_module

    payload, output, prompts = case(stage)
    before = json.dumps(payload, sort_keys=True)
    valid = output.model_dump_json()
    raw = output.model_dump(mode="json")
    if fault == "duplicate_json":
        invalid = '{"schema_version":"5",' + valid[1:]
        marker = "duplicate JSON object member"
    elif fault == "immutable_window":
        raw = replace_fixture_ids(raw, {raw["logical_windows"][0]["logical_window_id"]: "renamed"})
        raw["candidates"][0].pop("central_question")
        invalid, marker = json.dumps(raw), "immutable_request_mismatch"
    elif stage == "discovery":
        raw["batch_id"] = "wrong"
        raw["candidates"][0].pop("central_question")
        invalid, marker = json.dumps(raw), "immutable_request_mismatch"
    elif stage == "topic_chain":
        raw.pop("central_question")
        raw["source_dispositions"] = []
        invalid, marker = json.dumps(raw), "missing_source_disposition"
    else:
        raw.pop("review_reason")
        raw["risk_treatments"] = []
        invalid, marker = json.dumps(raw), "missing_risk_treatment"
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(structured_module, "codex_cli_contract_version", lambda _: contract)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(kwargs["stdin_stream"].read().decode())
        assert len(calls) <= 2
        assert "read-only" in argv
        schema = json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text())
        assert schema == structured_module._strict_codex_schema(
            type(output).model_json_schema(mode="validation")
        )
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            valid if len(calls) == 2 and repair_valid else invalid
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(structured_module, "run_cancellable_process", fake_run)
    llm = structured_module.CodexStructuredLLMProvider(
        prompts=prompts,
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
    )
    if repair_valid:
        result = llm.generate(subject_id="subject", payload=payload, response_model=type(output))
        assert result.output == output and result.repaired
        attempts = result.repair_attempts
    else:
        with pytest.raises(StructuredProviderError) as caught:
            llm.generate(subject_id="subject", payload=payload, response_model=type(output))
        attempts = caught.value.repair_attempts
        assert len(attempts) == 2
    assert len(calls) == 2 and marker in calls[1] and "immutable_request" in calls[1]
    assert any(marker in error for error in attempts[0]["validation_errors"])
    assert json.dumps(payload, sort_keys=True) == before


@pytest.mark.parametrize("failure", ["incomplete", "refusal", "multipart"])
def test_openai_failure_precedence_retains_complete_indexed_lineage_errors(failure):
    payload, output, prompts = case("boundary_review")
    raw = output.model_dump(mode="json")
    raw.pop("review_reason")
    raw["risk_treatments"].extend(
        dict(
            risk_id=f"unknown_{index}",
            treatment="uncertain",
            reason="fixture",
            evidence_cue_ids=[11],
        )
        for index in range(205)
    )
    invalid = json.dumps(raw)
    responses = Responses(
        [invalid],
        status="incomplete" if failure == "incomplete" else "completed",
        extra_parts=({"type": "output_text", "text": invalid},)
        if failure == "multipart"
        else ({"type": "refusal", "refusal": "synthetic refusal"},)
        if failure == "refusal"
        else (),
    )
    with pytest.raises(StructuredProviderError) as caught:
        provider(prompts, responses).generate(
            subject_id="subject", payload=payload, response_model=type(output)
        )
    expected = {
        "incomplete": "STRUCTURED_RESPONSE_INCOMPLETE",
        "refusal": "STRUCTURED_RESPONSE_REFUSED",
        "multipart": "STRUCTURED_UNEXPECTED_OUTPUT",
    }[failure]
    assert caught.value.code == expected and len(responses.calls) == 1
    errors = caught.value.repair_attempts[0]["validation_errors"]
    assert sum("unknown_risk" in error for error in errors) >= 205
    if failure == "multipart":
        parts = caught.value.repair_attempts[0]["business_output_parts"]
        assert [(p["output_index"], p["content_index"]) for p in parts] == [(0, 0), (0, 1)]
        for index in range(2):
            assert (
                sum(
                    error.startswith(f"output[0].content[{index}]: ") and "unknown_risk" in error
                    for error in errors
                )
                == 205
            )
