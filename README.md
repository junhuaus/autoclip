# LiveClip

LiveClip is a local-first Chinese livestream highlight editor for Apple Silicon Macs. It turns a local 2–4 hour video into reviewable 9:16 clips, lets a user adjust and approve exact revisions, and creates immutable MP4/SRT/manifest/ZIP deliveries.

> Development status: the LiveClip v1 baseline is `delivered`. The selected real chain—OpenRouter `openai/whisper-large-v3` ASR followed by the local Codex CLI editor—has processed the repository's read-only 46:20 input: 33/33 ASR chunks succeeded, Codex scored 41 candidates, and 15 non-degraded clean review clips were produced. The current “高光时刻” board uses one full-width horizontal row per clip, exposes the AI-authored high-impact sentence, keeps grounded keywords as editor-only navigation, and supports atomic multi-candidate review without A/B variants or another ASR call. The authoritative evidence and remaining limits are in [STATUS.md](STATUS.md).

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
liveclip export-review PROJECT_ID --zip
liveclip db-backup
liveclip db-restore --backup /absolute/path/backup.sqlite3 --output /absolute/path/restored/liveclip.sqlite3
```

All commands above are implemented. `review` creates an immutable human revision when title/boundary/subtitle fields change, `rerender` queues or foreground-executes the current revision, and `deliver` creates a new immutable delivery version. Foreground CLI processing uses the same SQLite lease/idempotency mechanism as Worker processing.

For new semantic clipping work, choose `semantic_windowed` explicitly (the Web selects it by default;
the bare CLI/API default remains A for backward-compatible automation):

```bash
liveclip run \
  --input /absolute/path/live.ts \
  --algorithm semantic_windowed \
  --profile vocal_coach_live \
  --min-duration 45 --target-duration 60 --max-duration 90 \
  --score-threshold 75 --max-clips 15 \
  --prompt-debug --no-render --wait
```

`semantic_windowed` scans 120-second logical windows at a 60-second step. Four logical windows are
deduplicated into one 300-second Discovery batch with a half-open 240-second candidate-start ownership
interval; uncached batches run with bounded concurrency five. A structured open-topic report on either
side schedules one 180-second boundary union. Every Discovery batch may return any number of candidates
and does no final scoring. Global Review receives candidate source text, nearby context and boundary
results—not the whole livestream—and owns duplicate/merge/split decisions and all final scoring. Python maps
global cue IDs to source milliseconds, accepts only one continuous 45–90 second range, recomputes the
six score fields, requires a score strictly greater than 75, applies risk/manual-review gates and uses
Top-N only as a ceiling. `--no-render` persists the final plan without FFmpeg. `--prompt-debug` prints
only loaded Prompt files, version/hash, profile, token estimate and window mode; it never
prints the transcript.

Full-first `semantic_global` remains available as a comparison mode. It uses tokenizer budgeting to
choose a whole-transcript request or 10–20 minute fallback transport windows; it is no longer the Web
default because whole-live retries have higher latency and a larger failure blast radius.

Discovery builds a complete topic map before proposing clips. Every medium/high-value topic must
either reference a candidate or carry a structured no-candidate reason; risk is recorded but never
used to suppress discovery. Before Global Review, Python adds exact candidate/topic milliseconds and
durations. Global Review must account for every medium/high topic through a structured coverage
decision and must provide cue boundaries for any duration rejection. Python is the sole duration
authority and sends a contradictory duration claim through the one bounded repair path.

Candidates and final clips also preserve the source opening quote, opening relevance, semantic-core
cue range, source closing quote, first complete payoff, boundary compactness, source fidelity,
irrelevant intro/outro cues and quality flags. Among legal 45–90 second ranges the Agent must choose
the shortest natural interval that contains the complete promise; 60 seconds is a soft target and
90 seconds is never a target to fill. An irrelevant opening/outro, unfinished ending, internal topic
switch, unsupported title reframing or padding with welcome/CTA/assistant chatter cannot be retained.
Editorial value (`keep`/`drop`) is separate from release status (`clear`/`manual`): high-risk medical diagnosis, absolute/commercial
claims and music-rights material can remain valuable review candidates without becoming automatic
selections. Ordinary low-severity vocal-health advice is distinct from medical diagnosis.

The Prompt bundle loads in stable order: `main.md`, `common_rules.md`, the selected stage, and the
selected profile. Add a profile under `src/liveclip/clipping_skills/semantic_global_v1/profiles/`,
declare it in `manifest.yaml`, extend the typed profile allowlist and add loader tests; a profile
cannot override continuity, duration, score or safety rules. Evaluation examples are not loaded into
production Prompts.

Run the checked-in 701-cue regression without ASR or rendering:

```bash
liveclip semantic-eval \
  --algorithm semantic_windowed \
  --transcript tests/fixtures/8-16-3-full-transcript.txt \
  --output data/evaluations/8-16-3-semantic-windowed-local \
  --provider mock --model-context-tokens 128000 \
  --baseline data/evaluations/previous-semantic-run
