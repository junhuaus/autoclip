import { expect, test as base } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import { setTimeout } from "node:timers/promises";

const test = base.extend<{ denialContext: import("@playwright/test").BrowserContext }>({
  denialContext: async ({ browser }, use) => {
    // Never inherit the production form's authenticated storage or cookies.
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    try {
      await use(context);
    } finally {
      await context.close();
    }
  },
});

// API authorization and renewable signed URLs must not be retained in browser traces.
test.use({ trace: "off", screenshot: "off", video: "off" });

async function writeEvidence(path: string, value: object): Promise<void> {
  const temporary = `${path}.tmp`;
  await writeFile(temporary, JSON.stringify(value), { flag: "wx", mode: 0o600 });
  await rename(temporary, path);
}

async function readWaitingMarker(path: string): Promise<Record<string, unknown>> {
  const deadline = Date.now() + 150_000;
  while (Date.now() < deadline) {
    try {
      return JSON.parse(await readFile(path, "utf8")) as Record<string, unknown>;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    await setTimeout(100);
  }
  throw new Error("trusted completion waiting marker did not arrive");
}

type Goal = {
  intent_id: string;
  project_id: string;
  run_id: string;
  generation: number;
  status: string;
  version: number;
  delivery_id: string | null;
  outcome: string | null;
  delivery_progress?: Record<string, unknown>;
};

type GoalResponse = { goal: Goal; download_url: string | null };

async function apiFetch<T>(
  page: import("@playwright/test").Page,
  path: string,
  token: string,
  init: { method?: string; body?: unknown; idempotencyKey?: string; sessionCsrf?: boolean } = {},
): Promise<{ status: number; headers: Record<string, string>; body: T }> {
  return page.evaluate(async ({ path, token, init }) => {
    const headers: Record<string, string> = init.sessionCsrf ? {} : { Authorization: `Bearer ${token}` };
    if (init.sessionCsrf && !["GET", "HEAD", "OPTIONS"].includes((init.method ?? "GET").toUpperCase())) {
      // Keep session discovery and its token entirely inside browser memory.
      try {
        const response = await fetch("/api/v1/session", { credentials: "same-origin" });
        if (!response.ok) throw new Error();
        const session = await response.json();
        if (session?.credential_kind !== "session"
          || typeof session.csrf_token !== "string" || !session.csrf_token.trim()) {
          throw new Error();
        }
        headers["X-CSRF-Token"] = session.csrf_token;
      } catch {
        throw new Error("B2 session CSRF discovery failed");
      }
    }
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
    const response = await fetch(path, {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
    return {
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: await response.json() as T,
    };
  }, { path, token, init });
}

type GoalIdentity = Pick<Goal, "intent_id" | "project_id" | "run_id" | "generation">;
type GoalAuth = { mode: "session" } | { mode: "bearer"; token: string };

async function readGoal(
  context: import("@playwright/test").BrowserContext,
  location: string,
  auth: GoalAuth,
  identity: GoalIdentity,
  timeout = 10_000,
): Promise<GoalResponse> {
  const response = await context.request.get(location, {
    headers: auth.mode === "bearer" ? { Authorization: `Bearer ${auth.token}` } : {},
    maxRedirects: 0,
    timeout,
  }).catch(() => {
    throw new Error("completion goal request failed");
  });
  try {
    expect(response.status()).toBe(200);
    const body: GoalResponse = await response.json().catch(() => {
      throw new Error("completion goal returned invalid JSON");
    });
    for (const [field, value] of Object.entries(identity)) {
      expect(body.goal[field as keyof GoalIdentity]).toBe(value);
    }
    expect(Number.isSafeInteger(body.goal.version)).toBe(true);
    expect(body.goal.version).toBeGreaterThanOrEqual(1);
    expect(body.goal.delivery_id === null || /^[a-f0-9]{32}$/.test(body.goal.delivery_id)).toBe(true);
    expect(body.download_url === null || typeof body.download_url === "string").toBe(true);
    expect(body.goal.outcome === null || ["processed", "delivered", "no_eligible_clips",
      "no_selected_clips", "cancelled"].includes(body.goal.outcome)).toBe(true);
    expect(["queued", "waiting_work", "waiting_selection", "succeeded"]).toContain(body.goal.status);
    return body;
  } finally {
    await response.dispose();
  }
}

async function waitForGoal(
  context: import("@playwright/test").BrowserContext,
  location: string,
  auth: GoalAuth,
  identity: GoalIdentity,
  wanted: string,
): Promise<GoalResponse> {
  const deadline = Date.now() + 150_000;
  while (Date.now() < deadline) {
    const body = await readGoal(context, location, auth, identity, Math.max(1, Math.min(10_000, deadline - Date.now())));
    if (body.goal.status === wanted) return body;
    expect(body.goal.status).not.toBe("succeeded");
    await setTimeout(Math.min(500, Math.max(0, deadline - Date.now())));
  }
  throw new Error(`completion goal did not reach ${wanted}`);
}

test("browser disconnect preserves a manual completion and its one signed ZIP", async ({ browser, denialContext }) => {
  const inputPath = process.env.LIVECLIP_E2E_INPUT;
  const token = process.env.LIVECLIP_E2E_TOKEN;
  const closedMarker = process.env.LIVECLIP_E2E_OBSERVER_CLOSED_MARKER;
  const waitMarker = process.env.LIVECLIP_E2E_WAIT_MARKER;
  const downloadReceipt = process.env.LIVECLIP_E2E_DOWNLOAD_RECEIPT;
  if (!inputPath || !token || !closedMarker || !waitMarker || !downloadReceipt) {
    throw new Error("isolated completion fixture environment is missing");
  }

  const context = await browser.newContext();
  const observer = await context.newPage();
  await observer.goto("/");
  const canonical = process.env.LIVECLIP_E2E_SCENARIO === "b2";
  if (canonical) test.setTimeout(300_000);
  const createPath = canonical ? "/api/v1/completion-goals/from-preset" : "/api/v1/completion-goals";
  const requestBody = canonical ? {
    input_path: inputPath, preset_id: "short_highlight_v1", selection_policy: "manual",
  } : {
    job: {
      input_path: inputPath,
      top_n: 1,
      minimum_clip_seconds: 8,
      semantic_target_clip_seconds: 10,
      maximum_clip_seconds: 12,
    },
    options: { target: "delivery", selection_policy: "manual", include_zip: true },
  };
  let key = "completion-browser-manual-v1";
  let created: Awaited<ReturnType<typeof apiFetch<GoalResponse>>>;
  let createProof: object | undefined;
  if (canonical) {
    const password = process.env.LIVECLIP_E2E_PASSWORD;
    if (!password) throw new Error("B2 login fixture is missing");
    await observer.getByLabel("账号").fill("local-admin");
    await observer.getByLabel("密码").fill(password);
    await observer.getByRole("button", { name: "登录工作台" }).click();
    await observer.getByRole("button", { name: "＋ 新建项目", exact: true }).click();
    const dialog = observer.getByRole("dialog");
    await dialog.getByLabel("方案视频路径").fill(inputPath);
    await dialog.getByLabel("选片方式").selectOption("manual");
    const responsePromise = observer.waitForResponse((response) =>
      response.url().endsWith(createPath) && response.request().method() === "POST");
    await dialog.getByRole("button", { name: "按方案创建", exact: true }).click();
    const response = await responsePromise;
    key = response.request().headers()["idempotency-key"];
    expect(key).toMatch(/^liveclip-web-completion-/);
    expect(response.request().postDataJSON()).toEqual(requestBody);
    created = { status: response.status(), headers: response.headers(), body: await response.json() as GoalResponse };
    await expect.poll(() => observer.evaluate(() => sessionStorage.getItem("liveclip.confirmed-completion")))
      .toBe(created.body.goal.intent_id);
    await expect.poll(() => observer.evaluate(() => sessionStorage.getItem("liveclip.pending-completion")))
      .toBeNull();
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(observer.getByRole("region", { name: "处理目标观察" })).toContainText(created.body.goal.intent_id);
    await expect(observer.locator(".project-card").filter({ hasText: inputPath.split("/").at(-1) })).toHaveCount(1);
    createProof = { intent_id: created.body.goal.intent_id, project_id: created.body.goal.project_id,
      run_id: created.body.goal.run_id, generation: created.body.goal.generation,
      request_key: key, request_body: requestBody, confirmed_before_reload: true,
      pending_cleared: true, modal_closed: true, observed_unix_ms: Date.now() };
  } else {
    created = await apiFetch<GoalResponse>(observer, createPath, token, {
      method: "POST", body: requestBody, idempotencyKey: key,
    });
  }
  expect(created.status).toBe(202);
  expect(created.headers["retry-after"]).toBe("1");
  const location = created.headers.location;
  expect(location).toBe(`/api/v1/completion-goals/${created.body.goal.intent_id}`);
  expect(created.body.download_url).toBeNull();

  // Closing the sole observer must not send a cancellation command or stop the independent Worker.
  if (canonical) {
    // Unmount every observer while retaining the production tab's session identity.
    await observer.goto("about:blank");
  } else {
    await observer.close();
    expect(observer.isClosed()).toBe(true);
    expect(context.pages()).toHaveLength(0);
  }
  const closedUnixMs = Date.now();
  const identity = {
    project_id: created.body.goal.project_id,
    run_id: created.body.goal.run_id,
    intent_id: created.body.goal.intent_id,
    generation: created.body.goal.generation,
  };
  await writeEvidence(closedMarker, {
    schema_version: "liveclip.completion-observer-closed.v1",
    ...identity,
    closed_unix_ms: closedUnixMs,
  });
  // Stay disconnected: only Node filesystem reads and a timer await the SQLite watcher.
  const marker = await readWaitingMarker(waitMarker);
  expect(Object.keys(marker).sort()).toEqual([
    "schema_version", "project_id", "run_id", "intent_id", "generation",
    "completion_task_id", "deferred_attempt_count", "observed_unix_ms",
    "observer_closed_unix_ms",
  ].sort());
  expect(marker.schema_version).toBe("liveclip.completion-waiting.v1");
  for (const [field, value] of Object.entries(identity)) expect(marker[field]).toBe(value);
  expect(marker.completion_task_id).toMatch(/^[a-f0-9]{32}$/);
  expect(Number.isSafeInteger(marker.deferred_attempt_count)).toBe(true);
  expect(marker.deferred_attempt_count).toBeGreaterThanOrEqual(1);
  expect(marker.observer_closed_unix_ms).toBe(closedUnixMs);
  expect(Number.isSafeInteger(marker.observed_unix_ms)).toBe(true);
  expect(marker.observed_unix_ms).toBeGreaterThanOrEqual(closedUnixMs);
  expect(marker.observed_unix_ms).toBeLessThanOrEqual(Date.now());
  const reconnected = canonical ? observer : await context.newPage();
  await reconnected.goto("/");
  const unauthenticated = await denialContext.newPage();
  await unauthenticated.goto("/");
  expect((await denialContext.cookies()).length).toBe(0);
  const denied = await apiFetch<Record<string, unknown>>(unauthenticated, location, "invalid-fixture-token");
  expect(denied.status).toBe(401);
  expect(JSON.stringify(denied.body)).not.toContain(identity.intent_id);
  expect(denied.body.download_url).toBeUndefined();
  const auth: GoalAuth = canonical ? { mode: "session" } : { mode: "bearer", token };
  const waiting = await waitForGoal(context, location, auth, identity, "waiting_selection");
  expect(waiting.download_url).toBeNull();
  expect(waiting.goal.delivery_id).toBeNull();

  const replay = await apiFetch<GoalResponse>(reconnected, createPath, token, {
    method: "POST", body: requestBody, idempotencyKey: key, sessionCsrf: canonical,
  });
  expect(replay.status).toBe(202);
  expect(replay.body.goal.intent_id).toBe(created.body.goal.intent_id);
  expect(replay.body.goal.project_id).toBe(created.body.goal.project_id);
  expect(replay.body.goal.run_id).toBe(created.body.goal.run_id);
  expect(replay.body.goal.generation).toBe(created.body.goal.generation);
  expect(replay.body.goal.status).toBe("waiting_selection");
  expect(replay.body.goal.delivery_id).toBeNull();
  expect(replay.body.download_url).toBeNull();

  const clips = await apiFetch<Array<{ clip: { clip_id: string; edit_plan_revision: number } }>>(
    reconnected, `/api/v1/projects/${waiting.goal.project_id}/clips`, token, { sessionCsrf: canonical },
  );
  expect(clips.status).toBe(200);
  expect(clips.body).toHaveLength(1);
  const selected = clips.body[0].clip;
  const submitted = await apiFetch<GoalResponse>(reconnected, `${location}/selection`, token, {
    method: "POST",
    sessionCsrf: canonical,
    body: {
      expected_version: waiting.goal.version,
      selected: [{ clip_id: selected.clip_id, expected_revision: selected.edit_plan_revision }],
    },
  });
  expect(submitted.status).toBe(200);

  if (canonical) {
    const pauseRoot = process.env.LIVECLIP_E2E_B2_PAUSES;
    if (!pauseRoot) throw new Error("B2 packaging fixture is missing");
    const panel = reconnected.getByRole("region", { name: "处理目标观察" });
    const observations: object[] = [];
    for (const count of [1, 2]) {
      const pause = await readWaitingMarker(`${pauseRoot}/pause-${count}.json`);
      expect(pause.project_id).toBe(identity.project_id);
      expect(pause.run_id).toBe(identity.run_id);
      expect(pause.completed).toBe(count);
      expect(pause.total).toBe(4);
      await expect(panel).toContainText(identity.intent_id, { timeout: 8000 });
      await expect(panel).toContainText(`当前阶段工作量：${count} / 4 files`, { timeout: 8000 });
      await expect(panel).toContainText("writing_metadata");
      await expect(panel.getByRole("link", { name: "下载交付 ZIP" })).toHaveCount(0);
      if (count === 1) {
        await reconnected.reload();
        await expect(panel).toContainText(identity.intent_id, { timeout: 8000 });
        await expect(panel).toContainText("当前阶段工作量：1 / 4 files", { timeout: 8000 });
      } else {
        await reconnected.goto("about:blank");
        await reconnected.goto("/");
        await expect(panel).toContainText(identity.intent_id, { timeout: 8000 });
        await expect(panel).toContainText("当前阶段工作量：2 / 4 files", { timeout: 8000 });
      }
      await expect(panel.getByRole("link", { name: "下载交付 ZIP" })).toHaveCount(0);
      const read = await readGoal(context, location, auth, identity);
      expect(read.goal.delivery_progress?.completed).toBe(count);
      expect(read.goal.delivery_progress?.attempt_id).toBe(pause.attempt_id);
      observations.push({ intent_id: identity.intent_id, ...pause,
        observed_unix_ms: Date.now(), reloaded: count === 1, navigated: count === 2,
        progress: read.goal.delivery_progress });
      await writeEvidence(`${pauseRoot}/release-${count}.json`, { attempt_id: pause.attempt_id, completed: count });
    }
    await writeEvidence(`${pauseRoot}/browser.json`, { create: createProof, observations });
  }

  const completed = await waitForGoal(context, location, auth, identity, "succeeded");
  expect(completed.goal.outcome).toBe("delivered");
  expect(completed.goal.delivery_id).toMatch(/^[a-f0-9]{32}$/);
  expect(completed.download_url).toBeTruthy();
  let downloadUrl = completed.download_url as string;
  if (canonical) {
    const panel = reconnected.getByRole("region", { name: "处理目标观察", exact: true });
    await expect(panel).toBeVisible({ timeout: 8000 });
    await expect(panel.getByText(`目标：${identity.intent_id}`, { exact: true })).toBeVisible({ timeout: 8000 });
    await expect(panel.getByText(`项目：${identity.project_id}`, { exact: true })).toBeVisible();
    await expect(panel).toContainText("状态：succeeded · 结果：delivered", { timeout: 8000 });
    const link = panel.getByRole("link", { name: "下载交付 ZIP", exact: true });
    await expect(link).toBeVisible({ timeout: 8000 });
    await expect(reconnected.getByRole("button", { name: "登录工作台", exact: true })).toHaveCount(0);
    await expect(reconnected.getByLabel("账号", { exact: true })).toHaveCount(0);
    const href = await link.getAttribute("href");
    expect(typeof href === "string" && href.length > 0).toBe(true);
    const origin = new URL(reconnected.url()).origin;
    const uiUrl = new URL(href as string, origin);
    const goalUrl = new URL(downloadUrl, origin);
    // Renewable signatures may differ; compare the authorized Delivery identity only.
    for (const url of [uiUrl, goalUrl]) {
      expect(url.origin).toBe(origin);
      expect(url.pathname).toBe(`/api/v1/deliveries/${completed.goal.delivery_id}/download`);
      expect(url.username === "" && url.password === "" && url.hash === "").toBe(true);
    }
    downloadUrl = uiUrl.href;
  }
  expect((await denialContext.cookies()).length).toBe(0);
  const deniedArchive = await unauthenticated.evaluate(async (url) => {
    const response = await fetch(url, {
      headers: { Authorization: "Bearer invalid-fixture-token" },
    });
    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      type: response.headers.get("Content-Type"),
      disposition: response.headers.get("Content-Disposition"),
      hasZipMagic: bytes[0] === 0x50 && bytes[1] === 0x4b,
    };
  }, downloadUrl);
  expect(deniedArchive.status).toBe(401);
  expect(deniedArchive.type).toBe("application/json");
  expect(deniedArchive.disposition).toBeNull();
  expect(deniedArchive.hasZipMagic).toBe(false);
  const archiveResponse = await context.request.get(downloadUrl, {
    headers: auth.mode === "bearer" ? { Authorization: `Bearer ${auth.token}` } : {},
    maxRedirects: 0,
    timeout: 30_000,
  }).catch(() => {
    // Do not expose renewable signed URLs or authorization in request diagnostics.
    throw new Error("authorized ZIP request failed");
  });
  expect(archiveResponse.status()).toBe(200);
  const bytes = await archiveResponse.body();
  const archive = {
    status: archiveResponse.status(),
    type: archiveResponse.headers()["content-type"],
    disposition: archiveResponse.headers()["content-disposition"],
    length: bytes.length,
    magic: Array.from(bytes.subarray(0, 2)),
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
  await archiveResponse.dispose();
  expect(archive.status).toBe(200);
  expect(archive.type).toBe("application/zip");
  expect(archive.disposition).toBe('attachment; filename="liveclip-v001.zip"');
  expect(archive.length).toBeGreaterThan(1_000);
  expect(archive.magic).toEqual([0x50, 0x4b]);
  expect(archive.sha256).toMatch(/^[a-f0-9]{64}$/);
  await writeEvidence(downloadReceipt, {
    schema_version: "liveclip.completion-browser-download.v1",
    project_id: identity.project_id,
    run_id: identity.run_id,
    intent_id: identity.intent_id,
    delivery_id: completed.goal.delivery_id,
    observer_closed_unix_ms: closedUnixMs,
    waiting_observed_unix_ms: marker.observed_unix_ms,
    response_status: archive.status,
    content_type: archive.type,
    content_disposition: archive.disposition,
    size_bytes: archive.length,
    sha256: archive.sha256,
  });

  const finalReplay = await apiFetch<GoalResponse>(reconnected, createPath, token, {
    method: "POST", body: requestBody, idempotencyKey: key, sessionCsrf: canonical,
  });
  const finalRead = await readGoal(context, location, auth, identity);
  expect(finalReplay.body.goal.delivery_id).toBe(completed.goal.delivery_id);
  expect(finalRead.goal.delivery_id).toBe(completed.goal.delivery_id);
  expect(finalReplay.status).toBe(202);
  for (const [field, value] of Object.entries(identity)) {
    expect(finalReplay.body.goal[field as keyof GoalIdentity]).toBe(value);
  }
  expect(finalReplay.body.download_url).toBeTruthy();
  expect(finalRead.download_url).toBeTruthy();
  await context.close();
});
