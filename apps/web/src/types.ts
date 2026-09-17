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

export type ProjectLifecycle =
  | "draft"
  | "processing"
  | "needs_attention"
  | "editorial_review"
  | "changes_requested"
  | "approval"
  | "ready_to_publish"
  | "published"
  | "archived";

export type ProjectPriority = "low" | "normal" | "high" | "urgent";

export type ReviewStatus = "pending_review" | "approved" | "rejected";
export type RenderStatus = "queued" | "running" | "succeeded" | "failed" | "stale";
export type DeliveryStatus = "queued" | "creating" | "succeeded" | "failed";
export type EditPackageStatus = "queued" | "creating" | "succeeded" | "failed";
export type RenderKind = "proxy" | "final";

export interface ProviderHealth {
  mode: "mock" | "openai" | "mock-codex" | "openai-codex" | "openrouter-codex" | "mlx-codex";
  asr_provider: "mock" | "openai" | "openrouter" | "mlx";
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
  lifecycle: ProjectLifecycle;
  lifecycle_before_archive: ProjectLifecycle | null;
  management_version: number;
  assignee: WorkspaceMember | null;
  priority: ProjectPriority;
  due_at: string | null;
  updated_at: string | null;
  owner: WorkspaceMember;
  members: WorkspaceMember[];
  current_user_role: WorkspaceRole;
  allowed_actions: ProjectAction[];
  allowed_lifecycle_transitions: ProjectLifecycle[];
}

export type ProjectRoleFilter = "owner" | "editor" | "reviewer" | "viewer";
export type ProjectVisibilityFilter = "private" | "workspace";
export type ProjectAssigneeFilter = "any" | "me" | "unassigned" | "user";
export type ProjectDueFilter = "any" | "overdue" | "today" | "next_7_days" | "unscheduled";
export type ProjectSearchSort = "updated_desc" | "due_asc" | "priority_desc" | "name_asc";
export interface ProjectSearchCriteria {
  query: string;
  lifecycles: ProjectLifecycle[];
  priorities: ProjectPriority[];
  roles: ProjectRoleFilter[];
  visibilities: ProjectVisibilityFilter[];
  platforms: ReleasePlatform[];
  assignee: ProjectAssigneeFilter;
  assignee_user_id: string | null;
  due: ProjectDueFilter;
  sort: ProjectSearchSort;
}

export type ProjectSearchMatchScope =
  | "project"
  | "source"
  | "clip_title"
  | "clip_hook"
  | "transcript"
  | "assignee"
  | "lifecycle"
  | "platform";

export interface ProjectSearchMatch {
  scope: ProjectSearchMatchScope;
  text: string;
  clip_id: string | null;
  release_item_id: string | null;
}

export interface ProjectSearchItem {
  project: ProjectSnapshot;
  matches: ProjectSearchMatch[];
}

export interface ProjectSearchSummary {
  visible_total: number;
  needs_attention: number;
  processing: number;
  review: number;
  publish: number;
  archived: number;
  overdue: number;
  lifecycle_counts: Record<ProjectLifecycle, number>;
  priority_counts: Record<ProjectPriority, number>;
}

export interface ProjectSearchPage {
  schema_version: "1";
  criteria: ProjectSearchCriteria;
  query_fingerprint: string;
  evaluated_at: string;
  timezone: string;
  total_count: number;
  limit: number;
  next_cursor: string | null;
  summary: ProjectSearchSummary;
  items: ProjectSearchItem[];
}

