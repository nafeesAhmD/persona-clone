"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { StatusMessage } from "@/components/StatusMessage";
import { RealtimeVoicePanel } from "@/components/realtime/RealtimeVoicePanel";
import { getChatProfile } from "@/lib/api";
import { realtimeErrorMessage } from "@/lib/realtime/errors";
import { getRealtimeSettings } from "@/lib/realtimeApi";
import type { CloneChatProfile } from "@/types/clone";
import type { RealtimeSettings } from "@/types/realtime";

const REASON_CODE: Record<string, string> = {
  disabled: "realtime_disabled",
  provider_not_configured: "provider_not_configured",
  voice_off: "consent_missing",
  consent_missing: "consent_missing",
};

/** /clone/[id]/voice/live: a live voice conversation with a clone (owner or permitted user). */
export function LiveVoicePage({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneChatProfile | null>(null);
  const [settings, setSettings] = useState<RealtimeSettings | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    getChatProfile(cloneId)
      .then(async (profile) => {
        // Settings are owner-only; other users just try to start (the API decides).
        // Loaded before the panel shows, so it starts with the owner's speech mode.
        if (profile.is_owner) setSettings(await getRealtimeSettings(cloneId).catch(() => null));
        setError(null);
        setClone(profile);
      })
      .catch(setError);
  }, [cloneId]);

  useEffect(load, [load]);

  if (error) return <ApiErrorState error={error} thing="clone" onRetry={load} />;
  if (!clone) return <StatusMessage title="Loading…" />;

  const blocked = settings && (!settings.available || !settings.enabled);
  const reason = settings
    ? !settings.available
      ? realtimeErrorMessage(REASON_CODE[settings.reason ?? ""] ?? "provider_not_configured")
      : !settings.enabled
        ? realtimeErrorMessage("realtime_off")
        : null
    : null;

  return (
    <main className="mx-auto max-w-3xl px-4 pb-[calc(var(--app-bottom-nav-h,0px)+2rem)] pt-6 sm:px-6 sm:pt-10">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <Link href={`/clone/${clone.id}`} className="inline-flex min-h-11 items-center text-muted hover:text-white md:min-h-0">
          ← Back to chat
        </Link>
        {clone.is_owner && (
          <Link href={`/clone/${clone.id}/voice`} className="inline-flex min-h-11 items-center text-accent-soft hover:underline md:min-h-0">
            Voice settings
          </Link>
        )}
      </div>
      <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Live voice with {clone.name}</h1>
      <p className="mt-2 text-sm text-muted">
        Talk naturally: {clone.name} hears you when you stop speaking and answers out loud. Talk over the answer (or press
        &ldquo;Stop speaking&rdquo;) to interrupt. English, Urdu and Roman Urdu work as far as the server&apos;s speech
        services support them.
      </p>

      {blocked ? (
        <div className="mt-6 rounded-2xl border border-amber-500/40 bg-amber-500/5 p-4 text-sm text-amber-200" role="alert">
          <p>{reason}</p>
          {clone.is_owner && (
            <Link href={`/clone/${clone.id}/voice`} className="mt-3 inline-flex min-h-11 items-center text-accent-soft hover:underline">
              Open voice settings
            </Link>
          )}
        </div>
      ) : (
        <div className="mt-6">
          <RealtimeVoicePanel
            target={{ kind: "clone", cloneId: clone.id }}
            cloneName={clone.name}
            initialSpeechMode={settings?.speech_mode ?? "voice"}
            clonedVoice={settings?.capabilities.cloned_voice ?? false}
            maxUtteranceSeconds={settings?.limits.max_utterance_seconds}
            maxUtteranceBytes={settings?.limits.max_utterance_bytes}
          />
        </div>
      )}
    </main>
  );
}
