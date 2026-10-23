"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  ErrorNote,
  Loading,
  PageHeader,
  Panel,
  SuccessNote,
  buttonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";
import type { PlatformSettings, PlatformSettingsUpdate, RateLimitName } from "@/types/admin";

type Switch = "maintenance_mode" | "public_registration_enabled" | "public_clone_discovery_enabled" | "public_chat_enabled";

const SWITCHES: { key: Switch; label: string; help: string; risky: (on: boolean) => boolean }[] = [
  {
    key: "maintenance_mode",
    label: "Maintenance mode",
    help: "Everyone except administrators sees “System is temporarily under maintenance.” Sessions are kept.",
    risky: (on) => on,
  },
  {
    key: "public_registration_enabled",
    label: "New registrations",
    help: "When off, nobody can create an account. Existing users can still log in.",
    risky: (on) => !on,
  },
  {
    key: "public_clone_discovery_enabled",
    label: "Public discovery (Explore)",
    help: "When off, /explore lists nothing. Direct links to public and unlisted clones keep working.",
    risky: (on) => !on,
  },
  {
    key: "public_chat_enabled",
    label: "Public chat for visitors",
    help: "When off, visitors can't chat with any clone (voice and avatar too). Owners' own chats aren't affected.",
    risky: (on) => !on,
  },
];

const LIMIT_LABELS: Record<RateLimitName, string> = {
  login: "Login attempts",
  chat: "Chat messages (users)",
  public_chat: "Public chat messages",
  public_voice: "Public voice requests",
  public_avatar: "Public avatar videos",
  voice: "Voice requests (users)",
  avatar_video: "Avatar videos (users)",
};

export default function AdminSettingsPage() {
  const { data, error, loading } = useAdminData(adminApi.settings, []);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [pending, setPending] = useState<{ key: Switch; value: boolean } | null>(null);
  const [limits, setLimits] = useState<Partial<Record<RateLimitName, string>>>({});
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const current = settings ?? data;

  async function save(changes: PlatformSettingsUpdate, message: string) {
    setBusy(true);
    setSaveError(null);
    try {
      const updated = await adminApi.updateSettings(changes);
      setSettings(updated);
      setLimits({});
      setNotice(message);
      setPending(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Couldn't save settings.");
    } finally {
      setBusy(false);
    }
  }

  function saveLimits() {
    const changes: Partial<Record<RateLimitName, number | null>> = {};
    for (const [name, value] of Object.entries(limits) as [RateLimitName, string][]) {
      changes[name] = value.trim() === "" ? null : Number(value);
    }
    save({ rate_limits: changes }, "Rate limits saved.");
  }

  const switchInfo = pending ? SWITCHES.find((s) => s.key === pending.key) : null;

  return (
    <>
      <PageHeader title="Platform Settings" description="Changes apply within a few seconds and are recorded in the audit log. No API keys are stored here." />
      <SuccessNote message={notice} />
      <ErrorNote message={error ?? (pending ? null : saveError)} />
      {loading && !current && <Loading />}
      {current && (
        <div className="space-y-6">
          <Panel title="Switches">
            <ul className="divide-y divide-border">
              {SWITCHES.map((s) => {
                const on = current[s.key];
                return (
                  <li key={s.key} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="max-w-xl">
                      <p className="text-sm font-medium text-white">{s.label}</p>
                      <p className="text-xs text-muted">{s.help}</p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={on}
                      aria-label={s.label}
                      disabled={busy}
                      className={`relative h-6 w-11 rounded-full transition ${on ? (s.key === "maintenance_mode" ? "bg-amber-500" : "bg-accent") : "bg-border"}`}
                      onClick={() => {
                        const next = !on;
                        if (s.risky(next)) setPending({ key: s.key, value: next });
                        else save({ [s.key]: next }, `${s.label}: ${next ? "on" : "off"}.`);
                      }}
                    >
                      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${on ? "left-5" : "left-0.5"}`} />
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel title="Rate limits (per minute)">
            <p className="mb-3 text-xs text-muted">Leave a field empty to use the default from the environment.</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(Object.keys(LIMIT_LABELS) as RateLimitName[]).map((name) => {
                const override = current.rate_limits[name];
                return (
                  <label key={name} className="flex items-center justify-between gap-3 text-sm">
                    <span>
                      {LIMIT_LABELS[name]}
                      <span className="block text-xs text-muted">default {current.default_rate_limits[name]}</span>
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      className={`${inputClass} w-24`}
                      placeholder={String(current.default_rate_limits[name])}
                      value={limits[name] ?? (override !== undefined ? String(override) : "")}
                      onChange={(e) => setLimits((prev) => ({ ...prev, [name]: e.target.value }))}
                    />
                  </label>
                );
              })}
            </div>
            <button type="button" className={`${buttonClass} mt-4`} disabled={busy || Object.keys(limits).length === 0} onClick={saveLimits}>
              Save rate limits
            </button>
          </Panel>
          <p className="text-xs text-muted">Last changed {formatDate(current.updated_at)}</p>
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={`${pending?.value ? "Turn on" : "Turn off"}: ${switchInfo?.label ?? ""}?`}
        message={switchInfo?.help ?? ""}
        confirmLabel={pending?.value ? "Turn on" : "Turn off"}
        busy={busy}
        error={saveError}
        onConfirm={() => pending && save({ [pending.key]: pending.value }, `${switchInfo?.label}: ${pending.value ? "on" : "off"}.`)}
        onCancel={() => { setPending(null); setSaveError(null); }}
      />
    </>
  );
}
