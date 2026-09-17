import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CompletionWatch, saveConfirmedGoal } from "../src/CompletionWatch";
import { LiveClipApiClient, LiveClipApiError } from "../src/api";
import type { CompletionGoalResponse } from "../src/types";

const id = "a".repeat(32);
const response: CompletionGoalResponse = {
  goal: {
    intent_id: id, project_id: "project", run_id: "run", generation: 1,
    requester_user_id: "owner", actor_user_id: "owner",
    options: { schema_version: "1", target: "delivery", selection_policy: "manual", include_zip: true, preset_id: "mini_lesson_v1" },
    status: "waiting_work", version: 1, selection_submitted: false, delivery_id: null,
    outcome: null, blocking_code: null, safe_error_message: null,
    delivery_progress: {
      schema_version: "1", phase: "writing_zip", unit: "bytes", completed: 10, total: null,
      attempt_id: "b".repeat(32), business_advanced_at: "2030-01-01T00:00:00Z",
      worker_heartbeat_at: "2030-01-01T00:00:02Z", lease_fresh: true,
    },
  }, download_url: null,
};

beforeEach(() => sessionStorage.clear());
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it("reconnects from a separate confirmed reference using GET only", async () => {
  sessionStorage.setItem("liveclip.pending-completion", "pending-request-identity");
  saveConfirmedGoal(id);
  const api = new LiveClipApiClient();
  const get = vi.spyOn(api, "completionGoal").mockResolvedValue(response);
  const create = vi.spyOn(api, "createCompletionFromPreset");
  const first = render(<CompletionWatch api={api} />);
  expect(await screen.findByText(/总量待定/)).toBeInTheDocument();
  expect(screen.getByText(/心跳不是进度/)).toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  first.unmount();
  render(<CompletionWatch api={api} />);
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  expect(get).toHaveBeenLastCalledWith(id);
  expect(create).not.toHaveBeenCalled();
  expect(sessionStorage.getItem("liveclip.pending-completion")).toBe("pending-request-identity");
});

it("discards obsolete authorized responses after authentication changes", async () => {
  const oldApi = new LiveClipApiClient();
  const newApi = new LiveClipApiClient("other-test-identity");
  let finish!: (value: CompletionGoalResponse) => void;
  vi.spyOn(oldApi, "completionGoal").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  vi.spyOn(newApi, "completionGoal").mockRejectedValue(new LiveClipApiError("denied", { status: 403, code: "FORBIDDEN", correlationId: null }));
  const view = render(<CompletionWatch api={oldApi} intentId={id} />);
  view.rerender(<CompletionWatch api={newApi} intentId={id} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("目标不可访问");
  await act(async () => { finish(response); });
  expect(screen.queryByText(/project/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it.each(["waiting_selection", "succeeded"] as const)("never offers a package for %s without delivered outcome", async (status) => {
  const api = new LiveClipApiClient();
  vi.spyOn(api, "completionGoal").mockResolvedValue({
    ...response, goal: { ...response.goal, status, outcome: status === "succeeded" ? "no_selected_clips" : null },
    download_url: "/must-not-be-shown",
  });
  render(<CompletionWatch api={api} intentId={id} />);
  await screen.findByText(/项目：project/);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it.each([401, 403, 404])("clears previously visible protected content on HTTP %s", async (status) => {
  vi.useFakeTimers();
  const api = new LiveClipApiClient();
  const get = vi.spyOn(api, "completionGoal")
    .mockResolvedValueOnce(response)
    .mockRejectedValue(new LiveClipApiError("denied", { status, code: "DENIED", correlationId: null }));
  render(<CompletionWatch api={api} intentId={id} />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText(/项目：project/)).toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByRole("alert")).toHaveTextContent("目标不可访问");
  expect(screen.queryByText(/项目：project/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(get).toHaveBeenCalledTimes(2);
});

it("recovers transient GET failure and displays only the API bound delivered link", async () => {
  vi.useFakeTimers();
  const api = new LiveClipApiClient();
  const get = vi.spyOn(api, "completionGoal")
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ ...response, goal: { ...response.goal, status: "succeeded", outcome: "delivered", delivery_id: "delivery" }, download_url: "/api/bound-archive" });
  render(<CompletionWatch api={api} intentId={id} />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole("alert")).toHaveTextContent("正在重新连接");
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByRole("link", { name: "下载交付 ZIP" })).toHaveAttribute("href", "/api/bound-archive");
  expect(get).toHaveBeenCalledTimes(2);
});
