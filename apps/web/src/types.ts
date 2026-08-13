export type PipelineRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type StageRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export type ProjectStatus =
  | "imported"
  | "processing"
  | "pending_review"
  | "ready_for_delivery"
  | "delivered"
  | "failed";

export type ReviewStatus = "pending_review" | "approved" | "rejected";
export type RenderStatus = "queued" | "running" | "succeeded" | "failed" | "stale";
export type DeliveryStatus = "queued" | "creating" | "succeeded" | "failed";
export type RenderKind = "proxy" | "final";

export interface ProviderHealth {
  mode: "mock" | "openai" | "mock-codex" | "openai-codex" | "openrouter-codex";
  asr_provider: "mock" | "openai" | "openrouter";
  llm_provider: "mock" | "openai" | "codex_cli";
  asr_ready: boolean;
  llm_ready: boolean;
  processing_ready: boolean;
  blocking_issues: string[];
  warnings: string[];
}

export interface HealthResponse {
  schema_version: "1";
  status: "ok";
  version: string;
  database: "ok";
  providers: ProviderHealth;
}

export interface StageSnapshot {
  stage: string;
  status: StageRunStatus;
  progress: number;
  retry_count: number;
  error_code: string | null;
  safe_error_message: string | null;
}

export interface RunSnapshot {
  run_id: string;
  project_id: string;
  status: PipelineRunStatus;
  progress: number;
  cancellation_requested: boolean;
  error_code: string | null;
  safe_error_message: string | null;
  stages: StageSnapshot[];
}

export interface ProjectSnapshot {
  project_id: string;
  name: string;
  source_filename: string;
  status: ProjectStatus;
  current_run_id: string;
  generation: number;
  visibility: "private" | "workspace";
  owner: WorkspaceMember;
  members: WorkspaceMember[];
  current_user_role: WorkspaceRole;
}

export type WorkspaceRole = "owner" | "editor" | "reviewer" | "viewer";

export interface WorkspaceUser {
  user_id: string;
  username: string;
  display_name: string;
  system_role: "administrator" | "member";
}

export interface WorkspaceMember {
  user_id: string;
  username: string;
  display_name: string;
  role: WorkspaceRole;
}

export interface SessionResponse {
  schema_version: "1";
  user: WorkspaceUser;
  credential_kind: "session" | "legacy";
  csrf_token: string | null;
  expires_at: string | null;
}

export interface LoginResponse {
  schema_version: "1";
  user: WorkspaceUser;
  csrf_token: string;
  expires_at: string;
}

