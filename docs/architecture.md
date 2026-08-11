# Architecture

`docs/SOLUTION.md` is the detailed decision document. These diagrams summarize the durable boundaries.

## Modules

```mermaid
flowchart TB
  CLI[Typer CLI] --> APP[Application services]
  API[FastAPI] --> APP
  WORKER[Worker] --> APP
  WEB[React review console] -->|HTTP| API
  APP --> DOMAIN[Domain + state transitions]
  APP --> PORTS[Provider / repository / renderer ports]
  DB[SQLAlchemy + SQLite] -.implements.-> PORTS
  MEDIA[Filesystem + FFmpeg media] -.implements.-> PORTS
  ASR[Mock / OpenAI / OpenRouter ASR] -.implements.-> PORTS
  LLM[Mock / OpenAI Responses / Codex CLI LLM] -.implements.-> PORTS
  RENDER[FFmpeg renderer] -.implements.-> PORTS
  DELIVERY[Delivery adapter] -.implements.-> PORTS
```

## Data flow and cloud boundary

```mermaid
flowchart LR
  SOURCE[(Local source video)] --> PRE[Local audio preprocessing]
  PRE --> CHUNKS[Local compressed chunks]
  CHUNKS -->|audio only| ROUTER[OpenRouter]
  ROUTER -->|routed audio| OASR[Whisper Large V3 host]
  OASR --> TRANSCRIPT[(Local transcript)]
  TRANSCRIPT --> CAND[Local deterministic candidates]
  CAND -->|bounded text + metadata| EDITOR[OpenAI Responses or local Codex CLI process]
  EDITOR -->|cloud inference; no tools| VALIDATE[Local strict validation]
  VALIDATE --> META[Separate title / Hook / reason / risks / captions]
  VALIDATE --> PROXY[Local clean proxy renderer]
  META --> REVIEW[Human review]
  PROXY --> REVIEW
  REVIEW --> FINAL[Local final renderer with approved overlays]
  SOURCE --> PROXY
  SOURCE --> FINAL
  FINAL --> LOCAL[(Local finals/deliveries)]
  PROXY --> LOCAL_PROXY[(Local review proxies)]
```

Video frames, files, database, proxies, finals and deliveries stay local. In the default chain, prepared audio passes through OpenRouter to its selected Whisper host. Bounded transcript data then goes separately to the local Codex CLI process, whose inference remains cloud-based through saved ChatGPT authentication. Codex never receives source video/audio and is not ASR. Direct OpenAI ASR/Responses modes remain explicit alternatives.

## Pipeline and review

```mermaid
stateDiagram-v2
  [*] --> ingest
  ingest --> preprocess
  preprocess --> transcribe
  transcribe --> candidates
  candidates --> edit
  edit --> proxy_render
  proxy_render --> pending_review
  pending_review --> approved
  pending_review --> rejected
  approved --> final_render
  final_render --> ready_for_delivery
  ready_for_delivery --> delivered
  approved --> pending_review: new EditPlan revision
  delivered --> pending_review: later edit
```

PipelineRun, StageRun, review, Render and Delivery each have separate state machines; the diagram is user flow, not a single status enum.

## Durable command and media access

```mermaid
flowchart LR
  UI[Web / CLI / REST] --> SVC[Shared application service]
  SVC -->|BEGIN IMMEDIATE| TASK[(SQLite Task + lease fence)]
  TASK --> CLAIM[Worker or foreground claim]
  CLAIM --> TMP[Task-scoped temporary output]
  TMP --> PIN[No-follow pinned FD + size + SHA]
  PIN --> CHECK[Same bytes: ffprobe + full decode + quality]
  CHECK -->|expected SHA + no-replace publish + DB fence| ASSET[(Committed Asset)]
  UI -->|poll resource ID| SVC
  ASSET --> SIGN[Short-lived path/purpose HMAC URL]
  SIGN --> RANGE[No-follow verified HTTP Range stream]
```

Long operations return durable IDs immediately. Foreground CLI and Worker compete through the same atomic claim; neither adapter bypasses the lease, generation, revision or input-fingerprint fences. Browser media URLs expose generated asset IDs, never arbitrary source paths.

## Delivery byte identity

```mermaid
flowchart LR
  APPROVED[Approved current render + SRT] --> PIN[Pin each member FD + SHA]
  PIN --> ZIP[Stream members into pinned ZIP FD]
  ZIP --> VERIFY[Verify every ZIP member + manifest]
  VERIFY --> TREE[Pin exact directory tree]
  TREE --> RENAME[Atomic no-replace rename]
  RENAME --> REHASH[Rebind + rehash every canonical member]
  REHASH --> COMMIT[Asset commit with expected SHA]
```

No ZIP member is reopened by an ordinary pathname after validation. A member or archive endpoint replacement fails publication or recovery; it cannot become a successful Delivery.

## EditPlan execution boundary

```mermaid
flowchart LR
  TEXT[Untrusted transcript] --> MODEL[LLM: no tools]
  MODEL --> WIRE[Strict wire schema]
  WIRE --> DOMAIN[Domain invariants + whitelist]
  DOMAIN --> MODE{System-owned render mode}
  MODE -->|review: none| MAP[Local layout/effect mapping]
  MODE -->|final: title_and_captions| PNG[Pillow text rasterization]
  PNG --> MAP
  MAP --> ARGV[System-built FFmpeg argv]
  ARGV --> EXEC[subprocess shell=False]
```

No path, command, filtergraph, SQL, code or script is accepted from the model.

Review proxies always use the `none` text mode and expose editorial fields separately. Final renders use `title_and_captions` only for the approved current revision. The text mode participates in the render fingerprint.

## Revision and invalidation

```mermaid
flowchart TD
  R1[EditPlan revision 1] --> P1[Proxy render r1]
  R1 --> A1[Review decision r1]
  CHANGE[Title/boundary/caption change] --> R2[EditPlan revision 2]
  CHANGE -->|marks| P1S[Proxy/final r1 stale]
  R2 --> P2[Proxy render r2]
  R2 --> A2[Approval r2]
  A2 --> F2[Validated final r2]
  F2 --> D[Immutable Delivery snapshot]
```