export interface SavedProjectView {
  view_id: string;
  name: string;
  criteria_schema_version: "1";
  criteria: ProjectSearchCriteria;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SavedProjectViewsResponse {
  schema_version: "1";
  views: SavedProjectView[];
}

export type WorkspaceRole = "owner" | "editor" | "reviewer" | "viewer";
export type ProjectAction =
  | "read"
  | "manage_members"
  | "manage_project"
  | "run_pipeline"
  | "edit_clip"
  | "review_clip"
  | "comment"
  | "render"
  | "export"
  | "deliver"
  | "manage_release"
  | "approve_release";

export interface ProjectManagementRequest {
  expected_management_version: number;
  visibility: "private" | "workspace";
  assignee_user_id: string | null;
  priority: ProjectPriority;
  due_at: string | null;
}

export interface ProjectLifecycleRequest {
  expected_management_version: number;
  target: ProjectLifecycle;
  reason: string;
}

export interface ProjectActivity {
  event_id: string;
  actor_username: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}

export interface ProjectActivityResponse {
  schema_version: "1";
  project_id: string;
  events: ProjectActivity[];
}

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

export interface AdminProjectMember extends WorkspaceMember {
  is_active: boolean;
}

export interface AdminProjectSnapshot {
  project_id: string;
  name: string;
  source_filename: string;
  pipeline_status: PipelineRunStatus | null;
  current_run_id: string | null;
  generation: number;
  visibility: "private" | "workspace";
  lifecycle: ProjectLifecycle;
  management_version: number;
  assignee: AdminProjectMember | null;
  priority: ProjectPriority;
  due_at: string | null;
  updated_at: string | null;
  owner: AdminProjectMember;
  members: AdminProjectMember[];
  administrative_context: true;
  allowed_governance_actions: Array<"view" | "transfer_ownership">;
}

export interface AdminProjectsResponse {
  schema_version: "1";
  projects: AdminProjectSnapshot[];
}

export interface AdminProjectResponse {
  schema_version: "1";
  project: AdminProjectSnapshot;
}

export interface AdminAuditEvent {
  event_id: string;
  actor_username: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  project_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  correlation_id: string | null;
  created_at: string;
}

export interface AdminAuditEventsResponse {
  schema_version: "1";
  events: AdminAuditEvent[];
}

export interface ProjectStorageUsage {
  project_id: string;
  project_name: string;
  lifecycle: string;
  actual_bytes: number;
  actual_file_count: number;
  tracked_asset_bytes: number;
  stale_render_asset_bytes: number;
  orphan_asset_bytes: number;
  pending_asset_bytes: number;
  untracked_bytes: number;
  untracked_file_count: number;
  missing_committed_asset_count: number;
  unsafe_entry_count: number;
  source_reference_bytes: number;
}

export interface StorageReport {
  schema_version: "1";
  scanned_at: string;
  filesystem_capacity_bytes: number;
  filesystem_free_bytes: number;
  data_directory_bytes: number;
  database_bytes: number;
  migration_backup_bytes: number;
  database_backup_bytes: number;
  purge_quarantine_bytes: number;
  purge_quarantine_file_count: number;
  project_directory_bytes: number;
  unknown_project_directory_bytes: number;
  unknown_project_file_count: number;
  other_bytes: number;
  unsafe_entry_count: number;
  projects: ProjectStorageUsage[];
  policy: {
    automatic_project_purge: false;
    source_media_deletion: false;
    safe_cleanup_committed_artifact_deletion: false;
    safe_cleanup_scope: "terminal_attempt_worktrees_and_completed_purge_quarantine";
    archive_retains_artifacts: true;
    destructive_project_purge_available: true;
    purge_requires_archived_project: true;
    purge_creates_database_backup: true;
  };
}

export interface StorageCleanupResult {
  schema_version: "1";
  inspected_attempts: number;
  cleaned_attempts: number;
  failed_attempts: number;
  inspected_purge_quarantines: number;
  cleaned_purge_quarantines: number;
  failed_purge_quarantines: number;
  report: StorageReport;
}

export interface ProjectPurgePlan {
  schema_version: "1";
  project_id: string;
  project_name: string;
  lifecycle: string;
  management_version: number;
  generated_bytes: number;
  generated_file_count: number;
  unsafe_entry_count: number;
  source_filename: string | null;
  source_media_preserved: true;
  active_run_count: number;
  active_task_count: number;
  blockers: string[];
  ready: boolean;
  snapshot_fingerprint: string;
  confirmation_phrase: string;
}

export interface ProjectPurgeResult {
  schema_version: "1";
  project_id: string;
  project_name: string;
  purged_at: string;
  removed_generated_bytes: number;
  removed_generated_file_count: number;
  source_media_preserved: true;
  database_backup_filename: string;
  database_backup_sha256: string;
  filesystem_cleanup_pending: boolean;
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
  clipping_algorithm?: "a" | "b" | "b_v2_experimental" | "semantic_global" | "semantic_windowed";
  semantic_profile?: "general" | "vocal_coach_live";
  clip_profile?: "short_highlight" | "mini_lesson";
  semantic_target_clip_seconds?: number;
  semantic_score_threshold?: number;
  semantic_full_context_budget_ratio?: number;
  semantic_model_context_tokens?: number;
  semantic_no_render?: boolean;
  semantic_prompt_debug?: boolean;
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

export type CompletionPresetId = "short_highlight_v1" | "mini_lesson_v1";
export type CompletionSelectionPolicy = "default" | "manual";
export type CompletionIntentStatus =
  | "queued"
  | "waiting_work"
  | "waiting_selection"
  | "needs_action"
  | "succeeded"
  | "cancelled";
export type CompletionOutcome =
  | "processed"
  | "delivered"
  | "no_eligible_clips"
  | "no_selected_clips"
  | "cancelled";

export interface CompletionPresetSummary {
  schema_version: "1";
  preset_id: CompletionPresetId;
  display_name_zh: string;
  clip_profile: "short_highlight" | "mini_lesson";
  minimum_clip_seconds: number;
  target_clip_seconds: number;
  maximum_clip_seconds: number;
  default_selection_policy: CompletionSelectionPolicy;
  acceptance_status: "experimental";
}

export interface CompletionPresetsResponse {
  schema_version: "1";
  presets: CompletionPresetSummary[];
}

export interface CompletionPresetCreateRequest {
  input_path: string;
  preset_id: CompletionPresetId;
  selection_policy: CompletionSelectionPolicy;
}

export interface CompletionGoalSnapshot {
  intent_id: string;
  project_id: string;
  run_id: string;
  generation: number;
  requester_user_id: string;
  actor_user_id: string;
  options: {
    schema_version: "1";
    target: "process_only" | "delivery";
    selection_policy: CompletionSelectionPolicy;
    include_zip: boolean;
    preset_id: string | null;
  };
  status: CompletionIntentStatus;
  version: number;
  selection_submitted: boolean;
  delivery_id: string | null;
  outcome: CompletionOutcome | null;
  blocking_code: string | null;
  safe_error_message: string | null;
  delivery_progress: DeliveryProgressSnapshot | null;
}

export interface DeliveryProgressSnapshot {
  schema_version: "1";
  phase:
    | "queued"
    | "copying_hashing"
    | "writing_metadata"
    | "writing_zip"
    | "verifying_package"
    | "committing_assets"
    | "succeeded"
    | "failed"
    | "cancelled";
  unit: "bytes" | "files" | "members" | "assets" | null;
  completed: number | null;
  total: number | null;
  attempt_id: string | null;
  business_advanced_at: string | null;
  worker_heartbeat_at: string | null;
  lease_fresh: boolean;
}

export interface CompletionGoalResponse {
  goal: CompletionGoalSnapshot;
  download_url: string | null;
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
  download_video_url: string | null;
  download_subtitle_url: string | null;
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

export interface CommentIdentity {
  user_id: string | null;
  username: string;
  display_name: string;
}

export interface ClipCommentMessage {
  comment_id: string;
  author: CommentIdentity;
  body: string;
  mentions: CommentIdentity[];
  created_at: string;
}

export type ClipCommentThreadAction = "reply" | "resolve" | "reopen";

export interface ClipCommentThread {
  thread_id: string;
  project_id: string;
  clip_id: string;
  edit_plan_revision: number;
  current_revision: number;
  is_current_revision: boolean;
  is_current_generation: boolean;
  source_time_ms: number;
  clip_time_ms: number;
  current_clip_time_ms: number | null;
  status: "open" | "resolved";
  version: number;
  allowed_actions: ClipCommentThreadAction[];
  created_by: CommentIdentity;
  resolved_by: CommentIdentity | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  comments: ClipCommentMessage[];
}

export interface ClipCommentThreads {
  schema_version: "1";
  clip_id: string;
  current_revision: number;
  total_count: number;
  next_offset: number | null;
  threads: ClipCommentThread[];
}

export interface ClipCommentThreadCreateRequest {
  expected_revision: number;
  clip_time_ms: number;
  body: string;
  mentioned_user_ids: string[];
}

export interface ClipCommentReplyRequest {
  body: string;
  mentioned_user_ids: string[];
}

export interface ClipCommentStatusRequest {
  expected_thread_version: number;
  status: "open" | "resolved";
}

export interface ClipPatchRequest {
  expected_revision: number;
  source_start_ms?: number;
  source_end_ms?: number;
  score?: number;
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
  resource_type: "render" | "delivery" | "edit_package" | "release_package";
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

export interface EditPackageItemRequest {
  clip_id: string;
  expected_revision: number;
}

export interface EditPackageCreateRequest {
  items: EditPackageItemRequest[];
  preset: "clean_editing";
  content: "full" | "metadata_only";
  include_zip: boolean;
}

export interface EditPackageSnapshot {
  edit_package_id: string;
  project_id: string;
  task_id: string;
  requested_by_user_id: string;
  version: number;
  package_version: string;
  status: EditPackageStatus;
  clip_count: number;
  preset: "clean_editing";
  content: "full" | "metadata_only";
  manifest_asset_id: string | null;
  zip_asset_id: string | null;
  include_zip: boolean;
  error_code: string | null;
  safe_error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface EditPackageDetailResponse {
  edit_package: EditPackageSnapshot;
  download_url: string | null;
}

export type ReleasePlatform =
  | "douyin"
  | "xiaohongshu"
  | "bilibili_vertical"
  | "youtube_shorts"
  | "tiktok"
  | "generic_vertical";
export type ReleaseCaptionMode = "clean_separate" | "burned";
export type ReleaseApprovalStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "changes_requested";
export type ReleaseItemStatus =
  | "draft"
  | "ready"
  | "scheduled_external"
  | "published"
  | "failed"
  | "withdrawn";
export type ReleasePackageStatus = "queued" | "creating" | "succeeded" | "failed";

export interface ReleaseChecklist {
  hook_confirmed: boolean;
  first_frame_confirmed: boolean;
  subtitles_confirmed: boolean;
  music_rights_confirmed: boolean;
  likeness_confirmed: boolean;
  personal_data_confirmed: boolean;
  claims_confirmed: boolean;
  sponsorship_confirmed: boolean;
  platform_policy_confirmed: boolean;
}

export interface ReleasePreflightCheck {
  code: string;
  category: string;
  outcome: "passed" | "blocked" | "warning" | "info";
  message: string;
}

export interface ReleasePreflight {
  schema_version: string;
  preset_id: string;
  checked_at: string;
  passed: boolean;
  blocker_count: number;
  warning_count: number;
  checks: ReleasePreflightCheck[];
}

export interface ReleaseAssignee {
  user_id: string;
  username: string;
  display_name: string;
}

export interface ReleaseMetricSnapshot {
  metric_id: string;
  captured_at: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  followers_gained: number;
  notes: string | null;
  recorded_by_username: string;
  created_at: string;
}

export interface ReleasePackageSnapshot {
  release_package_id: string;
  release_item_id: string;
  project_id: string;
  task_id: string;
  requested_by_user_id: string;
  version: number;
  package_version: string;
  release_item_version: number;
  current: boolean;
  published_artifact: boolean;
  status: ReleasePackageStatus;
  preset_version: string;
  caption_mode: ReleaseCaptionMode;
  manifest_asset_id: string | null;
  zip_asset_id: string | null;
  video_sha256: string;
  manifest_sha256: string | null;
  zip_sha256: string | null;
  include_zip: boolean;
  error_code: string | null;
  safe_error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ReleasePublicationEvidence {
  schema_version: "liveclip.release-publication-evidence.v1";
  release_package_id: string;
  package_version: string;
  release_item_version: number;
  preset_version: string;
  caption_mode: ReleaseCaptionMode;
  video_sha256: string;
  artifact_kind: "zip" | "manifest";
  artifact_sha256: string;
  manifest_sha256: string;
  zip_sha256: string | null;
  recorded_at: string;
}

export interface ReleaseItemSnapshot {
  release_item_id: string;
  project_id: string;
  clip_id: string;
  edit_plan_revision: number;
  current_edit_plan_revision: number;
  stale: boolean;
  stale_reason: "revision_changed" | "project_run_changed" | null;
  platform: ReleasePlatform;
  preset_version: string;
  account_label: string;
  title: string;
  title_variants: string[];
  description: string;
  hashtags: string[];
  cta: string;
  caption_mode: ReleaseCaptionMode;
  cover_time_ms: number;
  clip_duration_ms: number;
  high_impact_sentence: string;
  risk_flags: string[];
  preview_asset_id: string | null;
  assignee: ReleaseAssignee | null;
  planned_publish_at: string | null;
  approval_status: ReleaseApprovalStatus;
  status: ReleaseItemStatus;
  checklist: ReleaseChecklist;
  preflight: ReleasePreflight;
  management_version: number;
  external_url: string | null;
  external_id: string | null;
  published_at: string | null;
  result_notes: string | null;
  publication_evidence: ReleasePublicationEvidence | null;
  metrics: ReleaseMetricSnapshot[];
  packages: ReleasePackageSnapshot[];
  created_at: string;
  updated_at: string;
}

export interface PlatformPreset {
  platform: ReleasePlatform;
  version: string;
  checked_at: string;
  label: string;
  recommended_width: number;
  recommended_height: number;
  minimum_width: number;
  minimum_height: number;
  maximum_dimension: number | null;
  maximum_duration_ms: number | null;
  maximum_file_bytes: number | null;
  safe_zone: {
    top: number;
    right: number;
    bottom: number;
    left: number;
    basis: string;
  };
  account_policy_confirmation_required: boolean;
  policy_notes: string[];
  official_sources: string[];
}

export interface ReleasePresetsResponse {
  schema_version: "1";
  presets: PlatformPreset[];
  current_versions: Record<ReleasePlatform, string>;
}

export interface ReleaseItemsResponse {
  schema_version: "1";
  project_id: string;
  releases: ReleaseItemSnapshot[];
  preview_media_urls: Record<string, string>;
}

export interface ReleasePackageDetailResponse {
  schema_version: "1";
  release_package: ReleasePackageSnapshot;
  download_url: string | null;
  download_kind: "zip" | "manifest" | null;
}

export interface ReleaseItemCreateRequest {
  clip_id: string;
  expected_revision: number;
  platform: ReleasePlatform;
  account_label: string;
  caption_mode: ReleaseCaptionMode;
  assignee_user_id: string | null;
  planned_publish_at: string | null;
}

export interface ReleaseItemUpdateRequest {
  expected_management_version: number;
  edit_plan_revision: number;
  title: string;
  title_variants: string[];
  description: string;
  hashtags: string[];
  cta: string;
  caption_mode: ReleaseCaptionMode;
  cover_time_ms: number;
  assignee_user_id: string | null;
  planned_publish_at: string | null;
  checklist: ReleaseChecklist;
}

export interface ReleaseApprovalRequest {
  expected_management_version: number;
  target: ReleaseApprovalStatus;
  reason: string;
}

export interface ReleaseStatusRequest {
  expected_management_version: number;
  target: ReleaseItemStatus;
  release_package_id?: string;
  external_url?: string;
  external_id?: string;
  published_at?: string;
  result_notes?: string;
}

export interface ReleaseMetricRequest {
  captured_at: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  followers_gained: number;
  notes: string | null;
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
