import { type FormEvent, useEffect, useRef, useState } from "react";
import { LiveClipApiClient, createIdempotencyKey, errorMessage } from "./api";
import type { CompletionGoalResponse, CompletionPresetCreateRequest, CompletionPresetSummary } from "./types";
import { saveConfirmedGoal } from "./CompletionWatch";

const STORAGE_KEY = "liveclip.pending-completion";
type Pending = { key: string; hash: string };

export function CompletionCreate({ api, onBusyChange, onCreated, onOpenProject, disabled = false }: {
  api: LiveClipApiClient;
  onBusyChange?: (busy: boolean) => void;
  onCreated?: (created: CompletionGoalResponse) => void;
  onOpenProject?: (projectId: string) => void;
  disabled?: boolean;
}) {
  const [presets, setPresets] = useState<CompletionPresetSummary[]>([]);
  const [form, setForm] = useState<CompletionPresetCreateRequest | null>(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CompletionGoalResponse | null>(null);
  const pending = useRef<Pending | null>(null);
  const locked = useRef(false);
  // A saved identity may be matched after re-entering the form on reload.
  const attempted = useRef(false);
  const lifetime = useRef(0);

  useEffect(() => {
    const current = ++lifetime.current;
    let active = true;
    api.completionPresets().then(({ presets: choices }) => {
      if (!active) return;
      setPresets(choices);
      if (choices.length) setForm({ input_path: "", preset_id: choices[0].preset_id, selection_policy: choices[0].default_selection_policy });
    }).catch(() => { if (active) setError("无法加载剪辑方案，请重新打开重试。"); });
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) {
        const value: unknown = JSON.parse(raw);
        if (typeof value !== "object" || value === null || Object.keys(value).sort().join() !== "hash,key") throw new Error();
        const saved = value as Pending;
        if (typeof saved.key !== "string" || !/^liveclip-web-completion-[A-Za-z0-9-]+$/.test(saved.key) || saved.key.length > 200 || typeof saved.hash !== "string" || !/^[a-f0-9]{64}$/.test(saved.hash)) throw new Error();
        pending.current = saved;
      }
    } catch {
      setWarning("无法恢复已保存的请求；刷新后的重试可能创建新项目。");
    }
    return () => { active = false; if (lifetime.current === current) lifetime.current++; };
  }, [api]);

  function clearPending(identity = pending.current) {
    if (!identity) return;
    if (pending.current?.key === identity.key && pending.current.hash === identity.hash) {
      pending.current = null;
    }
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) {
        const stored = JSON.parse(raw) as Pending | null;
        // Another dialog lifetime may now own the single recovery slot.
        if (stored?.key === identity.key && stored.hash === identity.hash) {
          sessionStorage.removeItem(STORAGE_KEY);
        }
      }
    }
    catch { setWarning("浏览器无法保存请求状态；请勿刷新页面后重试。"); }
  }

  function change(next: CompletionPresetCreateRequest) {
    if (locked.current) return;
    if (attempted.current) clearPending();
    setResult(null);
    setForm(next);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form || locked.current || disabled) return;
    locked.current = true;
    onBusyChange?.(true);
    setBusy(true);
    setError("");
    attempted.current = true;
    const current = lifetime.current;
    try {
      const canonical = JSON.stringify({ input_path: form.input_path, preset_id: form.preset_id, selection_policy: form.selection_policy });
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
      if (lifetime.current !== current) return;
      const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
      if (pending.current?.hash !== hash) pending.current = { key: createIdempotencyKey("completion"), hash };
      const identity = pending.current;
      try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(identity)); }
      catch { setWarning("浏览器无法保存请求状态；本页重试有效，请勿刷新页面后重试。"); }
      const created = await api.createCompletionFromPreset(form, identity.key);
      if (lifetime.current !== current) return;
      if (saveConfirmedGoal(created.goal.intent_id)) clearPending(identity);
      else setWarning("目标已保存，但浏览器无法保存重连信息；请记录目标 ID。原请求身份仍保留。");
      setResult(created);
      onCreated?.(created);
    } catch (failure) {
      if (lifetime.current === current) setError(`${errorMessage(failure)}。保持表单不变可重试同一请求。`);
    } finally {
      if (lifetime.current === current) {
        locked.current = false;
        setBusy(false);
        onBusyChange?.(false);
      }
    }
  }

  return <section aria-label="按方案创建">
    <h3>选择剪辑方案</h3>
    <p>实验性方案。提交后保存处理目标，交付包将在处理完成后生成。</p>
    <p>刷新后请重新填写相同视频路径和选项，以恢复上次未确认的请求。</p>
    {warning && <p role="status">{warning}</p>}
    {error && <p role="alert">{error}</p>}
    {form && <form className="create-form" onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy}>
        <legend>剪辑方案</legend>
        {presets.map((preset) => <label key={preset.preset_id}>
          <input type="radio" name="completion-preset" checked={form.preset_id === preset.preset_id} onChange={() => change({ ...form, preset_id: preset.preset_id })} />
          {preset.display_name_zh} · 实验性 · {preset.minimum_clip_seconds}–{preset.maximum_clip_seconds} 秒（目标 {preset.target_clip_seconds} 秒）
        </label>)}
        <label>方案视频路径<input required maxLength={4096} value={form.input_path} onChange={(event) => change({ ...form, input_path: event.target.value })} /></label>
        <label>选片方式<select value={form.selection_policy} onChange={(event) => change({ ...form, selection_policy: event.target.value as CompletionPresetCreateRequest["selection_policy"] })}>
          <option value="default">默认选片</option><option value="manual">手动选片</option>
        </select></label>
      </fieldset>
      <button className="button button-primary" disabled={busy || disabled} type="submit">{busy ? "正在保存…" : "按方案创建"}</button>
    </form>}
    {result && <div role="status"><p>处理目标已保存：{result.goal.intent_id}</p><p>项目：{result.goal.project_id}</p><p>当前状态：{result.goal.status}</p><p>交付尚需处理完成后确认。</p>{onOpenProject && <button className="button button-secondary" type="button" disabled={busy} onClick={() => onOpenProject(result.goal.project_id)}>打开项目</button>}</div>}
  </section>;
}
