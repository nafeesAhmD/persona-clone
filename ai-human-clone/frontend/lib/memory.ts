import type { CloneMemory, MemoryStatus, MemoryType } from "@/types/memory";

/** Same limit as MEMORY_MAX_LENGTH on the server. */
export const MEMORY_MAX_CHARACTERS = 1000;

export const MEMORY_TYPES: { value: MemoryType; label: string }[] = [
  { value: "fact", label: "Fact" },
  { value: "preference", label: "Preference" },
  { value: "communication_preference", label: "Communication Preference" },
  { value: "skill", label: "Skill" },
  { value: "experience", label: "Experience" },
  { value: "project", label: "Project" },
  { value: "goal", label: "Goal" },
  { value: "background", label: "Background" },
  { value: "instruction", label: "Instruction" },
  { value: "other", label: "Other" },
];

export const MEMORY_TABS: { status: MemoryStatus; label: string; icon: string; empty: string }[] = [
  {
    status: "candidate",
    label: "Pending",
    icon: "⏳",
    empty: "No suggestions waiting. In a chat with your clone, use \"Find memories\" to get some.",
  },
  { status: "approved", label: "Approved", icon: "✓", empty: "No approved memories yet. Add one, or approve a suggestion." },
  { status: "rejected", label: "Rejected", icon: "✕", empty: "Nothing rejected." },
  { status: "archived", label: "Archived", icon: "▢", empty: "Nothing archived." },
];

/** Keyboard navigation for the status tabs (WAI-ARIA tabs pattern): arrows wrap, Home/End jump. */
export function nextTab(current: MemoryStatus, key: string): MemoryStatus | null {
  const index = MEMORY_TABS.findIndex((tab) => tab.status === current);
  const last = MEMORY_TABS.length - 1;
  let next: number;
  if (key === "ArrowRight" || key === "ArrowDown") next = index >= last ? 0 : index + 1;
  else if (key === "ArrowLeft" || key === "ArrowUp") next = index <= 0 ? last : index - 1;
  else if (key === "Home") next = 0;
  else if (key === "End") next = last;
  else return null;
  return MEMORY_TABS[next].status;
}

export function memoryTypeLabel(type: MemoryType): string {
  return MEMORY_TYPES.find((t) => t.value === type)?.label ?? type;
}

export function sourceText(memory: CloneMemory): string {
  return memory.source === "manual" ? "Added by you" : "AI suggested this memory";
}

export function formatConfidence(confidence: number | null): string {
  return confidence === null ? "—" : `${Math.round(confidence * 100)}%`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
