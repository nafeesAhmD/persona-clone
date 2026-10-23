"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Drawer } from "@/components/mobile/Drawer";
import { BackIcon, LogoMark, LogoutIcon, MenuIcon } from "@/components/mobile/icons";
import { useLogout } from "@/components/mobile/useLogout";
import { drawerLinks, isLinkActive, mobileTitle, parentPath } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const iconButton = "grid h-11 w-11 shrink-0 place-items-center rounded-lg text-muted hover:text-white active:bg-white/5";

/** Phone top bar (hidden from md up): back button on nested pages, logo/title, menu. */
export function MobileTopBar({ pathname }: { pathname: string }) {
  const { status, user } = useAuth();
  const { logout, loggingOut } = useLogout();
  const [menuOpen, setMenuOpen] = useState(false);
  const parent = parentPath(pathname);
  const title = mobileTitle(pathname);
  const close = () => setMenuOpen(false);

  return (
    <>
      <header className="pt-safe pl-safe pr-safe sticky top-0 z-30 border-b border-border/60 bg-surface/90 backdrop-blur md:hidden">
        <nav aria-label="Top" className="flex h-16 items-center gap-1 px-2 short:h-12">
          {parent ? (
            <Link href={parent} aria-label="Back" className={iconButton}>
              <BackIcon />
            </Link>
          ) : null}
          <Link
            href={status === "authenticated" ? "/dashboard" : "/"}
            className={cn("flex min-h-11 min-w-0 items-center gap-2 rounded-lg px-1 font-semibold tracking-tight", !parent && "pl-2")}
          >
            <LogoMark />
            {/* The page name doubles as a visual title; the real <h1> is in the page. */}
            {/* Logged out, narrow phones need the room for Login / Sign up: show just the logo. */}
            <span className={cn("truncate", status !== "authenticated" && "hidden min-[400px]:inline")}>
              {title ?? "Clone Me"}
            </span>
            <span className="sr-only"> – Clone Me home</span>
          </Link>

          <div className="ml-auto flex shrink-0 items-center gap-1">
            {status === "anonymous" && (
              <>
                <Link
                  href="/explore"
                  aria-current={isLinkActive("/explore", pathname) ? "page" : undefined}
                  className="hidden min-h-11 items-center rounded-lg px-2 text-sm text-muted hover:text-white aria-[current=page]:text-white min-[400px]:flex"
                >
                  Explore
                </Link>
                <Link
                  href="/login"
                  aria-current={isLinkActive("/login", pathname) ? "page" : undefined}
                  className="flex min-h-11 items-center rounded-lg px-2 text-sm text-muted hover:text-white aria-[current=page]:text-white"
                >
                  Login
                </Link>
                <Link
                  href="/register"
                  className="flex min-h-11 items-center rounded-lg bg-accent px-3 text-sm font-medium text-ink hover:bg-accent/90"
                >
                  <span className="min-[360px]:hidden">Sign up</span>
                  <span className="hidden min-[360px]:inline">Create Account</span>
                </Link>
              </>
            )}
            {status !== "loading" && (
              <button
                type="button"
                onClick={() => setMenuOpen(true)}
                aria-label="Open menu"
                aria-haspopup="dialog"
                aria-expanded={menuOpen}
                className={cn(iconButton, status === "anonymous" && "min-[400px]:hidden")}
              >
                <MenuIcon />
              </button>
            )}
          </div>
        </nav>
      </header>

      <Drawer open={menuOpen} title="Menu" onClose={close}>
        {user && (
          <div className="mb-3 px-3 pb-3 text-sm">
            <p className="truncate font-medium">{user.full_name || user.username}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
          </div>
        )}
        <ul className="space-y-1">
          {drawerLinks(status === "authenticated" ? user : null).map((link) => {
            const current = isLinkActive(link.href, pathname);
            return (
              <li key={link.key}>
                <Link
                  href={link.href}
                  onClick={close}
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "flex min-h-12 items-center justify-between rounded-xl px-3 text-base",
                    current ? "bg-accent/15 font-semibold text-white" : "text-gray-200 hover:bg-white/5",
                    link.key === "admin" && !current && "text-amber-300",
                  )}
                >
                  {link.label}
                  {current && <span className="text-xs font-normal text-accent-soft">Current</span>}
                </Link>
              </li>
            );
          })}
        </ul>
        {status === "authenticated" && (
          <div className="mt-3 border-t border-border pt-3">
            <button
              type="button"
              disabled={loggingOut}
              onClick={async () => {
                close();
                await logout();
              }}
              className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-left text-base text-rose-300 hover:bg-rose-500/10 disabled:opacity-60"
            >
              <LogoutIcon className="h-5 w-5" />
              {loggingOut ? "Logging out…" : "Logout"}
            </button>
          </div>
        )}
      </Drawer>
    </>
  );
}
