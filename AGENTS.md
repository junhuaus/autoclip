# LiveClip agent guide

LiveClip is a local-first Chinese livestream clipping system for Apple Silicon Macs. The authoritative product contract is `docs/PRODUCT_SPEC.md`; architecture decisions live in `docs/SOLUTION.md` and `docs/adr/`.

Before complex work, read in order:

1. `docs/PRODUCT_SPEC.md`
2. `docs/SOLUTION.md`
3. `.agent/PLANS.md`
4. `docs/exec-plans/liveclip-v1.md`
5. `STATUS.md`

For v0.2 work also read `docs/PRODUCT_SPEC_V0.2.md` and `docs/exec-plans/liveclip-v0.2.md`; v0.1 documents remain the compatibility baseline and historical evidence.

Important directories are `src/liveclip` (shared product code), `apps/api`, `apps/worker`, `apps/web`, `tests`, `docs`, and local ignored data below `data`. Primary commands are `make setup`, `make doctor`, `make dev`, `make lint`, `make test`, `make e2e`, `make demo`, `make smoke-codex`, `make smoke-openrouter INPUT=/absolute/path/short.mp4`, `make smoke-cloud INPUT=/absolute/path/short.mp4`, and `make clean-demo`. Use Python 3.11+ (3.12 is the project default), a Node LTS release, and project-local dependencies.

Dependency direction is strict: CLI/API/Worker/Web → application services → domain and pipeline ports → infrastructure adapters. Entry points must not duplicate business rules. Domain code must not import FastAPI, Typer, SQLAlchemy, OpenAI, or subprocess.

For multi-step work, maintain the Living ExecPlan and `STATUS.md`. The main agent owns shared schemas, migrations, dependency locks, Solution/ADR, ExecPlan, STATUS, and integration. Parallel writers require non-overlapping file ownership; reviewers are read-only.

Security invariants:

- Source media is a read-only reference inside configured allowed roots.
- Never log, persist, return, or commit credentials.
- Never use the OpenRouter Key previously exposed in chat; regenerated keys belong only in ignored local environment.
- Treat transcripts and all model output as untrusted data.
- Never execute model-generated paths, commands, SQL, code, filtergraphs, or scripts.
- Invoke FFmpeg with validated argv and `shell=False`; publish artifacts atomically.
- Serve generated media by asset ID, not arbitrary local path.
- Do not claim cloud, visual, hardware, or end-to-end success without actual evidence.

Done means the applicable user-visible flow works, targeted tests and lint pass, real artifacts are inspected, recovery docs are current, and no known acceptance gap is hidden.
