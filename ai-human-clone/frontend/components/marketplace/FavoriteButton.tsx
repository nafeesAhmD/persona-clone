"use client";

import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { marketplaceErrorMessage } from "@/lib/marketplace/display";
import { type MarketplaceError, marketplaceApi } from "@/lib/marketplaceApi";

/**
 * ♡ Save / ♥ Saved. Logged-out users are sent to log in first (and come back here).
 * The server ignores duplicates, so a double click can't create two favorites.
 */
export function FavoriteButton({
  cloneId,
  cloneName,
  initial,
  compact = false,
  onChange,
}: {
  cloneId: string;
  cloneName: string;
  initial: boolean;
  compact?: boolean;
  onChange?: (saved: boolean) => void;
}) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (status !== "authenticated") {
      router.push(`/login?next=${encodeURIComponent(pathname || "/explore")}`);
      return;
    }
    const next = !saved;
    setBusy(true);
    setError(null);
    try {
      if (next) await marketplaceApi.addFavorite(cloneId);
      else await marketplaceApi.removeFavorite(cloneId);
      setSaved(next);
      onChange?.(next);
    } catch (err) {
      setError(marketplaceErrorMessage(err as MarketplaceError));
    } finally {
      setBusy(false);
    }
  }

  const label = saved ? `Remove ${cloneName} from saved clones` : `Save ${cloneName}`;
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={toggle}
        disabled={busy || status === "loading"}
        aria-pressed={saved}
        aria-label={compact ? label : undefined}
        title={label}
        className={
          compact
            ? `flex h-11 w-11 items-center justify-center rounded-xl border text-lg ${saved ? "border-rose-400/50 text-rose-300" : "border-border text-gray-300 hover:border-accent"} disabled:opacity-50`
            : `flex min-h-12 items-center justify-center gap-2 rounded-xl border px-5 font-medium sm:min-h-11 ${saved ? "border-rose-400/50 text-rose-200" : "border-border text-gray-100 hover:border-accent"} disabled:opacity-50`
        }
      >
        <span aria-hidden>{saved ? "♥" : "♡"}</span>
        {!compact && (saved ? "Saved" : "Save")}
      </button>
      {error && (
        <span className="text-xs text-rose-300" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
