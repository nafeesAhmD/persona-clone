"use client";

import { cn } from "@/lib/utils";

export type ChatMode = "normal" | "agent";

const OPTIONS: { value: ChatMode; icon: string; label: string }[] = [
  { value: "normal", icon: "💬", label: "Normal Chat" },
  { value: "agent", icon: "🤖", label: "Agent Mode" },
];

/** Normal Chat / Agent Mode. Shown only when the clone's agent is on and the viewer may run it. */
export function ChatModeSwitch({
  mode,
  onChange,
  disabled = false,
}: {
  mode: ChatMode;
  onChange: (mode: ChatMode) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <div role="group" aria-label="Chat mode" className="inline-flex rounded-xl border border-border bg-surface-raised p-0.5">
        {OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={mode === option.value}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex min-h-11 items-center gap-1 rounded-lg px-3 transition disabled:cursor-not-allowed disabled:opacity-60 md:min-h-8",
              mode === option.value ? "bg-cyan/15 font-medium text-cyan" : "text-muted hover:text-white",
            )}
          >
            <span aria-hidden="true">{option.icon}</span>
            {option.label}
          </button>
        ))}
      </div>
      {mode === "agent" && (
        <p className="min-w-0 text-muted compact:hidden">Works in visible steps with the tools its owner allowed.</p>
      )}
    </div>
  );
}
