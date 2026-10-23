"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  Panel,
  SuccessNote,
  Table,
  buttonClass,
  dangerButtonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { useAuth } from "@/components/AuthProvider";
import { adminApi } from "@/lib/adminApi";
import type { AdminUserDetail, AdminUserRow } from "@/types/admin";

const LIMIT = 20;

export default function AdminUsersPage() {
  const { user: me } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("created_at");
  const { data, error, loading, reload } = useAdminData(
    () => adminApi.users({ page, limit: LIMIT, search: query, status, sort, order: sort === "created_at" ? "desc" : "asc" }),
    [page, query, status, sort],
  );
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [target, setTarget] = useState<AdminUserRow | AdminUserDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function openDetail(userId: string) {
    setActionError(null);
    try {
      setDetail(await adminApi.user(userId));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't load the user.");
    }
  }

  async function toggle() {
    if (!target) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await adminApi.setUserActive(target.id, !target.is_active);
      setNotice(`${updated.email} is now ${updated.is_active ? "active" : "disabled"}.`);
      if (detail?.id === updated.id) setDetail(updated);
      setTarget(null);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't change the account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Users" description="Disable or reactivate accounts. Accounts are never deleted here." />
      <SuccessNote message={notice} />
      <ErrorNote message={error ?? (target ? null : actionError)} />
      <form
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQuery(search.trim());
        }}
      >
        <input
          aria-label="Search users"
          className={`${inputClass} min-w-56 flex-1`}
          placeholder="Search email, username or name"
          value={search}
          maxLength={100}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select aria-label="Status" className={inputClass} value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
          <option value="">All users</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
          <option value="admin">Admins</option>
        </select>
        <select aria-label="Sort" className={inputClass} value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="created_at">Newest</option>
          <option value="email">Email</option>
          <option value="username">Username</option>
        </select>
        <button type="submit" className={buttonClass}>
          Search
        </button>
      </form>

      {loading && !data && <Loading />}
      {data && (
        <>
          <Table head={["User", "Status", "Clones", "Joined", ""]} empty={data.items.length === 0}>
            {data.items.map((u) => (
              <tr key={u.id}>
                <td className="px-3 py-2">
                  <button type="button" className="text-left hover:underline" onClick={() => openDetail(u.id)}>
                    <span className="block font-medium text-white">{u.email}</span>
                    <span className="text-xs text-muted">
                      @{u.username}
                      {u.full_name ? ` · ${u.full_name}` : ""}
                    </span>
                  </button>
                </td>
                <td className="space-x-1 px-3 py-2">
                  <Badge color={u.is_active ? "green" : "red"}>{u.is_active ? "active" : "disabled"}</Badge>
                  {u.is_admin && <Badge color="amber">admin</Badge>}
                </td>
                <td className="px-3 py-2">{u.clone_count}</td>
                <td className="px-3 py-2 text-muted">{formatDate(u.created_at)}</td>
                <td className="px-3 py-2 text-right">
                  {u.id !== me?.id && !u.is_admin && (
                    <button
                      type="button"
                      className={u.is_active ? dangerButtonClass : buttonClass}
                      onClick={() => { setActionError(null); setTarget(u); }}
                    >
                      {u.is_active ? "Disable" : "Reactivate"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} limit={data.limit} total={data.total} onPage={setPage} />
        </>
      )}

      {detail && (
        <Panel title={`Details: ${detail.email}`} className="mt-6">
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            {[
              ["Clones", detail.clone_count],
              ["Documents", detail.document_count],
              ["Memories", detail.memory_count],
              ["Conversations", detail.conversation_count],
              ["Messages", detail.message_count],
              ["Status", detail.is_active ? "Active" : "Disabled"],
              ["Joined", formatDate(detail.created_at)],
              ["Updated", formatDate(detail.updated_at)],
              ["Login locked until", formatDate(detail.locked_until)],
            ].map(([label, value]) => (
              <div key={label as string}>
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="text-white">{value}</dd>
              </div>
            ))}
          </dl>
          <button type="button" className={`${buttonClass} mt-4`} onClick={() => setDetail(null)}>
            Close
          </button>
        </Panel>
      )}

      <ConfirmDialog
        open={target !== null}
        title={target?.is_active ? "Disable this account?" : "Reactivate this account?"}
        message={
          target?.is_active
            ? `${target.email} will be signed out on their next request and can't log in. Their public AI Clones stop answering visitors. Nothing is deleted, and you can reactivate the account later.`
            : `${target?.email} will be able to log in again.`
        }
        confirmLabel={target?.is_active ? "Disable account" : "Reactivate"}
        busy={busy}
        error={actionError}
        onConfirm={toggle}
        onCancel={() => setTarget(null)}
      />
    </>
  );
}
