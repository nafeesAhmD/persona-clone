"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getAvatarSettings } from "@/lib/api";
import { liveApi } from "@/lib/liveApi";
import { REALISM_STATE_LABELS, type RealismInput, type RealismState, realismChecklist } from "@/lib/voiceClone";
import { getVoiceClone } from "@/lib/voiceCloneApi";

const STATE_STYLE: Record<RealismState, { icon: string; className: string }> = {
  done: { icon: "✓", className: "border-emerald-500/40 text-emerald-200" },
  partial: { icon: "◐", className: "border-amber-400/40 text-amber-200" },
  todo: { icon: "○", className: "border-border text-gray-200" },
  unavailable: { icon: "⚠", className: "border-rose-500/40 text-rose-300" },
  unknown: { icon: "?", className: "border-border text-muted" },
};

/**
 * "Make it look and sound real": your own voice + realistic avatar videos + live call face.
 * Each check loads on its own; a failing call only marks that row "Unknown".
 */
export function RealismChecklist({ cloneId }: { cloneId: string }) {
  const [input, setInput] = useState<RealismInput | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getVoiceClone(cloneId), getAvatarSettings(cloneId), liveApi.status(cloneId)]).then(([voice, avatar, live]) => {
      if (cancelled) return;
      setInput({
        voice: voice.status === "fulfilled" ? voice.value : null,
        avatar: avatar.status === "fulfilled" ? avatar.value : null,
        live: live.status === "fulfilled" ? live.value : null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [cloneId]);

  const items = input ? realismChecklist(input) : [];
  const doneCount = items.filter((i) => i.state === "done").length;

  return (
    <section className="rounded-2xl border border-border bg-surface-raised p-5" aria-labelledby="realism-heading">
      <h2 id="realism-heading" className="font-semibold">Make it look and sound real</h2>
      <p className="mt-2 text-sm text-muted">
        Your voice, a realistic face in videos and a live video call face. Everything stays labelled as AI-generated.
      </p>
      {!input ? (
        <p className="mt-4 text-sm text-muted" role="status">Checking…</p>
      ) : (
        <>
          <p className="mt-3 text-sm" role="status">
            {doneCount} of {items.length} done
          </p>
          <ul className="mt-3 space-y-3">
            {items.map((item) => {
              const style = STATE_STYLE[item.state];
              return (
                <li key={item.key} className="rounded-xl border border-border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{item.title}</span>
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${style.className}`}>
                      <span aria-hidden="true">{style.icon}</span>
                      {REALISM_STATE_LABELS[item.state]}
                    </span>
                  </div>
                  <p className="mt-1 text-muted">{item.detail}</p>
                  {(item.state === "unavailable" || item.state === "unknown") && (
                    <p className="mt-1 break-words text-xs text-muted">{item.serverHint}</p>
                  )}
                  <Link
                    href={`/clone/${cloneId}/${item.path}`}
                    className={
                      item.state === "done" || item.state === "unavailable"
                        ? "mt-1 inline-flex min-h-11 items-center text-sm text-accent-soft hover:underline"
                        : "mt-2 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
                    }
                  >
                    {item.linkLabel}
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
