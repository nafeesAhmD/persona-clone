"use client";

import { useSyncExternalStore } from "react";

import { clearLastChat, readLastChat, writeLastChat, type KeyValueStorage } from "@/lib/navigation";

/** Remembers the last opened clone chat (per user) for the mobile "Chat" tab. */

const CHANGE_EVENT = "ahc:last-chat-change";

function storage(): KeyValueStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // blocked storage (some private modes) throws on access
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

export function useLastChatId(userId: string | null | undefined): string | null {
  return useSyncExternalStore(
    subscribe,
    () => readLastChat(storage(), userId),
    () => null,
  );
}

export function rememberLastChat(userId: string | null | undefined, cloneId: string): void {
  if (readLastChat(storage(), userId) === cloneId) return;
  if (writeLastChat(storage(), userId, cloneId)) window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function forgetLastChat(userId: string | null | undefined): void {
  clearLastChat(storage(), userId);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
}
