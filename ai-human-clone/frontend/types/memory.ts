export type MemoryType =
  | "fact"
  | "preference"
  | "communication_preference"
  | "skill"
  | "experience"
  | "project"
  | "goal"
  | "background"
  | "instruction"
  | "other";

export type MemoryStatus = "candidate" | "approved" | "rejected" | "archived";
export type MemorySource = "conversation" | "manual";

/** A long-term memory of a clone (owner only). The content is user data: render it as plain text. */
export interface CloneMemory {
  id: string;
  clone_id: string;
  memory_type: MemoryType;
  content: string;
  confidence: number | null;
  status: MemoryStatus;
  source: MemorySource;
  source_conversation_id: string | null;
  /** "public": usable for visitors of the public clone once approved. */
  visibility: "private" | "public";
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

export interface MemoryCreatePayload {
  memory_type: MemoryType;
  content: string;
}

export type MemoryUpdatePayload = Partial<MemoryCreatePayload & { status: MemoryStatus }>;

export interface MemoryExtractionResult {
  candidates: CloneMemory[];
  skipped: { duplicates: number; sensitive: number; invalid: number };
  message: string;
}
