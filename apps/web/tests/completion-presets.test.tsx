import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { CompletionCreate } from "../src/CompletionCreate";
import { App } from "../src/App";
import { LiveClipApiClient } from "../src/api";
import type { CompletionGoalResponse, CompletionPresetsResponse } from "../src/types";
import { renderWithClient } from "./test-utils";

const summaries: CompletionPresetsResponse = {
  schema_version: "1",
  presets: [
    { schema_version: "1", preset_id: "short_highlight_v1", display_name_zh: "短高光", clip_profile: "short_highlight", minimum_clip_seconds: 45, target_clip_seconds: 60, maximum_clip_seconds: 90, default_selection_policy: "default", acceptance_status: "experimental" },
    { schema_version: "1", preset_id: "mini_lesson_v1", display_name_zh: "完整小课", clip_profile: "mini_lesson", minimum_clip_seconds: 90, target_clip_seconds: 180, maximum_clip_seconds: 300, default_selection_policy: "default", acceptance_status: "experimental" },
  ],
};
const accepted: CompletionGoalResponse = {
  goal: { intent_id: "saved-goal", project_id: "saved-project", run_id: "saved-run", generation: 1, requester_user_id: "user", actor_user_id: "user", options: { schema_version: "1", target: "delivery", selection_policy: "default", include_zip: true, preset_id: "short_highlight_v1" }, status: "queued", version: 1, selection_submitted: false, delivery_id: null, outcome: null, blocking_code: null, safe_error_message: null, delivery_progress: null },
  download_url: null,
};

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function setup() {
  const api = new LiveClipApiClient();
  vi.spyOn(api, "completionPresets").mockResolvedValue(summaries);
  const create = vi.spyOn(api, "createCompletionFromPreset");
  return { api, create, user: userEvent.setup() };
}

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("方案视频路径"), "/synthetic/video.mp4");
}
async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "按方案创建" }));
}

