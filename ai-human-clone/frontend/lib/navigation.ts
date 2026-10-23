/**
 * Navigation rules shared by the desktop top bar, the mobile top bar, the mobile
 * drawer and the mobile bottom navigation.
 *
 * Pure logic only (no React, no DOM) so it can be unit tested with `node --test`.
 */

export type AuthStatus = "loading" | "authenticated" | "anonymous";

export type BottomNavKey = "home" | "clones" | "chat" | "analytics" | "profile";

export interface NavLink {
  key: string;
  href: string;
  label: string;
}

export interface BottomNavItem {
  key: BottomNavKey;
  href: string;
  label: string;
}

/** Only ids made of safe characters are used to build links (they come from localStorage). */
const SAFE_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function isSafeId(value: unknown): value is string {
  return typeof value === "string" && SAFE_ID.test(value);
}

/** Strip a query string / hash and a trailing slash: "/clones/?a=1" -> "/clones". */
export function normalizePath(pathname: string | null | undefined): string {
  if (!pathname) return "/";
  const path = pathname.split(/[?#]/)[0] || "/";
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

function segments(pathname: string): string[] {
  return normalizePath(pathname).split("/").filter(Boolean);
}

/** The clone id when the path is the owner's chat screen `/clone/[id]`, else null. */
export function cloneIdFromChatPath(pathname: string): string | null {
  const parts = segments(pathname);
  if (parts.length === 2 && parts[0] === "clone" && isSafeId(parts[1])) return parts[1];
  return null;
}

/** The "Chat" tab: the last opened clone chat if known, else the clones list. */
export function chatHref(lastCloneId: string | null | undefined): string {
  return isSafeId(lastCloneId) ? `/clone/${lastCloneId}` : "/clones";
}

export function bottomNavItems(lastCloneId: string | null | undefined): BottomNavItem[] {
  return [
    { key: "home", href: "/dashboard", label: "Home" },
    { key: "clones", href: "/clones", label: "Clones" },
    { key: "chat", href: chatHref(lastCloneId), label: "Chat" },
    { key: "analytics", href: "/analytics", label: "Analytics" },
    { key: "profile", href: "/profile", label: "Profile" },
  ];
}

/** Which bottom tab a route belongs to (null: none of them). */
export function activeBottomNavKey(pathname: string): BottomNavKey | null {
  const parts = segments(pathname);
  const [first, , third] = parts;
  if (first === "dashboard" || first === "create-clone") return "home";
  if (first === "clones") return "clones";
  if (first === "analytics") return "analytics";
  if (first === "profile") return "profile";
  if (first === "clone" && parts.length >= 2) {
    if (parts.length === 2 || third === "chat" || third === "call") return "chat";
    if (third === "analytics") return "analytics";
    return "clones"; // edit, details, knowledge, memory, voice, avatar, sharing
  }
  return null;
}

/**
 * Full-height screens manage their own layout (composer pinned to the bottom,
 * call controls), so the bottom navigation is hidden there.
 */
export function isFullHeightRoute(pathname: string): boolean {
  const parts = segments(pathname);
  if (parts[0] === "c" && parts.length >= 2) return true; // public clone chat
  if (parts[0] === "clone" && parts.length >= 2) {
    return parts.length === 2 || parts[2] === "call" || parts[2] === "chat";
  }
  return false;
}

/** Bottom navigation: only for logged-in users, and never on full-height screens. */
export function shouldShowBottomNav(pathname: string, status: AuthStatus): boolean {
  return status === "authenticated" && !isFullHeightRoute(pathname);
}

/**
 * The logical parent of a nested page, used by the mobile back button.
 * Top-level pages (dashboard, clones, profile, analytics, explore…) return null.
 */
export function parentPath(pathname: string): string | null {
  const parts = segments(pathname);
  const [first, second, third] = parts;

  switch (first) {
    case "clone": {
      if (!second) return "/clones";
      const base = `/clone/${second}`;
      if (parts.length === 2) return "/clones"; // the chat screen
      if (third === "details") return "/clones";
      if (third === "knowledge" && parts.length > 3) return `${base}/knowledge`;
      if (third === "agent" && parts.length > 3) return `${base}/agent`; // an agent task -> the agent page
      return `${base}/details`; // edit, knowledge, memory, voice, avatar, sharing, call, analytics, chat, agent
    }
    case "create-clone":
      return "/dashboard";
    case "c":
      return second ? "/explore" : null;
    case "explore":
      if (!second) return null;
      return second === "categories" ? "/explore" : "/explore/categories"; // a category -> all categories
    case "organizations":
      if (!second) return null;
      if (parts.length === 2) return "/organizations";
      return `/organizations/${second}`;
    case "developer":
      return parts.length > 1 ? "/developer" : null;
    case "admin": {
      if (parts.length <= 2) return second && second !== "dashboard" ? "/admin/dashboard" : null;
      return `/admin/${second}`; // e.g. /admin/system/errors -> /admin/system
    }
    default:
      return null;
  }
}

export interface NavUser {
  is_admin?: boolean;
}

/** Links in the mobile drawer (Logout is a separate button). */
export function drawerLinks(user: NavUser | null): NavLink[] {
  if (!user) {
    return [
      { key: "explore", href: "/explore", label: "Explore" },
      { key: "login", href: "/login", label: "Login" },
      { key: "register", href: "/register", label: "Create Account" },
    ];
  }
  const links: NavLink[] = [
    { key: "explore", href: "/explore", label: "Explore" },
    { key: "saved", href: "/saved-clones", label: "Saved Clones" },
    { key: "organizations", href: "/organizations", label: "Organizations" },
    { key: "billing", href: "/billing", label: "Billing" },
    { key: "developer", href: "/developer", label: "Developer" },
  ];
  if (user.is_admin) links.push({ key: "admin", href: "/admin/dashboard", label: "Admin" });
  return links;
}

/** Desktop top bar: the always-visible links, and the ones grouped under "More". */
export function desktopLinks(user: NavUser | null): { primary: NavLink[]; more: NavLink[] } {
  if (!user) {
    return {
      primary: [
        { key: "home", href: "/", label: "Home" },
        { key: "explore", href: "/explore", label: "Explore" },
        { key: "login", href: "/login", label: "Login" },
      ],
      more: [],
    };
  }
  const more: NavLink[] = [
    { key: "saved", href: "/saved-clones", label: "Saved Clones" },
    { key: "organizations", href: "/organizations", label: "Organizations" },
    { key: "billing", href: "/billing", label: "Billing" },
    { key: "developer", href: "/developer", label: "Developer" },
  ];
  if (user.is_admin) more.push({ key: "admin", href: "/admin/dashboard", label: "Admin" });
  return {
    primary: [
      { key: "dashboard", href: "/dashboard", label: "Dashboard" },
      { key: "clones", href: "/clones", label: "Clones" },
      { key: "explore", href: "/explore", label: "Explore" },
      { key: "analytics", href: "/analytics", label: "Analytics" },
      { key: "profile", href: "/profile", label: "Profile" },
    ],
    more,
  };
}

/**
 * Whether a link should be marked as the current section. "/" only matches itself;
 * other links match their own path and anything below it.
 */
export function isLinkActive(href: string, pathname: string): boolean {
  const path = normalizePath(pathname);
  const target = normalizePath(href);
  if (target === "/") return path === "/";
  if (target === "/admin/dashboard") return path === "/admin" || path.startsWith("/admin/");
  return path === target || path.startsWith(`${target}/`);
}

/** Of several section links, the longest matching one wins (so /admin/system/errors isn't also "System"). */
export function activeHref(hrefs: string[], pathname: string): string | null {
  const path = normalizePath(pathname);
  const matches = hrefs.filter((href) => {
    const target = normalizePath(href);
    return path === target || path.startsWith(`${target}/`);
  });
  matches.sort((a, b) => b.length - a.length);
  return matches[0] ?? null;
}

/** localStorage key for the last opened chat, per user so a shared device doesn't mix accounts. */
export function lastChatStorageKey(userId: string): string {
  return `ahc:last-chat:${userId}`;
}

/** Minimal Storage shape, so the helpers can be tested without a browser. */
export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** Read the remembered clone id; storage may be missing or throw (private mode). */
export function readLastChat(storage: KeyValueStorage | null | undefined, userId: string | null | undefined): string | null {
  if (!storage || !userId) return null;
  try {
    const value = storage.getItem(lastChatStorageKey(userId));
    return isSafeId(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeLastChat(
  storage: KeyValueStorage | null | undefined,
  userId: string | null | undefined,
  cloneId: string,
): boolean {
  if (!storage || !userId || !isSafeId(cloneId)) return false;
  try {
    storage.setItem(lastChatStorageKey(userId), cloneId);
    return true;
  } catch {
    return false;
  }
}

export function clearLastChat(storage: KeyValueStorage | null | undefined, userId: string | null | undefined): void {
  if (!storage || !userId) return;
  try {
    storage.removeItem(lastChatStorageKey(userId));
  } catch {
    // Storage unavailable: nothing to clear.
  }
}

/** A short title for the mobile top bar on known routes (null: show the app name). */
export function mobileTitle(pathname: string): string | null {
  const parts = segments(pathname);
  const [first, , third] = parts;
  const titles: Record<string, string> = {
    dashboard: "Home",
    clones: "Clones",
    analytics: "Analytics",
    profile: "Profile",
    explore: "Explore",
    "create-clone": "Create Clone",
    organizations: "Organizations",
    billing: "Billing",
    developer: "Developer",
    admin: "Admin",
    login: "Login",
    register: "Create Account",
    invite: "Invitation",
  };
  if (first === "clone" && parts.length >= 3) {
    const sub: Record<string, string> = {
      edit: "Edit Clone",
      details: "Clone Details",
      knowledge: "Knowledge",
      memory: "Memory",
      voice: "Voice",
      avatar: "Avatar",
      sharing: "Sharing",
      call: "Live Call",
      analytics: "Clone Analytics",
      agent: "AI Agent",
    };
    return sub[third] ?? null;
  }
  if (first === "clone") return "Chat";
  if (first === "c") return "AI Clone";
  return first ? titles[first] ?? null : null;
}
