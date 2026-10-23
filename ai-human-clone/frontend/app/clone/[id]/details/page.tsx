import type { Metadata } from "next";

import { CloneDetails } from "@/components/clone/CloneDetails";
import { RequireAuth } from "@/components/RequireAuth";

interface ClonePageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ saved?: string }>;
}

export const metadata: Metadata = {
  title: "Clone Details · Clone Me",
};

export default async function ClonePage({ params, searchParams }: ClonePageProps) {
  const [{ id }, { saved }] = await Promise.all([params, searchParams]);
  return (
    <RequireAuth>
      <CloneDetails cloneId={id} justSaved={saved === "1"} />
    </RequireAuth>
  );
}
