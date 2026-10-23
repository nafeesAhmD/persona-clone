import type { Metadata } from "next";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { RequireAuth } from "@/components/RequireAuth";

interface ClonePageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ c?: string }>;
}

export const metadata: Metadata = {
  title: "Chat · Clone Me",
};

// The clone chat. Login is required; the API decides who may chat with the clone.
export default async function ClonePage({ params, searchParams }: ClonePageProps) {
  const [{ id }, { c }] = await Promise.all([params, searchParams]);
  return (
    <RequireAuth>
      <main>
        <ChatWindow cloneId={id} initialConversationId={c ?? null} />
      </main>
    </RequireAuth>
  );
}
