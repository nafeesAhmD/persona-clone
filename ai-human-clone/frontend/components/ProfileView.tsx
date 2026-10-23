"use client";

import { type FormEvent, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Field, FormAlert, inputClass, primaryButtonClass } from "@/components/FormField";
import { changePassword, updateProfile } from "@/lib/api";
import { PASSWORD_RULE, USERNAME_RULE, validatePassword, validateUsername } from "@/lib/validation";
import type { User } from "@/types/auth";

type Mode = "view" | "edit" | "password";

function memberSince(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function ProfileView() {
  const { user, setUser } = useAuth();
  const [mode, setMode] = useState<Mode>("view");
  const [notice, setNotice] = useState<string | null>(null);

  if (!user) return null; // RequireAuth renders this only when logged in.

  function done(message: string, updated?: User) {
    if (updated) setUser(updated);
    setNotice(message);
    setMode("view");
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8 sm:px-6 sm:py-16">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Profile</h1>

      {notice && (
        <div className="mt-6">
          <FormAlert kind="success">{notice}</FormAlert>
        </div>
      )}

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-8">
        {mode === "view" && (
          <>
            <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              <Detail label="Full Name" value={user.full_name || "—"} />
              <Detail label="Username" value={`@${user.username}`} />
              <Detail label="Email" value={user.email} />
              <Detail label="Member Since" value={memberSince(user.created_at)} />
            </dl>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <button
                type="button"
                onClick={() => { setNotice(null); setMode("edit"); }}
                className="min-h-11 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-ink hover:bg-accent/90"
              >
                Edit Profile
              </button>
              <button
                type="button"
                onClick={() => { setNotice(null); setMode("password"); }}
                className="min-h-11 rounded-xl border border-border px-5 py-2.5 text-sm hover:border-accent"
              >
                Change Password
              </button>
            </div>
          </>
        )}
        {mode === "edit" && (
          <EditProfileForm user={user} onCancel={() => setMode("view")} onSaved={(u) => done("Profile updated.", u)} />
        )}
        {mode === "password" && (
          <ChangePasswordForm onCancel={() => setMode("view")} onSaved={() => done("Password changed.")} />
        )}
      </section>
    </main>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 break-words">{value}</dd>
    </div>
  );
}

function FormButtons({ submitting, label, onCancel }: { submitting: boolean; label: string; onCancel: () => void }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <button type="submit" disabled={submitting} className={`${primaryButtonClass} sm:w-auto`}>
        {submitting ? "Saving…" : label}
      </button>
      <button type="button" onClick={onCancel} disabled={submitting} className="min-h-12 rounded-xl border border-border px-5 py-3 text-sm hover:border-accent disabled:opacity-50">
        Cancel
      </button>
    </div>
  );
}

function EditProfileForm({ user, onCancel, onSaved }: { user: User; onCancel: () => void; onSaved: (user: User) => void }) {
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [username, setUsername] = useState(user.username);
  const [errors, setErrors] = useState<{ fullName?: string; username?: string }>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = {
      fullName: fullName.trim() ? undefined : "Full name is required.",
      username: validateUsername(username),
    };
    setErrors(nextErrors);
    if (nextErrors.fullName || nextErrors.username) return;

    setSubmitting(true);
    setApiError(null);
    try {
      onSaved(await updateProfile({ full_name: fullName.trim(), username: username.trim().toLowerCase() }));
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not update the profile.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-busy={submitting} className="space-y-5">
      <h2 className="font-semibold">Edit Profile</h2>
      <Field label="Full Name" htmlFor="fullName" error={errors.fullName}>
        <input id="fullName" name="name" autoComplete="name" autoCapitalize="words" enterKeyHint="next" required value={fullName} onChange={(e) => setFullName(e.target.value)} className={inputClass} />
      </Field>
      <Field label="Username" htmlFor="username" hint={USERNAME_RULE} error={errors.username}>
        <input id="username" name="username" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} enterKeyHint="done" required value={username} onChange={(e) => setUsername(e.target.value)} className={inputClass} />
      </Field>
      <p className="text-xs text-muted">Email can&apos;t be changed yet.</p>
      {apiError && <FormAlert>{apiError}</FormAlert>}
      <FormButtons submitting={submitting} label="Save Changes" onCancel={onCancel} />
    </form>
  );
}

function ChangePasswordForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = {
      current: current ? undefined : "Enter your current password.",
      next: validatePassword(next) ?? (next === current ? "Choose a different password." : undefined),
      confirm: confirm === next ? undefined : "Passwords do not match.",
    };
    setErrors(nextErrors);
    if (nextErrors.current || nextErrors.next || nextErrors.confirm) return;

    setSubmitting(true);
    setApiError(null);
    try {
      await changePassword({ current_password: current, new_password: next });
      onSaved();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not change the password.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-busy={submitting} className="space-y-5">
      <h2 className="font-semibold">Change Password</h2>
      <Field label="Current Password" htmlFor="currentPassword" error={errors.current}>
        <input id="currentPassword" name="current-password" type="password" autoComplete="current-password" enterKeyHint="next" required value={current} onChange={(e) => setCurrent(e.target.value)} className={inputClass} />
      </Field>
      <Field label="New Password" htmlFor="newPassword" hint={PASSWORD_RULE} error={errors.next}>
        <input id="newPassword" name="new-password" type="password" autoComplete="new-password" enterKeyHint="next" required value={next} onChange={(e) => setNext(e.target.value)} className={inputClass} />
      </Field>
      <Field label="Confirm New Password" htmlFor="confirmPassword" error={errors.confirm}>
        <input id="confirmPassword" name="confirm-password" type="password" autoComplete="new-password" enterKeyHint="done" required value={confirm} onChange={(e) => setConfirm(e.target.value)} className={inputClass} />
      </Field>
      {apiError && <FormAlert>{apiError}</FormAlert>}
      <FormButtons submitting={submitting} label="Change Password" onCancel={onCancel} />
    </form>
  );
}