```

When only Global Review rules changed, reuse a compatible validated Discovery artifact instead of
paying for and waiting on the same full-transcript Discovery again. Window mode can also resume the
exact completed batches from a failed run and call only missing batches:

```bash
liveclip semantic-eval \
  --transcript tests/fixtures/8-16-3-full-transcript.txt \
  --output data/evaluations/8-16-3-global-review-iteration \
  --provider configured \
  --reuse-discovery-from data/evaluations/8-16-3-prior-run
```

Full-context reuse fails closed unless source hash, profile, model/provider, runtime limits, context
mode, reasoning effort and Discovery Prompt hash all match. Window-batch reuse recomputes the provider
operation key from the complete current payload and accepts a batch only on an exact match. The new
run manifest records the source run and actual missing-batch call count.

After semantic evaluation, apply an explicit review artifact and create real media plus a directly
browsable Delivery. The review is bound to the exact plan SHA-256, must classify every kept clip and
may revise boundaries only through existing transcript cue IDs; the command rechecks the configured
45–90 second range before FFmpeg runs:

```bash
liveclip semantic-deliver \
  --source /absolute/path/live.ts \
  --transcript tests/fixtures/8-16-3-full-transcript.txt \
  --plan data/evaluations/run/final-validated.json \
  --review data/evaluations/run/offline-review.json \
  --output data/exports/reviewed-run
```

The output contains immutable renders, `reviewed-render-manifest.json`, and
`deliveries/v001/index.html`, subtitles, checksums and `delivery.zip`. The manifest and offline index
carry the same grounded editorial metadata used by the Web review card: each clip shows its high-impact
`hook` plus transcript-backed `keywords` with clip-relative time, source time and honest word/segment
timing precision. Boundary decisions remain review data and never become source-specific rules in
Discovery or Global Review. A later review may
pass `--reuse-renders-from` with the prior `reviewed-render-manifest.json`; only exact
source-SHA/range/hash matches are reused, so a one-clip boundary change re-encodes only that clip.

Use `--provider configured` only when a real configured provider is intended. The output directory
contains `discovery-raw.json`, exact `global-review-agent-raw.json`, deterministically normalized
`global-review-raw.json`, `final-validated.json`, `run-manifest.json`, `prompt-debug.json` and
`before-after-report.md`; a repair also creates `repair-attempts.json`.
Rejected candidate groups, duplicate targets, coverage decisions and validator-added rejections are
retained in the final audit instead of being silently discarded. Directories are no-clobber. See
[ADR-024](docs/adr/024-full-first-semantic-global-clipping.md).

`export-review` is intentionally different from formal `deliver`: it snapshots every current
successful clean review proxy while clips may still be `pending_review`, leaves all review and
Project state unchanged, and creates a versioned self-contained offline package. The package
contains MP4s, SRTs, per-clip and combined Markdown descriptions, JSON metadata, SHA-256 checksums,
an offline `index.html`, and `offline-review.zip`. Open `index.html` after extraction to play and
inspect the clips without API, Worker, Web, ASR, or LLM services.

The offline-review manifest v2 records the exact Pipeline generation, Project revision epoch,
EditPlan revision, review state, clean-proxy RenderJob, producer Task and committed Asset lineage.
LiveClip rechecks that snapshot immediately before and after atomic publication and withdraws a
raced package. Interrupted private attempts are recovered safely on the next export. This remains
a review snapshot, not an approval or formal Delivery.

## Local Web workflow

```bash
make dev
```

This serializes any pending SQLite migration, starts FastAPI at `http://127.0.0.1:8765`, the durable Worker and Vite at `http://127.0.0.1:5173`, prints the addresses, and stops all child processes on Ctrl+C. The home page is a video-editor “我的项目” workspace with personal project/workload counts, search, lifecycle filters, owner/member/role context and a focused next action. New Projects are private: only the creator/owner sees one until members are explicitly added. An owner may instead make a Project workspace-visible, which gives other active accounts read-only viewer access. A creator can add editors/reviewers/viewers, remove non-assigned non-owners or explicitly transfer ownership from the Project page; the former owner becomes an editor. The Web hides or disables mutations using capabilities returned by the server.

