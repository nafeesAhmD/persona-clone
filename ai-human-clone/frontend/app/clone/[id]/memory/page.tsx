import type { Metadata } from "next";

import { MemoryManager } from "@/components/memory/MemoryManager";
import { RequireAuth } from "@/components/RequireAuth";

interface MemoryPageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Long-Term Memory · Clone Me",
};

export default async function MemoryPage({ params }: MemoryPageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <main>
        <MemoryManager cloneId={id} />
      </main>
    </RequireAuth>
  );
}
