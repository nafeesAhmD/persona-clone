"use client";

import { useState } from "react";

import { cn, initials } from "@/lib/utils";

interface CloneAvatarProps {
  name: string;
  size?: "sm" | "md" | "lg" | "xl";
  /** Optional image URL (owner-provided or from the API). Falls back to initials if it fails. */
  src?: string | null;
  /** Rounded square instead of a circle. */
  square?: boolean;
}

const SIZES = {
  sm: "h-8 w-8 text-xs",
  md: "h-11 w-11 text-sm",
  lg: "h-16 w-16 text-lg",
  xl: "h-24 w-24 text-2xl",
};

export function CloneAvatar({ name, size = "md", src, square = false }: CloneAvatarProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = Boolean(src) && failedSrc !== src;
  const shape = square ? "rounded-2xl" : "rounded-full";

  return (
    <div
      role="img"
      aria-label={`${name} avatar (AI)`}
      className={cn(
        "relative grid shrink-0 place-items-center bg-gradient-to-br from-accent-soft to-accent font-semibold text-ink",
        shape,
        SIZES[size],
      )}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- avatar_url may be any owner-provided URL
        <img
          src={src!}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailedSrc(src ?? null)}
          className={cn("h-full w-full object-cover", shape)}
        />
      ) : (
        <span aria-hidden="true">{initials(name)}</span>
      )}
      <span
        aria-hidden="true"
        className="absolute -bottom-1 -right-1 rounded-full border border-surface bg-surface-raised px-1 text-[9px] font-bold text-accent-soft"
      >
        AI
      </span>
    </div>
  );
}
