"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

/** GET /api/mobile/config: public feature switches and limits (no secrets). */
export interface MobileConfig {
  app_name: string;
  version: string;
  maintenance_mode: boolean;
  registration_enabled: boolean;
  discovery_enabled: boolean;
  public_chat_enabled: boolean;
  billing_enabled: boolean;
  max_upload_mb: number;
  voice: {
    speech_to_text: boolean;
    text_to_speech: boolean;
    max_recording_seconds: number;
    max_audio_mb: number;
  };
  avatar: {
    enabled: boolean;
    videos: boolean;
    live_calls: boolean;
    max_image_mb: number;
    max_video_seconds: number;
  };
}

/**
 * Used until the config arrives or when it can't be loaded. Optimistic about
 * features (the API still enforces every switch and limit; a disabled feature
 * answers with a clear error) so a config hiccup never hides the app's features.
 */
export const DEFAULT_MOBILE_CONFIG: MobileConfig = {
  app_name: "Clone Me",
  version: "",
  maintenance_mode: false,
  registration_enabled: true,
  discovery_enabled: true,
  public_chat_enabled: true,
  billing_enabled: false,
  max_upload_mb: 10,
  voice: { speech_to_text: true, text_to_speech: true, max_recording_seconds: 120, max_audio_mb: 10 },
  avatar: { enabled: true, videos: true, live_calls: true, max_image_mb: 5, max_video_seconds: 60 },
};

export type MobileConfigStatus = "loading" | "ready" | "fallback";

// One request per page session, shared by every component that asks.
let cached: MobileConfig | null = null;
let pending: Promise<MobileConfig | null> | null = null;

function loadMobileConfig(): Promise<MobileConfig | null> {
  if (cached) return Promise.resolve(cached);
  pending ??= apiFetch<MobileConfig>("/api/mobile/config", { cache: "no-store" }, { timeoutMs: 10_000 })
    .then((config) => {
      cached = { ...DEFAULT_MOBILE_CONFIG, ...config, voice: { ...DEFAULT_MOBILE_CONFIG.voice, ...config.voice }, avatar: { ...DEFAULT_MOBILE_CONFIG.avatar, ...config.avatar } };
      return cached;
    })
    .catch(() => {
      pending = null; // try again on the next mount (e.g. after coming back online)
      return null;
    });
  return pending;
}

/** Forget the cached config (e.g. after an admin changed switches). */
export function invalidateMobileConfig() {
  cached = null;
  pending = null;
}

/** The mobile/PWA client config, with safe defaults while loading or if the API is unreachable. */
export function useMobileConfig(): { config: MobileConfig; status: MobileConfigStatus } {
  const [state, setState] = useState<{ config: MobileConfig; status: MobileConfigStatus }>(() =>
    cached ? { config: cached, status: "ready" } : { config: DEFAULT_MOBILE_CONFIG, status: "loading" },
  );

  useEffect(() => {
    if (cached) return;
    let cancelled = false;
    loadMobileConfig().then((config) => {
      if (!cancelled) setState(config ? { config, status: "ready" } : { config: DEFAULT_MOBILE_CONFIG, status: "fallback" });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
