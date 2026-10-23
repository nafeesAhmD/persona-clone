import type { Metadata } from "next";

import { RequireAuth } from "@/components/RequireAuth";
import { LiveVoicePage } from "@/components/realtime/LiveVoicePage";

interface LiveVoicePageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Live Voice · AI Human Clone",
};

export default async function LiveVoiceRoute({ params }: LiveVoicePageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <LiveVoicePage cloneId={id} />
    </RequireAuth>
  );
}
