import type { Metadata } from "next";

import { DeveloperShell } from "@/components/developer/DeveloperShell";

export const metadata: Metadata = {
  title: "Developer · Clone Me",
  robots: { index: false, follow: false },
};

export default function DeveloperLayout({ children }: { children: React.ReactNode }) {
  return <DeveloperShell>{children}</DeveloperShell>;
}
