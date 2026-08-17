import { HttpResponse, http } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { App } from "../src/App";
import type { AdminProjectSnapshot } from "../src/types";
import { projectSearchPage } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

const disabledOwner = {
  user_id: "owner-disabled",
  username: "former-owner",
  display_name: "原负责人",
  role: "owner" as const,
  is_active: false,
};

const successor = {
  user_id: "successor-active",
  username: "new-owner",
  display_name: "接任编辑",
  role: "viewer" as const,
  is_active: true,
};

const project: AdminProjectSnapshot = {
  project_id: "private-project-1",
  name: "八月直播项目",
  source_filename: "8.15-1.ts",
  pipeline_status: "completed",
  current_run_id: "run-1",
  generation: 2,
  visibility: "private",
  lifecycle: "editorial_review",
  management_version: 1,
  assignee: null,
  priority: "high",
  due_at: null,
  updated_at: "2026-08-15T14:00:00Z",
  owner: disabledOwner,
  members: [disabledOwner, successor],
  administrative_context: true,
  allowed_governance_actions: ["view", "transfer_ownership"],
};

it("lets an administrator find a private project with a disabled owner and transfer it", async () => {
  let currentProject = project;
  let requestedTransfer: unknown = null;
  let transferCompleted = false;
  server.use(
    http.get("/api/v1/projects/search", () => HttpResponse.json(projectSearchPage([]))),
    http.get("/api/v1/admin/projects", () => HttpResponse.json({
      schema_version: "1",
      projects: [currentProject],
    })),
    http.get("/api/v1/admin/users", () => HttpResponse.json({
      schema_version: "1",
      users: [
        {
          user_id: "user-local-admin",
          username: "local-admin",
          display_name: "本机管理员",
          system_role: "administrator",
          is_active: true,
          password_configured: true,
          created_at: "2026-08-13T00:00:00Z",
          updated_at: "2026-08-13T00:00:00Z",
          last_login_at: null,
        },
        {
          user_id: successor.user_id,
          username: successor.username,
          display_name: successor.display_name,
          system_role: "member",
          is_active: true,
          password_configured: true,
          created_at: "2026-08-13T00:00:00Z",
          updated_at: "2026-08-13T00:00:00Z",
          last_login_at: null,
        },
      ],
    })),
    http.get("/api/v1/admin/audit-events", () => HttpResponse.json({
      schema_version: "1",
      events: transferCompleted ? [{
        event_id: "event-transfer",
        actor_username: "local-admin",
        action: "project.ownership_transferred_by_administrator",
        target_type: "project",
        target_id: project.project_id,
        project_id: project.project_id,
        before: { owner_user_id: disabledOwner.user_id },
        after: { owner_user_id: successor.user_id, administrative_context: true },
        correlation_id: "request-1",
        created_at: "2026-08-15T15:00:00Z",
      }] : [],
    })),
    http.post("/api/v1/admin/projects/:projectId/ownership-transfer", async ({ request }) => {
      requestedTransfer = await request.json();
      transferCompleted = true;
      const formerOwner = { ...disabledOwner, role: "editor" as const };
      const nextOwner = { ...successor, role: "owner" as const };
      currentProject = {
        ...currentProject,
        management_version: 2,
        owner: nextOwner,
        members: [nextOwner, formerOwner],
      };
      return HttpResponse.json({ schema_version: "1", project: currentProject });
    }),
  );

  const user = userEvent.setup();
  renderWithClient(<App />);
  await screen.findByText("还没有项目");
  await user.click(screen.getByRole("button", { name: "项目治理" }));

  expect(await screen.findByRole("heading", { name: "项目治理" })).toBeVisible();
  expect(screen.getByText("8.15-1.ts")).toBeVisible();
  expect(screen.getByText("原负责人")).toBeVisible();
  expect(screen.getByText("已停用")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "移交负责人" }));
  expect(screen.getByText(/不会把管理员加入项目/)).toBeVisible();
  const confirmButton = screen.getByRole("button", { name: "确认移交负责人" });
  expect(confirmButton).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("新负责人"), successor.user_id);
  await user.type(screen.getByLabelText("输入完整项目名确认"), project.name);
  await user.click(confirmButton);

  await waitFor(() => expect(requestedTransfer).toEqual({
    new_owner_user_id: successor.user_id,
  }));
  expect(await screen.findByText("接任编辑")).toBeVisible();
  expect(await screen.findByText("管理员移交项目负责人")).toBeVisible();
});
