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
  if (!inputPath || !token) {
    throw new Error("isolated real E2E fixture environment is missing");
  }

  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("AUTHENTICATION_REQUIRED");
  await page.getByLabel("本机 API Bearer token（可选）").fill(token);
  await page.getByRole("button", { name: "应用" }).click();
  await expect(page.getByText("还没有项目")).toBeVisible();

  await page.getByLabel("本地视频绝对路径").fill(inputPath);
  await page.getByLabel("候选数量").fill("1");
  await page.getByLabel("最短秒数").fill("8");
  await page.getByLabel("最长秒数").fill("12");
  const acceptedJob = page.waitForResponse(
    (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/jobs",
  );
  await page.getByRole("button", { name: "创建项目并启动处理" }).click();
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
  const transcript = page.getByRole("region", { name: "转写" });
  await expect(transcript).toBeVisible();
  await expect(transcript.getByText("今天我们聊三个能立刻改善直播表达的方法。")).toBeVisible();
  await expect(transcript.locator("ol.transcript-list > li")).toHaveCount(4);
  await expect(page.getByRole("heading", { name: "高光候选" })).toBeVisible();

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
  await expect(page.locator('.hero-status [data-status="delivered"]')).toHaveText("已交付");

  const projectResponse = await page.request.get(`/api/v1/projects/${job.project_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(projectResponse.status()).toBe(200);
  expect((await projectResponse.json()).status).toBe("delivered");
  await page.screenshot({ path: testInfo.outputPath("delivered.png"), fullPage: true });
});
