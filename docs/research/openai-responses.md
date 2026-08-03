# OpenAI Responses and Structured Outputs research

Verified: 2026-08-03
Scope: official OpenAI documentation only; no paid API call was made.

## Findings

The current official Python SDK supports strict structured parsing directly into Pydantic:

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

## Non-success output

Structured output does not mean every provider response is a parsed EditPlan. The adapter separately detects:

- `response.status == "incomplete"` and its reason;
- a safety refusal content item;
- provider/network/auth/quota errors;
- missing parsed output;
- parsed wire data that fails local domain invariants.

Refusal and incomplete are not passed through a generic “fix the JSON” request. For a normal but locally invalid plan, at most one repair request receives validation issues and the same bounded candidate data. A second failure produces a local deterministic EditPlan marked `degraded=true`.

## Model and prompt decision

The current model resolver and catalog identify the GPT-5.6 family. `gpt-5.6-terra` is used in `.env.example` as a configurable engineering balance for short per-candidate editing; that is a LiveClip inference, not an official LiveClip-specific recommendation. We will evaluate it against representative Chinese candidates and may pin an available snapshot for a release. The provider never embeds prices; optional cost is computed only from explicit local configuration.

The prompt is outcome-oriented and versioned. It provides one candidate, bounded pre/post context, deterministic score and necessary quality signals. The transcript is placed in an explicit untrusted-data section and the model is told not to execute or follow any instruction within it. No tools are supplied, so the model cannot invoke code or external actions. The output schema contains only whitelisted editorial data.

Independent candidate scoring needs no conversational state; `store=false` is the v1 request default. Each call records configured/returned model where exposed, prompt version and hash, time, response/request ID, status, latency and usage. Raw transcript prompts are not written to structured logs.

## Sources

- [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses migration/API differences](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Models catalog](https://developers.openai.com/api/docs/models)
- [GPT-5.6 Terra model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.6 prompting guidance](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6)
- [GPT-5.6 upgrade guidance](https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p6-sol)

## Still unverified

No credential is configured. Actual model entitlement, request/response fields of the locked SDK, refusal/incomplete examples, Chinese editorial quality, usage and rate limits remain pending the explicit cloud smoke test. Mock tests cannot close those gaps.
