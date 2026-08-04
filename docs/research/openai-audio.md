# OpenAI file transcription research

Verified: 2026-08-03
Scope: official OpenAI documentation and the locked official Python SDK; no paid API call was made.

## Findings

The current File transcription guide recommends `gpt-transcribe` for ordinary recorded-speech transcription. The locked official Python SDK is `openai==2.52.0`; its method contract was inspected locally without making a request. The documented Python call remains:

```python
from openai import OpenAI

client = OpenAI()
with open("audio.m4a", "rb") as audio_file:
    result = client.audio.transcriptions.create(
        model="gpt-transcribe",
        file=audio_file,
    )
```

Files are limited to 25 MB. The guide's supported list is `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, and `webm`; the API reference also lists `flac` and `ogg`. LiveClip will emit the common documented `m4a`/AAC format and keep a safety margin below 25 MB rather than depend on the inconsistent additions.

`gpt-transcribe` accepts `prompt`, keyword hints and plural language hints. Chinese codes documented by the guide include `cmn` and regional `zh-cn`, `zh-tw`, and `zh-hk`. The locked SDK exposes `keywords` and `languages` directly. Request construction is model-specific: `gpt-transcribe` uses those newer fields, while `whisper-1` uses `language`, `prompt`, `verbose_json`, and timestamp granularities.

## Timestamp decision

The same current guide says `timestamp_granularities[]` is only supported for `whisper-1`. With `response_format="verbose_json"`, it can return transcript text, duration, segment start/end, and optional word start/end. That capability is required for source-aligned candidate generation and accurate edit boundaries.

LiveClip therefore records two separate facts:

- OpenAI's general recorded-speech recommendation: `gpt-transcribe`.
- LiveClip v1's capability-driven default: `whisper-1`, until a recommended model exposes real segment timestamps or an evidence-backed alignment step is added. A configured model without segment timestamps is rejected for the full editing pipeline instead of assigning invented boundaries.

The v1 request shape is:

```python
result = client.audio.transcriptions.create(
    model="whisper-1",
    file=audio_file,
    language="zh",
    prompt=domain_vocabulary,
    response_format="verbose_json",
    timestamp_granularities=["segment", "word"],
)
```

If a response omits word timestamps, `word_timing_status` is `unavailable`; values are never synthesized. A text-only response without reliable segment alignment is not sufficient for the full editing pipeline.

Current model capability matrix:

| Model | Relevant output | LiveClip v1 use |
| --- | --- | --- |
| `gpt-transcribe` | Current general recommendation; text/JSON and context hints | Not the full-pipeline default because it lacks required segment timestamps |
| `gpt-4o-transcribe` / mini | JSON only; improved general recognition claims | Not sufficient for source-aligned editing |
| `whisper-1` | `verbose_json` segment and word timestamps | Capability-driven v1 default |
| `gpt-4o-transcribe-diarize` | Speaker-labelled diarized segments | Optional future speaker workflow, not the v1 default |

For `gpt-transcribe`, `languages` is plural and must not be sent together with the older singular `language`. For `whisper-1`, LiveClip sends only singular `language="zh"`.

## Responses and usage

The API reference describes several response variants. Verbose transcription includes text/language/duration and optional segments/words. Usage may be a token-based object or a duration object containing audio seconds. The locked SDK exposes object-response request IDs through public `_request_id`, and failed status request IDs through `APIStatusError.request_id`. The adapter normalizes both usage shapes and persists the raw non-secret shape, request ID, configured/returned model when available, latency, audio seconds, attempt and retry counts.

The adapter must not infer success merely from a text property when required segment timestamps are absent. SDK request shape, response parsing and request-ID extraction are covered by local contract tests against the locked version.

## Retry policy

Retry with bounded exponential backoff and jitter for connection/timeouts, actual rate limiting and retryable 5xx. Honor `Retry-After` within a configured cap. The official SDK retries eligible failures twice by default; LiveClip disables that internal retry and owns the bounded loop so request/retry metrics remain exact. Authentication, invalid parameters, invalid/unauthorized models, content errors and quota/spend-limit responses are deterministic until configuration/account state changes and are not blindly retried. Standard tests simulate errors and never call the service.

## Long media implications

Two-to-four-hour video is converted to streaming mono compressed audio and divided into size- and duration-bounded chunks with overlap. Each chunk stores source-time bounds, bytes, hash and cache key. Sentences should not be cut when a nearby pause is available. Successful chunk responses are immutable cache entries. Local chunk times are converted to integer source milliseconds, and overlap duplicates are removed using both time ownership and normalized text similarity.

## Sources

- [File transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text)
- [Create transcription API reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)
- [Whisper model](https://developers.openai.com/api/docs/models/whisper-1)
- [GPT-4o Transcribe model](https://developers.openai.com/api/docs/models/gpt-4o-transcribe)
- [Pinned OpenAI Python 2.52 transcription source](https://github.com/openai/openai-python/blob/v2.52.0/src/openai/resources/audio/transcriptions.py)
- [Official Python SDK: request IDs, errors and retries](https://github.com/openai/openai-python)
- [API error codes](https://developers.openai.com/api/docs/guides/error-codes)

## Still unverified

No credential is configured. Actual account model access, Chinese accuracy, returned usage variant, rate limits and cloud latency remain pending `make smoke-cloud`. A cloud failure must not fall back to Mock.
