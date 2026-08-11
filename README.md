# LiveClip

LiveClip is a local-first Chinese livestream highlight editor for Apple Silicon Macs. It turns a local 2–4 hour video into reviewable 9:16 clips, lets a user adjust and approve exact revisions, and creates immutable MP4/SRT/manifest/ZIP deliveries.

> Development status: the LiveClip v1 baseline is `delivered`. The selected real chain—OpenRouter `openai/whisper-large-v3` ASR followed by the local Codex CLI editor—has now processed the repository's read-only 46:20 input: 33/33 ASR chunks succeeded, Codex scored 39 candidates, and 15 non-degraded clean review clips were produced. The authoritative evidence and remaining limits are in [STATUS.md](STATUS.md).

## Architecture

Typer CLI, FastAPI and a single Worker call the same application services and pure domain rules. SQLite stores both domain state and a fenced durable task queue. FFmpeg performs deterministic local media work. In the default real mode, OpenRouter receives prepared audio chunks for Whisper transcription and the locally installed Codex CLI receives bounded transcript data for editorial scoring. The direct OpenAI ASR/Responses path remains available. Source video frames and all generated assets remain local. See [Solution](docs/SOLUTION.md) and [architecture diagrams](docs/architecture.md).

ASR (“automatic speech recognition”) is the stage that turns Chinese speech into timestamped text. Codex CLI is the editor after ASR: it reads that text, scores content, suggests safe boundaries and writes titles. Codex cannot directly listen to the video, so a Codex login does not replace `OPENROUTER_API_KEY` for real ASR.

## Development environment

Primary target: Apple Silicon M3, macOS, Python 3.12 (compatible with 3.11+), Node LTS, FFmpeg and ffprobe. Docker, an external database, an external queue and local model weights are not required.

On an Apple Silicon Mac with Homebrew, the reproducible baseline is:

```bash
brew install uv node@22 ffmpeg git
brew install --cask google-chrome  # required only by make test/e2e
uname -m                           # must print arm64
make setup NODE_LTS_BIN="$(brew --prefix node@22)/bin"
NODE_LTS_BIN="$(brew --prefix node@22)/bin" make doctor
```

`uv` installs the project-local native Python 3.12; `make setup` is repeatable and installs locked Python/Web dependencies. Chrome is required only for the checked browser test suite; ordinary CLI/API/Web use is not tied to it. `make test` and `make e2e` verify the standard macOS Chrome path before expensive work. For a nonstandard installation, set `LIVECLIP_CHROME_EXECUTABLE` to an executable absolute path. If Node LTS is already `/usr/local/bin/node`, the `NODE_LTS_BIN` override is unnecessary.

```bash
make setup
make doctor
make lint
make test
make e2e
make demo
```

`make setup` uses uv to provision a project-local native Python and installs frontend dependencies when the Web lockfile exists. For the normal Codex-backed real chain, authenticate Codex once, then configure ASR locally:

```bash
codex login
cp .env.example .env.local
chmod 600 .env.local
# Edit only the ignored local .env.local:
# LIVECLIP_AI_PROVIDER=openrouter-codex
# LIVECLIP_ALLOWED_MEDIA_ROOTS=/absolute/path/to/media
# OPENROUTER_API_KEY=<your newly regenerated local key>
make doctor
```

Never put a real key in `.env.example`, Git or a Codex conversation. Revoke the Key that was previously exposed before using LiveClip. `openrouter-codex` means OpenRouter Whisper Large V3 ASR plus the installed Codex CLI editor. The Codex process reuses saved ChatGPT authentication; inference is still cloud-based and no local model weights are installed. See [OpenRouter setup](docs/integrations/openrouter.md).

## CLI workflow

```bash
liveclip doctor
liveclip run --input /absolute/path/live.mp4 --top-n 15 --wait
liveclip status PROJECT_ID
liveclip clips PROJECT_ID
liveclip review CLIP_ID --approve
liveclip review CLIP_ID --start 125.5 --end 183.2 --title 修改后的标题 --approve
liveclip review CLIP_ID --subtitle-text "修订后的整段字幕" --approve
liveclip review CLIP_ID --reject --reason "内容不完整"
liveclip rerender CLIP_ID --wait
liveclip deliver PROJECT_ID --zip
```

