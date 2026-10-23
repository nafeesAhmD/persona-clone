"use client";

import Link from "next/link";

import { AnalyticsIcon, ChatIcon, ClonesIcon, HomeIcon, ProfileIcon } from "@/components/mobile/icons";
import { activeBottomNavKey, bottomNavItems, type BottomNavKey } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const ICONS: Record<BottomNavKey, (props: { className?: string }) => React.ReactNode> = {
  home: HomeIcon,
  clones: ClonesIcon,
  chat: ChatIcon,
  analytics: AnalyticsIcon,
  profile: ProfileIcon,
};

/** Phone tab bar (hidden from md up). Fixed to the bottom, above the home indicator. */
export function BottomNav({ pathname, lastCloneId }: { pathname: string; lastCloneId: string | null }) {
  const active = activeBottomNavKey(pathname);

  return (
    <nav
      aria-label="Main"
      className="pb-safe pl-safe pr-safe fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 backdrop-blur md:hidden"
    >
      <ul className="mx-auto grid h-16 max-w-md grid-cols-5">
        {bottomNavItems(lastCloneId).map((item) => {
          const Icon = ICONS[item.key];
          const current = active === item.key;
          return (
            <li key={item.key} className="flex">
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "relative flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors",
                  current ? "text-white" : "text-muted active:text-white",
                )}
              >
                {/* Active indicator: a bar plus bold label, so it doesn't rely on colour alone. */}
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute top-0 h-0.5 w-8 rounded-full bg-accent-soft transition-opacity",
                    current ? "opacity-100" : "opacity-0",
                  )}
                />
                <Icon className={cn("h-6 w-6", current && "text-accent-soft")} />
                <span className={current ? "font-semibold" : undefined}>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
