import type { Metadata } from "next";

import { CreateClone } from "@/components/clone/CreateClone";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Create Clone · Clone Me",
};

export default function CreateClonePage() {
  return (
    <RequireAuth>
      <CreateClone />
    </RequireAuth>
  );
}
