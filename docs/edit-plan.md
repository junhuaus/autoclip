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
  "layout": "vertical_blur_background",
  "caption_template": "clean_zh_v1",
  "effect": "none",
  "risk_flags": [],
  "prompt_version": "editing_v1",
  "model": "configured-model",
  "degraded": false
}
```

Allowed v1 values:

- layout: `vertical_blur_background`, `center_crop`
- caption template: `clean_zh_v1`
- effect: `none`, `fade_in_out`

Pydantic uses strict types and `extra='forbid'`. Start is nonnegative; end is greater than start and within source duration; duration is within configured limits; an AI adjustment stays inside the candidate context window. Score is 0–100. Title, Hook and reason are limited to 40, 80 and 240 characters. Candidate and Prompt identifiers are at most 64 characters, model is at most 100, and there are at most 8 risk flags of 32 characters each. No generic extension map exists. Unknown fields and any path, command, code, script, SQL, URL intended for execution, or filter string are rejected.

Captions are structured relative cues attached to the same revision:

```json
{"start_ms": 0, "end_ms": 2400, "text": "字幕文本"}
```

Cue bounds are ordered, nonnegative, non-overlapping and no later than the clip duration. A cue is at least 250 ms and contains at most 120 normalized characters. A revision has at most 32 cues and also obeys the duration-density budget of one cue per 1.5 seconds. Display text is split into at most 36-character parts only after validation; title plus caption parts may create at most 64 overlays. Text is rasterized locally and never enters executable FFmpeg syntax.

The exported JSON Schema is checked in at `docs/schemas/edit-plan-v1.schema.json`. Run `make schema` after an intentional domain change; `make lint` drift-checks the tracked bytes, and a unit test compares the parsed file with `EditPlan.model_json_schema()`. The provider's strict editorial wire model intentionally excludes system-owned EditPlan fields; provider parsing is followed by independent domain construction and validation. A repair call is allowed once for a normal invalid structure; then the system creates a deterministic plan with `degraded=true`.
