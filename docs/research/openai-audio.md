# OpenAI file transcription research

Verified: 2026-08-03
Scope: official OpenAI documentation only; no paid API call was made.

## Findings

The current File transcription guide recommends `gpt-transcribe` for ordinary recorded-speech transcription. The official Python SDK example uses:

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

`gpt-transcribe` accepts `prompt`, keyword hints and language hints. Chinese codes documented by the guide include `cmn` and regional `zh-cn`, `zh-tw`, and `zh-hk`. Request construction must be model-specific: `gpt-transcribe` uses plural language/context fields described in the guide, while existing models such as `whisper-1` use the older parameters.

## Timestamp decision

The same current guide says `timestamp_granularities[]` is only supported for `whisper-1`. With `response_format="verbose_json"`, it can return transcript text, duration, segment start/end, and optional word start/end. That capability is required for source-aligned candidate generation and accurate edit boundaries.

LiveClip therefore records two separate facts:

- OpenAI's general recorded-speech recommendation: `gpt-transcribe`.
- LiveClip v1's capability-driven default: `whisper-1`, until a recommended model exposes real segment timestamps or an evidence-backed alignment step is added.

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

If a configured model does not support word timestamps, `word_timing_status` is `unavailable`; values are never synthesized. A text-only response without reliable segment alignment is not sufficient for the full editing pipeline.

## Responses and usage

The API reference describes several response variants. Verbose transcription includes text/language/duration and optional segments/words. Usage may be a token-based object or a duration object containing audio seconds. The adapter must normalize both and preserve the raw non-secret shape for diagnostics. It also persists request ID, configured and returned model where available, latency, audio seconds, attempt and retry counts.

Request-ID access is SDK-version-sensitive and will receive a contract test after `uv.lock` pins the official SDK. The adapter must not infer success merely from a text property when requested timestamp fields are absent.

## Retry policy

Retry with bounded exponential backoff and jitter for connection/timeouts, actual rate limiting and retryable 5xx. Honor provider retry hints within a configured cap. Authentication, invalid parameters, invalid/unauthorized models, content errors and quota/spend-limit responses are deterministic until configuration/account state changes and are not blindly retried. Standard tests simulate errors and never call the service.

## Long media implications

Two-to-four-hour video is converted to streaming mono compressed audio and divided into size- and duration-bounded chunks with overlap. Each chunk stores source-time bounds, bytes, hash and cache key. Sentences should not be cut when a nearby pause is available. Successful chunk responses are immutable cache entries. Local chunk times are converted to integer source milliseconds, and overlap duplicates are removed using both time ownership and normalized text similarity.

## Sources

- [File transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text)
- [Create transcription API reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)
- [API overview and request IDs](https://developers.openai.com/api/reference/overview)
- [API error codes](https://developers.openai.com/api/docs/guides/error-codes)

## Still unverified

No credential is configured. Actual account model access, Chinese accuracy, current SDK request-ID attribute, returned usage variant, rate limits and cloud latency remain pending `make smoke-cloud`. A cloud failure must not fall back to Mock.
