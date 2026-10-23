import type { Metadata } from "next";
import { Suspense } from "react";

import { MarketplaceHome } from "@/components/marketplace/MarketplaceHome";
import { StatusMessage } from "@/components/StatusMessage";

export const metadata: Metadata = {
  title: "Explore AI Clones · Clone Me",
  description: "Discover AI Clones that their owners chose to publish: search by name, profession, skill or tag.",
};

export default function ExplorePage() {
  return (
    // Filters live in the URL (useSearchParams), which needs a Suspense boundary.
    <Suspense fallback={<StatusMessage title="Loading AI Clones…" />}>
      <MarketplaceHome />
    </Suspense>
  );
}
