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
import { adminApi } from "@/lib/adminApi";
import type { AdminCloneDetail, AdminCloneRow } from "@/types/admin";

const LIMIT = 20;

export default function AdminClonesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [visibility, setVisibility] = useState("");
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useAdminData(
    () => adminApi.clones({ page, limit: LIMIT, search: query, visibility, status }),
    [page, query, visibility, status],
  );
  const [detail, setDetail] = useState<AdminCloneDetail | null>(null);
  const [target, setTarget] = useState<AdminCloneRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const disabling = target ? !target.admin_disabled : false;

  async function openDetail(cloneId: string) {
    try {
      setDetail(await adminApi.clone(cloneId));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't load the clone.");
    }
  }

  async function apply() {
    if (!target) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await adminApi.setCloneStatus(target.id, disabling ? "disabled" : "active");
      setNotice(`${updated.name} is now ${updated.status}.`);
      if (detail?.id === updated.id) setDetail(updated);
      setTarget(null);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't change the clone.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="AI Clones" description="Metadata and counts only. Disabling is reversible and keeps all data." />
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
          aria-label="Search clones"
          className={`${inputClass} min-w-56 flex-1`}
          placeholder="Search name, slug or owner email"
          value={search}
          maxLength={100}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select aria-label="Visibility" className={inputClass} value={visibility} onChange={(e) => { setPage(1); setVisibility(e.target.value); }}>
          <option value="">Any visibility</option>
          <option value="public">Public</option>
          <option value="unlisted">Unlisted</option>
          <option value="private">Private</option>
        </select>
        <select aria-label="Status" className={inputClass} value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="draft">Draft</option>
          <option value="disabled">Disabled</option>
        </select>
        <button type="submit" className={buttonClass}>
          Search
        </button>
      </form>

      {loading && !data && <Loading />}
      {data && (
        <>
          <Table head={["Clone", "Owner", "Visibility", "Status", "Created", ""]} empty={data.items.length === 0}>
            {data.items.map((c) => (
              <tr key={c.id}>
                <td className="px-3 py-2">
                  <button type="button" className="text-left hover:underline" onClick={() => openDetail(c.id)}>
                    <span className="block font-medium text-white">{c.name}</span>
                    <span className="text-xs text-muted">/c/{c.slug}</span>
                  </button>
                </td>
                <td className="px-3 py-2 text-muted">{c.owner_email}</td>
                <td className="px-3 py-2">
                  <Badge color={c.visibility === "public" ? "blue" : "gray"}>{c.visibility}</Badge>
                </td>
                <td className="space-x-1 px-3 py-2">
                  <Badge color={c.status === "active" ? "green" : c.status === "disabled" ? "red" : "gray"}>{c.status}</Badge>
                  {c.admin_disabled && <Badge color="amber">admin lock</Badge>}
                </td>
                <td className="px-3 py-2 text-muted">{formatDate(c.created_at)}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    className={c.admin_disabled ? buttonClass : dangerButtonClass}
                    onClick={() => { setActionError(null); setTarget(c); }}
                  >
                    {c.admin_disabled ? "Enable" : "Disable"}
                  </button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} limit={data.limit} total={data.total} onPage={setPage} />
        </>
      )}

      {detail && (
        <Panel title={`Details: ${detail.name}`} className="mt-6">
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {[
              ["Owner", detail.owner_email],
              ["Visibility", detail.visibility],
              ["Status", detail.status],
              ["Public chat", detail.public_chat_enabled ? "On" : "Off"],
              ["Documents", `${detail.document_count} (${detail.public_document_count} public)`],
              ["Memories", `${detail.memory_count} (${detail.public_memory_count} public)`],
              ["Conversations", detail.conversation_count],
              ["Messages", detail.message_count],
              ["Visitor sessions", detail.public_session_count],
              ["Voice", detail.voice_enabled ? (detail.public_voice_enabled ? "On (public)" : "On") : "Off"],
              ["Avatar", detail.avatar_enabled ? (detail.public_avatar_enabled ? "On (public)" : "On") : "Off"],
              ["Updated", formatDate(detail.updated_at)],
            ].map(([label, value]) => (
              <div key={label as string}>
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="break-words text-white">{value}</dd>
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
        title={disabling ? "Disable this AI Clone?" : "Enable this AI Clone?"}
        message={
          disabling
            ? `Public chat, voice and avatar for "${target?.name}" stop immediately and the owner can't turn it back on. All data is kept; you can enable it again later.`
            : `"${target?.name}" becomes active again. Its owner's public settings apply as before.`
        }
        confirmLabel={disabling ? "Disable clone" : "Enable clone"}
        busy={busy}
        error={actionError}
        onConfirm={apply}
        onCancel={() => setTarget(null)}
      />
    </>
  );
}
