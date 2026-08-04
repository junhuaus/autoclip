# OpenAI Responses and Structured Outputs research

Verified: 2026-08-03
Scope: official OpenAI documentation and the locked official Python SDK; no paid API call was made.

## Findings

The locked official Python SDK is `openai==2.52.0`. It supports strict structured parsing directly into Pydantic:

```python
response = client.responses.parse(
    model=configured_model,
    input=messages,
    text_format=EditPlanWire,
    store=False,
)
parsed = response.output_parsed
```

For a raw `responses.create` call, JSON Schema is passed under `text.format`, not Chat Completions' `response_format`:

```python
text={
    "format": {
        "type": "json_schema",
        "name": "edit_plan",
        "strict": True,
        "schema": schema,
    }
}
```

Strict Structured Outputs is preferred to JSON mode because it enforces the supported schema subset. Root and nested objects require `additionalProperties: false`; fields are required, with nullable types used for optional semantics. Schema property counts, nesting and supported keywords are bounded. The wire model will be deliberately small and contract-tested against the pinned SDK.

The current documented limits are 5,000 object properties, 10 nesting levels, 120,000 total characters across schema names/descriptions/enums, and 1,000 aggregate enum values. LiveClip's wire schema remains far below these limits and excludes system-owned fields such as candidate ID, prompt version, model and degraded state.

## Non-success output

`ParsedResponse.output_parsed` returns the first parsed `output_text` item and otherwise returns `None`; structured output therefore does not mean every provider response is a parsed EditPlan. The adapter separately detects:

- `response.status == "incomplete"` and its reason;
- every other non-`completed` status, including a provider-reported failed response;
- a safety refusal content item;
- provider/network/auth/quota errors, with request IDs preserved when available;
- missing parsed output;
- parsed wire data that fails local domain invariants.

Refusal and incomplete are not passed through a generic “fix the JSON” request. For a normal but locally invalid plan, at most one repair request receives validation issues and the same bounded candidate data. A second failure produces a local deterministic EditPlan marked `degraded=true`.

The locked status union is `completed | failed | in_progress | cancelled | queued | incomplete`; current incomplete reasons are `max_output_tokens` and `content_filter`. The adapter scans content items for refusal before reading `output_parsed`, and treats unexpected tool-call output as invalid rather than executing it.

## Model and prompt decision

Current model guidance identifies the GPT-5.6 family: `gpt-5.6-sol` for flagship capability, `gpt-5.6-terra` for an intelligence/cost balance, and `gpt-5.6-luna` for high-volume efficiency. `gpt-5.6-terra` remains the configurable `.env.example` choice for short per-candidate editing; that is a LiveClip inference, not an official LiveClip-specific recommendation. The provider never embeds prices; optional cost is computed only from explicit local configuration.

The prompt is outcome-oriented and versioned. It provides one candidate, bounded pre/post context, deterministic score and necessary quality signals. The transcript is placed in an explicit untrusted-data section and the model is told not to execute or follow any instruction within it. No tools are supplied, so the model cannot invoke code or external actions. The output schema contains only whitelisted editorial data.

Independent candidate scoring needs no conversational state; `store=false` is the v1 request default. The request supplies an empty tool list, so untrusted transcript content has no execution channel. Each call records configured/returned model where exposed, prompt version and hash, time, response/request ID, status, latency and usage. Raw transcript prompts are not written to structured logs.

The SDK's own eligible-error retries are disabled with `max_retries=0`; the shared LiveClip retry policy owns bounded attempts, `Retry-After`, jitter and metrics. Responses token usage records input/output/total tokens plus cache and reasoning details when present.

## Sources

- [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses migration/API differences](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Models catalog](https://developers.openai.com/api/docs/models)
- [GPT-5.6 Terra model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [Current model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Official Python SDK: request IDs, errors and retries](https://github.com/openai/openai-python)
- [Pinned SDK Response type](https://github.com/openai/openai-python/blob/v2.52.0/src/openai/types/responses/response.py)
- [Pinned SDK Responses usage](https://github.com/openai/openai-python/blob/v2.52.0/src/openai/types/responses/response_usage.py)

## Still unverified

No credential is configured. Actual model entitlement, real refusal/incomplete payloads, Chinese editorial quality, usage and rate limits remain pending the explicit cloud smoke test. Local SDK contract tests cannot close those cloud-only gaps.
