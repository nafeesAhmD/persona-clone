"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { activeHref } from "@/lib/navigation";
import { cn } from "@/lib/utils";

interface SectionNavProps {
  label: string;
  heading: string;
  headingClass: string;
  items: { href: string; label: string }[];
  pathname: string;
}

/**
 * Sub-navigation of an area (admin, developer). lg and up: a vertical sidebar.
 * Smaller screens: a horizontally scrolling row of tabs (the page itself never
 * scrolls sideways); the current tab is scrolled into view.
 */
export function SectionNav({ label, heading, headingClass, items, pathname }: SectionNavProps) {
  const active = activeHref(
    items.map((item) => item.href),
    pathname,
  );
  const activeRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [active]);

  return (
    <aside className="min-w-0 lg:w-52 lg:shrink-0">
      <p className={cn("mb-2 px-1 text-xs font-semibold uppercase tracking-wider lg:px-3", headingClass)}>{heading}</p>
      <nav aria-label={label} className="-mx-4 sm:-mx-6 lg:mx-0">
        <ul className="scrollbar-none flex snap-x gap-1 overflow-x-auto px-4 pb-1 sm:px-6 lg:flex-col lg:overflow-visible lg:px-0 lg:pb-0">
          {items.map((item) => {
            const current = active === item.href;
            return (
              <li key={item.href} className="shrink-0 snap-start">
                <Link
                  ref={current ? activeRef : undefined}
                  href={item.href}
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "flex min-h-11 items-center whitespace-nowrap rounded-lg border px-3 text-sm lg:min-h-0 lg:border-0 lg:py-2",
                    current
                      ? "border-accent/50 bg-accent/15 font-medium text-white"
                      : "border-border text-muted hover:bg-surface-raised hover:text-white",
                  )}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
