"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/AuthProvider";
import { BottomNav } from "@/components/mobile/BottomNav";
import { rememberLastChat, useLastChatId } from "@/components/mobile/lastChat";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { Navbar } from "@/components/Navbar";
import { cloneIdFromChatPath, shouldShowBottomNav } from "@/lib/navigation";

/**
 * The app frame. md and up: the desktop top Navbar. Below md: MobileTopBar
 * (back button, title, drawer menu) and, for logged-in users outside full-height
 * screens, the BottomNav. Pages render their own <main>.
 */
export function MobileShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const { status, user } = useAuth();
  const userId = status === "authenticated" ? user?.id : null;
  const lastCloneId = useLastChatId(userId);
  const showBottomNav = shouldShowBottomNav(pathname, status);

  // Remember the last opened clone chat for the "Chat" tab.
  const chatCloneId = cloneIdFromChatPath(pathname);
  useEffect(() => {
    if (chatCloneId && userId) rememberLastChat(userId, chatCloneId);
  }, [chatCloneId, userId]);

  return (
    <>
      <a
        href="#main-content"
        className="sr-only z-[60] rounded-lg bg-accent px-4 py-2 text-ink focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <Navbar />
      <MobileTopBar pathname={pathname} />
      <div id="main-content" tabIndex={-1} className={showBottomNav ? "pb-bottom-nav outline-none md:pb-0" : "outline-none"}>
        {children}
      </div>
      {showBottomNav && <BottomNav pathname={pathname} lastCloneId={lastCloneId} />}
    </>
  );
}
