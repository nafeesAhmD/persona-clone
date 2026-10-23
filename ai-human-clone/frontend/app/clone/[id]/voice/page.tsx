import type { Metadata } from "next";

import { RequireAuth } from "@/components/RequireAuth";
import { VoiceSettingsPanel } from "@/components/voice/VoiceSettingsPanel";

interface VoicePageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Voice · Clone Me",
};

export default async function VoicePage({ params }: VoicePageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <main>
        <VoiceSettingsPanel cloneId={id} />
      </main>
    </RequireAuth>
  );
}
