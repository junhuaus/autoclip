import { HttpResponse, http } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { App } from "../src/App";
import { projectSearchPage } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

it("shows login for a signed-out editor and enters the project dashboard", async () => {
  let signedIn = false;
  server.use(
    http.get("/api/v1/session", () => signedIn
      ? HttpResponse.json({
          schema_version: "1",
          user: { user_id: "admin-1", username: "admin", display_name: "管理员", system_role: "administrator" },
          credential_kind: "session",
          csrf_token: "csrf-test",
          expires_at: "2026-08-14T00:00:00Z",
        })
      : HttpResponse.json({ error: { schema_version: "1", code: "AUTHENTICATION_REQUIRED", message: "Authentication is required", retryable: false, resource_id: null, correlation_id: "auth-1", details: [] } }, { status: 401 })),
    http.post("/api/v1/auth/login", async ({ request }) => {
      const body = await request.json() as { username: string; password: string };
      if (body.username !== "admin" || body.password !== "administrator password") return HttpResponse.json({}, { status: 401 });
      signedIn = true;
      return HttpResponse.json({ schema_version: "1", user: { user_id: "admin-1", username: "admin", display_name: "管理员", system_role: "administrator" }, csrf_token: "csrf-test", expires_at: "2026-08-14T00:00:00Z" });
    }),
    http.get("/api/v1/projects/search", () => HttpResponse.json(projectSearchPage([]))),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);

  expect(await screen.findByRole("heading", { name: "登录 LiveClip" })).toBeVisible();
  await user.type(screen.getByLabelText("账号"), "admin");
  await user.type(screen.getByLabelText("密码"), "administrator password");
  await user.click(screen.getByRole("button", { name: "登录工作台" }));
  expect(await screen.findByRole("heading", { name: "我的项目" })).toBeVisible();
  expect(screen.getByRole("button", { name: "成员管理" })).toBeVisible();
});

it("lets an administrator create and disable an editor account", async () => {
  let users = [{ user_id: "admin-1", username: "admin", display_name: "管理员", system_role: "administrator", is_active: true, password_configured: true, created_at: "2026-08-13T00:00:00Z", updated_at: "2026-08-13T00:00:00Z", last_login_at: null }];
  server.use(
    http.post("/api/v1/admin/users", async ({ request }) => {
      const body = await request.json() as Record<string, string>;
      users = [...users, { user_id: "editor-1", username: body.username, display_name: body.display_name, system_role: "member", is_active: true, password_configured: true, created_at: "2026-08-13T00:00:00Z", updated_at: "2026-08-13T00:00:00Z", last_login_at: null }];
      return HttpResponse.json({ schema_version: "1", users }, { status: 201 });
    }),
    http.get("/api/v1/admin/users", () => HttpResponse.json({ schema_version: "1", users })),
    http.patch("/api/v1/admin/users/editor-1", async ({ request }) => {
      const body = await request.json() as { is_active?: boolean };
      users = users.map((item) => item.user_id === "editor-1" ? { ...item, is_active: body.is_active ?? item.is_active } : item);
      return HttpResponse.json({ schema_version: "1", users });
    }),
    http.get("/api/v1/projects/search", () => HttpResponse.json(projectSearchPage([]))),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);
  await screen.findByText("还没有项目");
  await user.click(screen.getByRole("button", { name: "成员管理" }));
  expect(await screen.findByRole("heading", { name: "成员与权限" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "＋ 新建成员" }));
  await user.type(screen.getByLabelText("姓名"), "林编辑");
  await user.type(screen.getByLabelText("登录账号"), "lin-editor");
  await user.type(screen.getByLabelText("初始密码"), "editor password 2026");
  await user.click(screen.getByRole("button", { name: "创建成员" }));
  expect(await screen.findByText("林编辑")).toBeVisible();
  const disableButtons = screen.getAllByRole("button", { name: "停用" });
  await user.click(disableButtons.at(-1)!);
  await waitFor(() => expect(screen.getByText("已停用")).toBeVisible());
});
