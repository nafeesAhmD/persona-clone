import type { Metadata } from "next";

import { AgentExecutionView } from "@/components/agent/AgentExecutionView";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Agent Task · Clone Me",
};

export default async function AgentExecutionPage({ params }: { params: Promise<{ id: string; executionId: string }> }) {
  const { id, executionId } = await params;
  return (
    <RequireAuth>
      <AgentExecutionView cloneId={id} executionId={executionId} />
    </RequireAuth>
  );
}
