import type { Metadata } from "next";

import { SharingPanel } from "@/components/public/SharingPanel";
import { RequireAuth } from "@/components/RequireAuth";

interface SharingPageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Share Clone · Clone Me",
  robots: { index: false, follow: false },
};

export default async function SharingPage({ params }: SharingPageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <main>
        <SharingPanel cloneId={id} />
      </main>
    </RequireAuth>
  );
}
