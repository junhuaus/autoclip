# LiveClip

LiveClip is a local-first Chinese livestream highlight editor for Apple Silicon Macs. It will turn a local 2–4 hour video into reviewable 9:16 clips, let a user adjust and approve exact revisions, and create immutable MP4/SRT/manifest/ZIP deliveries.

> Development status: M0–M3 are locally committed after independent review. REST/review/delivery services, complete CLI commands and the React review console pass local API, component and Chrome E2E acceptance. Real cloud providers are the active M4 work. The authoritative snapshot is [STATUS.md](STATUS.md).

## Architecture

Typer CLI, FastAPI and a single Worker call the same application services and pure domain rules. SQLite stores both domain state and a fenced durable task queue. FFmpeg performs deterministic local media work. OpenAI receives prepared audio chunks for transcription and bounded transcript data for editorial scoring; source video frames and all generated assets remain local. See [Solution](docs/SOLUTION.md) and [architecture diagrams](docs/architecture.md).

## Development environment

Primary target: Apple Silicon M3, macOS, Python 3.12 (compatible with 3.11+), Node LTS, FFmpeg and ffprobe. Docker, an external database, an external queue and local model weights are not required.

```bash
make setup
make doctor
make lint
make test
make demo
```

`make setup` uses uv to provision a project-local native Python and installs frontend dependencies when the Web lockfile exists. Copy `.env.example` to an ignored `.env` and set absolute allowed media roots before importing real files. Never place a real key in `.env.example` or commit `.env`.

## CLI workflow

```bash
liveclip doctor
liveclip run --input /absolute/path/live.mp4 --top-n 15 --wait
liveclip status PROJECT_ID
liveclip clips PROJECT_ID
liveclip review CLIP_ID --start 125.5 --end 183.2 --title 修改后的标题 --approve
liveclip rerender CLIP_ID --wait
liveclip deliver PROJECT_ID --zip
```

All commands above are implemented. `review` creates an immutable human revision when title/boundary/subtitle fields change, `rerender` queues or foreground-executes the current revision, and `deliver` creates a new immutable delivery version. Foreground CLI processing uses the same SQLite lease/idempotency mechanism as Worker processing.

## Local Web workflow

```bash
make dev
```

This serializes any pending SQLite migration, starts FastAPI at `http://127.0.0.1:8765`, the durable Worker and Vite at `http://127.0.0.1:5173`, prints the addresses, and stops all child processes on Ctrl+C. The review console creates projects from allowed absolute paths, shows Pipeline progress/transcript/candidates, plays signed Range-enabled proxies, edits revisions/captions, approves or rejects, rerenders, and creates/downloads versioned deliveries. An optional Bearer token is held only in page memory.

## REST API

The OpenAPI document is available at `http://127.0.0.1:8765/openapi.json`; health is `GET /api/v1/health`. Long operations return HTTP 202 with `Location`, `Retry-After`, a durable resource ID and polling URL. Creating endpoints support `Idempotency-Key`; generated media is addressed by asset ID and supports one HTTP byte range. See [API contract](docs/api.md).

## Demo and cloud smoke

`make demo` now requires no API key and creates real copyright-free H.264/AAC media, three overlapped mono audio chunks, a Mock Chinese transcript, three candidates and validated proxies. It approves one Demo clip, creates a human title revision that stales the old proxy, renders a validated 1080×1920 final, then emits SRT, manifest and `delivery.zip`. It prints the project ID and every required absolute path; reruns create a new isolated Demo project.

```bash
make demo
make clean-demo  # removes only validated generated content below data/demo
```

`make smoke-cloud INPUT=/absolute/path/short.mp4` remains planned for M4. It will be opt-in, require real OpenAI configuration and never fall back to Mock; it is not yet an implemented cloud-success path.

## Data and privacy

- Source video is a read-only path reference below `LIVECLIP_ALLOWED_MEDIA_ROOTS` and is not copied by default.
- Video frames, SQLite, transcripts, intermediate/generated videos and deliveries stay under the local data directory.
- Prepared audio chunks are uploaded to the configured ASR provider.
- Only bounded candidate transcript/context and metadata are sent to the LLM provider.
- The API key is read from local environment only and is excluded from database, logs, UI, errors and Git.

Default project data will live under `data/projects`; Demo-owned data lives under `data/demo`. Both are ignored except placeholder directories.

## Recovery and troubleshooting

Use `liveclip status`, the API run retry endpoint, or the Web retry action for failed durable work. Expired leases are recovered by the same queue; stale revision renders cannot enter a Delivery. Consult structured local logs, then resume engineering work using [AGENTS.md](AGENTS.md), the [Living ExecPlan](docs/exec-plans/liveclip-v1.md), and [STATUS.md](STATUS.md).

Known development-host differences are tracked in Solution: current PATH Python and Node are unsuitable defaults, FFmpeg lacks subtitles/drawtext but supports the deterministic raster-overlay path, and VideoToolbox is unavailable inside the Codex sandbox while succeeding on the host. `libx264` is the automatic fallback.

## Current limitations

The M1 Demo intentionally uses a 32-second source and explicit 8–12 second clip settings for fast repeatable local acceptance; product defaults remain 30–90 seconds. Persistent Mock processing, API/Web review, revision/rerender/delivery CLI and foreground/Worker lease competition are verified on generated local media. Real OpenAI calls, full 30–90 second raster performance, Apple M3 performance and representative 2–4 hour processing remain M4/M5 work. The repository `input/` long videos are reserved for read-only M5 and final acceptance runs. See STATUS for exact evidence.
