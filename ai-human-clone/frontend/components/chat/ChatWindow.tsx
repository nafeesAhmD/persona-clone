"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type FormEvent, Fragment, useCallback, useEffect, useReducer, useRef, useState } from "react";

import { AgentRunView } from "@/components/agent/AgentRunView";
import { useAgentExecution } from "@/components/agent/useAgentExecution";
import { AiDisclosure } from "@/components/AiDisclosure";
import { ApiErrorState } from "@/components/ApiErrorState";
import { ChatBubble } from "@/components/ChatBubble";
import { ChatModeSwitch, type ChatMode } from "@/components/chat/ChatModeSwitch";
import { ConversationSidebar } from "@/components/chat/ConversationSidebar";
import { MemorySuggestions } from "@/components/chat/MemorySuggestions";
import { CloneAvatar } from "@/components/CloneAvatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusMessage } from "@/components/StatusMessage";
import { VoiceStatusBar } from "@/components/voice/VoiceStatusBar";
import {
  ApiError,
  createAnswerVideo,
  deleteConversation,
  extractMemories,
  getChatProfile,
  getConversation,
  getConversations,
  getLlmStatus,
  speakMessage,
  streamCloneMessage,
} from "@/lib/api";
import { agentApi } from "@/lib/agentApi";
import { canUseAgentMode, outcomeMessage } from "@/lib/agentStatus";
import { canUseBrowserVoice } from "@/lib/browserVoice";
import { failureKind, isNearBottom, isRetryable, sendFailureMessage } from "@/lib/chatState";
import { isAbortError } from "@/lib/uploadWithProgress";
import { transcribeRecording, useVoiceRecorder } from "@/lib/useVoiceRecorder";
import { useViewportFill } from "@/lib/useViewportFill";
import { cn } from "@/lib/utils";
import {
  INITIAL_VOICE_STATE,
  type VoiceErrorCode,
  canRetryRecording,
  canStartRecording,
  httpErrorCode,
  voiceReducer,
} from "@/lib/voiceStates";
import type { AgentExecution, AgentProfile } from "@/types/agent";
import type { ChatMessage, ChatSource, CloneChatProfile, ConversationListItem } from "@/types/clone";
import type { CloneMemory } from "@/types/memory";

interface ChatWindowProps {
  cloneId: string;
  initialConversationId?: string | null;
}

const STREAMING_ID = "streaming-reply";

const SUGGESTIONS: Record<"urdu" | "english", string[]> = {
  urdu: ["Aap kya kaam karte hain?", "Aap ke projects kaun se hain?", "Aap ki skills kya hain?"],
  english: ["What do you do?", "What projects have you worked on?", "What are your skills?"],
};

function suggestionsFor(clone: CloneChatProfile): string[] {
  const language = (clone.preferred_language ?? "").toLowerCase();
  return language.includes("urdu") ? SUGGESTIONS.urdu : SUGGESTIONS.english;
}

function localMessage(role: ChatMessage["role"], content: string, error = false): ChatMessage {
  return { id: crypto.randomUUID(), role, content, created_at: new Date().toISOString(), error };
}

const AUTO_PLAY_KEY = "ai-clone:auto-play-voice";
const RESPONSE_MODE_KEY = "ai-clone:response-mode";

type ResponseMode = "text" | "voice" | "avatar";

const MODE_LABELS: Record<ResponseMode, { icon: string; label: string }> = {
  text: { icon: "💬", label: "Text" },
  voice: { icon: "🔊", label: "Voice" },
  avatar: { icon: "🎬", label: "Avatar" },
};

/** A turn that failed: kept so "Retry" can re-send it, only when the user taps it. */
interface FailedTurn {
  text: string;
  voice: boolean;
  userMessageId: string;
}

/** An Agent Mode turn: the task being followed and how its final answer is delivered. */
interface AgentChatRun {
  executionId: string;
  /** The user's message the live step list is shown under. */
  userMessageId: string;
  spoken: boolean;
  mode: ResponseMode;
}

/** The modes this clone offers to this viewer (avatar videos are for the owner). */
function availableModes(clone: CloneChatProfile): ResponseMode[] {
  const modes: ResponseMode[] = ["text"];
  if (clone.voice_enabled) modes.push("voice");
  if (clone.voice_enabled && clone.avatar_enabled && clone.is_owner) modes.push("avatar");
  return modes;
}

function effectiveMode(clone: CloneChatProfile, chosen: ResponseMode): ResponseMode {
  return availableModes(clone).includes(chosen) ? chosen : "text";
}

function errorKindOf(error: unknown): string | undefined {
  const kind = (error as { kind?: unknown } | null)?.kind;
  return typeof kind === "string" ? kind : undefined;
}

