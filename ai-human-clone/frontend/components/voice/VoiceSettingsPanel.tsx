"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { Field, FormAlert, inputClass } from "@/components/FormField";
import { StatusMessage } from "@/components/StatusMessage";
import { RealtimeSettingsCard } from "@/components/realtime/RealtimeSettingsCard";
import { VoiceCloneSection } from "@/components/voice/VoiceCloneSection";
import { VoiceReply } from "@/components/voice/VoiceReply";
import { ApiError, getClone, getVoiceSettings, testVoice, updateVoiceSettings } from "@/lib/api";
import { canUseBrowserVoice, speakInBrowser } from "@/lib/browserVoice";
import { voiceSupportProblem } from "@/lib/useVoiceRecorder";
import { voiceErrorMessage } from "@/lib/voiceStates";
import type { CloneProfile } from "@/types/clone";
import type { VoiceLanguage, VoiceSettings, VoiceSettingsUpdate } from "@/types/voice";

const LANGUAGES: { value: VoiceLanguage; label: string }[] = [
  { value: "auto", label: "Automatic (follow each answer)" },
  { value: "en", label: "English" },
  { value: "ur", label: "Urdu" },
];

interface Notice {
  kind: "success" | "error";
  text: string;
}

export function VoiceSettingsPanel({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [settings, setSettings] = useState<VoiceSettings | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [consentChecked, setConsentChecked] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [language, setLanguage] = useState<VoiceLanguage>("auto");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [testText, setTestText] = useState("Hello, this is my AI Clone.");
  const [testAudio, setTestAudio] = useState<string | null>(null);

  const apply = useCallback((next: VoiceSettings) => {
    setSettings(next);
    setVoiceId(next.voice_id ?? next.voices[0]?.id ?? "");
    setLanguage(next.voice_language);
    setEnabled(next.voice_enabled);
    setConsentChecked(next.voice_consent_given);
  }, []);

  const load = useCallback(() => {
    Promise.all([getClone(cloneId), getVoiceSettings(cloneId)])
      .then(([cloneData, voice]) => {
        setClone(cloneData);
        apply(voice);
        setLoadError(null);
      })
      .catch(setLoadError);
  }, [cloneId, apply]);

  useEffect(load, [load]);

  // The cloned voice changes voice_type / the voice list: refresh the settings quietly.
  const refreshSettings = useCallback(() => {
    getVoiceSettings(cloneId).then(apply).catch(() => undefined);
  }, [cloneId, apply]);

  async function save(label: string, update: VoiceSettingsUpdate, success: string) {
    setBusy(label);
    setNotice(null);
    try {
      apply(await updateVoiceSettings(cloneId, update));
      setNotice({ kind: "success", text: success });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not save the voice settings." });
    } finally {
      setBusy(null);
    }
  }

  async function runTest() {
    setBusy("test");
    setNotice(null);
    setTestAudio(null);
    const text = testText.trim() || "Hello, this is my AI Clone.";
    try {
      setTestAudio((await testVoice(cloneId, text)).audio_url);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : undefined;
      if ((status === undefined || status === 429 || status >= 500) && canUseBrowserVoice()) {
        speakInBrowser(text, () => undefined);
        setNotice({
          kind: "error",
          text: "The AI voice is busy or has reached its free limit for now, so your browser's voice was used. Try again later for the AI voice.",
        });
      } else {
        setNotice({ kind: "error", text: err instanceof Error ? err.message : "The voice test failed." });
      }
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <ApiErrorState error={loadError} thing="clone" onRetry={load} />;
  if (!clone || !settings) return <StatusMessage title="Loading voice settings…" />;

  const available = Boolean(settings.stt_provider && settings.tts_provider);
  const consented = settings.voice_consent_given;
  const selected = settings.voices.find((v) => v.id === voiceId);

  return (
    <div className="mx-auto max-w-3xl px-4 pb-8 pt-6 sm:px-6 sm:pb-12 sm:pt-12">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <Link href={`/clone/${clone.id}/details`} className="inline-flex min-h-11 items-center text-muted hover:text-white md:min-h-0">
          ← Back to {clone.name}
        </Link>
        <Link href={`/clone/${clone.id}`} className="inline-flex min-h-11 items-center text-accent-soft hover:underline md:min-h-0">
          Open chat
        </Link>
      </div>
      <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Voice</h1>
      <p className="mt-2 text-muted">Let people talk to {clone.name} and hear its answers.</p>
      <p className="mt-3 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-sm text-accent-soft">
        {settings.voice_type === "custom"
          ? "Personalised voice. It is still an AI-generated voice, not a recording of the real person."
          : "AI-generated voice. It is not the real person's voice, and the clone always presents itself as an AI representation."}
      </p>

      {!available && (
        <div className="mt-4">
          <FormAlert>
            Voice isn&apos;t available on this server: no speech-to-text or text-to-speech provider is configured
            (see STT_PROVIDER / TTS_PROVIDER in the README).
          </FormAlert>
        </div>
      )}
      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-4 sm:mt-8 sm:p-7" aria-labelledby="consent-heading">
        <h2 id="consent-heading" className="text-lg font-semibold">Voice Consent</h2>
        {consented ? (
          <>
            <p className="mt-2 text-sm text-emerald-200">
              Consent given{settings.voice_consent_at ? ` on ${new Date(settings.voice_consent_at).toLocaleString()}` : ""}.
            </p>
            <button
              type="button"
              onClick={() => save("withdraw", { voice_consent_given: false }, "Consent withdrawn. Voice is now off.")}
              disabled={busy !== null}
              className="mt-4 min-h-11 rounded-xl border border-rose-500/40 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
            >
              {busy === "withdraw" ? "Saving…" : "Withdraw consent"}
            </button>
          </>
        ) : (
          <>
            <p className="mt-2 text-sm text-muted">Voice can only be turned on after you confirm this.</p>
            <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm">
              <input
                id="voice-consent"
                type="checkbox"
                checked={consentChecked}
                onChange={(e) => setConsentChecked(e.target.checked)}
                className="mt-0.5 accent-accent"
              />
              I confirm that I have permission to use this voice for this AI Clone.
            </label>
            <button
              type="button"
              onClick={() => save("consent", { voice_consent_given: true }, "Voice consent saved.")}
              disabled={!consentChecked || busy !== null}
              className="mt-4 min-h-11 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy === "consent" ? "Saving…" : "Save Voice Consent"}
            </button>
          </>
        )}
      </section>

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-4 sm:p-7" aria-labelledby="settings-heading">
        <h2 id="settings-heading" className="text-lg font-semibold">Voice Settings</h2>
        <div className="mt-5 space-y-5">
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <input
              id="voice-enabled"
              type="checkbox"
              checked={enabled}
              disabled={!consented || !available}
              onChange={(e) => setEnabled(e.target.checked)}
              className="accent-accent"
            />
            <span>
              <span className="font-medium">Voice Enabled</span>
              <span className="block text-xs text-muted">
                {consented ? "Show the microphone in chat and speak answers." : "Give voice consent first."}
              </span>
            </span>
          </label>
          <Field label="Voice Provider" htmlFor="voice-provider">
            <select id="voice-provider" value={settings.tts_provider ?? ""} disabled className={`${inputClass} max-sm:text-base`}>
              <option value={settings.tts_provider ?? ""}>{settings.tts_provider ?? "Not configured"}</option>
            </select>
          </Field>
          <Field label="Voice" htmlFor="voice-id" hint={selected?.description}>
            <select
              id="voice-id"
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              disabled={settings.voices.length === 0}
              className={`${inputClass} max-sm:text-base`}
            >
              {settings.voices.map((voice) => (
                <option key={voice.id} value={voice.id} disabled={voice.is_custom && !consented}>
                  {voice.name} · {voice.is_custom ? "personalised voice (needs consent)" : "AI voice"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Language" htmlFor="voice-language">
            <select
              id="voice-language"
              value={language}
              onChange={(e) => setLanguage(e.target.value as VoiceLanguage)}
              className={`${inputClass} max-sm:text-base`}
            >
              {LANGUAGES.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            onClick={() =>
              save(
                "settings",
                {
                  voice_language: language,
                  ...(voiceId ? { voice_id: voiceId } : {}),
                  ...(enabled !== settings.voice_enabled ? { voice_enabled: enabled } : {}),
                },
                "Voice settings saved.",
              )
            }
            disabled={busy !== null}
            className="min-h-11 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-wait disabled:opacity-60"
          >
            {busy === "settings" ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </section>

      <VoiceCloneSection
        cloneId={clone.id}
        voiceConsent={consented}
        voiceEnabled={settings.voice_enabled}
        onChanged={refreshSettings}
      />

      <RealtimeSettingsCard cloneId={clone.id} refreshKey={settings} />

      <DeviceSupport />

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-4 sm:p-7" aria-labelledby="test-heading">
        <h2 id="test-heading" className="text-lg font-semibold">Test Voice</h2>
        <p className="mt-1 text-sm text-muted">
          {settings.voice_enabled ? "Hear the saved voice." : "Turn voice on and save to test it."}
        </p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label htmlFor="voice-test-text" className="sr-only">Text to speak</label>
          <input
            id="voice-test-text"
            value={testText}
            maxLength={500}
            onChange={(e) => setTestText(e.target.value)}
            className={`${inputClass} max-sm:text-base`}
          />
          <button
            type="button"
            onClick={runTest}
            disabled={!settings.voice_enabled || busy !== null}
            className="min-h-11 shrink-0 rounded-xl border border-accent/50 px-5 py-2.5 text-sm text-accent-soft hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "test" ? "Generating voice…" : "Test Voice"}
          </button>
        </div>
        {testAudio && (
          <div className="mt-4">
            <VoiceReply key={testAudio} audioUrl={testAudio} autoPlay />
          </div>
        )}
      </section>
    </div>
  );
}

/** What this browser/device supports for voice (text labels, not color only). */
function DeviceSupport() {
  const recording = voiceSupportProblem();
  const browserVoice = canUseBrowserVoice();
  const rows: { label: string; ok: boolean; detail: string }[] = [
    {
      label: "Microphone recording",
      ok: recording === null,
      detail: recording === null ? "Supported. The browser asks for permission the first time you tap the mic." : voiceErrorMessage(recording),
    },
    {
      label: "Browser voice (fallback)",
      ok: browserVoice,
      detail: browserVoice ? "Available when the AI voice is busy." : "Not available in this browser.",
    },
  ];
  return (
    <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-4 sm:p-7" aria-labelledby="device-heading">
      <h2 id="device-heading" className="text-lg font-semibold">This device</h2>
      <ul className="mt-3 space-y-2 text-sm">
        {rows.map((row) => (
          <li key={row.label} className="flex gap-2">
            <span aria-hidden className={row.ok ? "text-emerald-300" : "text-amber-300"}>{row.ok ? "✓" : "⚠"}</span>
            <span>
              <span className="font-medium">{row.label}: {row.ok ? "Yes" : "No"}</span>
              <span className="block text-xs text-muted">{row.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
