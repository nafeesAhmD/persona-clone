"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EmptyState, LoadingBlock, Notice, PageShell, Sheet, btnPrimary, btnSecondary, inputCls, labelCls, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { useAuth } from "@/components/AuthProvider";
import { RoleBadge } from "@/components/organizations/shared";
import { orgApi } from "@/lib/orgApi";
import { orgErrorMessage } from "@/lib/orgRoles";

function CreateOrganizationSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Please enter a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const org = await orgApi.create({ name: name.trim(), description: description.trim() || null });
      router.push(`/organizations/${encodeURIComponent(org.id)}`);
    } catch (err) {
      setError(orgErrorMessage(err, "Couldn't create the organization."));
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} title="New organization" onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <label htmlFor="org-name" className={labelCls}>
            Name
          </label>
          <input
            id="org-name"
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={160}
            required
            autoComplete="organization"
            aria-invalid={!!error && !name.trim()}
            aria-describedby={error ? "org-create-error" : undefined}
          />
        </div>
        <div>
          <label htmlFor="org-description" className={labelCls}>
            Description <span className="font-normal text-muted">(optional)</span>
          </label>
          <textarea
            id="org-description"
            className={`${inputCls} min-h-24 py-2`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            rows={3}
          />
        </div>
        {error && (
          <p id="org-create-error" role="alert" className="text-sm text-rose-300">
            {error}
          </p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className={btnSecondary} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className={btnPrimary} disabled={busy}>
            {busy ? "Creating…" : "Create organization"}
          </button>
        </div>
      </form>
    </Sheet>
  );
}

export function OrganizationsList() {
  const { user } = useAuth();
  const { data, error, reload } = useApiData(() => orgApi.list(), "orgs");
  const [creating, setCreating] = useState(false);

  const newButton = (
    <button type="button" className={btnPrimary} onClick={() => setCreating(true)}>
      New organization
    </button>
  );

  return (
    <PageShell title="Organizations" description="Work on clones together with your team." actions={newButton}>
      {error && !data ? (
        <ApiErrorState error={error} thing="organizations" onRetry={reload} />
      ) : !data ? (
        <LoadingBlock label="Loading organizations…" />
      ) : data.length === 0 ? (
        <EmptyState title="No organizations yet" body="Create one to invite teammates and share clones, or open an invitation link you received." />
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.map((org) => (
            <li key={org.id}>
              <Link
                href={`/organizations/${encodeURIComponent(org.id)}`}
                className="block min-h-11 rounded-2xl border border-border bg-surface-raised/60 p-4 hover:border-accent"
              >
                <div className="flex items-start justify-between gap-2">
                  <h2 className="min-w-0 break-words font-semibold text-white">{org.name}</h2>
                  {org.owner_id === user?.id && <RoleBadge role="owner" />}
                </div>
                {org.description && <p className="mt-1 line-clamp-2 text-sm text-muted">{org.description}</p>}
                <p className="mt-2 text-xs text-muted">/{org.slug}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && data.length > 0 && (
        <div className="mt-4">
          <Notice tone="info">Got an invitation? Open the invite link you were sent while signed in to join.</Notice>
        </div>
      )}
      <CreateOrganizationSheet open={creating} onClose={() => setCreating(false)} />
    </PageShell>
  );
}