The review console shows Pipeline progress and candidates, plays signed Range-enabled clean review/delivery masters, edits revisions/captions, approves or rejects one or several selected candidates atomically, rerenders changed revisions, and creates/downloads versioned deliveries. It intentionally omits a separate full-livestream transcript panel. “高光时刻” is a one-column list: every full-width row places the vertical video on the left and editorial content on the right, followed by the row's complete subtitle section at the bottom. The persisted EditPlan `hook` is presented as “高光语句”—AI-authored, candidate-grounded copy suitable for editorial consideration as on-screen text. Grounded terms are explicitly labelled “编辑关键词”; they are editor navigation metadata, not audience-facing copy. Clicking a keyword or subtitle seeks only that row's video. Segment-level keyword windows come from the existing ASR transcript and are labelled honestly when word timing is unavailable, without repeating ASR. The clean master is generated immediately after selection and contains no LiveClip-generated title or captions; score, title, high-impact sentence, reason, risks and caption cues remain separate metadata. Approval keeps that exact master, pending/rejected clips are omitted, and Delivery performs no second render. An optional approved burned derivative may write text into the picture. Each current clean master also offers individual MP4/SRT download. Owners and editors can separately tick “选择导出” on any number of current rows and create an immutable “剪辑交接包”: clean MP4, matching editable SRT, JSON/CSV descriptions, high-impact sentences, keyword times, thumbnails, checksums and a Chinese Jianying/CapCut import guide. It uses portable interchange files rather than claiming an undocumented Jianying private draft format. Provider diagnostics live under the top-right account/system menu, keeping the editor's dashboard task-focused. An optional Bearer token is held only in page memory.

The v0.2 development line adds local login and administrator “成员管理” and “项目治理” pages while package version `0.1.0` remains the stable baseline. To opt in without committing a credential, put a 12–128 character value in ignored `.env.local` as `LIVECLIP_BOOTSTRAP_ADMIN_PASSWORD`; it initializes only a missing password for `LIVECLIP_WORKSPACE_USERNAME`. Restart `make dev`, sign in, then create editors/reviewers as ordinary members and grant their Project roles inside each private Project. Clearing the environment variable does not erase a configured password. Administrator disable, password reset and system-role changes revoke existing browser sessions.

“项目治理” is an explicit system-administration context. It lists every Project, including a private Project whose recorded owner has been disabled, and shows recent sanitized security/governance audit events. It does not add the administrator as a Project member or grant clip/media/export access. An administrator may explicitly transfer ownership to any active account after entering the exact Project name; the new user becomes the unique owner, the former owner becomes an editor, the Project management version advances and one audit event records the before/after owner. Create a `liveclip db-backup` recovery point before an operational ownership transfer.

