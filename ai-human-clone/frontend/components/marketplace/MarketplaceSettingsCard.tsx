"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { inputClass } from "@/components/FormField";
import { MarketplaceCard } from "@/components/marketplace/MarketplaceCard";
import { CATEGORIES } from "@/lib/marketplace/categories";
import { MAX_SHORT_DESCRIPTION, marketplaceErrorMessage } from "@/lib/marketplace/display";
import { MAX_TAGS_PER_CLONE, isValidTag, normalizeTag } from "@/lib/marketplace/filters";
import { type MarketplaceError, marketplaceApi } from "@/lib/marketplaceApi";
import type { MarketplaceAnalytics, MarketplaceSettings, MarketplaceSettingsUpdate } from "@/types/marketplace";

interface Notice {
  kind: "success" | "error";
  text: string;
}

/**
 * The owner's marketplace controls (on the Sharing page): publish with a confirmation,
 * category, tags, short description, the eligibility checklist, a card preview, basic
 * discovery numbers, and removing the clone from discovery (nothing else changes).
 * `refreshKey` changes when visibility / public chat change, so the checklist reloads.
 */
export function MarketplaceSettingsCard({ cloneId, refreshKey }: { cloneId: string; refreshKey: string }) {
  const [settings, setSettings] = useState<MarketplaceSettings | null>(null);
  const [analytics, setAnalytics] = useState<MarketplaceAnalytics | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState("");
  const [description, setDescription] = useState("");

  const adopt = useCallback((data: MarketplaceSettings) => {
    setSettings(data);
    setCategory(data.category ?? "");
    setTags(data.tags);
    setDescription(data.short_description ?? "");
  }, []);

  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .settings(cloneId)
      .then((data) => {
        if (cancelled) return;
        adopt(data);
        setLoadError(null);
      })
      .catch((err: unknown) => !cancelled && setLoadError(marketplaceErrorMessage(err as MarketplaceError)));
    marketplaceApi
      .analytics(cloneId, 30)
      .then((data) => !cancelled && setAnalytics(data))
      .catch(() => undefined); // numbers are optional
    return () => {
      cancelled = true;
    };
  }, [cloneId, refreshKey, adopt]);

  async function save(update: MarketplaceSettingsUpdate, success: string) {
    setBusy(true);
    setNotice(null);
    try {
      adopt(await marketplaceApi.updateSettings(cloneId, update));
      setNotice({ kind: "success", text: success });
    } catch (err) {
      setNotice({ kind: "error", text: marketplaceErrorMessage(err as MarketplaceError) });
    } finally {
      setBusy(false);
      setConfirming(false);
      setConfirmingRemove(false);
    }
  }

  function addTag() {
    const tag = normalizeTag(tagDraft);
    if (!tag) return;
    if (!isValidTag(tag)) {
      setNotice({ kind: "error", text: "Tags are 2–30 characters: letters, numbers, spaces and + # . -" });
      return;
    }
    if (tags.length >= MAX_TAGS_PER_CLONE) {
      setNotice({ kind: "error", text: `At most ${MAX_TAGS_PER_CLONE} tags.` });
      return;
    }
    if (!tags.includes(tag)) setTags([...tags, tag]);
    setTagDraft("");
  }

  if (loadError) {
    return (
      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7">
        <h2 className="text-lg font-semibold">Marketplace</h2>
        <p className="mt-3 text-sm text-rose-200" role="alert">{loadError}</p>
      </section>
    );
  }
  if (!settings) {
    return (
      <section className="mt-6 h-40 animate-pulse rounded-2xl border border-border bg-surface-raised/60" aria-label="Loading marketplace settings" />
    );
  }

  const details: MarketplaceSettingsUpdate = {
    category: category || null,
    tags,
    short_description: description.trim() || null,
  };
  const dirty =
    (settings.category ?? "") !== category ||
    settings.tags.join(",") !== tags.join(",") ||
    (settings.short_description ?? "") !== description.trim();
  const missing = settings.requirements.filter((r) => !r.ok && r.key !== "discovery_on");
  const preview = {
    ...settings.preview,
    category: category ? { slug: category, name: CATEGORIES.find((c) => c.slug === category)?.name ?? category } : null,
    tags,
    short_description: description.trim() || null,
  };

  return (
    <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="marketplace-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="marketplace-heading" className="text-lg font-semibold">Marketplace</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            settings.suspended
              ? "bg-rose-500/15 text-rose-200"
              : settings.listed
                ? "bg-emerald-500/15 text-emerald-200"
                : "bg-white/5 text-muted"
          }`}
        >
          {settings.suspended ? "Suspended by moderators" : settings.listed ? "Listed" : settings.enabled ? "Enabled, not listed" : "Not listed"}
        </span>
      </div>
      <p className="mt-1 text-sm text-muted">
        List this clone on Explore so people can discover it by search, category and tags. Removing it from the marketplace
        keeps your clone, its link and its visibility exactly as they are.
      </p>

      {notice && (
        <p
          className={`mt-4 rounded-lg px-3 py-2 text-sm ${notice.kind === "success" ? "bg-emerald-500/10 text-emerald-200" : "bg-rose-500/10 text-rose-200"}`}
          role={notice.kind === "error" ? "alert" : "status"}
        >
          {notice.text}
        </p>
      )}

      <h3 className="mt-5 text-sm font-medium">Requirements</h3>
      <ul className="mt-2 space-y-1 text-sm">
        {settings.requirements.map((r) => (
          <li key={r.key} className="flex items-center gap-2">
            <span aria-hidden className={r.ok ? "text-emerald-300" : "text-rose-300"}>{r.ok ? "✓" : "✗"}</span>
            <span className={r.ok ? "text-gray-200" : "text-gray-300"}>{r.label}</span>
            <span className="sr-only">{r.ok ? "(done)" : "(missing)"}</span>
          </li>
        ))}
      </ul>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="mp-category" className="text-sm text-muted">Category</label>
          <select id="mp-category" value={category} onChange={(e) => setCategory(e.target.value)} className={`${inputClass} mt-1`}>
            <option value="">No category</option>
            {CATEGORIES.map((c) => (
              <option key={c.slug} value={c.slug}>{c.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="mp-tag" className="text-sm text-muted">Tags ({tags.length}/{MAX_TAGS_PER_CLONE})</label>
          <div className="mt-1 flex gap-2">
            <input
              id="mp-tag"
              value={tagDraft}
              maxLength={30}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addTag();
                }
              }}
              placeholder="e.g. python"
              className={inputClass}
            />
            <button type="button" onClick={addTag} className="min-h-11 shrink-0 rounded-xl border border-border px-3 text-sm hover:border-accent">
              Add
            </button>
          </div>
          {tags.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2" aria-label="Tags">
              {tags.map((tag) => (
                <li key={tag} className="flex items-center gap-1 rounded-full border border-border py-0.5 pl-3 pr-1 text-xs">
                  #{tag}
                  <button
                    type="button"
                    onClick={() => setTags(tags.filter((t) => t !== tag))}
                    aria-label={`Remove tag ${tag}`}
                    className="flex h-7 w-7 items-center justify-center rounded-full text-muted hover:text-white"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="mp-description" className="text-sm text-muted">Short description</label>
          <textarea
            id="mp-description"
            value={description}
            maxLength={MAX_SHORT_DESCRIPTION}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="One or two sentences about what people can ask this clone."
            className={`${inputClass} mt-1`}
          />
          <p className="mt-1 text-right text-xs text-muted">{description.length}/{MAX_SHORT_DESCRIPTION}</p>
        </div>
      </div>

      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <button
          type="button"
          disabled={busy || !dirty}
          onClick={() => void save(details, "Marketplace details saved.")}
          className="min-h-11 rounded-xl border border-accent/50 px-4 text-sm text-accent-soft hover:bg-accent/10 disabled:opacity-50"
        >
          Save details
        </button>
        {settings.enabled ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => setConfirmingRemove(true)}
            className="min-h-11 rounded-xl border border-rose-400/40 px-4 text-sm text-rose-200 hover:bg-rose-500/10 disabled:opacity-50"
          >
            Remove from marketplace
          </button>
        ) : (
          <button
            type="button"
            disabled={busy || missing.length > 0}
            onClick={() => setConfirming(true)}
            className="min-h-11 rounded-xl bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
          >
            Publish to marketplace
          </button>
        )}
        <Link href={settings.public_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center justify-center rounded-xl border border-border px-4 text-sm hover:border-accent">
          View public profile
        </Link>
      </div>
      {!settings.enabled && missing.length > 0 && (
        <p className="mt-2 text-xs text-muted">Complete the requirements above to publish.</p>
      )}

      <h3 className="mt-6 text-sm font-medium">Card preview</h3>
      <div className="mt-2 max-w-sm">
        <MarketplaceCard clone={preview} />
      </div>

      {analytics && <AnalyticsSummary analytics={analytics} />}

      <ConfirmDialog
        open={confirming}
        title="Publish to the marketplace?"
        message="Anyone will be able to find this AI Clone on Explore by search, category and tags, and chat with it publicly. Only content you marked public is used. You can remove it from the marketplace at any time."
        confirmLabel="Publish"
        busyLabel="Publishing…"
        busy={busy}
        onConfirm={() => void save({ ...details, enabled: true, confirm_publish: true }, "Published: your clone is in the marketplace.")}
        onCancel={() => setConfirming(false)}
      />
      <ConfirmDialog
        open={confirmingRemove}
        title="Remove from the marketplace?"
        message="The clone disappears from Explore and search. It is not deleted, and its link, visibility and public chat stay as they are."
        confirmLabel="Remove"
        busyLabel="Removing…"
        busy={busy}
        onConfirm={() => void save({ enabled: false }, "Removed from the marketplace.")}
        onCancel={() => setConfirmingRemove(false)}
      />
    </section>
  );
}

function AnalyticsSummary({ analytics }: { analytics: MarketplaceAnalytics }) {
  const max = Math.max(1, ...analytics.daily.map((d) => d.views));
  return (
    <div className="mt-6">
      <h3 className="text-sm font-medium">Last 30 days</h3>
      <dl className="mt-2 grid grid-cols-3 gap-3 text-center">
        {[
          { label: "Profile views", value: analytics.views },
          { label: "Saved by", value: analytics.favorites },
          { label: "Public chats started", value: analytics.public_chat_starts },
        ].map((stat) => (
          <div key={stat.label} className="rounded-xl border border-border px-2 py-3">
            <dt className="text-[11px] text-muted">{stat.label}</dt>
            <dd className="text-xl font-semibold">{stat.value}</dd>
          </div>
        ))}
      </dl>
      {analytics.daily.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-muted" id="mp-daily">Daily profile views</p>
          <div className="mt-1 flex h-20 items-end gap-0.5" role="img" aria-labelledby="mp-daily" aria-describedby="mp-daily-total">
            {analytics.daily.map((d) => (
              <div
                key={d.date}
                title={`${d.date}: ${d.views} views`}
                className="flex-1 rounded-t bg-accent/60"
                style={{ height: `${Math.max(2, Math.round((d.views / max) * 100))}%` }}
              />
            ))}
          </div>
          <p id="mp-daily-total" className="sr-only">
            {analytics.views} views in {analytics.daily.length} days.
          </p>
        </div>
      )}
      <p className="mt-2 text-xs text-muted">Each visitor counts once per 30 minutes. Search appearances aren&apos;t measured.</p>
    </div>
  );
}
