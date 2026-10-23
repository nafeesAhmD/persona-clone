"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { CloneAvatar } from "@/components/CloneAvatar";
import { FavoriteButton } from "@/components/marketplace/FavoriteButton";
import { CapabilityBadges, TagList } from "@/components/marketplace/MarketplaceCard";
import { ReportButton } from "@/components/marketplace/ReportDialog";
import { useMarketplaceProfile } from "@/components/marketplace/useMarketplaceProfile";
import { PublicChat } from "@/components/public/PublicChat";
import { ShareButton } from "@/components/public/ShareButton";
import { categoryIcon } from "@/lib/marketplace/categories";
import { publicImageUrl } from "@/lib/publicApi";
import type { PublicClone } from "@/types/public";

/** The public page of a clone: profile, AI disclosure, and the visitor chat. */
export function PublicCloneView({ clone }: { clone: PublicClone }) {
  const [chatOpen, setChatOpen] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  const image = publicImageUrl(clone.avatar_url);
  // Marketplace extras (category, tags, save) only when the clone is listed there.
  const { profile: listing } = useMarketplaceProfile(clone.slug);

  function startChat() {
    setChatOpen(true);
    setTimeout(() => chatRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-14">
      <section className="rounded-2xl border border-border bg-surface-raised p-5 sm:p-8">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-accent-soft">AI Clone</p>
        <div className="mt-3 flex flex-col items-start gap-4 min-[480px]:flex-row sm:gap-5">
          <CloneAvatar name={clone.name} size="xl" src={image} square />
          <div className="min-w-0 flex-1">
            <h1 className="break-words text-2xl font-bold tracking-tight sm:text-3xl">{clone.name}</h1>
            {clone.tagline && <p className="mt-1 text-gray-200">{clone.tagline}</p>}
            {clone.profession && <p className="mt-1 text-sm text-muted">{clone.profession}</p>}
            <p className={`mt-2 flex items-center gap-1.5 text-xs ${clone.public_chat_enabled ? "text-emerald-300" : "text-muted"}`}>
              <span className={`h-2 w-2 rounded-full ${clone.public_chat_enabled ? "bg-emerald-400" : "bg-gray-500"}`} aria-hidden />
              {clone.public_chat_enabled ? "Available to chat" : "Chat is currently turned off"}
            </p>
          </div>
        </div>
        {clone.bio && <p className="mt-5 whitespace-pre-wrap text-sm leading-relaxed text-gray-200">{clone.bio}</p>}
        {clone.skills.length > 0 && (
          <ul className="mt-5 flex flex-wrap gap-2" aria-label="Skills">
            {clone.skills.map((skill) => (
              <li key={skill} className="rounded-full border border-border px-3 py-1 text-xs text-gray-200">{skill}</li>
            ))}
          </ul>
        )}
        {listing && (
          <div className="mt-5 space-y-2">
            {listing.category && (
              <p className="text-xs text-muted">
                <Link href={`/explore/${listing.category.slug}`} className="inline-flex min-h-8 items-center hover:text-white">
                  <span aria-hidden>{categoryIcon(listing.category.slug)}&nbsp;</span>
                  {listing.category.name}
                </Link>
              </p>
            )}
            <TagList tags={listing.tags} />
            <CapabilityBadges capabilities={listing.capabilities} />
          </div>
        )}
        <div className="mt-6 space-y-1 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-xs text-accent-soft">
          <p>AI-generated responses.</p>
          <p>This is an AI representation, not the real person.</p>
        </div>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          {clone.public_chat_enabled && !chatOpen && (
            <button
              type="button"
              onClick={startChat}
              className="flex min-h-12 w-full items-center justify-center rounded-xl bg-accent px-5 font-medium text-ink shadow-lg shadow-accent/25 hover:bg-accent/90 sm:min-h-11 sm:w-auto"
            >
              Start Chat
            </button>
          )}
          {listing && (
            <FavoriteButton key={`${listing.id}:${listing.is_favorite}`} cloneId={listing.id} cloneName={clone.name} initial={listing.is_favorite} />
          )}
          <ShareButton title={`${clone.name} · AI Clone`} text={clone.tagline ?? `Chat with ${clone.name}, an AI Clone.`} />
          <ReportButton slug={clone.slug} cloneName={clone.name} />
        </div>
      </section>

      {clone.public_chat_enabled && chatOpen && (
        <div ref={chatRef} className="mt-6">
          <PublicChat clone={clone} />
        </div>
      )}

      <p className="mt-8 text-center text-xs text-muted">
        <Link href="/explore" className="inline-flex min-h-11 items-center hover:text-white">Explore more AI Clones</Link>
      </p>
    </main>
  );
}
