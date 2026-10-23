"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { ChoiceGroup } from "@/components/clone/ChoiceGroup";
import { SkillsInput } from "@/components/clone/SkillsInput";
import { Field, FormAlert, inputClass, primaryButtonClass } from "@/components/FormField";
import { COMMUNICATION_STYLES, LANGUAGES, RESPONSE_LENGTHS, STATUSES, VISIBILITIES } from "@/lib/clone-options";
import type { CloneProfile, CloneSettings } from "@/types/clone";

type Mode = "create" | "edit";

interface CloneFormProps {
  mode: Mode;
  initial?: CloneProfile;
  cancelHref: string;
  /** Called with the cleaned settings; throw to show an error. */
  onSubmit: (settings: CloneSettings, ownerConsent: boolean) => Promise<void>;
}

const LIMITS = { name: 120, tagline: 160, bio: 5000, profession: 120, personality: 2000, avatar: 500 };

type Errors = Partial<Record<"name" | "tagline" | "bio" | "profession" | "personality_description" | "avatar_url" | "consent", string>>;

function fromClone(clone?: CloneProfile): CloneSettings {
  return {
    name: clone?.name ?? "",
    tagline: clone?.tagline ?? "",
    bio: clone?.bio ?? "",
    profession: clone?.profession ?? "",
    skills: clone?.skills ?? [],
    preferred_language: clone?.preferred_language ?? "English",
    communication_style: clone?.communication_style ?? "Friendly",
    personality_description: clone?.personality_description ?? "",
    response_length: clone?.response_length ?? "medium",
    visibility: clone?.visibility ?? "private",
    avatar_url: clone?.avatar_url ?? "",
    status: clone?.status ?? "active",
  };
}

const FIELD_ORDER: (keyof Errors)[] = ["name", "tagline", "bio", "profession", "avatar_url", "personality_description", "consent"];

function withoutError(errors: Errors, key: keyof Errors): Errors {
  const next = { ...errors };
  delete next[key];
  return next;
}

const text = (value: string | null) => (value ?? "").trim();
const optional = (value: string | null) => text(value) || null;

function validate(values: CloneSettings, consent: boolean, mode: Mode): Errors {
  const errors: Errors = {};
  const tooLong = (value: string | null, max: number) => text(value).length > max && `Keep it under ${max} characters.`;
  if (!text(values.name)) errors.name = "Clone name is required.";
  else if (tooLong(values.name, LIMITS.name)) errors.name = `Keep it under ${LIMITS.name} characters.`;
  errors.tagline = tooLong(values.tagline, LIMITS.tagline) || undefined;
  errors.bio = tooLong(values.bio, LIMITS.bio) || undefined;
  errors.profession = tooLong(values.profession, LIMITS.profession) || undefined;
  errors.personality_description = tooLong(values.personality_description, LIMITS.personality) || undefined;
  const avatar = text(values.avatar_url);
  if (avatar && !/^https?:\/\/[^\s/]+\.[^\s]+$/i.test(avatar)) errors.avatar_url = "Enter a full http(s) image URL, or leave it empty.";
  if (mode === "create" && !consent) errors.consent = "You can only create a clone of yourself, with your consent.";
  return Object.fromEntries(Object.entries(errors).filter(([, v]) => v)) as Errors;
}

function Section({ step, title, description, children }: { step: number; title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-surface-raised p-5 sm:p-7">
      <div className="mb-5 flex items-start gap-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent/15 text-sm font-semibold text-accent-soft">{step}</span>
        <div>
          <h2 className="font-semibold">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
        </div>
      </div>
      <div className="space-y-5">{children}</div>
    </section>
  );
}

