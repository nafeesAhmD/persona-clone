"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { FormAlert } from "@/components/FormField";
import { realtimeErrorMessage } from "@/lib/realtime/errors";
import { getRealtimeSettings, updateRealtimeSettings } from "@/lib/realtimeApi";
import { cn } from "@/lib/utils";
import type { RealtimeSettings, RealtimeSettingsUpdate } from "@/types/realtime";

const REASON_CODE: Record<string, string> = {
  disabled: "realtime_disabled",
  provider_not_configured: "provider_not_configured",
  voice_off: "consent_missing",
  consent_missing: "consent_missing",
};

/** Owner settings for live voice (Phase 17), on the clone's Voice page. */
export function RealtimeSettingsCard({ cloneId, refreshKey }: { cloneId: string; refreshKey?: unknown }) {
  const [settings, setSettings] = useState<RealtimeSettings | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const load = useCallback(() => {
    getRealtimeSettings(cloneId)
      .then((data) => {
        setSettings(data);
        setLoadFailed(false);
      })
      .catch(() => setLoadFailed(true));
  }, [cloneId]);

  useEffect(load, [load, refreshKey]);

  async function save(update: RealtimeSettingsUpdate) {
    setSaving(true);
    setNotice(null);
    try {
      setSettings(await updateRealtimeSettings(cloneId, update));
      setNotice({ kind: "success", text: "Live voice settings saved." });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Couldn't save the live voice settings." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-4 sm:p-7" aria-labelledby="realtime-heading">
      <h2 id="realtime-heading" className="text-lg font-semibold">Live voice</h2>
      <p className="mt-1 text-sm text-muted">
        A hands-free conversation: speak, hear the answer, interrupt by talking over it. It uses the same knowledge, memories
        and personality as the chat.
      </p>

      {loadFailed && !settings && (
        <p className="mt-4 text-sm text-muted">Live voice settings aren&apos;t available on this server.</p>
      )}
      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      {settings && (
        <div className="mt-5 space-y-4">
          {!settings.available && (
            <FormAlert>{realtimeErrorMessage(REASON_CODE[settings.reason ?? ""] ?? "provider_not_configured")}</FormAlert>
          )}
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={settings.enabled}
              disabled={saving}
              onChange={(e) => save({ enabled: e.target.checked })}
              className="accent-accent"
            />
            <span>
              <span className="font-medium">Live voice enabled</span>
              <span className="block text-xs text-muted">You (and users allowed to chat with this clone) can start live voice.</span>
            </span>
          </label>
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={settings.public_enabled}
              disabled={saving}
              onChange={(e) => save({ public_enabled: e.target.checked })}
              className="accent-accent"
            />
            <span>
              <span className="font-medium">Allow public visitors</span>
              <span className="block text-xs text-muted">
                Off by default. Needs a public clone with public chat and public voice on. Visitors only get public knowledge.
              </span>
            </span>
          </label>
          <fieldset>
            <legend className="text-sm font-medium">Default voice of the answers</legend>
            <div className="mt-2 inline-flex rounded-xl border border-border bg-surface p-0.5 text-xs" role="radiogroup">
              {(["voice", "browser"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={settings.speech_mode === mode}
                  disabled={saving}
                  onClick={() => settings.speech_mode !== mode && save({ speech_mode: mode })}
                  className={cn(
                    "min-h-11 rounded-lg px-3 md:min-h-8",
                    settings.speech_mode === mode ? "bg-accent/20 font-medium text-accent-soft" : "text-muted hover:text-white",
                  )}
                >
                  {mode === "voice" ? (settings.capabilities.cloned_voice ? "Clone's voice" : "AI voice") : "Browser voice"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              Browser voice is instant but uses the listener&apos;s device voice. The clone&apos;s voice sounds like you, but on a
              server without a GPU each sentence can take about a minute.
            </p>
          </fieldset>
          <p className="text-xs text-muted">
            Provider: {settings.provider ?? "none"} · up to {Math.round(settings.limits.max_duration_seconds / 60)} min per session ·
            interruption {settings.capabilities.interruption ? "supported" : "not supported"}
          </p>
          <Link
            href={`/clone/${cloneId}/voice/live`}
            aria-disabled={!settings.available || !settings.enabled}
            className={cn(
              "inline-flex min-h-11 items-center rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent/90",
              (!settings.available || !settings.enabled) && "pointer-events-none opacity-50",
            )}
          >
            🎙️ Open live voice
          </Link>
        </div>
      )}
    </section>
  );
}
