import type { Metadata } from "next";

import { AvatarSettingsPanel } from "@/components/avatar/AvatarSettingsPanel";
import { RequireAuth } from "@/components/RequireAuth";

interface AvatarPageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Avatar · Clone Me",
};

export default async function AvatarPage({ params }: AvatarPageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <main>
        <AvatarSettingsPanel cloneId={id} />
      </main>
    </RequireAuth>
  );
}
