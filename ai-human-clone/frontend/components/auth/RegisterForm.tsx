"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Field, FormAlert, inputClass, primaryButtonClass } from "@/components/FormField";
import { registerAccount } from "@/lib/api";
import { PASSWORD_RULE, USERNAME_RULE, validateEmail, validatePassword, validateUsername } from "@/lib/validation";

interface Values {
  fullName: string;
  username: string;
  email: string;
  password: string;
  confirmPassword: string;
}

type Errors = Partial<Record<keyof Values, string>>;

const EMPTY: Values = { fullName: "", username: "", email: "", password: "", confirmPassword: "" };

function validate(values: Values): Errors {
  const errors: Errors = {
    fullName: values.fullName.trim() ? undefined : "Full name is required.",
    username: validateUsername(values.username),
    email: validateEmail(values.email),
    password: validatePassword(values.password),
    confirmPassword:
      values.confirmPassword !== values.password ? "Passwords do not match." : undefined,
  };
  return Object.fromEntries(Object.entries(errors).filter(([, v]) => v)) as Errors;
}

export function RegisterForm() {
  const router = useRouter();
  const { status, setUser } = useAuth();
  const [values, setValues] = useState<Values>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  // Already logged in: nothing to do here.
  useEffect(() => {
    if (status === "authenticated" && !submitting) router.replace("/dashboard");
  }, [status, submitting, router]);

  const update = (field: keyof Values) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setValues((prev) => ({ ...prev, [field]: event.target.value }));

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validate(values);
    setErrors(nextErrors);
    const firstInvalid = Object.keys(nextErrors)[0];
    if (firstInvalid) {
      // Field keys are the input ids: take keyboard and screen-reader users to the first problem.
      document.getElementById(firstInvalid)?.focus();
      return;
    }

    setSubmitting(true);
    setApiError(null);
    try {
      // Registering also starts a session (the API sets the cookie).
      const user = await registerAccount({
        full_name: values.fullName,
        username: values.username.trim().toLowerCase(),
        email: values.email.trim(),
        password: values.password,
      });
      setUser(user);
      router.push("/dashboard");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not create the account.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-busy={submitting} className="space-y-5">
      <Field label="Full Name" htmlFor="fullName" error={errors.fullName}>
        <input id="fullName" name="name" autoComplete="name" autoCapitalize="words" enterKeyHint="next" required value={values.fullName} onChange={update("fullName")} placeholder="Nafees Ahmed" className={inputClass} />
      </Field>
      <Field label="Username" htmlFor="username" hint={USERNAME_RULE} error={errors.username}>
        <input id="username" name="username" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} enterKeyHint="next" required value={values.username} onChange={update("username")} placeholder="nafees_ahmed" className={inputClass} />
      </Field>
      <Field label="Email" htmlFor="email" error={errors.email}>
        <input id="email" name="email" type="email" inputMode="email" autoComplete="email" autoCapitalize="none" spellCheck={false} enterKeyHint="next" required value={values.email} onChange={update("email")} placeholder="abc@example.com" className={inputClass} />
      </Field>
      <Field label="Password" htmlFor="password" hint={PASSWORD_RULE} error={errors.password}>
        <input id="password" name="new-password" type="password" autoComplete="new-password" enterKeyHint="next" required value={values.password} onChange={update("password")} className={inputClass} />
      </Field>
      <Field label="Confirm Password" htmlFor="confirmPassword" error={errors.confirmPassword}>
        <input id="confirmPassword" name="confirm-password" type="password" autoComplete="new-password" enterKeyHint="go" required value={values.confirmPassword} onChange={update("confirmPassword")} className={inputClass} />
      </Field>

      {apiError && <FormAlert>{apiError}</FormAlert>}

      <button type="submit" disabled={submitting} className={primaryButtonClass}>
        {submitting ? "Creating account…" : "Create Account"}
      </button>
    </form>
  );
}
