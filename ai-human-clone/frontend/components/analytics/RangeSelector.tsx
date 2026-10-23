"use client";

import { useId } from "react";

/** Segmented control built from native radio buttons (arrow keys work without extra code). */
export function Segmented<T extends string>({
  legend,
  options,
  value,
  onChange,
  wrap = false,
}: {
  wrap?: boolean;
  legend: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const name = useId();
  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">{legend}</legend>
      <div
        className={`grid gap-1 rounded-xl border border-border bg-surface p-1 ${wrap ? "grid-cols-2 sm:grid-cols-4" : ""}`}
        style={wrap ? undefined : { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
      >
        {options.map((option) => (
          <label key={option.value} className="relative block min-w-0">
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="peer sr-only"
            />
            <span className="flex min-h-11 cursor-pointer items-center justify-center truncate rounded-lg px-2 text-sm text-muted peer-checked:bg-accent/25 peer-checked:font-medium peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent hover:text-white">
              {option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
