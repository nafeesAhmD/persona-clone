"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  SuccessNote,
  Table,
  buttonClass,
  dangerButtonClass,
  formatDate,
  useAdminData,
} from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";

type Tab = "clones" | "documents" | "memories";
type Action =
  | { kind: "clone-private" | "clone-disable"; id: string; label: string }
  | { kind: "document" | "memory"; id: string; label: string };

const LIMIT = 20;

const ACTION_TEXT: Record<Action["kind"], { title: string; message: string; confirm: string }> = {
  "clone-private": {
    title: "Make this AI Clone private?",
    message: "Its public link and listing stop working right away. Nothing is deleted; the owner can review it.",
    confirm: "Make private",
  },
  "clone-disable": {
    title: "Disable this public AI Clone?",
    message: "Chat, voice and avatar stop for everyone and the owner can't re-enable it. Data is kept.",
    confirm: "Disable clone",
  },
  document: {
    title: "Remove this document from public answers?",
    message: "The document becomes private: visitors' answers stop using it at once. It isn't deleted.",
    confirm: "Make private",
  },
  memory: {
    title: "Remove this memory from public answers?",
    message: "The memory becomes private: visitors' answers stop using it at once. It isn't deleted.",
    confirm: "Make private",
  },
};

export default function AdminContentPage() {
  const [tab, setTab] = useState<Tab>("clones");
  const [page, setPage] = useState(1);
  const [action, setAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const clones = useAdminData(() => (tab === "clones" ? adminApi.publicClones({ page, limit: LIMIT }) : Promise.resolve(null)), [tab, page]);
  const documents = useAdminData(() => (tab === "documents" ? adminApi.publicDocuments({ page, limit: LIMIT }) : Promise.resolve(null)), [tab, page]);
  const memories = useAdminData(() => (tab === "memories" ? adminApi.publicMemories({ page, limit: LIMIT }) : Promise.resolve(null)), [tab, page]);
  const current = tab === "clones" ? clones : tab === "documents" ? documents : memories;

  async function confirm() {
    if (!action) return;
    setBusy(true);
    setActionError(null);
    try {
      if (action.kind === "clone-private") await adminApi.makeClonePrivate(action.id);
      if (action.kind === "clone-disable") await adminApi.disablePublicClone(action.id);
      if (action.kind === "document") await adminApi.makeDocumentPrivate(action.id);
      if (action.kind === "memory") await adminApi.makeMemoryPrivate(action.id);
      setNotice(`Done: ${action.label}`);
      setAction(null);
      current.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The action failed.");
    } finally {
      setBusy(false);
    }
  }

  const text = action ? ACTION_TEXT[action.kind] : null;

  return (
    <>
      <PageHeader title="Public Content" description="What visitors can see. Actions hide content; nothing is deleted and every action is audited." />
      <div role="tablist" className="mb-4 flex gap-2">
        {(["clones", "documents", "memories"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            className={`${buttonClass} ${tab === t ? "bg-accent/15" : ""}`}
            onClick={() => {
              setTab(t);
              setPage(1);
            }}
          >
            Public {t}
          </button>
        ))}
      </div>
      <SuccessNote message={notice} />
      <ErrorNote message={current.error} />
      {current.loading && !current.data && <Loading />}

      {tab === "clones" && clones.data && (
        <>
          <Table head={["Clone", "Owner", "Visibility", "Status", "Created", ""]} empty={clones.data.items.length === 0}>
            {clones.data.items.map((c) => (
              <tr key={c.id}>
                <td className="px-3 py-2">
                  <span className="block font-medium text-white">{c.name}</span>
                  <span className="text-xs text-muted">{c.tagline ?? `/c/${c.slug}`}</span>
                </td>
                <td className="px-3 py-2 text-muted">{c.owner_email}</td>
                <td className="px-3 py-2"><Badge color="blue">{c.visibility}</Badge></td>
                <td className="px-3 py-2"><Badge color={c.status === "active" ? "green" : "red"}>{c.status}</Badge></td>
                <td className="px-3 py-2 text-muted">{formatDate(c.created_at)}</td>
                <td className="space-x-2 whitespace-nowrap px-3 py-2 text-right">
                  <button type="button" className={buttonClass} onClick={() => setAction({ kind: "clone-private", id: c.id, label: `${c.name} is private` })}>
                    Make private
                  </button>
                  {c.status !== "disabled" && (
                    <button type="button" className={dangerButtonClass} onClick={() => setAction({ kind: "clone-disable", id: c.id, label: `${c.name} is disabled` })}>
                      Disable
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={clones.data.page} limit={clones.data.limit} total={clones.data.total} onPage={setPage} />
        </>
      )}

      {tab === "documents" && documents.data && (
        <>
          <Table head={["Document", "Clone", "Owner", "Size", "Added", ""]} empty={documents.data.items.length === 0}>
            {documents.data.items.map((d) => (
              <tr key={d.id}>
                <td className="px-3 py-2 font-medium text-white">{d.title}</td>
                <td className="px-3 py-2">{d.clone_name}</td>
                <td className="px-3 py-2 text-muted">{d.owner_email}</td>
                <td className="px-3 py-2 text-muted">{d.character_count.toLocaleString()} chars</td>
                <td className="px-3 py-2 text-muted">{formatDate(d.created_at)}</td>
                <td className="px-3 py-2 text-right">
                  <button type="button" className={dangerButtonClass} onClick={() => setAction({ kind: "document", id: d.id, label: `"${d.title}" is private` })}>
                    Make private
                  </button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={documents.data.page} limit={documents.data.limit} total={documents.data.total} onPage={setPage} />
        </>
      )}

      {tab === "memories" && memories.data && (
        <>
          <Table head={["Memory", "Clone", "Owner", "Added", ""]} empty={memories.data.items.length === 0}>
            {memories.data.items.map((m) => (
              <tr key={m.id}>
                <td className="max-w-md px-3 py-2">
                  <Badge>{m.memory_type}</Badge> <span className="text-white">{m.content}</span>
                </td>
                <td className="px-3 py-2">{m.clone_name}</td>
                <td className="px-3 py-2 text-muted">{m.owner_email}</td>
                <td className="px-3 py-2 text-muted">{formatDate(m.created_at)}</td>
                <td className="px-3 py-2 text-right">
                  <button type="button" className={dangerButtonClass} onClick={() => setAction({ kind: "memory", id: m.id, label: "memory is private" })}>
                    Make private
                  </button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={memories.data.page} limit={memories.data.limit} total={memories.data.total} onPage={setPage} />
        </>
      )}

      <ConfirmDialog
        open={action !== null}
        title={text?.title ?? ""}
        message={text?.message ?? ""}
        confirmLabel={text?.confirm ?? "Confirm"}
        busy={busy}
        error={actionError}
        onConfirm={confirm}
        onCancel={() => { setAction(null); setActionError(null); }}
      />
    </>
  );
}
