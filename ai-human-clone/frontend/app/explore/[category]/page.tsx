import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { MarketplaceHome } from "@/components/marketplace/MarketplaceHome";
import { StatusMessage } from "@/components/StatusMessage";
import { categoryName, isCategory } from "@/lib/marketplace/categories";

interface CategoryPageProps {
  params: Promise<{ category: string }>;
}

export async function generateMetadata({ params }: CategoryPageProps): Promise<Metadata> {
  const { category } = await params;
  const name = categoryName(category);
  if (!name) return { title: "Category not found", robots: { index: false, follow: false } };
  return { title: `${name} · Explore AI Clones`, description: `AI Clones published in ${name}.` };
}

export default async function CategoryPage({ params }: CategoryPageProps) {
  const { category } = await params;
  if (!isCategory(category)) notFound();
  return (
    <Suspense fallback={<StatusMessage title="Loading AI Clones…" />}>
      <MarketplaceHome fixedCategory={category} />
    </Suspense>
  );
}