export interface ManagedUser extends WorkspaceUser {
  is_active: boolean;
  password_configured: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

export interface AdminUsersResponse {
  schema_version: "1";
  users: ManagedUser[];
}

export interface AdminUserCreateRequest {
  username: string;
  display_name: string;
  system_role: "administrator" | "member";
  password: string;
}

export interface AdminUserPatchRequest {
  display_name?: string;
  system_role?: "administrator" | "member";
  is_active?: boolean;
}

export interface ProjectMemberCreateRequest {
  username: string;
  display_name: string;
  role: "editor" | "reviewer" | "viewer";
}

export interface ProjectMembersResponse {
  schema_version: "1";
  project_id: string;
  members: WorkspaceMember[];
}

export interface JobCreateRequest {
  input_path: string;
  top_n?: number;
  minimum_clip_seconds?: number;
  maximum_clip_seconds?: number;
}

export interface AcceptedPipelineResponse {
  project_id: string;
  run_id: string;
  status: string;
  status_url: string;
}

export interface TranscriptSegment {
  segment_id: string;
  index: number;
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface TranscriptSnapshot {
  project_id: string;
  run_id: string;
  language: string;
  provider: string;
  model: string;
  word_timing_status: string;
  segments: TranscriptSegment[];
}

export interface CaptionCue {
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface KeywordOccurrence {
  text: string;
  clip_start_ms: number;
  clip_end_ms: number;
  source_start_ms: number;
  source_end_ms: number;
  timing_precision: "word" | "segment";
}

export interface EditPlan {
  schema_version: string;
  candidate_id: string;
  source_start_ms: number;
  source_end_ms: number;
  score: number;
  title: string;
  hook: string;
  reason: string;
  layout: "center_crop";
  caption_template: "clean_zh_v1";
  effect: "none" | "fade_in_out";
  risk_flags: string[];
  prompt_version: string;
  model: string;
  degraded: boolean;
}

export interface ClipSummary {
  clip_id: string;
  candidate_key: string;
  edit_plan_revision: number;
  source_start_ms: number;
  source_end_ms: number;
  score: number;
  title: string;
  hook: string;
  reason: string;
  risk_flags: string[];
  captions: CaptionCue[];
  keywords: KeywordOccurrence[];
  review_status: ReviewStatus;
  proxy_status: RenderStatus | null;
  proxy_asset_id: string | null;
  allowed_actions: string[];
}

export interface ClipSummaryResponse {
  clip: ClipSummary;
  proxy_media_url: string | null;
}

export interface RenderSnapshot {
  render_id: string;
  task_id: string | null;
  kind: RenderKind;
  status: RenderStatus;
  edit_plan_revision: number;
  width: number;
  height: number;
  video_asset_id: string | null;
  subtitle_asset_id: string | null;
  quality_report_asset_id: string | null;
  contact_sheet_asset_id: string | null;
  error_code: string | null;
  safe_error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewSnapshot {
  status: ReviewStatus;
  reason: string | null;
  decided_at: string | null;
}

export interface ClipDetail {
  clip_id: string;
  project_id: string;
  run_id: string;
  generation: number;
  revision_epoch: number;
  candidate_key: string;
  allowed_start_ms: number;
  allowed_end_ms: number;
  transcript_text: string;
  context_before: string;
  context_after: string;
  rule_score: number;
  reasons: string[];
  rank: number | null;
  current_revision: number;
  plan: EditPlan;
  captions: CaptionCue[];
  keywords: KeywordOccurrence[];
  revision_created_at: string;
  review: ReviewSnapshot;
  renders: RenderSnapshot[];
  allowed_actions: string[];
}

export interface ClipDetailResponse {
  clip: ClipDetail;
  asset_urls: Record<string, string>;
}

export interface ClipPatchRequest {
  expected_revision: number;
  source_start_ms?: number;
  source_end_ms?: number;
  title?: string;
  layout?: "center_crop";
  captions?: CaptionCue[];
}

export interface ReviewActionRequest extends ClipPatchRequest {
  status: "approved" | "rejected";
  reason?: string;
}

export interface BatchReviewItemRequest {
  clip_id: string;
  expected_revision: number;
  status: "approved" | "rejected";
  reason?: string;
}

export interface BatchReviewRequest {
  items: BatchReviewItemRequest[];
}

export interface BatchReviewResponse {
  schema_version: "1";
  project_id: string;
  clips: ClipDetailResponse[];
}

export interface AcceptedTaskResponse {
  resource_type: "render" | "delivery";
  resource_id: string;
  task_id: string;
  status: string;
  status_url: string;
}

export interface QueuedRender {
  render_id: string;
  task_id: string;
  clip_id: string;
  edit_plan_revision: number;
  kind: RenderKind;
  status: RenderStatus;
}

export interface DeliverySnapshot {
  delivery_id: string;
  project_id: string;
  task_id: string;
  version: number;
  delivery_version: string;
  status: DeliveryStatus;
  clip_count: number;
  manifest_asset_id: string | null;
  zip_asset_id: string | null;
  include_zip: boolean;
  error_code: string | null;
  safe_error_message: string | null;
}

export interface DeliveryDetailResponse {
  delivery: DeliverySnapshot;
  download_url: string | null;
}

export interface ApiErrorItem {
  location: Array<string | number>;
  type: string;
}

export interface ApiErrorDetail {
  schema_version: "1";
  code: string;
  message: string;
  retryable: boolean;
  resource_id: string | null;
  correlation_id: string;
  details: ApiErrorItem[];
}

export interface ApiErrorEnvelope {
  error: ApiErrorDetail;
}
