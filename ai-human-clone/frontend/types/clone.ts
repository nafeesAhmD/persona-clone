export type ResponseLength = "short" | "medium" | "detailed";
export type Visibility = "private" | "public" | "unlisted";
export type CloneStatus = "draft" | "active" | "disabled";

/** A clone card: returned by GET /api/clones and /api/clones/public. */
export interface CloneSummary {
  id: string;
  name: string;
  slug: string;
  tagline: string | null;
  profession: string | null;
  skills: string[];
  preferred_language: string | null;
  visibility: Visibility;
  status: CloneStatus;
  avatar_url: string | null;
  created_at: string;
  updated_at: string;
  /** Knowledge sources, how many are in AI memory, and their memory chunks. */
  knowledge_count: number;
  indexed_count: number;
  chunk_count: number;
  /** Public access switches. */
  public_chat_enabled: boolean;
  public_voice_enabled: boolean;
  public_avatar_enabled: boolean;
}

/** Full clone settings, returned to the owner by GET /api/clones/{id}. */
export interface CloneProfile extends CloneSummary {
  bio: string | null;
  communication_style: string | null;
  personality_description: string | null;
  response_length: ResponseLength;
}

/** What a chat screen may show about a clone (no private settings). */
export interface CloneChatProfile {
  id: string;
  name: string;
  slug: string;
  tagline: string | null;
  profession: string | null;
  preferred_language: string | null;
  avatar_url: string | null;
  status: CloneStatus;
  is_owner: boolean;
  /** Whether any knowledge is in AI memory. */
  has_knowledge: boolean;
  /** Whether voice chat is turned on (the microphone is shown only then). */
  voice_enabled: boolean;
  /** Whether talking-avatar replies are on (owner's chat). */
  avatar_enabled: boolean;
}

/** Editable clone settings. owner_id, slug and timestamps are always set by the server. */
export interface CloneSettings {
  name: string;
  tagline: string | null;
  bio: string | null;
  profession: string | null;
  skills: string[];
  preferred_language: string | null;
  communication_style: string | null;
  personality_description: string | null;
  response_length: ResponseLength;
  visibility: Visibility;
  avatar_url: string | null;
  status: CloneStatus;
}

export interface CloneCreatePayload extends CloneSettings {
  owner_consent: boolean;
}

export type CloneUpdatePayload = Partial<CloneSettings>;

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";
export type SourceType = "file" | "manual_text";
export type IndexingStatus = "not_indexed" | "indexing" | "indexed" | "indexing_failed";

/** A knowledge source as listed (no extracted text; the server path is never sent). */
export interface DocumentListItem {
  id: string;
  title: string;
  source_type: SourceType;
  status: DocumentStatus;
  original_filename: string | null;
  file_type: string | null;
  mime_type: string | null;
  file_size: number | null;
  character_count: number;
  error_message: string | null;
  /** AI memory (vector index), separate from text extraction (`status`). */
  indexing_status: IndexingStatus;
  indexed_at: string | null;
  indexing_error: string | null;
  chunk_count: number;
  /** "public": visitors of the public clone may get answers from it. */
  visibility: "private" | "public";
  created_at: string;
  updated_at: string;
}

/**
 * One knowledge source with its extracted text. (Named DocumentDetail rather
 * than Document so it doesn't shadow the browser's global Document type.)
 * The text is untrusted user content: render it as plain text only.
 */
export interface DocumentDetail extends DocumentListItem {
  extracted_text: string | null;
}

export interface ManualKnowledgePayload {
  title: string;
  content: string;
}

export interface IndexResult {
  document_id: string;
  status: IndexingStatus;
  chunk_count: number;
  error: string | null;
}

export interface KnowledgeSearchResult {
  score: number;
  document_id: string;
  title: string;
  source_type: SourceType;
  chunk_index: number;
  text: string;
}

export interface KnowledgeSearchResponse {
  query: string;
  results: KnowledgeSearchResult[];
  message: string | null;
}

export type ChatRole = "user" | "assistant";

/** A knowledge source an answer drew on: which document, not its text. */
export interface ChatSource {
  document_id: string;
  title: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  created_at: string;
  /** Client-side only: sources and memory count shown under a fresh answer, and failed turns. */
  sources?: ChatSource[];
  memoriesUsed?: number;
  /** "voice": the user spoke this message (content is the transcript). Saved on the server. */
  input_mode?: "text" | "voice";
  /** The newest talking-avatar video job of this answer (from the server, or just started). */
  avatar_job_id?: string | null;
  avatar_job_status?: string | null;
  /** Client-side only: starting the avatar video failed before a job existed. */
  avatarError?: string | null;
  /** Client-side only: start playing the spoken answer as soon as it arrives (after a click). */
  playNow?: boolean;
  /** Client-side only: the spoken answer (an API audio URL), or why it's missing. */
  audioUrl?: string | null;
  audioError?: string | null;
  /** The AI voice was busy or unavailable: offer the browser's own voice instead. */
  browserVoice?: boolean;
  audioPending?: boolean;
  error?: boolean;
}

export interface SendMessageRequest {
  message: string;
  conversation_id: string | null;
}

export interface SendMessageResponse {
  conversation_id: string;
  message: ChatMessage;
  sources: ChatSource[];
  /** Approved long-term memories used for the answer (owner's own chats only). */
  memories_used: number;
}

export interface ConversationListItem {
  id: string;
  clone_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationListItem {
  messages: ChatMessage[];
}

export interface HealthResponse {
  status: string;
}
