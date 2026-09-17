import { useEffect, useState } from "react";
import { LiveClipApiClient, LiveClipApiError } from "./api";
import type { CompletionGoalResponse } from "./types";

const STORAGE_KEY = "liveclip.confirmed-completion";

export function saveConfirmedGoal(intentId: string): boolean {
  try {
    sessionStorage.setItem(STORAGE_KEY, intentId);
    return true;
  } catch { return false; }
}

export function CompletionWatch({ api, intentId }: {
  api: LiveClipApiClient; intentId?: string;
}) {
  const [view, setView] = useState<{ api: LiveClipApiClient; id: string; value: CompletionGoalResponse } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setView(null);
    setError("");
    let id = intentId;
    if (!id) {
      try { id = sessionStorage.getItem(STORAGE_KEY) ?? undefined; }
      catch { setError("无法读取已保存的目标 ID；请使用原请求恢复。"); }
    }
    if (!id) return;
    if (!/^[a-f0-9]{32}$/.test(id)) {
      setError("已保存的目标 ID 无效。");
      return;
    }
    const selected = id;
    async function poll() {
      try {
        const value = await api.completionGoal(selected);
        if (!active) return;
        if (value.goal.intent_id !== selected) throw new Error("Unexpected goal identity");
        setView({ api, id: selected, value });
        setError("");
        // Even terminal content and signed downloads need current authority.
        timer = setTimeout(() => void poll(), 2000);
      } catch (failure) {
        if (!active) return;
        setView(null);
        const denied = failure instanceof LiveClipApiError && [401, 403, 404].includes(failure.status);
        setError(denied ? "目标不可访问，请检查当前身份。" : "暂时无法读取目标，正在重新连接。");
        if (!denied) timer = setTimeout(() => void poll(), 2000);
      }
    }
    void poll();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [api, intentId]);

  const value = view?.api === api && (!intentId || view.id === intentId) ? view.value : null;
  if (!value && !error) return null;
  const goal = value?.goal;
  const progress = goal?.delivery_progress;
  return <section className="panel completion-watch" aria-label="处理目标观察">
    <h3>处理目标</h3>
    {error && <p role="alert">{error}</p>}
    {goal && <>
      <p>目标：{goal.intent_id}</p><p>项目：{goal.project_id}</p>
      <p>状态：{goal.status} · 结果：{goal.outcome ?? "尚未完成"}</p>
      {goal.status === "waiting_selection" && <p>等待授权用户提交手动选片；观察不会自动选片。</p>}
      {goal.blocking_code && <p>{goal.blocking_code}</p>}
      {goal.safe_error_message && <p>{goal.safe_error_message.slice(0, 500)}</p>}
      {progress && <div aria-label="交付阶段进度">
        <p>当前阶段：{progress.phase}</p>
        {progress.completed !== null && <p>当前阶段工作量：{progress.completed} / {progress.total === null ? "总量待定" : progress.total} {progress.unit}</p>}
        <p>工作推进时间：{progress.business_advanced_at ?? "尚无"}</p>
        <p>Worker 心跳：{progress.worker_heartbeat_at ?? "尚无"} · {progress.lease_fresh ? "租约有效" : "无新鲜租约"}（心跳不是进度）</p>
      </div>}
      {goal.status === "succeeded" && goal.outcome === "delivered" && value?.download_url && <a href={value.download_url}>下载交付 ZIP</a>}
    </>}
  </section>;
}