All commands above are implemented. `review` creates an immutable human revision when title/boundary/subtitle fields change, `rerender` queues or foreground-executes the current revision, and `deliver` creates a new immutable delivery version. Foreground CLI processing uses the same SQLite lease/idempotency mechanism as Worker processing.

## Local Web workflow

```bash
make dev
```

This serializes any pending SQLite migration, starts FastAPI at `http://127.0.0.1:8765`, the durable Worker and Vite at `http://127.0.0.1:5173`, prints the addresses, and stops all child processes on Ctrl+C. The review console creates projects from allowed absolute paths, shows Pipeline progress/transcript/candidates, plays signed Range-enabled clean proxies, edits revisions/captions, approves or rejects, rerenders, and creates/downloads versioned deliveries. A proxy contains no LiveClip-generated title or captions; score, title, Hook, reason, risks and caption cues are displayed alongside it as editable metadata. Only the approved final render may burn text. The home page names the ASR and editorial providers separately, warns when either is Mock, and disables full processing when a required real provider is missing. A “preflight passed” label confirms local configuration/login only; it does not claim remote quota or model availability. An optional Bearer token is held only in page memory.

In the page: enter the optional local API token, enter an allowed absolute media path and clip settings, create and start the project, wait for all six stages, inspect transcript/candidates, open a candidate editor, change title/bounds/caption cues, approve or reject it, render the current final revision, then create and download a new Delivery ZIP. Error, cancelled and retryable states expose their retry action; a stale video is never presented as the current revision.

`make e2e` runs both the controlled-API UI test and an isolated real composition. The real test uses Mock AI but starts actual FastAPI, a SQLite-leased Worker, Vite and FFmpeg under a temporary data root. It verifies HTTP 202 polling, six stages, signed Range 206, revision invalidation, approval, final render, v001 ZIP download and computed `delivered` state. Default isolated ports are 18765/15174 and may be overridden with `LIVECLIP_E2E_API_PORT`/`LIVECLIP_E2E_WEB_PORT`; ignored screenshots/traces live under `apps/web/test-results`.

## REST API

The OpenAPI document is available at `http://127.0.0.1:8765/openapi.json`; health is `GET /api/v1/health`. Long operations return HTTP 202 with `Location`, `Retry-After`, a durable resource ID and polling URL. Creating endpoints support `Idempotency-Key`; generated media is addressed by asset ID and supports one HTTP byte range. See [API contract](docs/api.md).

## Demo and cloud smoke

`make demo` requires no API key and creates real copyright-free H.264/AAC media, three overlapped mono audio chunks, a Mock Chinese transcript, three candidates and validated clean proxies with separate editorial metadata. It approves one Demo clip, creates a human title revision that stales the old proxy, renders a text-bearing validated 1080×1920 final, then emits SRT, manifest and `delivery.zip`. It prints the project ID and every required absolute path; reruns create a new isolated Demo project.

```bash
make demo
make clean-demo  # removes only validated generated content below data/demo
```

The Codex-only smoke makes one real, tool-disabled structured editorial call through the saved CLI login. It proves the editor connection, not ASR or video-content understanding:

```bash
make smoke-codex
```

The default full real smoke proves OpenRouter Whisper ASR and Codex editing together. It requires a short Chinese video inside an allowed root and a newly regenerated local Key:

```bash
make smoke-openrouter INPUT=/absolute/path/to/media/short.mp4
```

Success requires OpenRouter generation IDs, Codex thread IDs and positive token usage, non-degraded selected EditPlans, and zero Mock evidence.
Configured ASR vocabulary is sent through OpenRouter's documented Groq provider option. It is best effort because another matched upstream does not receive the Groq-specific option; smoke success proves the real chain, not that a particular term was recognized.

The full cloud smoke runs real timestamp ASR and the pure Responses editorial path and fails if either provider is absent, a selected plan is degraded, or any Mock evidence appears:

```bash
LIVECLIP_AI_PROVIDER=openai \
LIVECLIP_ALLOWED_MEDIA_ROOTS=/absolute/path/to/media \
OPENAI_API_KEY=... \
make smoke-cloud INPUT=/absolute/path/to/media/short.mp4
```

Missing configuration exits with `not_run` before cloud work. Keys are read only from the local environment and are never printed.

For normal real video processing with the Codex editor, keep `LIVECLIP_AI_PROVIDER=openrouter-codex`, configure the OpenRouter ASR prerequisites locally, run `make doctor`, then use `liveclip run ... --wait` or the Web page. No path silently falls back to Mock. `openai-codex` remains an explicit alternative for an OpenAI Platform ASR key.

