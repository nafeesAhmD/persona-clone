import type { Metadata } from "next";

import { KnowledgeManager } from "@/components/knowledge/KnowledgeManager";
import { RequireAuth } from "@/components/RequireAuth";

interface KnowledgePageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Knowledge · Clone Me",
};

export default async function KnowledgePage({ params }: KnowledgePageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <main>
        <KnowledgeManager cloneId={id} />
      </main>
    </RequireAuth>
  );
}