export function CloneForm({ mode, initial, cancelHref, onSubmit }: CloneFormProps) {
  const [values, setValues] = useState<CloneSettings>(() => fromClone(initial));
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const set = <K extends keyof CloneSettings>(key: K, value: CloneSettings[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    // Editing a field clears its error, so fixed problems stop showing.
    if (key in errors) setErrors((prev) => withoutError(prev, key as keyof Errors));
  };
  const bind = (key: "name" | "tagline" | "bio" | "profession" | "personality_description" | "avatar_url") => ({
    value: values[key] ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(key, e.target.value),
  });

  // Saved values that aren't in the preset lists (e.g. older free-text styles) stay selectable.
  const languages = values.preferred_language && !LANGUAGES.includes(values.preferred_language)
    ? [...LANGUAGES, values.preferred_language]
    : LANGUAGES;
  const styles = values.communication_style && !COMMUNICATION_STYLES.includes(values.communication_style)
    ? [...COMMUNICATION_STYLES, values.communication_style]
    : COMMUNICATION_STYLES;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validate(values, consent, mode);
    setErrors(nextErrors);
    const firstError = FIELD_ORDER.find((key) => nextErrors[key]);
    if (firstError) {
      // Take the user to the first problem (values stay as typed).
      requestAnimationFrame(() => document.getElementById(firstError === "consent" ? "owner_consent" : firstError)?.focus());
      return;
    }

    setSubmitting(true);
    setApiError(null);
    try {
      await onSubmit(
        {
          ...values,
          name: text(values.name),
          tagline: optional(values.tagline),
          bio: optional(values.bio),
          profession: optional(values.profession),
          preferred_language: optional(values.preferred_language),
          communication_style: optional(values.communication_style),
          personality_description: optional(values.personality_description),
          avatar_url: optional(values.avatar_url),
        },
        consent,
      );
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Something went wrong. Please try again.");
      setSubmitting(false);
    }
  }

  const busyLabel = mode === "create" ? "Creating your AI Clone..." : "Saving changes...";
  const submitLabel = mode === "create" ? "Create My AI Clone" : "Save Changes";

  return (
    <form onSubmit={handleSubmit} noValidate aria-busy={submitting} className="space-y-6">
      <Section step={1} title="Basic Information">
        <Field label="Clone Name *" htmlFor="name" error={errors.name}>
          <input id="name" {...bind("name")} autoComplete="off" autoCapitalize="words" enterKeyHint="next" required maxLength={LIMITS.name} placeholder="AI Human Clone" className={inputClass} />
        </Field>
        <Field label="Tagline" htmlFor="tagline" hint="Optional" error={errors.tagline}>
          <input id="tagline" {...bind("tagline")} autoComplete="off" enterKeyHint="next" maxLength={LIMITS.tagline} placeholder="Ask my digital AI version" className={inputClass} />
        </Field>
        <Field label="Bio / About Me" htmlFor="bio" error={errors.bio}>
          <textarea id="bio" rows={4} {...bind("bio")} maxLength={LIMITS.bio} placeholder="Who you are, what you do, what you care about." className={inputClass} />
        </Field>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Field label="Profession" htmlFor="profession" error={errors.profession}>
            <input id="profession" {...bind("profession")} autoComplete="organization-title" enterKeyHint="next" maxLength={LIMITS.profession} placeholder="Software Developer" className={inputClass} />
          </Field>
          <Field label="Avatar Image URL" htmlFor="avatar_url" hint="Optional" error={errors.avatar_url}>
            <input id="avatar_url" type="url" inputMode="url" autoComplete="off" autoCapitalize="none" spellCheck={false} enterKeyHint="next" {...bind("avatar_url")} maxLength={LIMITS.avatar} placeholder="https://…" className={inputClass} />
          </Field>
        </div>
      </Section>

      <Section step={2} title="Skills" description="Press Enter after each skill.">
        <SkillsInput id="skills" skills={values.skills} onChange={(skills) => set("skills", skills)} />
      </Section>

      <Section step={3} title="Language" description="The language your clone replies in.">
        <label htmlFor="preferred_language" className="sr-only">Preferred Language</label>
        <select
          id="preferred_language"
          value={values.preferred_language ?? ""}
          onChange={(e) => set("preferred_language", e.target.value)}
          className={inputClass}
        >
          {languages.map((language) => (
            <option key={language} value={language}>{language}</option>
          ))}
        </select>
      </Section>

      <Section step={4} title="Communication Style" description="Pick one primary style.">
        <ChoiceGroup
          name="communication_style"
          label="Communication Style"
          columns={5}
          choices={styles.map((style) => ({ value: style, label: style }))}
          value={values.communication_style}
          onChange={(style) => set("communication_style", style)}
        />
      </Section>

      <Section step={5} title="Personality" description="Describe how your AI Clone should communicate.">
        <Field label="Personality" htmlFor="personality_description" error={errors.personality_description}>
          <textarea
            id="personality_description"
            rows={4}
            {...bind("personality_description")}
            maxLength={LIMITS.personality}
            placeholder="Talk in a friendly way, explain difficult things simply, and keep answers easy to understand."
            className={inputClass}
          />
        </Field>
      </Section>

      <Section step={6} title="Response Length">
        <ChoiceGroup
          name="response_length"
          label="Response Length"
          choices={RESPONSE_LENGTHS}
          value={values.response_length}
          onChange={(length) => set("response_length", length)}
        />
      </Section>

      <Section step={7} title="Privacy">
        <ChoiceGroup
          name="visibility"
          label="Visibility"
          choices={VISIBILITIES}
          value={values.visibility}
          onChange={(visibility) => set("visibility", visibility)}
        />
      </Section>

      {mode === "edit" && (
        <Section step={8} title="Status">
          <ChoiceGroup
            name="status"
            label="Status"
            choices={STATUSES}
            value={values.status}
            onChange={(status) => set("status", status)}
          />
        </Section>
      )}

      {mode === "create" && (
        <div>
          <label htmlFor="owner_consent" className="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border border-border bg-surface-raised p-4 text-sm text-gray-200">
            <input
              id="owner_consent"
              type="checkbox"
              required
              aria-invalid={errors.consent ? true : undefined}
              aria-describedby={errors.consent ? "owner_consent-error" : undefined}
              checked={consent}
              onChange={(e) => {
                setConsent(e.target.checked);
                setErrors((prev) => withoutError(prev, "consent"));
              }}
              className="mt-0.5 h-5 w-5 shrink-0 accent-accent"
            />
            I am creating an AI clone of myself, and I understand people chatting with it will be told they are
            talking to an AI.
          </label>
          {errors.consent && (
            <p id="owner_consent-error" className="mt-1.5 text-sm text-rose-300">
              <span aria-hidden="true">⚠ </span>
              {errors.consent}
            </p>
          )}
        </div>
      )}

      {Object.keys(errors).length > 0 && <FormAlert>Please fix the highlighted fields.</FormAlert>}
      {apiError && <FormAlert>{apiError}</FormAlert>}

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Link href={cancelHref} className="flex min-h-12 items-center justify-center rounded-xl border border-border px-5 py-3 text-center text-sm hover:border-accent">
          Cancel
        </Link>
        <button type="submit" disabled={submitting} className={`${primaryButtonClass} sm:w-auto sm:px-8`}>
          {submitting ? busyLabel : submitLabel}
        </button>
      </div>
    </form>
  );
}
