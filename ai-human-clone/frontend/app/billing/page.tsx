import type { Metadata } from "next";

import { BillingView } from "@/components/billing/BillingView";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Billing · Clone Me",
};

export default function BillingPage() {
  return (
    <RequireAuth>
      <BillingView />
    </RequireAuth>
  );
}
