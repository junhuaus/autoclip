import { type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";

import { type LiveClipApiClient } from "./api";

export function LoginPage({
  api,
  onAuthenticated,
}: {
  api: LiveClipApiClient;
  onAuthenticated: () => void;
}) {
  const login = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: onAuthenticated,
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    login.mutate({
      username: String(data.get("username") ?? ""),
      password: String(data.get("password") ?? ""),
    });
  };

  return (
    <main className="login-shell">
      <section className="login-brand" aria-label="LiveClip 产品说明">
        <span className="brand-mark login-logo">LC</span>
        <p className="eyebrow">直播内容工作流</p>
        <h1>从长直播到可发布高光，<br />让编辑团队专注判断。</h1>
        <p>项目、审核、交付集中管理。源视频与生成内容留在本机。</p>
        <div className="login-proof">
          <span><strong>私有</strong> 默认仅创作者可见</span>
          <span><strong>协作</strong> 编辑与审核职责分离</span>
          <span><strong>可追溯</strong> 关键操作留存审计记录</span>
        </div>
      </section>
      <section className="panel login-card" aria-labelledby="login-title">
        <p className="eyebrow">欢迎回来</p>
        <h2 id="login-title">登录 LiveClip</h2>
        <p>使用管理员分配的本地账号。</p>
        <form onSubmit={submit}>
          <label>账号
            <input name="username" required maxLength={80} autoComplete="username" autoFocus />
          </label>
          <label>密码
            <input name="password" type="password" required maxLength={128} autoComplete="current-password" />
          </label>
          <button type="submit" className="button button-primary" disabled={login.isPending}>
            {login.isPending ? "正在登录…" : "登录工作台"}
          </button>
          {login.isError ? <p className="form-error" role="alert">账号或密码不正确，请重试。</p> : null}
        </form>
        <small>无法登录？请联系本机 LiveClip 管理员重置密码。</small>
      </section>
    </main>
  );
}
