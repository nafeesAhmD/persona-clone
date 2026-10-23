import { redirect } from "next/navigation";

interface OldChatPageProps {
  params: Promise<{ id: string }>;
}

// The chat moved to /clone/[id]; keep old links working.
export default async function OldChatPage({ params }: OldChatPageProps) {
  const { id } = await params;
  redirect(`/clone/${id}`);
}
