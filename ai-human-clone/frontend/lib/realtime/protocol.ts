/**
 * Real-time voice wire protocol (pure: no React, no DOM). See docs/phase17/contract.md.
 *
 * The server sends JSON text frames; a spoken sentence is an `audio` header followed by
 * exactly one binary frame. `FrameAssembler` pairs them, so the hook only sees whole
 * events. Unknown or malformed messages are ignored, never thrown.
 */

import type { ClientMessage, ServerMessage } from "@/types/realtime";

export type RealtimeFrame =
  | { kind: "message"; message: ServerMessage }
  | { kind: "audio"; turn: number; seq: number; mime: string; data: ArrayBuffer };

const isNum = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isStr = (value: unknown): value is string => typeof value === "string";

/** A validated server message, or null for anything unknown or malformed. */
export function parseServerMessage(raw: string): ServerMessage | null {
  let data: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    data = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  switch (data.type) {
    case "ready":
      if (!isStr(data.session_id)) return null;
      return {
        type: "ready",
        session_id: data.session_id,
        conversation_id: isStr(data.conversation_id) ? data.conversation_id : null,
        speech_mode: data.speech_mode === "browser" ? "browser" : "voice",
        max_duration_seconds: isNum(data.max_duration_seconds) ? data.max_duration_seconds : 600,
      };
    case "state":
      if (data.state !== "listening" && data.state !== "thinking" && data.state !== "speaking") return null;
      return { type: "state", state: data.state };
    case "transcript":
      if (!isNum(data.turn) || !isStr(data.text)) return null;
      return { type: "transcript", turn: data.turn, text: data.text, language: isStr(data.language) ? data.language : null };
    case "answer_delta":
      if (!isNum(data.turn) || !isStr(data.text)) return null;
      return { type: "answer_delta", turn: data.turn, text: data.text };
    case "answer":
      if (!isNum(data.turn) || !isStr(data.text)) return null;
      return { type: "answer", turn: data.turn, text: data.text, message_id: isStr(data.message_id) ? data.message_id : null };
    case "audio":
      if (!isNum(data.turn) || !isNum(data.seq)) return null;
      return { type: "audio", turn: data.turn, seq: data.seq, mime: isStr(data.mime) ? data.mime : "audio/mpeg" };
    case "turn_done":
    case "interrupted":
      if (!isNum(data.turn)) return null;
      return { type: data.type, turn: data.turn };
    case "error":
      return {
        type: "error",
        code: isStr(data.code) ? data.code : "provider_unavailable",
        message: isStr(data.message) ? data.message : "Something went wrong.",
        ...(isNum(data.turn) ? { turn: data.turn } : {}),
        fatal: data.fatal === true,
      };
    case "ended": {
      const reason = data.reason;
      return {
        type: "ended",
        reason: reason === "client" || reason === "max_duration" || reason === "expired" ? reason : "error",
      };
    }
    case "pong":
      return { type: "pong" };
    default:
      return null;
  }
}

/** Pairs each `audio` header with the binary frame that follows it. */
export class FrameAssembler {
  private pending: { turn: number; seq: number; mime: string } | null = null;

  /** Feed one WebSocket frame; returns the complete event, or null (header waiting, junk). */
  feed(data: string | ArrayBuffer): RealtimeFrame | null {
    if (typeof data !== "string") {
      const header = this.pending;
      this.pending = null;
      if (!header) return null; // binary without a header: ignore
      return { kind: "audio", ...header, data };
    }
    const message = parseServerMessage(data);
    if (!message) return null;
    if (message.type === "audio") {
      this.pending = { turn: message.turn, seq: message.seq, mime: message.mime };
      return null;
    }
    return { kind: "message", message };
  }

  reset(): void {
    this.pending = null;
  }
}

export function clientMessage(message: ClientMessage): string {
  return JSON.stringify(message);
}

/** ws(s)://host/ws_path?ticket=… from the API base URL (http→ws, https→wss). */
export function buildWsUrl(apiUrl: string, wsPath: string, ticket: string): string {
  const base = new URL(apiUrl);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(wsPath.startsWith("/") ? wsPath : `/${wsPath}`, base);
  url.searchParams.set("ticket", ticket);
  return url.toString();
}

const SENTENCE_END = /[.!?।۔؟\n]/;

/** Collects streamed answer text and hands out whole sentences (for the browser's voice). */
export class SentenceBuffer {
  private text = "";

  push(delta: string): string[] {
    this.text += delta;
    const out: string[] = [];
    let index = this.findEnd();
    while (index >= 0) {
      const sentence = this.text.slice(0, index + 1).trim();
      this.text = this.text.slice(index + 1);
      if (sentence) out.push(sentence);
      index = this.findEnd();
    }
    return out;
  }

  /** The unfinished rest (at the end of an answer). */
  flush(): string | null {
    const rest = this.text.trim();
    this.text = "";
    return rest || null;
  }

  clear(): void {
    this.text = "";
  }

  private findEnd(): number {
    for (let i = 0; i < this.text.length; i += 1) {
      // A line break, or a sentence end followed by a space (so "3.5" is not split and
      // the last sentence waits for flush()).
      const char = this.text[i];
      if (char === "\n") return i;
      if (SENTENCE_END.test(char) && i + 1 < this.text.length && /\s/.test(this.text[i + 1])) return i;
    }
    return -1;
  }
}
