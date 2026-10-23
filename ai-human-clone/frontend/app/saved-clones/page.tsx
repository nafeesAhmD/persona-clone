import type { Metadata } from "next";

import { SavedClones } from "@/components/marketplace/SavedClones";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Saved AI Clones · AI Human Clone",
  robots: { index: false, follow: false },
};

export default function SavedClonesPage() {
  return (
    <RequireAuth>
      <SavedClones />
    </RequireAuth>
  );
}
