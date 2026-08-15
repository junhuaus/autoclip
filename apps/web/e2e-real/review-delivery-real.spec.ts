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
  await expect(page.getByText("v001 状态已更新。")).toBeVisible();
  const downloadLink = page.getByRole("link", { name: "下载 ZIP" });
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

  const projectResponse = await page.request.get(`/api/v1/projects/${job.project_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(projectResponse.status()).toBe(200);
  const deliveredProject = await projectResponse.json();
  expect(deliveredProject.status).toBe("delivered");
  expect(deliveredProject.lifecycle).toBe("editorial_review");
  await page.screenshot({ path: testInfo.outputPath("delivered.png"), fullPage: true });
});