Administrators also have a “存储管理” page. It scans the local data tree without following symbolic links, separates database/backups, known Project files, stale/pending/orphan/untracked files, unknown Project directories and interrupted purge quarantine. “安全清理” removes only terminal task worktrees or an exact completed-purge quarantine recorded with its device/inode identity. Large scans/deletions run after a short atomic quarantine claim, without holding SQLite's writer lock and blocking Worker heartbeats. If the process exits after the quarantine rename, the next janitor/safe-cleanup pass recognizes only the same recorded inode at the deterministic hidden cleanup endpoint and resumes; competing endpoints fail closed. Ordinary archive is read-only retention and deletes nothing. Permanent Project purge is deliberately separate: the Project must be archived with no active work, the administrator must enter both the exact Project name and `PURGE PROJECT_ID`, LiveClip creates and validates a no-clobber SQLite recovery point first, then quarantines and deletes only the Project's generated local directory and database graph. The external SourceMedia file is never deleted; every new source must be outside `LIVECLIP_DATA_DIR`, and purge additionally checks all existing Project/SourceMedia references.

The V2-M2 Project page adds “任务与生命周期”: the owner assigns an active Project member, sets priority/deadline/visibility, advances or returns the editorial stage with a required reason, archives/restores, and reads recent activity. Business stages are 草稿、处理中、需要处理、编辑审核、待修改、终审、待发布、已发布、已归档. They are intentionally separate from technical processing/Delivery status; only an explicit human transition records “已发布”. Concurrent browser tabs use `management_version` and receive 409 instead of overwriting one another.

The V2-M4 “短视频发布运营” workspace can draft a platform task from any current high point that has not been rejected; content approval, trusted current media and the nine-item editorial/rights/privacy checklist remain hard preflight gates before it can become ready. An owner or editor creates one independent task per platform/account, edits title variants, description, hashtags, CTA, caption mode, cover time, assignee and planned time, and previews the exact clean proxy or burned final render with the task's immutable preset safe zone. Editors submit; owners or reviewers approve, return or revoke approval. Queue and calendar views track preparing, ready, externally scheduled, published, failed and withdrawn work. A ready item produces an immutable complete platform ZIP containing the pinned MP4, matching SRT when selected, extracted cover PNG, editable copy, checklist/preflight evidence, manifest and checksums. A non-blocking duplicate-content warning compares prior immutable package/delivery evidence so cross-platform reuse remains an explicit editorial choice. Recording publication requires choosing that exact current successful ZIP and entering the actual publication time plus an external URL or platform content ID; the published card retains the package/video/artifact hashes and operator notes. LiveClip never stores social credentials or claims to upload/schedule content itself. For Jianying/CapCut follow-up editing, choose “干净视频 + 独立 SRT”.

For local multi-user isolation, keep the main signing/admin token and map each additional username to a different long random token in ignored `.env.local`:

```text
LIVECLIP_WORKSPACE_USERNAME=local-admin
LIVECLIP_API_TOKEN=<local-admin-token>
LIVECLIP_WORKSPACE_TOKENS={"lin-editor":"<distinct-editor-token>","wang-review":"<distinct-reviewer-token>"}
```

Restart `make dev`, add those usernames to the relevant Project, then each member enters only their own token in the account menu. Tokens never enter SQLite or the browser bundle.

In the page: enter the optional local API token, enter an allowed absolute media path and clip settings, create and start the project, wait for all six stages, inspect each “高光时刻” row with its high-impact sentence, editor keywords and bottom subtitle block, download one MP4/SRT or select several rows for a Jianying-friendly editing ZIP, open the editor, change title/bounds/caption cues, approve or reject it, render the current final revision, then create and download a formal Delivery ZIP. Error, cancelled and retryable states expose their retry action; a stale video is never presented as the current revision.

