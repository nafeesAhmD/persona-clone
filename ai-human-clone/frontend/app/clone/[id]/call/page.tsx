import type { Metadata } from "next";

import { LiveCall } from "@/components/live/LiveCall";
import { RequireAuth } from "@/components/RequireAuth";

interface CallPageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Video Call · Clone Me",
};

export default async function CallPage({ params }: CallPageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <LiveCall cloneId={id} />
    </RequireAuth>
  );
}
