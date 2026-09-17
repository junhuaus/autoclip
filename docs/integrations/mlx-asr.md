# Local MLX ASR setup

`mlx-codex` uses the complete unquantized Whisper `large-v3` model locally for transcription and the
existing Codex CLI for later editorial analysis. Audio does not leave the Mac. Transcript text still
goes to Codex, whose inference is cloud-backed through the saved ChatGPT login.

From the repository root, install the optional runtime and the exact 3.08 GB model snapshot:

```bash
cd "/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2" && make setup-local-asr
```

The installer pins the Hub commit and verifies exact SHA-256 values after download. It is safe to run
again: completed files are reused and verification repeats. Model files stay under ignored
`data/models/whisper-large-v3-mlx` and must never be committed.

Set these values in ignored `.env.local`:

```dotenv
LIVECLIP_AI_PROVIDER=mlx-codex
LIVECLIP_MLX_ASR_MODEL_PATH=./data/models/whisper-large-v3-mlx
LIVECLIP_ALLOWED_MEDIA_ROOTS=/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/input
```

No `OPENROUTER_API_KEY` or `OPENAI_API_KEY` is needed for ASR. Codex must already be logged in. Verify
the package, Metal access, FFmpeg, model bytes and Codex login before creating a run:

```bash
cd "/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2" && .venv/bin/liveclip doctor
```

Run one bounded real transcription before committing to a long input. `START` and `DURATION` are
seconds; the smoke prints local segment timestamps and text for inspection and creates no Project:

```bash
cd "/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2" && make smoke-mlx INPUT="/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/input/8-30.ts" START=0 DURATION=30
```

For a separately bounded and authorized full run, keep the independent Worker
awake in one terminal:

```bash
cd "/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2" && caffeinate -i .venv/bin/liveclip-worker
```

In another terminal, save and watch the durable goal, keeping the printed
request key for same-body recovery after a lost response:

```bash
cd "/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2" && .venv/bin/liveclip auto "/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/input/8-30.ts"
```

Local ASR always uses one inference worker even if `ASR_CONCURRENCY` is higher. A different or damaged
model yields `MLX_ASR_NOT_READY` before processing. There is no automatic cloud or Mock fallback.