function voiceCodeOf(error: unknown): VoiceErrorCode {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return "offline";
  return httpErrorCode(error instanceof ApiError ? error.status : undefined, errorKindOf(error));
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

const headerChip =
  "inline-flex min-h-8 items-center rounded-full border border-border px-2.5 py-1 text-muted hover:border-accent hover:text-white";
const menuItem = "flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm text-gray-200 hover:bg-surface";

export function ChatWindow({ cloneId, initialConversationId = null }: ChatWindowProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [clone, setClone] = useState<CloneChatProfile | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [conversations, setConversations] = useState<ConversationListItem[] | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingConversation, setLoadingConversation] = useState(Boolean(initialConversationId));
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Short phone screens: the "Reply as" / auto-play row is collapsed behind a toggle.
  const [replyOptionsOpen, setReplyOptionsOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<ConversationListItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [failedTurns, setFailedTurns] = useState<Record<string, FailedTurn>>({});
  const [atBottom, setAtBottom] = useState(true);
  // Memory suggestions for the open conversation (owner only).
  const [suggestions, setSuggestions] = useState<{ memories: CloneMemory[]; message: string } | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  // Voice input: an explicit state machine (lib/voiceStates.ts).
  const recorder = useVoiceRecorder();
  const [voice, dispatchVoice] = useReducer(voiceReducer, INITIAL_VOICE_STATE);
  /** The recording waiting to be sent (time limit reached) or re-sent after a failure. */
  const [parked, setParked] = useState<Blob | null>(null);
  const upload = useRef<AbortController | null>(null);
  const voiceTurn = useRef(0);
  // Auto-play is a per-browser preference, off unless the user turned it on.
  const [autoPlay, setAutoPlay] = useState(() => {
    try {
      return typeof window !== "undefined" && localStorage.getItem(AUTO_PLAY_KEY) === "1";
    } catch {
      return false; // storage unavailable
    }
  });
  // How the clone answers: text only, text + voice, or text + talking-avatar video.
  const [responseMode, setResponseMode] = useState<ResponseMode>(() => {
    try {
      const saved = typeof window !== "undefined" ? localStorage.getItem(RESPONSE_MODE_KEY) : null;
      return saved === "voice" || saved === "avatar" ? saved : "text";
    } catch {
      return "text";
    }
  });
  // Agent Mode (Phase 16): offered only when the clone's agent is on and this viewer may run it.
  const [agentProfile, setAgentProfile] = useState<AgentProfile | null>(null);
  const [chatMode, setChatMode] = useState<ChatMode>("normal");
  const [agentRun, setAgentRun] = useState<AgentChatRun | null>(null);
  const agentAvailable = canUseAgentMode(agentProfile);
  const agentModeOn = agentAvailable && chatMode === "agent";
  const frameRef = useViewportFill<HTMLDivElement>();
  const scrollerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  /** Follow new content only while the reader is at the newest message. */
  const follow = useRef(true);
  const streaming = useRef(false);

  // Keep the selected conversation in the URL (?c=...) so refresh and back work.
  const showInUrl = useCallback(
    (id: string | null) => router.replace(id ? `${pathname}?c=${id}` : pathname, { scroll: false }),
    [router, pathname],
  );

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await getConversations(cloneId));
    } catch {
      setConversations((prev) => prev ?? []);
    }
  }, [cloneId]);

  const loadClone = useCallback(() => {
    let cancelled = false;
    getChatProfile(cloneId)
      .then((profile) => {
        if (cancelled) return;
        setLoadError(null);
        setClone(profile);
        refreshConversations();
      })
      .catch((error: unknown) => !cancelled && setLoadError(error));
    getLlmStatus()
      .then((status) => !cancelled && setDemoMode(status.provider === "demo"))
      .catch(() => undefined);
    // Agent Mode is optional: any failure (agent off, no access) simply hides it.
    agentApi
      .get(cloneId)
      .then((profile) => !cancelled && setAgentProfile(profile))
      .catch(() => !cancelled && setAgentProfile(null));
    return () => {
      cancelled = true;
    };
  }, [cloneId, refreshConversations]);

  useEffect(loadClone, [loadClone]);

  // Load the conversation named in the URL once, when the page opens. Later URL
  // changes come from this component itself (showInUrl) and must not reload
  // messages: that would wipe an answer that is still streaming in.
  const openedFromUrl = useRef(initialConversationId);
  useEffect(() => {
    const id = openedFromUrl.current;
    openedFromUrl.current = null;
    if (!id) return;
    getConversation(id)
      .then((conversation) => setMessages(conversation.messages))
      .catch(() => {
        setConversationId(null); // deleted or not ours: start fresh
        showInUrl(null);
      })
      .finally(() => setLoadingConversation(false));
  }, [showInUrl]);

  // Scroll to the newest message, unless the reader scrolled up to read older ones.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || !follow.current) return;
    scroller.scrollTo({
      top: scroller.scrollHeight,
      behavior: streaming.current || prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [messages]);

  // Escape closes the drawer / menu.
  useEffect(() => {
    if (!sidebarOpen && !menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSidebarOpen(false);
      setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidebarOpen, menuOpen]);

  // "Complete" is shown briefly, then the voice bar goes away.
  useEffect(() => {
    if (voice.stage !== "complete") return;
    const timer = window.setTimeout(() => dispatchVoice({ type: "reset" }), 2500);
    return () => window.clearTimeout(timer);
  }, [voice.stage]);

  // Leaving the page stops an upload in progress.
  useEffect(() => () => upload.current?.abort(), []);

  function onScroll() {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const near = isNearBottom(scroller);
    follow.current = near;
    if (near !== atBottom) setAtBottom(near);
  }

  function jumpToLatest() {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    follow.current = true;
    setAtBottom(true);
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  function openDrawer() {
    setMenuOpen(false);
    setSidebarOpen(true);
    requestAnimationFrame(() => drawerRef.current?.focus());
  }

  function closeSuggestions() {
    setSuggestions(null);
    setExtractError(null);
  }

  async function findMemories() {
    setMenuOpen(false);
    if (!conversationId || extracting || sending) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const result = await extractMemories(conversationId);
      setSuggestions({ memories: result.candidates, message: result.message });
    } catch (error) {
      setSuggestions(null);
      setExtractError(error instanceof Error ? error.message : "Could not look for memories.");
    } finally {
      setExtracting(false);
    }
  }

  async function openConversation(id: string) {
    if (sending || id === conversationId) {
      setSidebarOpen(false);
      return;
    }
    closeSuggestions();
    setAgentRun(null);
    setSidebarOpen(false);
    setConversationId(id);
    setLoadingConversation(true);
    setFailedTurns({});
    follow.current = true;
    showInUrl(id);
    try {
      setMessages((await getConversation(id)).messages);
    } catch {
      setMessages([localMessage("assistant", "This conversation couldn't be loaded.", true)]);
    } finally {
      setLoadingConversation(false);
    }
  }

  function newChat() {
    if (sending) return;
    closeSuggestions();
    setAgentRun(null);
    setSidebarOpen(false);
    setConversationId(null);
    setMessages([]);
    setFailedTurns({});
    follow.current = true;
    showInUrl(null);
    inputRef.current?.focus();
  }

  const updateStreaming = useCallback((update: (message: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === STREAMING_ID ? update(m) : m)));
  }, []);

  const updateMessage = useCallback((id: string, update: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...update } : m)));
  }, []);

  /** "Generating voice…" for a saved answer; if it fails, the text answer stays. Null = voice is playing. */
  async function speakAnswer(conversation: string, messageId: string, playNow = false): Promise<VoiceErrorCode | null> {
    updateMessage(messageId, { audioPending: true, audioError: null });
    try {
      const { audio_url } = await speakMessage(conversation, messageId);
      updateMessage(messageId, { audioPending: false, audioUrl: audio_url, playNow });
      return null;
    } catch (error) {
      const status = error instanceof ApiError ? error.status : undefined;
      // Busy, out of quota, down or unreachable: read it with the browser's voice instead.
      // Other reasons (e.g. voice turned off) are shown as they are.
      const temporary = status === undefined || status === 429 || status >= 500;
      if (temporary && canUseBrowserVoice()) {
        updateMessage(messageId, {
          audioPending: false,
          audioError: "The AI voice is busy right now, so your browser's voice is used.",
          browserVoice: true,
          playNow: playNow || autoPlay,
        });
        return null;
      }
      const reason = status && !temporary ? (error as Error).message : "Voice generation temporarily unavailable";
      updateMessage(messageId, { audioPending: false, audioError: reason });
      return voiceCodeOf(error);
    }
  }

  /**
   * One turn through the normal (streaming) chat. A spoken question also gets a spoken answer.
   * Returns false when the turn failed (it then shows an error bubble with Retry).
   */
  async function send(text: string, { voice: spokenTurn = false }: { voice?: boolean } = {}): Promise<boolean> {
    if (!text || sending || !clone) return false;
    if (agentModeOn) return sendToAgent(text, spokenTurn);
    const mode = effectiveMode(clone, responseMode);
    const wantsAvatar = mode === "avatar";
    const wantsVoice = spokenTurn || mode === "voice";
    const userMessage: ChatMessage = { ...localMessage("user", text), input_mode: spokenTurn ? "voice" : "text" };
    follow.current = true; // your own message always scrolls into view
    setAtBottom(true);
    setMessages((prev) => [
      ...prev,
      userMessage,
      { id: STREAMING_ID, role: "assistant", content: "", created_at: new Date().toISOString() },
    ]);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "";
    setSending(true);
    streaming.current = true;

    let sources: ChatSource[] = [];
    let memoriesUsed = 0;
    let activeConversation = conversationId;
    let answer: ChatMessage | null = null;
    try {
      answer = await streamCloneMessage(clone.id, text, conversationId, {
        onMeta: (meta) => {
          sources = meta.sources;
          memoriesUsed = meta.memories_used ?? 0;
          activeConversation = meta.conversation_id;
          if (meta.conversation_id !== conversationId) {
            setConversationId(meta.conversation_id);
            showInUrl(meta.conversation_id);
          }
        },
        onDelta: (piece) => updateStreaming((m) => ({ ...m, content: m.content + piece })),
      }, spokenTurn ? "voice" : "text");
      const saved = answer;
      updateStreaming(() => ({ ...saved, sources, memoriesUsed, audioPending: wantsVoice && !wantsAvatar }));
    } catch (error) {
      const kind = failureKind(error, typeof navigator === "undefined" || navigator.onLine !== false);
      const failed = localMessage("assistant", sendFailureMessage(kind, error instanceof Error ? error.message : undefined), true);
      updateStreaming(() => failed);
      if (isRetryable(kind)) {
        setFailedTurns((prev) => ({ ...prev, [failed.id]: { text, voice: spokenTurn, userMessageId: userMessage.id } }));
      }
      if (spokenTurn) dispatchVoice({ type: "fail", code: voiceCodeOf(error) });
    } finally {
      streaming.current = false;
      setSending(false);
      refreshConversations(); // new title / order
    }

    if (!answer || !activeConversation) return false;
    await deliverAnswer(activeConversation, answer.id, { wantsAvatar, wantsVoice, spokenTurn });
    return true;
  }

  /** Only after a saved answer: a video (avatar mode) or speech (voice mode / spoken question). */
  async function deliverAnswer(
    activeConversation: string,
    answerId: string,
    { wantsAvatar, wantsVoice, spokenTurn }: { wantsAvatar: boolean; wantsVoice: boolean; spokenTurn: boolean },
  ) {
    if (wantsAvatar) {
      if (spokenTurn) dispatchVoice({ type: "answer_ready", speak: false });
      await startAvatarVideo(activeConversation, answerId);
    } else if (wantsVoice) {
      if (spokenTurn) dispatchVoice({ type: "answer_ready", speak: true });
      const problem = await speakAnswer(activeConversation, answerId);
      if (spokenTurn) {
        dispatchVoice(problem ? { type: "fail", code: problem, detail: "The text answer is shown in the chat." } : { type: "voice_ready" });
      }
    } else if (spokenTurn) {
      dispatchVoice({ type: "answer_ready", speak: false });
    }
  }

  /**
   * Agent Mode turn: starts a task with the message as its goal. The live step list
   * shows under the message; the final answer (saved on the server as a normal
   * message) is added when the task finishes (finishAgentRun).
   */
  async function sendToAgent(text: string, spokenTurn: boolean): Promise<boolean> {
    if (!clone) return false;
    const mode = effectiveMode(clone, responseMode);
    const userMessage: ChatMessage = { ...localMessage("user", text), input_mode: spokenTurn ? "voice" : "text" };
    follow.current = true;
    setAtBottom(true);
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "";
    setSending(true);
    try {
      const started = await agentApi.run(clone.id, {
        goal: text,
        conversation_id: conversationId,
        input_mode: spokenTurn ? "voice" : "text",
      });
      setAgentRun({ executionId: started.execution_id, userMessageId: userMessage.id, spoken: spokenTurn, mode });
      return true;
    } catch (error) {
      setSending(false);
      const kind = failureKind(error, typeof navigator === "undefined" || navigator.onLine !== false);
      const failed = localMessage("assistant", sendFailureMessage(kind, error instanceof Error ? error.message : undefined), true);
      setMessages((prev) => [...prev, failed]);
      if (isRetryable(kind)) {
        setFailedTurns((prev) => ({ ...prev, [failed.id]: { text, voice: spokenTurn, userMessageId: userMessage.id } }));
      }
      if (spokenTurn) dispatchVoice({ type: "fail", code: voiceCodeOf(error) });
      return false;
    }
  }

  /** The saved final answer of a task (falls back to its summary if the conversation can't be read). */
  async function loadFinalMessage(execution: AgentExecution): Promise<ChatMessage> {
    const fallback = (id: string): ChatMessage => ({
      id,
      role: "assistant",
      content: execution.result_summary || "Done.",
      created_at: execution.completed_at ?? new Date().toISOString(),
    });
    if (!execution.final_message_id) return fallback(crypto.randomUUID());
    if (execution.conversation_id) {
      try {
        const saved = (await getConversation(execution.conversation_id)).messages.find((m) => m.id === execution.final_message_id);
        if (saved) return saved;
      } catch {
        // Use the summary below.
      }
    }
    return fallback(execution.final_message_id);
  }

  /** A task reached a final state: add its answer (or why it stopped), then voice / avatar like a normal answer. */
  async function finishAgentRun(execution: AgentExecution) {
    const run = agentRun;
    setSending(false);
    void refreshConversations();
    const conversation = execution.conversation_id;
    if (conversation && conversation !== conversationId) {
      setConversationId(conversation);
      showInUrl(conversation);
    }
    if (execution.status !== "completed") {
      const stopped = execution.status === "cancelled";
      setMessages((prev) => [
        ...prev,
        localMessage("assistant", outcomeMessage(execution) ?? "The agent couldn't finish this task.", !stopped),
      ]);
      if (run?.spoken) {
        dispatchVoice(stopped ? { type: "reset" } : { type: "fail", code: "unknown", detail: "The agent couldn't finish this task." });
      }
      return;
    }
    const answer = await loadFinalMessage(execution);
    const wantsAvatar = run?.mode === "avatar";
    const wantsVoice = Boolean(run?.spoken) || run?.mode === "voice";
    const canSpeak = Boolean(conversation && execution.final_message_id);
    setMessages((prev) =>
      prev.some((m) => m.id === answer.id) ? prev : [...prev, { ...answer, audioPending: canSpeak && wantsVoice && !wantsAvatar }],
    );
    if (conversation && canSpeak) {
      // Voice / avatar for the final answer only, never for the steps.
      await deliverAnswer(conversation, answer.id, { wantsAvatar, wantsVoice, spokenTurn: Boolean(run?.spoken) });
    } else if (run?.spoken) {
      dispatchVoice({ type: "answer_ready", speak: false });
    }
  }

  function dismissAgentRun() {
    setAgentRun(null);
    setSending(false);
  }

  // Follows the Agent Mode task (polling, busy flag); declared after finishAgentRun, which it calls.
  const agentExecution = useAgentExecution(agentRun?.executionId ?? null, (execution) => void finishAgentRun(execution));

  /** Retry a failed turn: only ever called from the Retry button. */
  function retryTurn(errorMessageId: string) {
    const turn = failedTurns[errorMessageId];
    if (!turn || sending) return;
    setFailedTurns((prev) => {
      const next = { ...prev };
      delete next[errorMessageId];
      return next;
    });
    setMessages((prev) => prev.filter((m) => m.id !== errorMessageId && m.id !== turn.userMessageId));
    void send(turn.text, { voice: turn.voice });
  }

  async function startAvatarVideo(conversation: string, messageId: string) {
    if (!clone) return;
    updateMessage(messageId, { avatarError: null });
    try {
      const { job_id } = await createAnswerVideo(clone.id, conversation, messageId);
      updateMessage(messageId, { avatar_job_id: job_id, avatar_job_status: "queued" });
    } catch (error) {
      // The answer stays; offer its voice instead.
      updateMessage(messageId, {
        avatarError: error instanceof Error ? error.message : "The avatar video couldn't start.",
      });
    }
  }

  function chooseMode(mode: ResponseMode) {
    setResponseMode(mode);
    try {
      localStorage.setItem(RESPONSE_MODE_KEY, mode);
    } catch {
      // Storage blocked: the choice lasts for this page only.
    }
  }

  // --- Voice turn: tap → listen → (tap) upload → transcribe → think → speak ---

  async function startVoice() {
    if (sending || !canStartRecording(voice)) return;
    const turn = ++voiceTurn.current;
    setParked(null);
    dispatchVoice({ type: "tap_record" });
    const problem = await recorder.startRecording((recording) => {
      // Time limit reached: keep the audio until the user taps Send (never upload by itself).
      if (turn !== voiceTurn.current) return;
      if (!recording) {
        dispatchVoice({ type: "fail", code: "empty_recording" });
        return;
      }
      setParked(recording);
      dispatchVoice({ type: "limit_reached" });
    });
    if (turn !== voiceTurn.current) {
      // Cancelled while the permission prompt was open.
      if (!problem) recorder.cancelRecording();
      return;
    }
    dispatchVoice(problem ? { type: "fail", code: problem } : { type: "permission_granted" });
  }

  async function uploadRecording(recording: Blob | null) {
    if (!clone) return;
    if (!recording || recording.size === 0) {
      dispatchVoice({ type: "fail", code: "empty_recording" });
      return;
    }
    const turn = voiceTurn.current;
    setParked(recording); // kept for "Try again" until the transcript is in
    const controller = new AbortController();
    upload.current = controller;
    dispatchVoice({ type: "upload_started" });
    try {
      const { text } = await transcribeRecording(clone.id, recording, {
        signal: controller.signal,
        onUploaded: () => turn === voiceTurn.current && dispatchVoice({ type: "uploaded" }),
      });
      if (turn !== voiceTurn.current) return;
      upload.current = null;
      if (!text.trim()) {
        setParked(null);
        dispatchVoice({ type: "fail", code: "empty_recording" });
        return;
      }
      setParked(null);
      dispatchVoice({ type: "transcribed" });
      await send(text.trim(), { voice: true });
    } catch (error) {
      upload.current = null;
      if (isAbortError(error) || turn !== voiceTurn.current) return;
      const status = error instanceof ApiError ? error.status : undefined;
      const detail = status && status < 500 && status !== 429 && error instanceof Error ? error.message : null;
      dispatchVoice({ type: "fail", code: voiceCodeOf(error), detail });
    }
  }

  async function sendVoice() {
    if (voice.stage === "listening") await uploadRecording(await recorder.stopRecording());
    else if (voice.stage === "recorded") await uploadRecording(parked);
  }

  function cancelVoice() {
    voiceTurn.current += 1;
    recorder.cancelRecording();
    upload.current?.abort();
    upload.current = null;
    setParked(null);
    dispatchVoice({ type: "cancel" });
  }

  function dismissVoice() {
    setParked(null);
    dispatchVoice({ type: "reset" });
  }

  function toggleAutoPlay(enabled: boolean) {
    setAutoPlay(enabled);
    try {
      localStorage.setItem(AUTO_PLAY_KEY, enabled ? "1" : "0");
    } catch {
      // Storage blocked (private window): the choice lasts for this page only.
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteConversation(pendingDelete.id);
      if (pendingDelete.id === conversationId) newChat();
      await refreshConversations();
      setPendingDelete(null);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Could not delete the conversation.");
    } finally {
      setDeleting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(input.trim());
  }

  function autoGrow(element: HTMLTextAreaElement) {
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
  }

  if (loadError) return <ApiErrorState error={loadError} thing="clone" onRetry={loadClone} />;
  if (!clone) return <StatusMessage title="Loading clone…" />;

  const waitingForFirstWord = messages.some((m) => m.id === STREAMING_ID && !m.content);
  const visible = messages.filter((m) => !(m.id === STREAMING_ID && !m.content));
  const isEmpty = !loadingConversation && messages.length === 0;
  const modes = availableModes(clone);
  const mode = effectiveMode(clone, responseMode);
  // While recording or uploading, the voice bar takes the composer's place.
  const voiceTakesComposer = ["requesting", "listening", "recorded", "uploading", "transcribing"].includes(voice.stage);
  const hasReplyOptions = (modes.length > 1 || clone.voice_enabled) && !voiceTakesComposer;
  const voiceBusy = voice.stage !== "idle" && voice.stage !== "complete" && voice.stage !== "error";

  const ownerLinks = clone.is_owner
    ? [
        { href: `/clone/${clone.id}/knowledge`, label: "Knowledge", icon: "📚" },
        { href: `/clone/${clone.id}/memory`, label: "Memory", icon: "🧠" },
        { href: `/clone/${clone.id}/voice`, label: "Voice", icon: "🎙" },
        { href: `/clone/${clone.id}/avatar`, label: "Avatar", icon: "🖼" },
        { href: `/clone/${clone.id}/details`, label: "Manage", icon: "⚙" },
      ]
    : [];

  return (
    <div ref={frameRef} className="flex h-[calc(100dvh-var(--app-header-h))] overflow-hidden">
      {/* Conversations: a slide-in sheet on mobile, a column from md up. */}
      <aside
        ref={drawerRef}
        tabIndex={-1}
        aria-label="Conversations"
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-[min(20rem,85vw)] border-r border-border bg-surface pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] outline-none transition-[transform,visibility] duration-200 motion-reduce:transition-none",
          "md:static md:z-auto md:w-72 md:translate-x-0 md:pb-0 md:pt-0 md:visible",
          sidebarOpen ? "visible translate-x-0" : "invisible -translate-x-full",
        )}
      >
        <ConversationSidebar
          conversations={conversations}
          selectedId={conversationId}
          busy={sending}
          onSelect={openConversation}
          onNewChat={newChat}
          onDelete={(conversation) => {
            setDeleteError(null);
            setPendingDelete(conversation);
          }}
          onClose={() => setSidebarOpen(false)}
        />
      </aside>
      {sidebarOpen && (
        <button
          type="button"
          aria-label="Close conversations"
          tabIndex={-1}
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
        />
      )}

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="relative border-b border-border bg-surface-raised/60">
          <div className="mx-auto flex max-w-3xl items-center gap-2 px-2 py-2 short:py-1 sm:gap-3 sm:px-4 md:flex-wrap md:py-3">
            <button
              type="button"
              onClick={openDrawer}
              aria-label="Open conversations"
              aria-expanded={sidebarOpen}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-border text-lg text-muted hover:text-white md:hidden"
            >
              <span aria-hidden>☰</span>
            </button>
            {clone.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- arbitrary owner-provided URL
              <img src={clone.avatar_url} alt="" className="h-9 w-9 shrink-0 rounded-full object-cover md:h-11 md:w-11" />
            ) : (
              <span className="hidden shrink-0 sm:block">
                <CloneAvatar name={clone.name} />
              </span>
            )}
            <div className="min-w-0 flex-1">
              <p className="hidden text-[11px] uppercase tracking-wider text-muted md:block">Clone Me</p>
              <h1 className="truncate font-semibold">{clone.name}</h1>
              <p className="truncate text-[11px] text-accent-soft md:hidden">AI-generated representation</p>
              {clone.profession && <p className="hidden truncate text-xs text-muted md:block">{clone.profession}</p>}
            </div>
            <Link
              href={`/clone/${clone.id}/call`}
              aria-label="Start a video call"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-emerald-500/90 text-lg text-black hover:bg-emerald-400 md:hidden"
            >
              <span aria-hidden>📹</span>
            </Link>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-label="More options"
              aria-expanded={menuOpen}
              aria-controls="chat-menu"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-border text-lg text-muted hover:text-white md:hidden"
            >
              <span aria-hidden>⋯</span>
            </button>

            {/* Desktop: everything as chips. */}
            <div className="hidden flex-wrap items-center gap-2 text-[11px] md:flex">
              {demoMode && (
                <span className="rounded-full border border-amber-400/40 px-2.5 py-1 font-medium text-amber-300">Demo mode</span>
              )}
              <span className="rounded-full border border-accent/40 px-2.5 py-1 font-medium text-accent-soft">
                AI-generated representation
              </span>
              <Link
                href={`/clone/${clone.id}/call`}
                className="rounded-full bg-emerald-500/90 px-2.5 py-1 font-semibold text-black hover:bg-emerald-400"
              >
                📹 Video call
              </Link>
              {clone.voice_enabled && (
                <Link
                  href={`/clone/${clone.id}/voice/live`}
                  className="rounded-full border border-emerald-400/50 px-2.5 py-1 font-semibold text-emerald-200 hover:bg-emerald-400/10"
                >
                  🎙️ Live voice
                </Link>
              )}
              {ownerLinks.map((link) => (
                <Link key={link.href} href={link.href} className={headerChip}>
                  {link.label}
                </Link>
              ))}
              {clone.is_owner && conversationId && !loadingConversation && (
                <button
                  type="button"
                  onClick={findMemories}
                  disabled={extracting || sending}
                  className="rounded-full border border-amber-400/40 px-2.5 py-1 text-amber-200 transition hover:bg-amber-400/10 disabled:opacity-50"
                >
                  {extracting ? "Looking for memories…" : "Find memories"}
                </button>
              )}
            </div>
          </div>

          {/* Mobile: the same actions in a menu. */}
          {menuOpen && (
            <>
              <button
                type="button"
                tabIndex={-1}
                aria-label="Close menu"
                onClick={() => setMenuOpen(false)}
                className="fixed inset-0 z-40 cursor-default md:hidden"
              />
              <div
                id="chat-menu"
                className="absolute right-2 top-full z-[45] mt-1 w-64 rounded-2xl border border-border bg-surface-raised p-2 shadow-2xl md:hidden"
              >
                {demoMode && <p className="px-3 py-2 text-xs text-amber-300">Demo mode: answers are simulated.</p>}
                <Link href={`/clone/${clone.id}/call`} className={menuItem} onClick={() => setMenuOpen(false)}>
                  <span aria-hidden>📹</span> Video call
                </Link>
                {clone.voice_enabled && (
                  <Link href={`/clone/${clone.id}/voice/live`} className={menuItem} onClick={() => setMenuOpen(false)}>
                    <span aria-hidden>🎙️</span> Live voice
                  </Link>
                )}
                {ownerLinks.map((link) => (
                  <Link key={link.href} href={link.href} className={menuItem} onClick={() => setMenuOpen(false)}>
                    <span aria-hidden>{link.icon}</span> {link.label}
                  </Link>
                ))}
                {clone.is_owner && conversationId && !loadingConversation && (
                  <button type="button" onClick={findMemories} disabled={extracting || sending} className={cn(menuItem, "disabled:opacity-50")}>
                    <span aria-hidden>✨</span> {extracting ? "Looking for memories…" : "Find memories in this chat"}
                  </button>
                )}
              </div>
            </>
          )}
        </header>

        {!clone.has_knowledge && (
          <p className="border-b border-amber-400/20 bg-amber-400/5 px-4 py-2 text-center text-xs text-amber-200">
            {clone.is_owner ? (
              <>
                This clone has no knowledge in AI memory yet, so it can only answer from its profile.{" "}
                <Link href={`/clone/${clone.id}/knowledge`} className="inline-block py-1 underline">
                  Add knowledge
                </Link>
              </>
            ) : (
              "This clone hasn't been given much knowledge yet, so its answers will be limited."
            )}
          </p>
        )}

        <div className="relative min-h-0 flex-1">
          <div
            ref={scrollerRef}
            onScroll={onScroll}
            className="h-full overflow-y-auto overscroll-contain"
            aria-busy={sending || loadingConversation}
          >
            <div className="mx-auto flex max-w-3xl flex-col gap-4 px-3 py-4 sm:px-4 sm:py-6">
              {loadingConversation && (
                <div className="space-y-3" aria-label="Loading conversation">
                  <p className="text-center text-sm text-muted">Loading conversation…</p>
                  <div className="h-10 w-2/3 animate-pulse rounded-2xl bg-surface-raised motion-reduce:animate-none" />
                  <div className="ml-auto h-10 w-1/2 animate-pulse rounded-2xl bg-surface-raised motion-reduce:animate-none" />
                </div>
              )}
              {isEmpty && (
                <div className="py-6 text-center sm:py-10">
                  <CloneAvatar name={clone.name} size="lg" />
                  <p className="mt-4 font-medium">Chat with {clone.name}</p>
                  <p className="mx-auto mt-1 max-w-md text-sm text-muted">
                    An AI clone that answers from the information its owner shared. It isn&apos;t the real person.
                  </p>
                  <div className="mt-5 flex flex-wrap justify-center gap-2">
                    {suggestionsFor(clone).map((question) => (
                      <button
                        key={question}
                        type="button"
                        onClick={() => send(question)}
                        className="min-h-11 rounded-full border border-border bg-surface-raised px-4 py-2 text-sm text-gray-200 transition hover:border-accent md:min-h-0 md:px-3 md:py-1.5 md:text-xs"
                      >
                        {question}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {visible.map((message, index) => {
                // An earlier answer to a spoken question (e.g. after a reload) can be spoken again on request.
                const answersVoice = message.role === "assistant" && visible[index - 1]?.input_mode === "voice";
                const isAnswer = message.role === "assistant" && conversationId && message.id !== STREAMING_ID && !message.error;
                const canListen = isAnswer && clone.voice_enabled;
                const listen = canListen ? () => void speakAnswer(conversationId, message.id, true) : undefined;
                const retryVideo =
                  isAnswer && mode === "avatar" && (message.avatar_job_id || message.avatarError)
                    ? () => void startAvatarVideo(conversationId, message.id)
                    : undefined;
                const showAgentRun = agentRun !== null && message.id === agentRun.userMessageId;
                return (
                  <Fragment key={message.id}>
                    <ChatBubble
                      message={message}
                      cloneId={clone.id}
                      cloneName={clone.name}
                      isOwner={clone.is_owner}
                      avatarPoster={clone.avatar_url}
                      autoPlay={autoPlay}
                      // "Play response" for earlier spoken answers; for videos it's the fallback when they fail.
                      onListen={answersVoice && !message.avatar_job_id ? listen : undefined}
                      onVoiceFallback={listen}
                      onRetry={failedTurns[message.id] && !sending ? () => retryTurn(message.id) : undefined}
                      onRetryVideo={retryVideo}
                    />
                    {showAgentRun && (
                      <div className="sm:pl-11">
                        <AgentRunView
                          run={agentExecution}
                          compact
                          tools={agentProfile?.tools}
                          detailsHref={`/clone/${encodeURIComponent(clone.id)}/agent/executions/${encodeURIComponent(agentRun.executionId)}`}
                          onDismiss={dismissAgentRun}
                        />
                      </div>
                    )}
                  </Fragment>
                );
              })}
              {waitingForFirstWord && (
                <p className="flex items-center gap-2 pl-1 text-xs text-muted sm:pl-11">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent/30 border-t-accent motion-reduce:animate-none" aria-hidden />
                  {clone.name} is thinking…
                </p>
              )}
            </div>
          </div>
          {!atBottom && visible.length > 0 && (
            <button
              type="button"
              onClick={jumpToLatest}
              className="absolute bottom-3 left-1/2 inline-flex min-h-11 -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-surface-raised/95 px-4 text-xs text-gray-100 shadow-lg backdrop-blur hover:border-accent"
            >
              <span aria-hidden>↓</span> Latest messages
            </button>
          )}
        </div>

        <div className="border-t border-border bg-surface pb-[max(0.5rem,env(safe-area-inset-bottom))]">
          <div className="mx-auto max-w-3xl space-y-2 px-3 pt-2 sm:space-y-3 sm:px-4 sm:pt-3">
            {suggestions && (
              <div className="max-h-[40dvh] overflow-y-auto overscroll-contain">
                <MemorySuggestions
                  cloneId={clone.id}
                  suggestions={suggestions.memories}
                  message={suggestions.message}
                  onChange={(memories) => setSuggestions((prev) => prev && { ...prev, memories })}
                  onClose={closeSuggestions}
                />
              </div>
            )}
            {extractError && (
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200" role="alert">
                {extractError}
              </p>
            )}
            {agentAvailable && !voiceTakesComposer && (
              <ChatModeSwitch mode={agentModeOn ? "agent" : "normal"} onChange={setChatMode} disabled={sending} />
            )}
            {hasReplyOptions && (
              <div
                id="chat-reply-options"
                className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs", !replyOptionsOpen && "compact:hidden")}
              >
                {modes.length > 1 && (
                  <div className="flex items-center gap-2" role="group" aria-label="Reply as">
                    <span className="text-muted">Reply as</span>
                    <div className="inline-flex rounded-xl border border-border bg-surface-raised p-0.5">
                      {modes.map((option) => (
                        <button
                          key={option}
                          type="button"
                          aria-pressed={mode === option}
                          onClick={() => chooseMode(option)}
                          className={cn(
                            "inline-flex min-h-11 items-center gap-1 rounded-lg px-3 transition md:min-h-8",
                            mode === option ? "bg-accent/20 font-medium text-accent-soft" : "text-muted hover:text-white",
                          )}
                        >
                          <span aria-hidden>{MODE_LABELS[option].icon}</span>
                          {MODE_LABELS[option].label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {clone.voice_enabled && (
                  <label className="flex min-h-11 cursor-pointer items-center gap-2 text-muted md:min-h-8">
                    <input
                      type="checkbox"
                      checked={autoPlay}
                      onChange={(e) => toggleAutoPlay(e.target.checked)}
                      className="h-4 w-4 accent-accent"
                    />
                    Auto-play voice
                  </label>
                )}
              </div>
            )}
            {/* Short phone screens: the header's "AI-generated representation" line stays as the notice. */}
            <AiDisclosure className="py-1.5 text-[11px] compact:hidden sm:py-2 sm:text-xs" />
            {voice.stage !== "idle" && (
              <VoiceStatusBar
                state={voice}
                seconds={recorder.seconds}
                maxSeconds={recorder.maxSeconds}
                onSend={() => void sendVoice()}
                onCancel={cancelVoice}
                onRetry={parked && canRetryRecording(voice.error) ? () => void uploadRecording(parked) : undefined}
                onDismiss={dismissVoice}
              />
            )}
            {!voiceTakesComposer && (
              <form onSubmit={handleSubmit} className="flex items-end gap-2">
                {hasReplyOptions && (
                  <button
                    type="button"
                    onClick={() => setReplyOptionsOpen((open) => !open)}
                    aria-expanded={replyOptionsOpen}
                    aria-controls="chat-reply-options"
                    aria-label={`Reply options (replying as ${MODE_LABELS[mode].label})`}
                    title="Reply options"
                    className={cn(
                      "hidden h-12 w-11 shrink-0 place-items-center rounded-xl border text-lg transition compact:grid",
                      replyOptionsOpen ? "border-accent bg-accent/15" : "border-border bg-surface-raised hover:border-accent",
                    )}
                  >
                    <span aria-hidden>{MODE_LABELS[mode].icon}</span>
                  </button>
                )}
                {clone.voice_enabled && (
                  <button
                    type="button"
                    onClick={() => void startVoice()}
                    disabled={sending || voiceBusy}
                    aria-label="Record a voice message"
                    title="Record a voice message"
                    className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-border bg-surface-raised text-lg transition hover:border-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span aria-hidden>🎤</span>
                  </button>
                )}
                <label htmlFor="chat-input" className="sr-only">
                  {agentModeOn ? "Task for the agent" : "Message"}
                </label>
                <textarea
                  id="chat-input"
                  ref={inputRef}
                  rows={1}
                  value={input}
                  enterKeyHint="send"
                  onChange={(e) => {
                    setInput(e.target.value);
                    autoGrow(e.target);
                  }}
                  onKeyDown={(e) => {
                    // Touch keyboards: Enter adds a new line; the Send button sends.
                    const touch = window.matchMedia?.("(pointer: coarse)").matches;
                    if (e.key === "Enter" && !e.shiftKey && !touch && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void send(input.trim());
                    }
                  }}
                  placeholder={agentModeOn ? "Give the agent a task…" : "Ask your AI Clone..."}
                  maxLength={4000}
                  // 16px on phones so iOS doesn't zoom into the field.
                  className="max-h-40 min-h-12 min-w-0 flex-1 resize-none rounded-xl border border-border bg-surface-raised px-4 py-3 text-base outline-none placeholder:text-muted focus:border-accent md:text-sm"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || sending}
                  className="grid h-12 min-w-12 shrink-0 place-items-center rounded-xl bg-accent px-3 text-sm font-medium text-ink transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50 md:px-5"
                >
                  <span aria-hidden className="text-lg md:hidden">{sending ? "…" : "➤"}</span>
                  <span className="sr-only md:not-sr-only">{sending ? "Sending…" : "Send"}</span>
                </button>
              </form>
            )}
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete conversation?"
        message={`"${pendingDelete?.title || "New conversation"}" and its messages will be removed.`}
        confirmLabel="Delete"
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
