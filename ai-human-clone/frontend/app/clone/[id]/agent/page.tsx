import type { Metadata } from "next";

import { AgentManager } from "@/components/agent/AgentManager";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "AI Agent · Clone Me",
};

export default async function AgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequireAuth>
      <AgentManager cloneId={id} />
    </RequireAuth>
  );
}
