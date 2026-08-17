import { HttpResponse, http } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { App } from "../src/App";
import { projectSearchPage } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

const projectId = "a".repeat(32);

function storageReport() {
  return {
    schema_version: "1",
    scanned_at: "2026-08-15T12:00:00Z",
    filesystem_capacity_bytes: 1_000_000,
    filesystem_free_bytes: 700_000,
    data_directory_bytes: 300_000,
    database_bytes: 20_000,
    migration_backup_bytes: 10_000,
    database_backup_bytes: 5_000,
    purge_quarantine_bytes: 0,
    purge_quarantine_file_count: 0,
    project_directory_bytes: 260_000,
    unknown_project_directory_bytes: 0,
    unknown_project_file_count: 0,
    other_bytes: 5_000,
    unsafe_entry_count: 0,
    projects: [{
      project_id: projectId,
      project_name: "已归档直播",
      lifecycle: "archived",
      actual_bytes: 260_000,
      actual_file_count: 4,
      tracked_asset_bytes: 250_000,
      stale_render_asset_bytes: 10_000,
      orphan_asset_bytes: 0,
      pending_asset_bytes: 0,
      untracked_bytes: 10_000,
      untracked_file_count: 1,
      missing_committed_asset_count: 0,
      unsafe_entry_count: 0,
      source_reference_bytes: 4_000_000,
    }],
    policy: {
      automatic_project_purge: false,
      source_media_deletion: false,
      safe_cleanup_committed_artifact_deletion: false,
      safe_cleanup_scope: "terminal_attempt_worktrees_and_completed_purge_quarantine",
      archive_retains_artifacts: true,
      destructive_project_purge_available: true,
      purge_requires_archived_project: true,
      purge_creates_database_backup: true,
    },
  } as const;
}

it("shows storage inventory and requires two exact confirmations before project purge", async () => {
  let purgeBody: Record<string, string> | null = null;
  server.use(
    http.get("/api/v1/projects/search", () => HttpResponse.json(projectSearchPage([]))),
    http.get("/api/v1/admin/storage", () => HttpResponse.json(storageReport())),
    http.get(`/api/v1/admin/storage/projects/${projectId}/purge-plan`, () =>
      HttpResponse.json({
        schema_version: "1",
        project_id: projectId,
        project_name: "已归档直播",
        lifecycle: "archived",
        management_version: 4,
        generated_bytes: 260_000,
        generated_file_count: 4,
        unsafe_entry_count: 0,
        source_filename: "source.ts",
        source_media_preserved: true,
        active_run_count: 0,
        active_task_count: 0,
        blockers: [],
        ready: true,
        snapshot_fingerprint: "b".repeat(64),
        confirmation_phrase: `PURGE ${projectId}`,
      })),
    http.post(`/api/v1/admin/storage/projects/${projectId}/purge`, async ({ request }) => {
      purgeBody = await request.json() as Record<string, string>;
      return HttpResponse.json({
        schema_version: "1",
        project_id: projectId,
        project_name: "已归档直播",
        purged_at: "2026-08-15T12:01:00Z",
        removed_generated_bytes: 260_000,
        removed_generated_file_count: 4,
        source_media_preserved: true,
        database_backup_filename: "liveclip-purge.sqlite3",
        database_backup_sha256: "c".repeat(64),
        filesystem_cleanup_pending: true,
      });
    }),
  );
  const user = userEvent.setup();
  renderWithClient(<App />);
  await screen.findByText("还没有项目");
  await user.click(screen.getByRole("button", { name: "存储管理" }));

  expect(await screen.findByRole("heading", { name: "存储与保留" })).toBeVisible();
  expect(screen.getByText("已归档直播")).toBeVisible();
  expect(screen.getByText(/源视频只是只读引用/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "准备永久清除" }));

  expect(await screen.findByRole("heading", { name: "永久清除“已归档直播”" })).toBeVisible();
  const purgeButton = screen.getByRole("button", { name: "永久清除项目" });
  expect(purgeButton).toBeDisabled();
  await user.type(screen.getByLabelText("输入完整项目名确认"), "已归档直播");
  await user.type(screen.getByLabelText(new RegExp(`再输入 PURGE ${projectId}`)), `PURGE ${projectId}`);
  expect(purgeButton).toBeEnabled();
  await user.click(purgeButton);

  expect(await screen.findByText(/数据库恢复点：liveclip-purge.sqlite3/)).toBeVisible();
  expect(screen.getByText(/等待安全清理重试/)).toBeVisible();
  await waitFor(() => expect(purgeBody).toEqual({
    snapshot_fingerprint: "b".repeat(64),
    project_name: "已归档直播",
    administrator_username: "local-admin",
    confirmation_phrase: `PURGE ${projectId}`,
  }));
});
