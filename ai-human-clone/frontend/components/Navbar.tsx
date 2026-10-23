"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { ChevronDownIcon, LogoMark } from "@/components/mobile/icons";
import { useLogout } from "@/components/mobile/useLogout";
import { desktopLinks, isLinkActive, type NavLink } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const linkClass =
  "inline-flex min-h-11 items-center rounded-md px-2 text-muted hover:text-white aria-[current=page]:text-white aria-[current=page]:underline aria-[current=page]:decoration-accent-soft aria-[current=page]:decoration-2 aria-[current=page]:underline-offset-8 lg:px-3";

/** Desktop top bar (md and up). Phones use MobileTopBar + BottomNav instead. */
export function Navbar() {
  const { status, user } = useAuth();
  const pathname = usePathname() ?? "/";
  const { logout, loggingOut } = useLogout();
  const links = desktopLinks(status === "authenticated" ? user : null);

  return (
    <header className="pt-safe sticky top-0 z-30 hidden border-b border-border/60 bg-surface/80 backdrop-blur md:block">
      <nav aria-label="Main" className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-2 px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2 font-semibold tracking-tight">
          <LogoMark />
          <span className="hidden lg:inline">Clone Me</span>
          <span className="sr-only lg:hidden">Clone Me home</span>
        </Link>
        <div className="flex items-center gap-1 text-sm">
          {status === "authenticated" && (
            <>
              {links.primary.map((link) => (
                <Link
                  key={link.key}
                  href={link.href}
                  aria-current={isLinkActive(link.href, pathname) ? "page" : undefined}
                  className={linkClass}
                >
                  {link.label}
                </Link>
              ))}
              <MoreMenu links={links.more} pathname={pathname} />
              <button type="button" onClick={logout} disabled={loggingOut} className={linkClass}>
                {loggingOut ? "Logging out…" : "Logout"}
              </button>
            </>
          )}
          {status === "anonymous" && (
            <>
              {links.primary.map((link) => (
                <Link
                  key={link.key}
                  href={link.href}
                  aria-current={isLinkActive(link.href, pathname) ? "page" : undefined}
                  className={linkClass}
                >
                  {link.label}
                </Link>
              ))}
              <Link
                href="/register"
                className="ml-1 inline-flex min-h-11 items-center rounded-lg bg-accent px-4 font-medium text-ink hover:bg-accent/90"
              >
                Create Account
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}

/** "More" disclosure (click/keyboard, never hover-only). Closes on Escape, outside click or selection. */
function MoreMenu({ links, pathname }: { links: NavLink[]; pathname: string }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const activeInside = links.some((link) => isLinkActive(link.href, pathname));

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    function onFocusOut(event: FocusEvent) {
      if (!rootRef.current?.contains(event.relatedTarget as Node | null)) setOpen(false);
    }
    const root = rootRef.current;
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    root?.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
      root?.removeEventListener("focusout", onFocusOut);
    };
  }, [open]);

  if (links.length === 0) return null;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((value) => !value)}
        className={cn(linkClass, "gap-1", activeInside && "text-white")}
      >
        More
        <ChevronDownIcon className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul
          id={menuId}
          className="absolute right-0 top-full z-40 mt-1 w-48 rounded-xl border border-border bg-surface-raised p-1 shadow-xl"
        >
          {links.map((link) => {
            const current = isLinkActive(link.href, pathname);
            return (
              <li key={link.key}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "flex min-h-11 items-center rounded-lg px-3 text-sm",
                    current ? "bg-accent/15 text-white" : "text-gray-200 hover:bg-white/5",
                    link.key === "admin" && !current && "text-amber-300",
                  )}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
