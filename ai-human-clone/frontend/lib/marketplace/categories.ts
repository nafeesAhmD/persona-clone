/**
 * The marketplace's fixed categories (pure). Same slugs and names as the server
 * (docs/phase18/contract.md); the API also returns them with live counts.
 */

export interface CategoryInfo {
  slug: string;
  name: string;
}

export const CATEGORIES: readonly CategoryInfo[] = [
  { slug: "education", name: "Education & Tutoring" },
  { slug: "technology", name: "Technology & Programming" },
  { slug: "business", name: "Business & Career" },
  { slug: "health", name: "Health & Wellness" },
  { slug: "creative", name: "Creative & Arts" },
  { slug: "lifestyle", name: "Lifestyle & Hobbies" },
  { slug: "language", name: "Languages" },
  { slug: "science", name: "Science & Research" },
  { slug: "entertainment", name: "Entertainment" },
  { slug: "other", name: "Other" },
];

export function isCategory(slug: unknown): slug is string {
  return typeof slug === "string" && CATEGORIES.some((c) => c.slug === slug);
}

export function categoryName(slug: string | null | undefined): string | null {
  if (!slug) return null;
  return CATEGORIES.find((c) => c.slug === slug)?.name ?? null;
}

/** An icon per category, only for decoration (always shown next to the name). */
const ICONS: Record<string, string> = {
  education: "🎓",
  technology: "💻",
  business: "💼",
  health: "🩺",
  creative: "🎨",
  lifestyle: "🌿",
  language: "🗣️",
  science: "🔬",
  entertainment: "🎬",
  other: "✨",
};

export function categoryIcon(slug: string | null | undefined): string {
  return (slug && ICONS[slug]) || "✨";
}
