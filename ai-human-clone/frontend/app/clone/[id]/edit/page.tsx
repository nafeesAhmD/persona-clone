import type { Metadata } from "next";

import { EditClone } from "@/components/clone/EditClone";
import { RequireAuth } from "@/components/RequireAuth";

interface EditClonePageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Edit Clone · Clone Me",
};

export default async function EditClonePage({ params }: EditClonePageProps) {
  const { id } = await params;
  return (
    <RequireAuth>
      <EditClone cloneId={id} />
    </RequireAuth>
  );
}
