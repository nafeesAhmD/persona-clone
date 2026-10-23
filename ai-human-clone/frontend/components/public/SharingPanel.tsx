"use client";

import Link from "next/link";
import QRCode from "qrcode";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FormAlert, inputClass } from "@/components/FormField";
import { MarketplaceSettingsCard } from "@/components/marketplace/MarketplaceSettingsCard";
import { StatusMessage } from "@/components/StatusMessage";
import { changeSlug, getClone, getPublicSettings, updatePublicSettings } from "@/lib/api";
import { canShareClone, copyLink, hasNativeShare, shareDataFor, shareOrCopy } from "@/lib/share";
import { cn } from "@/lib/utils";
import type { CloneProfile, Visibility } from "@/types/clone";
import type { PublicSettings, PublicSettingsUpdate } from "@/types/public";

const VISIBILITY_OPTIONS: { value: Visibility; label: string; help: string }[] = [
  { value: "private", label: "Private", help: "Only you can open and chat with it." },
  { value: "unlisted", label: "Unlisted", help: "Anyone with the exact link can open it. Not listed on Explore." },
  { value: "public", label: "Public", help: "Anyone can open it. To list it on Explore, publish it in the Marketplace section below." },
];

interface Notice {
  kind: "success" | "error";
  text: string;
}

