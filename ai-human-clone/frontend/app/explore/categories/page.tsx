import type { Metadata } from "next";

import { CategoryBrowser } from "@/components/marketplace/CategoryBrowser";

export const metadata: Metadata = {
  title: "Categories · Explore AI Clones",
  description: "Browse published AI Clones by category.",
};

export default function CategoriesPage() {
  return <CategoryBrowser />;
}
