# EditPlan v1

The canonical timebase is integer milliseconds from source start. EditPlan revisions are immutable; any title, time, layout, caption, effect, or caption-cue change creates a new revision and invalidates older renders.

Minimum content:

```json
{
  "schema_version": "1",
  "candidate_id": "uuid",
  "source_start_ms": 125500,
  "source_end_ms": 183200,
  "score": 88.0,
  "title": "简洁中文标题",
  "hook": "开场钩子说明",
  "reason": "推荐理由",
  "layout": "center_crop",
  "caption_template": "clean_zh_v1",
  "effect": "none",
  "risk_flags": [],
  "prompt_version": "editing_v2",
  "model": "configured-model",
  "degraded": false
}
```

Allowed v1 values:

- active layout: `center_crop` only
- caption template: `clean_zh_v1`
- effect: `none`, `fade_in_out`

Pydantic uses strict types and `extra='forbid'`. Start is nonnegative; end is greater than start and within source duration; duration is within configured limits; an AI adjustment stays inside the candidate context window. Score is 0–100. Title, Hook and reason are limited to 40, 80 and 240 characters. In the Chinese review UI the Hook is presented as “高光语句”: bounded candidate-grounded editorial copy suitable for consideration as on-screen text, distinct from timed editor keywords. Candidate and Prompt identifiers are at most 64 characters, model is at most 100, and there are at most 8 risk flags of 32 characters each. No generic extension map exists. Unknown fields and any path, command, code, script, SQL, URL intended for execution, or filter string are rejected. The Provider wire schema has no layout field; the system supplies `center_crop`. `vertical_blur_background` remains in the legacy persisted enum solely to read old audit rows, but active bounds validation and the renderer reject it.

Captions are structured relative cues attached to the same revision:

```json
{"start_ms": 0, "end_ms": 2400, "text": "字幕文本"}
```

Cue bounds are ordered, nonnegative, non-overlapping and no later than the clip duration. A cue is at least 250 ms and contains at most 120 normalized characters. A revision has at most 32 cues and also obeys the duration-density budget of one cue per 1.5 seconds. Display text is split into at most 36-character parts only after validation; title plus caption parts may create at most 64 overlays in a final render. Review proxies use no text overlays and present the same title/cues as separate metadata. Final text is rasterized locally and never enters executable FFmpeg syntax.

When word timing is unavailable, a Provider-sized transcript sentence that only grazes a clip boundary is omitted from caption cues if its full text cannot be assigned safely to that small overlap. Complete in-clip segments remain subject to the strict density budget and fail rather than being truncated or assigned invented timing.

The exported JSON Schema is checked in at `docs/schemas/edit-plan-v1.schema.json`. Run `make schema` after an intentional domain change; `make lint` drift-checks the tracked bytes, and a unit test compares the parsed file with `EditPlan.model_json_schema()`. The provider's strict editorial wire model intentionally excludes system-owned EditPlan fields; provider parsing is followed by independent domain construction and validation. A repair call is allowed once for a normal invalid structure; then the system creates a deterministic plan with `degraded=true`.
