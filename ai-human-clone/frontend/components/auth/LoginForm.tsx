"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { safeNextPath, useAuth } from "@/components/AuthProvider";
import { Field, FormAlert, inputClass, primaryButtonClass } from "@/components/FormField";
import { ApiError, login } from "@/lib/api";
import { validateEmail } from "@/lib/validation";

function nextPath(): string {
  return safeNextPath(new URLSearchParams(window.location.search).get("next"));
}

export function LoginForm() {
  const router = useRouter();
  const { status, setUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "authenticated" && !submitting) router.replace(nextPath());
  }, [status, submitting, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = { email: validateEmail(email), password: password ? undefined : "Password is required." };
    setErrors(nextErrors);
    if (nextErrors.email || nextErrors.password) {
      // Take keyboard and screen-reader users to the first problem.
      document.getElementById(nextErrors.email ? "email" : "password")?.focus();
      return;
    }

    setSubmitting(true);
    setApiError(null);
    try {
      const user = await login({ email: email.trim(), password });
      setUser(user);
      router.replace(nextPath());
    } catch (error) {
      setApiError(
        error instanceof ApiError && error.status === 401
          ? "Invalid email or password."
          : error instanceof Error
            ? error.message
            : "Could not log in.",
      );
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-busy={submitting} className="space-y-5">
      <Field label="Email" htmlFor="email" error={errors.email}>
        <input id="email" name="email" type="email" inputMode="email" autoComplete="email" autoCapitalize="none" spellCheck={false} enterKeyHint="next" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="abc@example.com" className={inputClass} />
      </Field>
      <Field label="Password" htmlFor="password" error={errors.password}>
        <input id="password" name="password" type="password" autoComplete="current-password" enterKeyHint="go" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
      </Field>

      {apiError && <FormAlert>{apiError}</FormAlert>}

      <button type="submit" disabled={submitting} className={primaryButtonClass}>
        {submitting ? "Logging in…" : "Login"}
      </button>
    </form>
  );
}