describe("preset completion creation", () => {
  it("preserves B's recovery identity when unmounted A succeeds late", async () => {
    const { api, create, user } = setup();
    let finishA!: (response: CompletionGoalResponse) => void;
    let loseB!: (error: Error) => void;
    create.mockImplementationOnce(() => new Promise((resolve) => { finishA = resolve; }));
    create.mockImplementationOnce(() => new Promise((_, reject) => { loseB = reject; }));
    const first = render(<CompletionCreate api={api} />);
    await fill(user);
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    first.unmount();

    const second = render(<CompletionCreate api={api} />);
    await fill(user);
    await user.click(screen.getByLabelText(/完整小课 · 实验性/));
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    const identityB = sessionStorage.getItem("liveclip.pending-completion");
    const keyB = create.mock.calls[1][1];
    expect(keyB).not.toBe(create.mock.calls[0][1]);
    await act(async () => { finishA(accepted); });
    expect(sessionStorage.getItem("liveclip.pending-completion")).toBe(identityB);
    expect(sessionStorage.getItem("liveclip.confirmed-completion")).toBeNull();
    // B committed on the server, but its response never reached this dialog.
    await act(async () => { loseB(new TypeError("response lost after commit")); });
    await screen.findByRole("alert");
    second.unmount();

    create.mockResolvedValue(accepted);
    render(<CompletionCreate api={api} />);
    await fill(user);
    await user.click(screen.getByLabelText(/完整小课 · 实验性/));
    await submit(user);
    await screen.findByText("当前状态：queued");
    expect(create.mock.calls[2]).toEqual(create.mock.calls[1]);
    expect(create.mock.calls[2][1]).toBe(keyB);
    expect(sessionStorage.getItem("liveclip.pending-completion")).toBeNull();
  });

  it("keeps the App dialog mounted until its preset request settles", async () => {
    const user = userEvent.setup();
    const confirmed = { ...accepted, goal: { ...accepted.goal, intent_id: "c".repeat(32) } };
    vi.spyOn(LiveClipApiClient.prototype, "completionPresets").mockResolvedValue(summaries);
    vi.spyOn(LiveClipApiClient.prototype, "completionGoal").mockResolvedValue(confirmed);
    const search = vi.spyOn(LiveClipApiClient.prototype, "searchProjects");
    let finish!: (response: CompletionGoalResponse) => void;
    const create = vi.spyOn(LiveClipApiClient.prototype, "createCompletionFromPreset")
      .mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    renderWithClient(<App />);
    await user.click(await screen.findByRole("button", { name: "＋ 新建项目" }));
    await fill(user);
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    const dialog = screen.getByRole("dialog");
    const cancel = within(dialog).getByRole("button", { name: "取消" });
    expect(cancel).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "创建并开始处理" })).toBeDisabled();
    await user.click(cancel);
    fireEvent.mouseDown(dialog.parentElement!);
    expect(screen.getByRole("dialog")).toBe(dialog);
    const searchesBeforeCreate = search.mock.calls.length;
    await act(async () => { finish(confirmed); });
    await waitFor(() => expect(cancel).toBeEnabled());
    await waitFor(() => expect(search.mock.calls.length).toBeGreaterThan(searchesBeforeCreate));
    await user.click(cancel);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "处理目标观察" })).toHaveTextContent("项目：saved-project");
  });

  it("renders server summaries, binds manual selection, and reports saved waiting state", async () => {
    const { api, create, user } = setup();
    create.mockResolvedValue({ ...accepted, goal: { ...accepted.goal, status: "waiting_selection" } });
    render(<CompletionCreate api={api} />);
    await fill(user);
    expect(screen.getByLabelText(/短高光 · 实验性/)).toBeChecked();
    await user.click(screen.getByLabelText(/完整小课 · 实验性/));
    await user.selectOptions(screen.getByLabelText("选片方式"), "manual");
    await submit(user);
    await screen.findByText("处理目标已保存：saved-goal");
    expect(create).toHaveBeenCalledWith({ input_path: "/synthetic/video.mp4", preset_id: "mini_lesson_v1", selection_policy: "manual" }, expect.any(String));
    expect(screen.getByText("项目：saved-project")).toBeInTheDocument();
    expect(screen.getByText("当前状态：waiting_selection")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(sessionStorage.getItem("liveclip.pending-completion")).toBeNull();
    expect(sessionStorage.getItem("liveclip.confirmed-completion")).toBe("saved-goal");
  });

  it("reuses the accepted-but-lost identity after retry and reload without saving the path", async () => {
    const { api, create, user } = setup();
    create.mockRejectedValue(new TypeError("lost response"));
    const view = render(<CompletionCreate api={api} />);
    await fill(user);
    await submit(user);
    await screen.findByRole("alert");
    const key = create.mock.calls[0][1];
    const saved = JSON.parse(sessionStorage.getItem("liveclip.pending-completion")!);
    expect(Object.keys(saved).sort()).toEqual(["hash", "key"]);
    expect(saved.hash).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(saved)).not.toContain("synthetic");
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(create.mock.calls[1][1]).toBe(key);
    view.unmount();
    render(<CompletionCreate api={api} />);
    await fill(user);
    create.mockResolvedValue(accepted);
    await submit(user);
    await screen.findByText("当前状态：queued");
    expect(create.mock.calls[2][1]).toBe(key);
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(4));
    expect(create.mock.calls[3][1]).not.toBe(key);
  });

  it.each(["source", "profile", "selection"])("invalidates identity after %s changes away and back", async (field) => {
    const { api, create, user } = setup();
    create.mockRejectedValue(new TypeError("lost"));
    render(<CompletionCreate api={api} />);
    await fill(user);
    await submit(user);
    await screen.findByRole("alert");
    const key = create.mock.calls[0][1];
    if (field === "source") {
      await user.type(screen.getByLabelText("方案视频路径"), "x");
      await user.keyboard("{Backspace}");
    } else if (field === "profile") {
      await user.click(screen.getByLabelText(/完整小课 · 实验性/));
      await user.click(screen.getByLabelText(/短高光 · 实验性/));
    } else {
      await user.selectOptions(screen.getByLabelText("选片方式"), "manual");
      await user.selectOptions(screen.getByLabelText("选片方式"), "default");
    }
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(create.mock.calls[1][1]).not.toBe(key);
    expect(create.mock.calls[1][0]).toEqual(create.mock.calls[0][0]);
  });

  it("locks concurrent submits before asynchronous hashing finishes", async () => {
    const { api, create, user } = setup();
    let finish!: (response: CompletionGoalResponse) => void;
    create.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<CompletionCreate api={api} />);
    await fill(user);
    const form = screen.getByRole("button", { name: "按方案创建" }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("方案视频路径")).toBeDisabled();
    finish(accepted);
    await screen.findByText("当前状态：queued");
  });

  it("warns on unavailable storage while retaining same-page retry", async () => {
    const { api, create, user } = setup();
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => { throw new Error("denied"); });
    create.mockRejectedValue(new TypeError("lost"));
    render(<CompletionCreate api={api} />);
    await fill(user);
    await submit(user);
    await screen.findByRole("alert");
    expect(screen.getByRole("status")).toHaveTextContent("请勿刷新");
    await submit(user);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1]);
  });

  it("warns about malformed saved identity", async () => {
    sessionStorage.setItem("liveclip.pending-completion", "{broken");
    const { api } = setup();
    render(<CompletionCreate api={api} />);
    expect(await screen.findByRole("status")).toHaveTextContent("无法恢复");
  });
});
