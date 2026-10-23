import type { Metadata } from "next";

import { ProfileView } from "@/components/ProfileView";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Profile · Clone Me",
};

export default function ProfilePage() {
  return (
    <RequireAuth>
      <ProfileView />
    </RequireAuth>
  );
}