## Data and privacy

- Source video is a read-only path reference below `LIVECLIP_ALLOWED_MEDIA_ROOTS` and is not copied by default.
- Video frames, SQLite, transcripts, intermediate/generated videos and deliveries stay under the local data directory.
- Prepared audio chunks are uploaded to the configured ASR provider. In `openrouter-codex`, they pass through OpenRouter to its selected upstream Whisper host.
- Only bounded candidate transcript/context and metadata are sent to the LLM provider. Codex receives them through stdin, never argv, and runs with executable tools disabled.
- The API key is read from local environment only and is excluded from database, logs, UI, errors and Git.
- Saved Codex authentication stays in the Codex credential store and is not copied into LiveClip data.

Default project data will live under `data/projects`; Demo-owned data lives under `data/demo`. Both are ignored except placeholder directories.

## Recovery and troubleshooting

Use `liveclip status`, the API run retry endpoint, or the Web retry action for failed durable work. Expired leases are recovered by the same queue; stale revision renders cannot enter a Delivery. Consult structured local logs, then resume engineering work using [AGENTS.md](AGENTS.md), the [Living ExecPlan](docs/exec-plans/liveclip-v1.md), and [STATUS.md](STATUS.md).

- `SOURCE_NOT_ALLOWED` or import refusal: make the real source path a descendant of one `LIVECLIP_ALLOWED_MEDIA_ROOTS` entry; symlink escapes and `..` are intentionally rejected.
- Port already in use: set `LIVECLIP_API_PORT` and/or `LIVECLIP_WEB_PORT` before `make dev`; Vite receives the API target automatically. For a non-5173 Web port, also set `LIVECLIP_CORS_ORIGINS=http://127.0.0.1:PORT`. E2E ports have their own variables above.
- Browser test preflight fails: install Google Chrome in `/Applications` or set `LIVECLIP_CHROME_EXECUTABLE`; the test never attaches to an unrelated browser session.
- OpenRouter smoke says `not_run`: set `openrouter-codex`, an allowed root and a safe local Key in `.env.local`; it never substitutes Mock.
- Web shows `OPENROUTER_ASR_NOT_CONFIGURED`: configure a safe Key only in ignored `.env.local`; a successful `codex login` alone cannot transcribe audio.
- Web shows `OPENAI_ASR_NOT_CONFIGURED`: the explicit `openai-codex`/`openai` mode needs an OpenAI Platform key.
- Web shows `CODEX_CLI_NOT_READY`: run `codex login` and `liveclip doctor`. LiveClip never asks you to paste that credential into the page.
- Provider status did not change after editing `.env` or logging in: restart `make dev`; health intentionally uses one startup preflight rather than launching Codex on every unauthenticated poll.
- A transient timeout/429/5xx is eligible for bounded task/provider retry. Authentication, invalid media, unsafe paths, bad parameters and integrity failures are deterministic; correct the input/configuration, then explicitly retry or start a new run.
- VideoToolbox failure is nonblocking: Doctor records the real encode attempt and rendering automatically uses `libx264`.

Known development-host differences are tracked in Solution: current PATH Python and Node are unsuitable defaults, FFmpeg lacks subtitles/drawtext but supports the deterministic raster-overlay path, and VideoToolbox is unavailable inside the Codex sandbox while succeeding on the host. `libx264` is the automatic fallback.

## Current limitations

The Demo intentionally uses a 32-second source and explicit 8–12 second clip settings for fast repeatable local acceptance; product defaults remain 30–90 seconds. Generated-media, API, CLI, Web, lease/recovery, VFR/rotation, revision, render and Delivery paths are verified. A read-only 2.19 GB, 46:20 repository input completed the real `OpenRouter ASR → Codex` path on 2026-08-05: 33 ASR chunks produced 233 timestamped segments, 39 Codex calls succeeded, and 15 non-degraded 540×960 clean proxies passed full decode. Word-level timing was unavailable in the observed upstream response and was not fabricated. This sample is shorter than the typical 2–4 hour target; representative 2–4 hour peak memory/runtime/disk, Apple M3 throughput, broader codec/device diversity and the Linux `renameat2` branch remain unverified. The current development host is Apple M2. See STATUS for exact evidence.
