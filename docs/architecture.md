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
  ASR[Mock / OpenAI ASR] -.implements.-> PORTS
  LLM[Mock / OpenAI LLM] -.implements.-> PORTS
  RENDER[FFmpeg renderer] -.implements.-> PORTS
  DELIVERY[Delivery adapter] -.implements.-> PORTS
```

## Data flow and cloud boundary

```mermaid
flowchart LR
  SOURCE[(Local source video)] --> PRE[Local audio preprocessing]
  PRE --> CHUNKS[Local compressed chunks]
  CHUNKS -->|audio only| OASR[OpenAI transcription]
  OASR --> TRANSCRIPT[(Local transcript)]
  TRANSCRIPT --> CAND[Local deterministic candidates]
  CAND -->|bounded text + metadata| OLLM[OpenAI Responses]
  OLLM --> VALIDATE[Local strict validation]
  VALIDATE --> RENDER[Local deterministic renderer]
  SOURCE --> RENDER
  RENDER --> LOCAL[(Local proxies/finals/deliveries)]
```

Video frames, files, database, proxies, finals and deliveries stay local. OpenAI receives prepared audio for ASR and bounded transcript data for editing.

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
  DOMAIN --> MAP[Local enum/template mapping]
  DOMAIN --> PNG[Pillow text rasterization]
  MAP --> ARGV[System-built FFmpeg argv]
  PNG --> ARGV
  ARGV --> EXEC[subprocess shell=False]
```

No path, command, filtergraph, SQL, code or script is accepted from the model.

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