`make e2e` runs both the controlled-API UI test and an isolated real composition. The real test uses Mock AI but starts actual FastAPI, a SQLite-leased Worker, Vite and FFmpeg under a temporary data root. It verifies HTTP 202 polling, six stages, signed Range 206, individual MP4/SRT links, a leased immutable EditPackage ZIP, revision invalidation, pre-approval clean-master rendering, approval, formal v001 Delivery reuse and computed `delivered` state. Default isolated ports are 18765/15174 and may be overridden with `LIVECLIP_E2E_API_PORT`/`LIVECLIP_E2E_WEB_PORT`; ignored screenshots/traces live under `apps/web/test-results`.

## REST API

The OpenAPI document is available at `http://127.0.0.1:8765/openapi.json`; health is `GET /api/v1/health`. Long operations return HTTP 202 with `Location`, `Retry-After`, a durable resource ID and polling URL. Creating endpoints support `Idempotency-Key`; generated media is addressed by asset ID and supports one HTTP byte range. See [API contract](docs/api.md).

## Demo and cloud smoke

`make demo` requires no API key and creates real copyright-free H.264/AAC media, three overlapped mono audio chunks, a Mock Chinese transcript, three candidates and validated clean masters with separate editorial metadata. It creates a human title revision that stales the old master, renders the revised clean 1080×1920 master before approval, approves that revision, then reuses it for SRT, manifest and `delivery.zip`. It prints the project ID and every required absolute path; reruns create a new isolated Demo project.

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

- Source video is a read-only path reference below `LIVECLIP_ALLOWED_MEDIA_ROOTS`, outside `LIVECLIP_DATA_DIR`, and is not copied by default. Keep imports in `input/` or another dedicated media root, never under `data/projects/`.
- Video frames, SQLite, transcripts, intermediate/generated videos and deliveries stay under the local data directory.
- Prepared audio chunks are uploaded to the configured ASR provider. In `openrouter-codex`, they pass through OpenRouter to its selected upstream Whisper host.
- Only bounded candidate transcript/context and metadata are sent to the LLM provider. Codex receives them through stdin, never argv, and runs with executable tools disabled.
- The API key is read from local environment only and is excluded from database, logs, UI, errors and Git.
- Saved Codex authentication stays in the Codex credential store and is not copied into LiveClip data.

Default project data will live under `data/projects`; Demo-owned data lives under `data/demo`. Both are ignored except placeholder directories.

## Recovery and troubleshooting

Use `liveclip status`, the API run retry endpoint, or the Web retry action for failed durable work. Expired leases are recovered by the same queue; stale revision renders cannot enter a Delivery. Consult structured local logs, then resume engineering work using [AGENTS.md](AGENTS.md), the [Living ExecPlan](docs/exec-plans/liveclip-v1.md), and [STATUS.md](STATUS.md).

Before a migration, ownership operation or destructive retention action, create a consistent backup. The command uses SQLite's online backup API, includes committed WAL data, requires `quick_check=ok`, zero foreign-key violations and one Alembic revision, computes SHA-256, and atomically publishes a new file without overwrite:

```bash
liveclip db-backup
# or choose a new absolute filename
liveclip db-backup --output /absolute/path/liveclip-before-change.sqlite3
```

Restore is intentionally offline and never replaces the live database. Stop `make dev`, restore to a new filename, inspect the printed revision/hash, then point `LIVECLIP_DATA_DIR` at a directory whose validated file is named `liveclip.sqlite3` before restarting:

```bash
liveclip db-restore \
  --backup /absolute/path/liveclip-before-change.sqlite3 \
  --output /absolute/path/recovered/liveclip.sqlite3
```

If either destination already exists, the command fails rather than overwriting it. Default operator and purge recovery points are under ignored `data/projects/database-backups/`; migration checkpoints remain under `data/projects/migration-backups/`.
See the [database backup and recovery runbook](docs/operations/database-recovery.md) before switching a restored data root.

- `SOURCE_NOT_ALLOWED` or import refusal: make the real source path a descendant of one `LIVECLIP_ALLOWED_MEDIA_ROOTS` entry and outside `LIVECLIP_DATA_DIR`; symlink escapes, generated Project/quarantine paths and `..` are intentionally rejected.
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
