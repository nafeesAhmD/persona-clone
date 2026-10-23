import type { Metadata } from "next";

import { InviteAccept } from "@/components/organizations/InviteAccept";

export const metadata: Metadata = {
  title: "Invitation · Clone Me",
  // The URL holds a one-time token: keep it out of search engines and referrers.
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

/** Not behind RequireAuth: logged-out visitors get a sign-in prompt that returns here. */
export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <InviteAccept token={token} />;
}
