import type { Metadata } from "next";

import { DocumentView } from "@/components/knowledge/DocumentView";
import { RequireAuth } from "@/components/RequireAuth";

interface DocumentPageProps {
  params: Promise<{ id: string; documentId: string }>;
}

export const metadata: Metadata = {
  title: "Knowledge · Clone Me",
};

export default async function DocumentPage({ params }: DocumentPageProps) {
  const { id, documentId } = await params;
  return (
    <RequireAuth>
      <DocumentView cloneId={id} documentId={documentId} />
    </RequireAuth>
  );
}
