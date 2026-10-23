import Link from "next/link";

import { CloneAvatar } from "@/components/CloneAvatar";
import { categoryIcon } from "@/lib/marketplace/categories";
import { capabilityBadges, cardSummary } from "@/lib/marketplace/display";
import { publicImageUrl } from "@/lib/publicApi";
import type { MarketplaceCapabilities, MarketplaceCard as Card } from "@/types/marketplace";

export function CapabilityBadges({ capabilities, className = "" }: { capabilities: MarketplaceCapabilities | null | undefined; className?: string }) {
  const badges = capabilityBadges(capabilities);
  if (badges.length === 0) return null;
  return (
    <ul className={`flex flex-wrap gap-1.5 ${className}`} aria-label="Available">
      {badges.map((badge) => (
        <li key={badge.key} className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent-soft">
          <span aria-hidden>{badge.icon} </span>
          {badge.label}
        </li>
      ))}
    </ul>
  );
}

export function TagList({ tags, max, className = "" }: { tags: string[]; max?: number; className?: string }) {
  const shown = max ? tags.slice(0, max) : tags;
  if (shown.length === 0) return null;
  return (
    <ul className={`flex flex-wrap gap-1.5 ${className}`} aria-label="Tags">
      {shown.map((tag) => (
        <li key={tag} className="rounded-full border border-border px-2 py-0.5 text-[11px] text-gray-300">
          #{tag}
        </li>
      ))}
      {max && tags.length > max && <li className="px-1 text-[11px] text-muted">+{tags.length - max}</li>}
    </ul>
  );
}

/** One clone in discovery results. Public metadata only; no ratings by design. */
export function MarketplaceCard({ clone, action }: { clone: Card; action?: React.ReactNode }) {
  const summary = cardSummary(clone);
  return (
    <div className="relative flex h-full flex-col rounded-2xl border border-border bg-surface-raised p-5 transition hover:border-accent">
      <div className="flex items-center gap-3">
        <CloneAvatar name={clone.name} src={publicImageUrl(clone.avatar_url)} square />
        <div className="min-w-0 flex-1">
          <Link href={`/c/${clone.slug}`} className="block truncate font-semibold after:absolute after:inset-0 after:rounded-2xl focus:outline-none">
            {clone.name}
          </Link>
          <p className="truncate text-xs text-muted">{clone.profession ?? "AI Clone"}</p>
        </div>
        {clone.featured && (
          <span className="shrink-0 rounded-full bg-amber-400/15 px-2 py-0.5 text-[11px] text-amber-200">Featured</span>
        )}
      </div>
      {summary && <p className="mt-3 line-clamp-2 text-sm text-gray-200">{summary}</p>}
      {clone.category && (
        <p className="mt-3 text-xs text-muted">
          <span aria-hidden>{categoryIcon(clone.category.slug)} </span>
          {clone.category.name}
        </p>
      )}
      <TagList tags={clone.tags} max={4} className="mt-2" />
      <div className="mt-auto flex items-end justify-between gap-2 pt-3">
        <CapabilityBadges capabilities={clone.capabilities} />
        {action && <div className="relative z-10 shrink-0">{action}</div>}
      </div>
    </div>
  );
}

export function CardGrid({ clones, action }: { clones: Card[]; action?: (clone: Card) => React.ReactNode }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {clones.map((clone) => (
        <li key={clone.id}>
          <MarketplaceCard clone={clone} action={action?.(clone)} />
        </li>
      ))}
    </ul>
  );
}

export function CardSkeletons({ count = 6 }: { count?: number }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="h-40 animate-pulse rounded-2xl border border-border bg-surface-raised/60" />
      ))}
    </ul>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200" role="alert">
      <span aria-hidden="true">⚠ </span>
      {message}
      {onRetry && (
        <button type="button" onClick={onRetry} className="ml-3 min-h-11 rounded-lg border border-rose-400/40 px-3 text-rose-100 hover:bg-rose-500/10">
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyBox({ children }: { children: React.ReactNode }) {
  return <p className="rounded-2xl border border-dashed border-border p-10 text-center text-sm text-muted">{children}</p>;
}
