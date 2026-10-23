import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PublicCloneView } from "@/components/public/PublicCloneView";
import type { PublicClone } from "@/types/public";

interface PublicClonePageProps {
  params: Promise<{ slug: string }>;
}

// Rendered per request so a clone made private disappears immediately.
export const dynamic = "force-dynamic";

/** Server-side lookup (inside Docker the API is reached at API_INTERNAL_URL). */
async function fetchClone(slug: string): Promise<PublicClone | null> {
  const base = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${base}/api/public/clones/${encodeURIComponent(slug)}`, { cache: "no-store" });
    return response.ok ? ((await response.json()) as PublicClone) : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: PublicClonePageProps): Promise<Metadata> {
  const { slug } = await params;
  const clone = await fetchClone(slug);
  if (!clone) return { title: "AI Clone not found", robots: { index: false, follow: false } };
  const title = `${clone.name} · AI Clone`;
  const description = clone.tagline || clone.profession || `Chat with ${clone.name}, an AI Clone.`;
  const publicBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const image = clone.avatar_url?.startsWith("/api/") ? `${publicBase}${clone.avatar_url}` : clone.avatar_url;
  return {
    title,
    description,
    // Only public clones may be indexed; unlisted ones are for people with the link.
    robots: clone.visibility === "public" ? { index: true, follow: true } : { index: false, follow: false },
    openGraph: { title, description, type: "profile", ...(image ? { images: [{ url: image }] } : {}) },
  };
}

export default async function PublicClonePage({ params }: PublicClonePageProps) {
  const { slug } = await params;
  const clone = await fetchClone(slug);
  if (!clone) notFound(); // a real 404 for wrong links and private clones
  return <PublicCloneView clone={clone} />;
}
