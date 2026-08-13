import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type LiveClipApiClient, errorMessage } from "./api";
import type { AdminUserCreateRequest, ManagedUser } from "./types";
import { EmptyState, ErrorState, LoadingState } from "./ui";

function roleLabel(user: ManagedUser): string {
  return user.system_role === "administrator" ? "管理员" : "成员";
}

export function AdminUsers({ api }: { api: LiveClipApiClient }) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null);
  const [editTarget, setEditTarget] = useState<ManagedUser | null>(null);
  const usersQuery = useQuery({ queryKey: ["admin-users"], queryFn: () => api.listUsers() });
  const syncUsers = (data: Awaited<ReturnType<LiveClipApiClient["listUsers"]>>) => {
    queryClient.setQueryData(["admin-users"], data);
  };
  const createMutation = useMutation({
    mutationFn: (body: AdminUserCreateRequest) => api.createUser(body),
    onSuccess: (data) => { syncUsers(data); setShowCreate(false); },
  });
  const updateMutation = useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: { is_active?: boolean; display_name?: string; system_role?: "administrator" | "member" } }) =>
      api.updateUser(userId, body),
    onSuccess: (data) => { syncUsers(data); setEditTarget(null); },
  });
  const resetMutation = useMutation({
    mutationFn: ({ userId, password }: { userId: string; password: string }) =>
      api.resetUserPassword(userId, password),
    onSuccess: (data) => { syncUsers(data); setResetTarget(null); },
  });

  const create = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    createMutation.mutate({
      username: String(data.get("username") ?? ""),
      display_name: String(data.get("display_name") ?? ""),
      system_role: data.get("system_role") === "administrator" ? "administrator" : "member",
      password: String(data.get("password") ?? ""),
    });
  };
  const reset = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!resetTarget) return;
    const data = new FormData(event.currentTarget);
    resetMutation.mutate({ userId: resetTarget.user_id, password: String(data.get("password")) });
  };
  const edit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editTarget) return;
    const data = new FormData(event.currentTarget);
    updateMutation.mutate({ userId: editTarget.user_id, body: { display_name: String(data.get("display_name") ?? ""), system_role: data.get("system_role") === "administrator" ? "administrator" : "member" } });
  };

  return (
    <main className="admin-page">
      <section className="dashboard-heading">
        <div><p className="eyebrow">系统管理</p><h1>成员与权限</h1><p>管理可登录账号。项目内角色由各项目负责人分配。</p></div>
        <button type="button" className="button button-primary" onClick={() => setShowCreate(true)}>＋ 新建成员</button>
      </section>
      <section className="panel user-manager">
        <div className="project-manager-heading"><div><h2>成员列表</h2><p>停用账号会立即撤销其所有网页登录会话。</p></div><button type="button" className="button button-ghost" onClick={() => void usersQuery.refetch()}>刷新</button></div>
        {usersQuery.isPending ? <LoadingState>正在加载成员…</LoadingState> : null}
        {usersQuery.isError ? <ErrorState error={usersQuery.error} onRetry={() => void usersQuery.refetch()} /> : null}
        {usersQuery.data?.users.length === 0 ? <EmptyState title="还没有成员" /> : null}
        {usersQuery.data?.users.length ? (
          <div className="user-table-wrap"><table className="user-table"><thead><tr><th>成员</th><th>系统权限</th><th>状态</th><th>最近登录</th><th>操作</th></tr></thead><tbody>
            {usersQuery.data.users.map((user) => <tr key={user.user_id}>
              <td><strong>{user.display_name}</strong><small>@{user.username}</small></td>
              <td><span className={`role-pill role-${user.system_role}`}>{roleLabel(user)}</span></td>
              <td>{user.is_active ? <span className="active-dot">可登录</span> : <span className="inactive-dot">已停用</span>}</td>
              <td>{user.last_login_at ? new Date(user.last_login_at).toLocaleString("zh-CN") : "从未登录"}</td>
              <td><div className="table-actions"><button type="button" className="button button-ghost" onClick={() => setEditTarget(user)}>编辑</button><button type="button" className="button button-ghost" onClick={() => setResetTarget(user)} disabled={!user.is_active}>重置密码</button><button type="button" className="button button-ghost" onClick={() => updateMutation.mutate({ userId: user.user_id, body: { is_active: !user.is_active } })}>{user.is_active ? "停用" : "恢复"}</button></div></td>
            </tr>)}
          </tbody></table></div>
        ) : null}
        {updateMutation.isError ? <p className="form-error" role="alert">{errorMessage(updateMutation.error)}</p> : null}
      </section>
      {showCreate ? <div className="modal-backdrop" role="presentation"><section className="panel create-dialog" role="dialog" aria-modal="true" aria-labelledby="new-user-title"><div className="section-heading"><div><p className="eyebrow">成员账号</p><h2 id="new-user-title">新建成员</h2></div><button type="button" className="button button-ghost" onClick={() => setShowCreate(false)}>取消</button></div><form className="create-form" onSubmit={create}><label>姓名<input name="display_name" required maxLength={120} autoFocus /></label><label>登录账号<input name="username" required pattern="[a-z0-9][a-z0-9._-]*" maxLength={80} placeholder="lin-editor" /></label><label>系统权限<select name="system_role" defaultValue="member"><option value="member">成员</option><option value="administrator">管理员</option></select></label><label>初始密码<input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label><p className="hint">项目负责人可在具体项目中授予编辑、审核或只读角色。</p><button className="button button-primary" type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? "正在创建…" : "创建成员"}</button>{createMutation.isError ? <p className="form-error" role="alert">{errorMessage(createMutation.error)}</p> : null}</form></section></div> : null}
      {editTarget ? <div className="modal-backdrop" role="presentation"><section className="panel create-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-user-title"><div className="section-heading"><div><p className="eyebrow">成员账号</p><h2 id="edit-user-title">编辑 {editTarget.display_name}</h2></div><button type="button" className="button button-ghost" onClick={() => setEditTarget(null)}>取消</button></div><form className="create-form" onSubmit={edit}><label>姓名<input name="display_name" required maxLength={120} defaultValue={editTarget.display_name} autoFocus /></label><label>系统权限<select name="system_role" defaultValue={editTarget.system_role}><option value="member">成员</option><option value="administrator">管理员</option></select></label><p className="hint">变更系统权限会撤销该成员当前会话；至少保留一名可用管理员。</p><button className="button button-primary" type="submit" disabled={updateMutation.isPending}>保存修改</button>{updateMutation.isError ? <p className="form-error" role="alert">{errorMessage(updateMutation.error)}</p> : null}</form></section></div> : null}
      {resetTarget ? <div className="modal-backdrop" role="presentation"><section className="panel create-dialog" role="dialog" aria-modal="true" aria-labelledby="reset-title"><div className="section-heading"><div><p className="eyebrow">安全操作</p><h2 id="reset-title">重置 {resetTarget.display_name} 的密码</h2></div><button type="button" className="button button-ghost" onClick={() => setResetTarget(null)}>取消</button></div><form className="create-form" onSubmit={reset}><label>新密码<input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" autoFocus /></label><p className="hint">保存后，该成员已登录的浏览器将立即退出。</p><button className="button button-primary" type="submit" disabled={resetMutation.isPending}>确认重置</button>{resetMutation.isError ? <p className="form-error" role="alert">{errorMessage(resetMutation.error)}</p> : null}</form></section></div> : null}
    </main>
  );
}
