import { expect, test } from "@playwright/test";

interface StatusPayload {
  status: string;
  safe_error_message?: string | null;
  error_code?: string | null;
}

async function waitForTerminal(
  fetchStatus: () => Promise<{ statusCode: number; body: StatusPayload }>,
  options: {
    success: string;
    failures: ReadonlySet<string>;
    timeoutMs?: number;
  },
): Promise<StatusPayload> {
  const { success, failures, timeoutMs = 120_000 } = options;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await fetchStatus();
    if (result.statusCode !== 200) {
      throw new Error(`status endpoint returned HTTP ${result.statusCode}`);
    }
    if (result.body.status === success) {
      return result.body;
    }
    if (failures.has(result.body.status)) {
      throw new Error(
        `resource entered ${result.body.status}: ${result.body.error_code ?? "UNKNOWN"} ${result.body.safe_error_message ?? ""}`,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`resource did not reach ${success} within ${timeoutMs}ms`);
}

test("drives the real API, leased Worker and FFmpeg through delivered", async ({ page }, testInfo) => {
  const inputPath = process.env.LIVECLIP_E2E_INPUT;
  const token = process.env.LIVECLIP_E2E_TOKEN;
  const password = process.env.LIVECLIP_E2E_PASSWORD;
  if (!inputPath || !token || !password) {
    throw new Error("isolated real E2E fixture environment is missing");
  }

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "登录 LiveClip" })).toBeVisible();
  await page.getByLabel("账号").fill("local-admin");
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录工作台" }).click();
  await expect(page.getByText("还没有项目")).toBeVisible();
  await expect(page.getByRole("heading", { name: "我的项目" })).toBeVisible();
  await expect(page.getByText(/Mock ASR/)).toHaveCount(0);
  await page.getByRole("button", { name: "＋ 新建项目" }).click();
  await expect(page.getByRole("button", { name: "创建并开始处理" })).toBeEnabled();

  await page.getByLabel("本地视频绝对路径").fill(inputPath);
  await page.getByLabel("高光数量").fill("1");
  await page.getByLabel("最短秒数").fill("8");
  await page.getByLabel("最长秒数").fill("12");
  const acceptedJob = page.waitForResponse(
    (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/jobs",
  );
  await page.getByRole("button", { name: "创建并开始处理" }).click();
  const jobResponse = await acceptedJob;
  expect(jobResponse.status()).toBe(202);
  const job = await jobResponse.json() as { project_id: string; run_id: string };
  expect(job.project_id).toMatch(/^[a-f0-9]{32}$/);
  expect(job.run_id).toMatch(/^[a-f0-9]{32}$/);
  await waitForTerminal(
    async () => {
      const response = await page.request.get(`/api/v1/runs/${job.run_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      return { statusCode: response.status(), body: await response.json() as StatusPayload };
    },
    { success: "completed", failures: new Set(["failed", "cancelled"]) },
  );

  await expect(page.getByRole("heading", { name: "处理进度" })).toBeVisible();
  await expect(page.getByLabel("总进度 100%")).toBeVisible();
  await expect(page.getByText("源视频绝对时间")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "转写" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "高光时刻" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "项目成员" })).toBeVisible();

  const firstCard = page.locator("article.clip-card").first();
  await expect(firstCard.getByRole("heading", { name: "高光语句" })).toBeVisible();
  const highlightSentence = firstCard.locator(".clip-highlight-sentence blockquote");
  await expect(highlightSentence).not.toBeEmpty();
  await expect(firstCard.getByRole("heading", { name: "编辑关键词" })).toBeVisible();
  await expect(firstCard.locator(".clip-captions")).toBeVisible();
  await expect(firstCard.locator(".clip-keywords")).toBeVisible();
  await expect(firstCard.locator(".clip-captions button").first()).toBeVisible();
  const cardMainBox = await firstCard.locator(":scope > .clip-card-main").boundingBox();
  const cardVideoBox = await firstCard.locator("video").boundingBox();
  const cardBodyBox = await firstCard.locator(".clip-card-body").boundingBox();
  const cardCaptionBox = await firstCard.locator(":scope > .clip-card-captions").boundingBox();
  expect(cardMainBox).not.toBeNull();
  expect(cardVideoBox).not.toBeNull();
  expect(cardBodyBox).not.toBeNull();
  expect(cardCaptionBox).not.toBeNull();
  expect((cardBodyBox as { x: number }).x).toBeGreaterThan((cardVideoBox as { x: number }).x);
  expect((cardCaptionBox as { y: number }).y).toBeGreaterThanOrEqual(
    (cardMainBox as { y: number; height: number }).y + (cardMainBox as { height: number }).height - 1,
  );
  const proxyVideo = page.locator("article.clip-card video").first();
  await expect(proxyVideo).toHaveAttribute("src", /\/api\/v1\/media\/.+signature=/);
  const proxyUrl = await proxyVideo.getAttribute("src");
  expect(proxyUrl).not.toBeNull();
  const proxyRange = await page.evaluate(async (url) => {
    const response = await fetch(url, { headers: { Range: "bytes=0-99" } });
    return {
      status: response.status,
      length: (await response.arrayBuffer()).byteLength,
      contentRange: response.headers.get("Content-Range"),
    };
  }, proxyUrl as string);
  expect(proxyRange.status).toBe(206);
  expect(proxyRange.length).toBe(100);
  expect(proxyRange.contentRange).toMatch(/^bytes 0-99\//);
  await expect(firstCard.getByRole("link", { name: "下载 MP4" })).toBeVisible();
  await expect(firstCard.getByRole("link", { name: "下载 SRT" })).toBeVisible();

  await firstCard.getByLabel("选择导出").check();
  const acceptedPackage = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/projects\/.+\/edit-packages$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: "生成所选剪辑交接包" }).click();
  const packageResponse = await acceptedPackage;
  expect(packageResponse.status()).toBe(202);
  const editPackage = await packageResponse.json() as { resource_id: string };
  await waitForTerminal(
    async () => {
      const response = await page.request.get(`/api/v1/edit-packages/${editPackage.resource_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await response.json() as { edit_package: StatusPayload };
      return { statusCode: response.status(), body: body.edit_package };
    },
    { success: "succeeded", failures: new Set(["failed"]) },
  );
  const handoffDownload = page.getByRole("link", { name: "下载剪辑交接 ZIP" });
  await expect(handoffDownload).toHaveAttribute(
    "href",
    /\/api\/v1\/edit-packages\/.+signature=/,
    { timeout: 8_000 },
  );
  const handoffUrl = await handoffDownload.getAttribute("href");
  const handoffArchive = await page.evaluate(async (url) => {
    const response = await fetch(url);
    const body = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      disposition: response.headers.get("Content-Disposition"),
      length: body.length,
      magic: Array.from(body.slice(0, 2)),
    };
  }, handoffUrl as string);
  expect(handoffArchive.status).toBe(200);
  expect(handoffArchive.disposition).toBe(
    'attachment; filename="liveclip-edit-package-v001.zip"',
  );
  expect(handoffArchive.length).toBeGreaterThan(1_000);
  expect(handoffArchive.magic).toEqual([0x50, 0x4b]);

  await page.getByRole("button", { name: "审核和编辑" }).first().click();
  const editor = page.locator("section.clip-editor");
  await expect(editor).toBeVisible();
  await editor.getByLabel("标题").fill("真实浏览器修订高光");
  await editor.getByLabel("文本").first().fill("真实浏览器逐 cue 修改字幕");
  await editor.getByRole("button", { name: "保存为新 revision" }).click();
  await expect(editor.getByText(/revision 2/)).toBeVisible();
  await expect(editor.getByText(/旧 revision 的 1 个渲染已失效/)).toBeVisible();
  await expect(editor.getByText("当前 revision 尚无可播放视频")).toBeVisible();

  await editor.getByRole("button", { name: "批准" }).click();
  await expect(editor.getByText("已批准")).toBeVisible();
  const acceptedRender = page.waitForResponse(
    (response) => response.request().method() === "POST" && /\/api\/v1\/clips\/.+\/render$/.test(new URL(response.url()).pathname),
  );
  await editor.getByRole("button", { name: "渲染最终视频" }).click();
  const renderResponse = await acceptedRender;
  expect(renderResponse.status()).toBe(202);
  const render = await renderResponse.json() as { resource_id: string };
  await waitForTerminal(
    async () => {
      const response = await page.request.get(`/api/v1/renders/${render.resource_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      return { statusCode: response.status(), body: await response.json() as StatusPayload };
    },
    { success: "succeeded", failures: new Set(["failed", "stale"]) },
  );
  await expect(editor.getByText("最终视频渲染状态已更新。")).toBeVisible();
  await expect(editor.getByText("当前 revision 2 · 最终视频")).toBeVisible();

  const createDelivery = page.getByRole("button", { name: "创建新交付版本" });
  await expect(createDelivery).toBeEnabled();
  const acceptedDelivery = page.waitForResponse(
    (response) => response.request().method() === "POST" && /\/api\/v1\/projects\/.+\/deliveries$/.test(new URL(response.url()).pathname),
  );
  await createDelivery.click();
  const deliveryResponse = await acceptedDelivery;
  expect(deliveryResponse.status()).toBe(202);
  const delivery = await deliveryResponse.json() as { resource_id: string };
  await waitForTerminal(
    async () => {
      const response = await page.request.get(`/api/v1/deliveries/${delivery.resource_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await response.json() as { delivery: StatusPayload };
      return { statusCode: response.status(), body: body.delivery };
    },
    { success: "succeeded", failures: new Set(["failed"]) },
  );
  const deliveryPanel = page.getByRole("region", { name: "交付包" });
  await expect(deliveryPanel.getByText("v001 状态已更新。")).toBeVisible();
  const downloadLink = deliveryPanel.getByRole("link", { name: "下载 ZIP" });
  await expect(downloadLink).toHaveAttribute("href", /\/api\/v1\/deliveries\/.+signature=/);
  const downloadUrl = await downloadLink.getAttribute("href");
  expect(downloadUrl).not.toBeNull();
  const archive = await page.evaluate(async (url) => {
    const response = await fetch(url);
    const body = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      disposition: response.headers.get("Content-Disposition"),
      length: body.length,
      magic: Array.from(body.slice(0, 2)),
    };
  }, downloadUrl as string);
  expect(archive.status).toBe(200);
  expect(archive.disposition).toBe('attachment; filename="liveclip-v001.zip"');
  expect(archive.length).toBeGreaterThan(1_000);
  expect(archive.magic).toEqual([0x50, 0x4b]);
  await expect(page.locator(".hero-status")).toContainText("技术状态 · 已交付");
  await expect(page.locator('.hero-status [data-status="editorial_review"]')).toHaveText(
    "编辑审核",
  );

  const releasePanel = page.getByRole("region", { name: "发布队列" });
  await releasePanel.getByRole("button", { name: "＋ 建立发布任务" }).click();
  const releaseCreateForm = releasePanel.locator(".release-create-form");
  await releaseCreateForm.getByLabel("高光时刻").selectOption({ index: 1 });
  await releaseCreateForm.getByLabel("目标平台").selectOption("douyin");
  await releaseCreateForm.getByLabel("发布账号").fill("真实 E2E 主账号");
  await releaseCreateForm.getByLabel("视频与字幕").selectOption("burned");
  const createdReleaseResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/projects\/.+\/releases$/.test(new URL(response.url()).pathname),
  );
  await releaseCreateForm.getByRole("button", { name: "建立发布任务" }).click();
  expect((await createdReleaseResponse).status()).toBe(201);

  const releaseCard = releasePanel.locator("article.release-card").first();
  await expect(releaseCard.getByText(/抖音 · 真实 E2E 主账号/)).toBeVisible();
  const checklistInputs = releaseCard.locator(".release-checklist input");
  expect(await checklistInputs.count()).toBe(9);
  for (let index = 0; index < 9; index += 1) {
    await checklistInputs.nth(index).check();
  }
  const savedReleaseResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      /\/api\/v1\/releases\/.+$/.test(new URL(response.url()).pathname),
  );
  await releaseCard.getByRole("button", { name: "保存发布设置" }).click();
  expect((await savedReleaseResponse).status()).toBe(200);

  const approvalReason = releaseCard.getByLabel("审核或状态说明");
  await approvalReason.fill("编辑已完成发布配置与合规检查");
  const submittedApprovalResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/releases\/.+\/approval$/.test(new URL(response.url()).pathname),
  );
  await releaseCard.getByRole("button", { name: "提交发布审核" }).click();
  expect((await submittedApprovalResponse).status()).toBe(200);
  await approvalReason.fill("审核人确认平台文案和权利清单");
  const approvedReleaseResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/releases\/.+\/approval$/.test(new URL(response.url()).pathname),
  );
  await releaseCard.getByRole("button", { name: "批准发布" }).click();
  expect((await approvedReleaseResponse).status()).toBe(200);

  const readyReleaseResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/releases\/.+\/status$/.test(new URL(response.url()).pathname),
  );
  await releaseCard.getByRole("button", { name: "标记可发布" }).click();
  expect((await readyReleaseResponse).status()).toBe(200);
  const acceptedReleasePackage = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/releases\/.+\/packages$/.test(new URL(response.url()).pathname),
  );
  await releaseCard.getByRole("button", { name: "生成平台包" }).click();
  const releasePackageResponse = await acceptedReleasePackage;
  expect(releasePackageResponse.status()).toBe(202);
  const releasePackage = await releasePackageResponse.json() as { resource_id: string };
  await waitForTerminal(
    async () => {
      const response = await page.request.get(
        `/api/v1/release-packages/${releasePackage.resource_id}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const body = await response.json() as { release_package: StatusPayload };
      return { statusCode: response.status(), body: body.release_package };
    },
    { success: "succeeded", failures: new Set(["failed"]) },
  );
  const releaseDownload = releaseCard.getByRole("link", { name: "下载平台 ZIP" });
  await expect(releaseDownload).toHaveAttribute(
    "href",
    /\/api\/v1\/release-packages\/.+signature=/,
    { timeout: 8_000 },
  );
  const releaseDownloadUrl = await releaseDownload.getAttribute("href");
  const releaseArchive = await page.evaluate(async (url) => {
    const response = await fetch(url);
    const body = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      disposition: response.headers.get("Content-Disposition"),
      length: body.length,
      magic: Array.from(body.slice(0, 2)),
    };
  }, releaseDownloadUrl as string);
  expect(releaseArchive.status).toBe(200);
  expect(releaseArchive.disposition).toMatch(
    /^attachment; filename="liveclip-release-douyin-[A-Za-z0-9_.-]+-[a-f0-9]{8}-v001\.zip"$/,
  );
  expect(releaseArchive.length).toBeGreaterThan(1_000);
  expect(releaseArchive.magic).toEqual([0x50, 0x4b]);

  const lifecyclePanel = page.getByRole("region", { name: "任务与生命周期" });
  for (const [target, reason] of [
    ["approval", "真实 E2E 进入项目终审"],
    ["ready_to_publish", "真实 E2E 发布材料已完成"],
  ] as const) {
    await lifecyclePanel.getByLabel("下一阶段").selectOption(target);
    await lifecyclePanel.getByLabel("操作说明").fill(reason);
    const lifecycleResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/api\/v1\/projects\/.+\/lifecycle$/.test(new URL(response.url()).pathname),
    );
    await lifecyclePanel.getByRole("button", { name: "确认推进" }).click();
    expect((await lifecycleResponse).status()).toBe(200);
  }
  await expect(page.locator('.hero-status [data-status="ready_to_publish"]')).toHaveText(
    "待发布",
  );
  const refreshedReleaseCard = releasePanel.locator("article.release-card").first();
  await refreshedReleaseCard.getByText("记录外部发布结果", { exact: true }).click();
  await refreshedReleaseCard.getByLabel("平台内容 ID").fill("douyin-e2e-001");
  await refreshedReleaseCard.getByLabel("结果说明").fill("真实浏览器记录外部发布证据");
  const publishedReleaseResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/releases\/.+\/status$/.test(new URL(response.url()).pathname),
  );
  await refreshedReleaseCard.getByRole("button", { name: "确认已在外部发布" }).click();
  expect((await publishedReleaseResponse).status()).toBe(200);
  await expect(refreshedReleaseCard.locator('[data-status="published"]')).toHaveText("已发布");

  await refreshedReleaseCard.getByText("记录发布效果", { exact: true }).click();
  await refreshedReleaseCard.getByLabel("播放").fill("1200");
  await refreshedReleaseCard.getByLabel("点赞").fill("88");
  const metricResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/releases\/.+\/metrics$/.test(new URL(response.url()).pathname),
  );
  await refreshedReleaseCard.getByRole("button", { name: "保存效果快照" }).click();
  expect((await metricResponse).status()).toBe(201);
  await expect(refreshedReleaseCard.getByRole("cell", { name: "1,200" })).toBeVisible();
  await expect(page.locator('.hero-status [data-status="published"]')).toHaveText("已发布");

  const projectResponse = await page.request.get(`/api/v1/projects/${job.project_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(projectResponse.status()).toBe(200);
  const deliveredProject = await projectResponse.json();
  expect(deliveredProject.status).toBe("delivered");
  expect(deliveredProject.lifecycle).toBe("published");
  await page.screenshot({ path: testInfo.outputPath("delivered.png"), fullPage: true });

  await page.getByRole("button", { name: "项目治理" }).click();
  await expect(page.getByRole("heading", { name: "项目治理" })).toBeVisible();
  await expect(page.getByText("普通“我的项目”仍只显示当前用户拥有或被分配的项目。")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "治理操作" })).toBeVisible();
  await expect(page.locator(".governance-table tbody tr")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "安全与治理审计" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("admin-governance.png"), fullPage: true });

  await page.getByRole("button", { name: "存储管理" }).click();
  await expect(page.getByRole("heading", { name: "存储与保留" })).toBeVisible();
  await expect(page.getByText("源视频只是只读引用，不在这里删除。")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "保留操作" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("admin-storage.png"), fullPage: true });
});
