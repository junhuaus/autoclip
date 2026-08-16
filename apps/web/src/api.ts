import type {
  AcceptedPipelineResponse,
  AcceptedTaskResponse,
  AdminAuditEventsResponse,
  AdminProjectResponse,
  AdminProjectsResponse,
  AdminUserCreateRequest,
  AdminUserPatchRequest,
  AdminUsersResponse,
  ApiErrorDetail,
  ApiErrorEnvelope,
  BatchReviewRequest,
  BatchReviewResponse,
  ClipCommentReplyRequest,
  ClipCommentStatusRequest,
  ClipCommentThread,
  ClipCommentThreadCreateRequest,
  ClipCommentThreads,
  ClipDetailResponse,
  ClipPatchRequest,
  ClipSummaryResponse,
  DeliveryDetailResponse,
  EditPackageCreateRequest,
  EditPackageDetailResponse,
  HealthResponse,
  JobCreateRequest,
  LoginResponse,
  ProjectSnapshot,
  ProjectManagementRequest,
  ProjectLifecycleRequest,
  ProjectActivityResponse,
  ProjectPurgePlan,
  ProjectPurgeResult,
  ProjectMemberCreateRequest,
  ProjectMembersResponse,
  QueuedRender,
  ReleaseApprovalRequest,
  ReleaseItemCreateRequest,
  ReleaseItemSnapshot,
  ReleaseItemUpdateRequest,
  ReleaseItemsResponse,
  ReleaseMetricRequest,
  ReleasePackageDetailResponse,
  ReleasePresetsResponse,
  ReleaseStatusRequest,
  RenderKind,
  ReviewActionRequest,
  RunSnapshot,
  SessionResponse,
  StorageCleanupResult,
  StorageReport,
  TranscriptSnapshot,
} from "./types";

export class LiveClipApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly correlationId: string | null;
  readonly details: ApiErrorDetail["details"];

  constructor(
    message: string,
    options: {
      status?: number;
      code?: string;
      retryable?: boolean;
      correlationId?: string | null;
      details?: ApiErrorDetail["details"];
    } = {},
  ) {
    super(message);
    this.name = "LiveClipApiError";
    this.status = options.status ?? 0;
    this.code = options.code ?? "NETWORK_ERROR";
    this.retryable = options.retryable ?? false;
    this.correlationId = options.correlationId ?? null;
    this.details = options.details ?? [];
  }
}

const SIGNED_URL_REFRESH_SAFETY_MS = 15_000;
const MIN_SIGNED_URL_REFRESH_MS = 5_000;
const MAX_SIGNED_URL_REFRESH_MS = 30 * 60_000;

export function signedUrlRefreshInterval(
  urls: ReadonlyArray<string | null | undefined>,
  nowMs = Date.now(),
): number | false {
  const expiries = urls.flatMap((value) => {
    if (!value) return [];
    try {
      const raw = new URL(value, "http://127.0.0.1").searchParams.get("expires");
      const expiresSeconds = raw === null ? Number.NaN : Number(raw);
      return Number.isSafeInteger(expiresSeconds) && expiresSeconds > 0
        ? [expiresSeconds * 1_000]
        : [];
    } catch {
      return [];
    }
  });
  if (expiries.length === 0) return false;
  const delay = Math.min(...expiries) - nowMs - SIGNED_URL_REFRESH_SAFETY_MS;
  return Math.max(
    MIN_SIGNED_URL_REFRESH_MS,
    Math.min(MAX_SIGNED_URL_REFRESH_MS, delay),
  );
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string" &&
    "message" in error &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

async function responseError(response: Response): Promise<LiveClipApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Never surface an untrusted raw response body.
  }
  if (isErrorEnvelope(payload)) {
    return new LiveClipApiError(payload.error.message, {
      status: response.status,
      code: payload.error.code,
      retryable: payload.error.retryable,
      correlationId: payload.error.correlation_id,
      details: payload.error.details,
    });
  }
  return new LiveClipApiError("LiveClip API 请求失败", {
    status: response.status,
    code: "HTTP_ERROR",
    correlationId: response.headers.get("X-Request-ID"),
  });
}

