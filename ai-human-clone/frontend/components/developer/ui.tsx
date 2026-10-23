"use client";

import { useEffect, useState } from "react";

import { buttonClass, inputClass } from "@/components/admin/ui";
import { developerApi } from "@/lib/developerApi";
import type { OrganizationOption } from "@/types/developer";

/** Copies text to the clipboard and says so (screen readers too). */
export function CopyButton({ text, label = "Copy", className = buttonClass }: { text: string; label?: string; className?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <button type="button" className={className} onClick={copy} aria-live="polite">
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed — select and copy" : label}
    </button>
  );
}

/**
 * A key or signing secret shown exactly once. It lives only in component state:
 * after "I've saved it" it's dropped and can never be shown again.
 */
export function SecretOnce({
  title,
  secret,
  note,
  onDone,
}: {
  title: string;
  secret: string;
  note: string;
  onDone: () => void;
}) {
  return (
    <section
      role="alert"
      aria-label={title}
      className="mb-6 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 sm:p-5"
    >
      <h2 className="text-sm font-semibold text-amber-200">{title}</h2>
      <p className="mt-1 text-sm text-amber-100">{note}</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <code
          className="block min-w-0 flex-1 select-all break-all rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-white"
          aria-label="Secret value"
        >
          {secret}
        </code>
        <CopyButton text={secret} />
      </div>
      <button type="button" className={`${buttonClass} mt-3`} onClick={onDone}>
        I&apos;ve saved it — hide
      </button>
    </section>
  );
}

/** Personal keys or one of the user's organizations (the server checks owner/admin). */
export function useOrganizations() {
  const [orgs, setOrgs] = useState<OrganizationOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    developerApi
      .organizations()
      .then((list) => !cancelled && setOrgs(list.map((o) => ({ id: o.id, name: o.name }))))
      .catch(() => !cancelled && setOrgs([]));
    return () => {
      cancelled = true;
    };
  }, []);
  return orgs;
}

export function OwnerSelect({
  orgs,
  value,
  onChange,
  id = "owner-select",
  label = "Account",
}: {
  orgs: OrganizationOption[];
  value: string;
  onChange: (value: string) => void;
  id?: string;
  label?: string;
}) {
  if (orgs.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <label htmlFor={id} className="text-sm text-muted">
        {label}
      </label>
      <select id={id} className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Personal</option>
        {orgs.map((org) => (
          <option key={org.id} value={org.id}>
            {org.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  return (
    <div className="relative">
      <pre
        tabIndex={0}
        aria-label={label}
        className="overflow-x-auto rounded-xl border border-border bg-surface p-4 pr-20 font-mono text-xs leading-relaxed text-gray-100"
      >
        <code>{code}</code>
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton text={code} className="min-h-10 rounded-md border border-border bg-surface-raised px-3 py-1.5 text-xs text-white hover:bg-surface sm:min-h-0 sm:px-2.5" />
      </div>
    </div>
  );
}

/** curl / JavaScript / Python versions of one example, as accessible tabs. */
export function CodeTabs({ id, examples }: { id: string; examples: { label: string; code: string }[] }) {
  const [active, setActive] = useState(0);
  return (
    <div>
      <div role="tablist" aria-label="Language" className="mb-2 flex flex-wrap gap-1">
        {examples.map((example, index) => (
          <button
            key={example.label}
            type="button"
            role="tab"
            id={`${id}-tab-${index}`}
            aria-selected={active === index}
            aria-controls={`${id}-panel-${index}`}
            tabIndex={active === index ? 0 : -1}
            onClick={() => setActive(index)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") setActive((active + 1) % examples.length);
              if (e.key === "ArrowLeft") setActive((active - 1 + examples.length) % examples.length);
            }}
            className={`min-h-11 rounded-lg px-3 py-1 text-xs md:min-h-0 ${
              active === index ? "bg-accent/20 text-white" : "text-muted hover:bg-surface-raised hover:text-white"
            }`}
          >
            {example.label}
          </button>
        ))}
      </div>
      {examples.map((example, index) => (
        <div
          key={example.label}
          role="tabpanel"
          id={`${id}-panel-${index}`}
          aria-labelledby={`${id}-tab-${index}`}
          hidden={active !== index}
        >
          <CodeBlock code={example.code} label={`${example.label} example`} />
        </div>
      ))}
    </div>
  );
}
