import type { Metadata, Viewport } from "next";

import { AuthProvider } from "@/components/AuthProvider";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { MobileShell } from "@/components/mobile/MobileShell";
import { PwaLayer } from "@/components/pwa/PwaLayer";

import "./globals.css";

export const metadata: Metadata = {
  title: "Clone Me",
  description:
    "Create a consent-based AI clone that answers questions using the knowledge and style you provide.",
  applicationName: "Clone Me",
  appleWebApp: { capable: true, title: "AI Clone", statusBarStyle: "black-translucent" },
  formatDetection: { telephone: false },
};

// Phones: fit the screen (incl. notches via safe-area insets) and resize the layout
// when the keyboard opens, so the chat composer stays visible.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: "#0b0d14",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-dvh font-sans antialiased">
        <AuthProvider>
          <MaintenanceBanner />
          <MobileShell>{children}</MobileShell>
          <PwaLayer />
        </AuthProvider>
      </body>
    </html>
  );
}
