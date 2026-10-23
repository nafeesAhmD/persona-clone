import { Children, cloneElement, isValidElement } from "react";

/** Text inputs: 16px on phones (globals.css) so iOS doesn't zoom; 44px+ tall. */
export const inputClass =
  "w-full min-h-11 rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none! placeholder:text-muted/70 focus:border-accent aria-[invalid=true]:border-rose-500/70";

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}

type ControlProps = { "aria-invalid"?: boolean | "true" | "false"; "aria-describedby"?: string };

/**
 * Label + control + hint + inline error. The single child control gets
 * aria-invalid and aria-describedby (hint/error) automatically.
 */
export function Field({ label, htmlFor, hint, error, children }: FieldProps) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  const describedBy = errorId; // the hint is already part of the label text

  const only = Children.count(children) === 1 ? Children.toArray(children)[0] : null;
  const control =
    only && isValidElement<ControlProps>(only)
      ? cloneElement(only, {
          "aria-invalid": error ? true : only.props["aria-invalid"],
          "aria-describedby": [only.props["aria-describedby"], describedBy].filter(Boolean).join(" ") || undefined,
        })
      : children;

  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-3 text-sm font-medium">
        {label}
        {hint && (
          <span id={hintId} className="text-xs font-normal text-muted">
            {hint}
          </span>
        )}
      </label>
      {control}
      {error && (
        <p id={errorId} className="mt-1.5 flex items-start gap-1 text-sm text-rose-300">
          <span aria-hidden="true">⚠</span>
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}

export function FormAlert({ kind = "error", children }: { kind?: "error" | "success"; children: React.ReactNode }) {
  const styles =
    kind === "error"
      ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
  return (
    <p role={kind === "error" ? "alert" : "status"} className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${styles}`}>
      {/* Icon + text, so the meaning doesn't depend on colour alone. */}
      <span aria-hidden="true">{kind === "error" ? "⚠" : "✓"}</span>
      <span className="min-w-0">{children}</span>
    </p>
  );
}

export const primaryButtonClass =
  "w-full min-h-12 rounded-xl bg-accent px-5 py-3 font-medium text-ink transition hover:bg-accent/90 disabled:cursor-wait disabled:opacity-60";