export function SharingPanel({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PublicSettingsUpdate | null>(null); // waiting for the safety confirmation
  const [slug, setSlug] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  // The share link uses the address this site is opened at (this page renders only in the browser).
  const [origin] = useState(() => (typeof window !== "undefined" ? window.location.origin : ""));

  const load = useCallback(() => {
    Promise.all([getClone(cloneId), getPublicSettings(cloneId)])
      .then(([cloneData, data]) => {
        setClone(cloneData);
        setSettings(data);
        setSlug(data.slug);
        setLoadError(null);
      })
      .catch(setLoadError);
  }, [cloneId]);

  useEffect(load, [load]);

  const shareUrl = settings ? `${origin || ""}${settings.share_path}` : "";
  // Never offer a private clone's link.
  const reachable = canShareClone(settings);

  useEffect(() => {
    if (!shareUrl || !reachable) return;
    let cancelled = false;
    QRCode.toDataURL(shareUrl, { margin: 1, width: 200 })
      .then((url) => !cancelled && setQr(url))
      .catch(() => !cancelled && setQr(null));
    return () => {
      cancelled = true;
    };
  }, [shareUrl, reachable]);

  async function apply(update: PublicSettingsUpdate, success: string) {
    setBusy(true);
    setNotice(null);
    try {
      setSettings(await updatePublicSettings(cloneId, update));
      setNotice({ kind: "success", text: success });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not save." });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  /** Anything that opens the clone to visitors asks for confirmation first. */
  function request(update: PublicSettingsUpdate, success: string) {
    if (!settings) return;
    const next = { ...settings, ...update };
    const opens = next.visibility !== "private" && next.public_chat_enabled;
    const wasOpen = settings.visibility !== "private" && settings.public_chat_enabled;
    if (opens && !wasOpen) setPending(update);
    else void apply(update, success);
  }

  async function saveSlug(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const data = await changeSlug(cloneId, slug.trim().toLowerCase());
      setSettings(data);
      setSlug(data.slug);
      setNotice({ kind: "success", text: "Link name saved. Old links stop working." });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not change the link name." });
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!reachable) return;
    if ((await copyLink(navigator, shareUrl)) === "copied") {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      setNotice({ kind: "error", text: "Couldn't copy. Select the link and copy it by hand." });
    }
  }

  /** The phone's share sheet (Web Share API), or copying the link where it isn't available. */
  async function share() {
    if (!reachable || !clone) return;
    setShareStatus(null);
    const outcome = await shareOrCopy(navigator, shareDataFor(clone.name, shareUrl));
    if (outcome === "copied") setShareStatus("Link copied. Paste it anywhere to share.");
    else if (outcome === "failed") setShareStatus("Couldn't share or copy. Select the link and copy it by hand.");
    else if (outcome === "shared") setShareStatus("Shared.");
  }

  if (loadError) return <ApiErrorState error={loadError} thing="clone" onRetry={load} />;
  if (!clone || !settings) return <StatusMessage title="Loading sharing settings…" />;

  const toggles: { key: "public_chat_enabled" | "public_voice_enabled" | "public_avatar_enabled"; label: string; help: string; disabled: boolean }[] = [
    { key: "public_chat_enabled", label: "Public Chat", help: "Visitors can chat with your clone without an account.", disabled: false },
    {
      key: "public_voice_enabled",
      label: "Public Voice",
      help: settings.voice_available ? "Visitors can speak and hear answers." : "Set up voice first.",
      disabled: !settings.public_chat_enabled || !settings.voice_available,
    },
    {
      key: "public_avatar_enabled",
      label: "Public Avatar",
      help: settings.avatar_available ? "Visitors can get talking-avatar video answers." : "Set up and turn on the avatar first.",
      disabled: !settings.public_chat_enabled || !settings.avatar_available,
    },
  ];

  return (
    <div className="mx-auto max-w-3xl px-4 pb-8 pt-6 sm:px-6 sm:pb-12 sm:pt-12">
      <Link href={`/clone/${clone.id}/details`} className="inline-flex min-h-11 items-center text-sm text-muted hover:text-white md:min-h-0">
        ← Back to {clone.name}
      </Link>
      <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Share Clone</h1>
      <p className="mt-2 text-muted">Decide who can open {clone.name}, and what visitors can use.</p>
      <p className="mt-3 rounded-xl border border-amber-400/30 bg-amber-400/5 px-4 py-3 text-sm text-amber-100">
        Only content you mark <strong>Public</strong> is used for visitors: {settings.public_document_count} public{" "}
        <Link href={`/clone/${clone.id}/knowledge`} className="underline">knowledge sources</Link> and{" "}
        {settings.public_memory_count} public approved{" "}
        <Link href={`/clone/${clone.id}/memory`} className="underline">memories</Link>. Everything else stays private.
      </p>
      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      <section className="mt-8 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="visibility-heading">
        <h2 id="visibility-heading" className="text-lg font-semibold">Visibility</h2>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Visibility">
          {VISIBILITY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={settings.visibility === option.value}
              disabled={busy}
              onClick={() => settings.visibility !== option.value && request({ visibility: option.value }, `Visibility set to ${option.label}.`)}
              className={cn(
                "min-h-11 rounded-xl border px-4 py-3 text-left transition",
                settings.visibility === option.value ? "border-accent bg-accent/10" : "border-border hover:border-accent/50",
              )}
            >
              <span className="block font-medium">{option.label}</span>
              <span className="mt-0.5 block text-xs text-muted">{option.help}</span>
            </button>
          ))}
        </div>

        <div className="mt-6 space-y-4">
          {toggles.map((toggle) => (
            <label key={toggle.key} className={cn("flex min-h-11 items-center gap-3 text-sm", toggle.disabled ? "opacity-60" : "cursor-pointer")}>
              <input
                id={toggle.key}
                type="checkbox"
                checked={settings[toggle.key]}
                disabled={busy || (toggle.disabled && !settings[toggle.key])}
                onChange={(e) => request({ [toggle.key]: e.target.checked }, `${toggle.label} ${e.target.checked ? "on" : "off"}.`)}
                className="accent-accent"
              />
              <span>
                <span className="font-medium">{toggle.label}</span>
                <span className="block text-xs text-muted">{toggle.help}</span>
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="link-heading">
        <h2 id="link-heading" className="text-lg font-semibold">Public link</h2>
        <form onSubmit={saveSlug} className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
          <label htmlFor="slug" className="shrink-0 text-sm text-muted">{origin}/c/</label>
          <input id="slug" value={slug} onChange={(e) => setSlug(e.target.value)} maxLength={50} className={`${inputClass} max-sm:text-base`} />
          <button type="submit" disabled={busy || slug === settings.slug} className="min-h-11 shrink-0 rounded-xl border border-accent/50 px-4 py-2.5 text-sm text-accent-soft hover:bg-accent/10 disabled:opacity-50">
            Save Link Name
          </button>
        </form>
        <p className="mt-1 text-xs text-muted">3–50 lowercase letters, numbers and hyphens.</p>

        {reachable ? (
          <div className="mt-5 flex flex-col gap-5 sm:flex-row">
            <div className="min-w-0 flex-1 space-y-3">
              <p className="break-all rounded-lg border border-border bg-surface px-3 py-2 text-sm" data-testid="share-url">{shareUrl}</p>
              <div className="grid grid-cols-1 gap-2 min-[400px]:flex min-[400px]:flex-wrap">
                <button
                  type="button"
                  onClick={() => void share()}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-ink hover:bg-accent/90"
                >
                  <span aria-hidden>↗</span>
                  {clone && typeof navigator !== "undefined" && hasNativeShare(navigator, shareDataFor(clone.name, shareUrl))
                    ? "Share this AI Clone"
                    : "Share this AI Clone (copy link)"}
                </button>
                <button
                  type="button"
                  onClick={() => void copy()}
                  className="inline-flex min-h-11 items-center justify-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
                >
                  {copied ? "✓ Copied!" : "Copy Link"}
                </button>
                <a
                  href={settings.share_path}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-11 items-center justify-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
                >
                  Preview as Visitor
                </a>
              </div>
              {shareStatus && (
                <p className="text-xs text-emerald-200" role="status">
                  {shareStatus}
                </p>
              )}
              <p className="text-xs text-muted">The public page never shows your account, private documents or memories.</p>
            </div>
            {qr && (
              // eslint-disable-next-line @next/next/no-img-element -- a generated data URL
              <img src={qr} alt={`QR code for ${shareUrl}`} className="mx-auto h-40 w-40 shrink-0 rounded-xl bg-white p-2 sm:mx-0" />
            )}
          </div>
        ) : (
          <p className="mt-5 rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted">
            Make the clone Unlisted or Public and turn on Public Chat to get a share link.
          </p>
        )}
      </section>

      <MarketplaceSettingsCard
        cloneId={cloneId}
        refreshKey={`${settings.visibility}:${settings.public_chat_enabled}:${settings.public_voice_enabled}:${settings.public_avatar_enabled}:${settings.slug}`}
      />

      <ConfirmDialog
        open={pending !== null}
        title="Enable Public Clone?"
        message="Your AI Clone will be accessible to people with the link or through public discovery depending on visibility settings. Only content explicitly marked public will be used."
        confirmLabel="Enable Public Clone"
        busyLabel="Saving…"
        busy={busy}
        onConfirm={() => pending && apply(pending, "Your clone is now open to visitors.")}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