export function createIdempotencyKey(scope: string): string {
  const random =
    typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `liveclip-web-${scope}-${random}`.slice(0, 200);
}

export class LiveClipApiClient {
  private readonly token: string;
  private readonly baseUrl: string;
  private csrfToken = "";

  constructor(token = "", baseUrl = "/api/v1") {
    this.token = token.trim();
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  health(): Promise<HealthResponse> {
    return this.request("/health");
  }

  session(): Promise<SessionResponse> {
    return this.request<SessionResponse>("/session").then((session) => {
      this.csrfToken = session.csrf_token ?? "";
      return session;
    });
  }

  login(username: string, password: string): Promise<LoginResponse> {
    return this.request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }).then((session) => {
      this.csrfToken = session.csrf_token;
      return session;
    });
  }

  async logout(): Promise<void> {
    await this.requestNoContent("/auth/logout", { method: "POST" });
    this.csrfToken = "";
  }

  listUsers(): Promise<AdminUsersResponse> {
    return this.request("/admin/users");
  }

  createUser(body: AdminUserCreateRequest): Promise<AdminUsersResponse> {
    return this.request("/admin/users", { method: "POST", body: JSON.stringify(body) });
  }

  updateUser(userId: string, body: AdminUserPatchRequest): Promise<AdminUsersResponse> {
    return this.request(`/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  disableUser(userId: string): Promise<AdminUsersResponse> {
    return this.request(`/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
  }

  resetUserPassword(userId: string, password: string): Promise<AdminUsersResponse> {
    return this.request(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    });
  }

  listAdminProjects(): Promise<AdminProjectsResponse> {
    return this.request("/admin/projects");
  }

  getAdminProject(projectId: string): Promise<AdminProjectResponse> {
    return this.request(`/admin/projects/${encodeURIComponent(projectId)}`);
  }

  transferAdminProjectOwnership(
    projectId: string,
    newOwnerUserId: string,
  ): Promise<AdminProjectResponse> {
    return this.request(`/admin/projects/${encodeURIComponent(projectId)}/ownership-transfer`, {
      method: "POST",
      body: JSON.stringify({ new_owner_user_id: newOwnerUserId }),
    });
  }

  listAdminAuditEvents(projectId?: string): Promise<AdminAuditEventsResponse> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return this.request(`/admin/audit-events${query}`);
  }

  storageReport(): Promise<StorageReport> {
    return this.request("/admin/storage");
  }

  cleanupSafeStorage(): Promise<StorageCleanupResult> {
    return this.request("/admin/storage/cleanup", {
      method: "POST",
      body: JSON.stringify({ confirmation: "CLEANUP_TERMINAL_ATTEMPTS" }),
    });
  }

  projectPurgePlan(projectId: string): Promise<ProjectPurgePlan> {
    return this.request(`/admin/storage/projects/${encodeURIComponent(projectId)}/purge-plan`);
  }

  purgeProject(
    projectId: string,
    command: {
      snapshot_fingerprint: string;
      project_name: string;
      administrator_username: string;
      confirmation_phrase: string;
    },
  ): Promise<ProjectPurgeResult> {
    return this.request(`/admin/storage/projects/${encodeURIComponent(projectId)}/purge`, {
      method: "POST",
      body: JSON.stringify(command),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (this.token) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }
    if (this.csrfToken && init.method && !["GET", "HEAD"].includes(init.method)) {
      headers.set("X-CSRF-Token", this.csrfToken);
    }

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        credentials: "include",
      });
    } catch {
      throw new LiveClipApiError("无法连接本机 LiveClip API", {
        code: "NETWORK_ERROR",
        retryable: true,
      });
    }

    if (!response.ok) {
      throw await responseError(response);
    }

    return (await response.json()) as T;
  }

  private async requestNoContent(path: string, init: RequestInit): Promise<void> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    if (this.csrfToken) headers.set("X-CSRF-Token", this.csrfToken);
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      credentials: "include",
    });
    if (!response.ok) throw await responseError(response);
  }

  listProjects(): Promise<ProjectSnapshot[]> {
    return this.request("/projects");
  }

  getProject(projectId: string): Promise<ProjectSnapshot> {
    return this.request(`/projects/${encodeURIComponent(projectId)}`);
  }

  updateProjectManagement(
    projectId: string,
    body: ProjectManagementRequest,
  ): Promise<ProjectSnapshot> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/management`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  transitionProjectLifecycle(
    projectId: string,
    body: ProjectLifecycleRequest,
  ): Promise<ProjectSnapshot> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/lifecycle`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  listProjectActivity(projectId: string): Promise<ProjectActivityResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/activity`);
  }

  listProjectMembers(projectId: string): Promise<ProjectMembersResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/members`);
  }

  addProjectMember(
    projectId: string,
    body: ProjectMemberCreateRequest,
  ): Promise<ProjectMembersResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/members`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  removeProjectMember(
    projectId: string,
    userId: string,
  ): Promise<ProjectMembersResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
      { method: "DELETE" },
    );
  }

  transferProjectOwnership(
    projectId: string,
    newOwnerUserId: string,
  ): Promise<ProjectMembersResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/ownership-transfer`, {
      method: "POST",
      body: JSON.stringify({ new_owner_user_id: newOwnerUserId }),
    });
  }

  createJob(body: JobCreateRequest): Promise<AcceptedPipelineResponse> {
    return this.request("/jobs", {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("job") },
      body: JSON.stringify(body),
    });
  }

  getRun(runId: string): Promise<RunSnapshot> {
    return this.request(`/runs/${encodeURIComponent(runId)}`);
  }

  cancelRun(runId: string): Promise<RunSnapshot> {
    return this.request(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
  }

  retryRun(runId: string): Promise<RunSnapshot> {
    return this.request(`/runs/${encodeURIComponent(runId)}/retry`, { method: "POST" });
  }

  getTranscript(projectId: string): Promise<TranscriptSnapshot> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/transcript`);
  }

  listClips(projectId: string): Promise<ClipSummaryResponse[]> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/clips`);
  }

  getClip(clipId: string): Promise<ClipDetailResponse> {
    return this.request(`/clips/${encodeURIComponent(clipId)}`);
  }

  listClipCommentThreads(
    clipId: string,
    options: {
      revision?: "current" | "all";
      status?: "open" | "resolved" | "all";
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<ClipCommentThreads> {
    const query = new URLSearchParams({
      revision: options.revision ?? "all",
      status: options.status ?? "all",
      limit: String(options.limit ?? 100),
      offset: String(options.offset ?? 0),
    });
    return this.request(
      `/clips/${encodeURIComponent(clipId)}/comment-threads?${query.toString()}`,
    );
  }

  createClipCommentThread(
    clipId: string,
    body: ClipCommentThreadCreateRequest,
    requestKey = createIdempotencyKey("comment-thread"),
  ): Promise<ClipCommentThread> {
    return this.request(`/clips/${encodeURIComponent(clipId)}/comment-threads`, {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
      body: JSON.stringify(body),
    });
  }

  replyToClipCommentThread(
    threadId: string,
    body: ClipCommentReplyRequest,
    requestKey = createIdempotencyKey("comment-reply"),
  ): Promise<ClipCommentThread> {
    return this.request(`/comment-threads/${encodeURIComponent(threadId)}/replies`, {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
      body: JSON.stringify(body),
    });
  }

  updateClipCommentThreadStatus(
    threadId: string,
    body: ClipCommentStatusRequest,
    requestKey = createIdempotencyKey("comment-status"),
  ): Promise<ClipCommentThread> {
    return this.request(`/comment-threads/${encodeURIComponent(threadId)}/status`, {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
      body: JSON.stringify(body),
    });
  }

  patchClip(clipId: string, body: ClipPatchRequest): Promise<ClipDetailResponse> {
    return this.request(`/clips/${encodeURIComponent(clipId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  reviewClip(clipId: string, body: ReviewActionRequest): Promise<ClipDetailResponse> {
    return this.request(`/clips/${encodeURIComponent(clipId)}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  reviewClipsBatch(
    projectId: string,
    body: BatchReviewRequest,
    requestKey = createIdempotencyKey("batch-review"),
  ): Promise<BatchReviewResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/reviews/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": requestKey },
      body: JSON.stringify(body),
    });
  }

  createRender(
    clipId: string,
    expectedRevision: number,
    kind: RenderKind,
  ): Promise<AcceptedTaskResponse> {
    return this.request(`/clips/${encodeURIComponent(clipId)}/render`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey(`${kind}-render`) },
      body: JSON.stringify({ expected_revision: expectedRevision, kind }),
    });
  }

  getRender(renderId: string): Promise<QueuedRender> {
    return this.request(`/renders/${encodeURIComponent(renderId)}`);
  }

  listDeliveries(projectId: string): Promise<DeliveryDetailResponse[]> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/deliveries`);
  }

  createDelivery(projectId: string, includeZip = true): Promise<AcceptedTaskResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/deliveries`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("delivery") },
      body: JSON.stringify({ include_zip: includeZip }),
    });
  }

  getDelivery(deliveryId: string): Promise<DeliveryDetailResponse> {
    return this.request(`/deliveries/${encodeURIComponent(deliveryId)}`);
  }

  listEditPackages(projectId: string): Promise<EditPackageDetailResponse[]> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/edit-packages`);
  }

  createEditPackage(
    projectId: string,
    body: EditPackageCreateRequest,
  ): Promise<AcceptedTaskResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/edit-packages`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("edit-package") },
      body: JSON.stringify(body),
    });
  }

  getEditPackage(editPackageId: string): Promise<EditPackageDetailResponse> {
    return this.request(`/edit-packages/${encodeURIComponent(editPackageId)}`);
  }

  listReleasePresets(): Promise<ReleasePresetsResponse> {
    return this.request("/release-presets");
  }

  listReleaseItems(projectId: string): Promise<ReleaseItemsResponse> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/releases`);
  }

  createReleaseItem(
    projectId: string,
    body: ReleaseItemCreateRequest,
  ): Promise<ReleaseItemSnapshot> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/releases`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("release-item") },
      body: JSON.stringify(body),
    });
  }

  getReleaseItem(releaseItemId: string): Promise<ReleaseItemSnapshot> {
    return this.request(`/releases/${encodeURIComponent(releaseItemId)}`);
  }

  updateReleaseItem(
    releaseItemId: string,
    body: ReleaseItemUpdateRequest,
  ): Promise<ReleaseItemSnapshot> {
    return this.request(`/releases/${encodeURIComponent(releaseItemId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  transitionReleaseApproval(
    releaseItemId: string,
    body: ReleaseApprovalRequest,
  ): Promise<ReleaseItemSnapshot> {
    return this.request(`/releases/${encodeURIComponent(releaseItemId)}/approval`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  transitionReleaseStatus(
    releaseItemId: string,
    body: ReleaseStatusRequest,
  ): Promise<ReleaseItemSnapshot> {
    return this.request(`/releases/${encodeURIComponent(releaseItemId)}/status`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  addReleaseMetric(
    releaseItemId: string,
    body: ReleaseMetricRequest,
  ): Promise<ReleaseItemSnapshot> {
    return this.request(`/releases/${encodeURIComponent(releaseItemId)}/metrics`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("release-metric") },
      body: JSON.stringify(body),
    });
  }

  createReleasePackage(
    releaseItemId: string,
    expectedReleaseItemVersion: number,
    includeZip: boolean,
  ): Promise<AcceptedTaskResponse> {
    return this.request(`/releases/${encodeURIComponent(releaseItemId)}/packages`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("release-package") },
      body: JSON.stringify({
        expected_release_item_version: expectedReleaseItemVersion,
        include_zip: includeZip,
      }),
    });
  }

  getReleasePackage(releasePackageId: string): Promise<ReleasePackageDetailResponse> {
    return this.request(`/release-packages/${encodeURIComponent(releasePackageId)}`);
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof LiveClipApiError ? error.message : "LiveClip 操作失败";
}
