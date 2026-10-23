import assert from "node:assert/strict";
import test from "node:test";

import {
  activeBottomNavKey,
  activeHref,
  bottomNavItems,
  chatHref,
  clearLastChat,
  cloneIdFromChatPath,
  desktopLinks,
  drawerLinks,
  isFullHeightRoute,
  isLinkActive,
  isSafeId,
  mobileTitle,
  normalizePath,
  parentPath,
  readLastChat,
  shouldShowBottomNav,
  writeLastChat,
  type KeyValueStorage,
} from "../lib/navigation.ts";

const ID = "3f2c1a7e-1111-4c2d-9e8f-0123456789ab";

function memoryStorage(): KeyValueStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

const throwingStorage: KeyValueStorage = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
  removeItem: () => {
    throw new Error("blocked");
  },
};

test("normalizePath strips query, hash and trailing slash", () => {
  assert.equal(normalizePath("/clones/?a=1"), "/clones");
  assert.equal(normalizePath("/explore#top"), "/explore");
  assert.equal(normalizePath("/"), "/");
  assert.equal(normalizePath(""), "/");
  assert.equal(normalizePath(null), "/");
});

test("isSafeId only accepts plain ids", () => {
  assert.ok(isSafeId(ID));
  assert.ok(!isSafeId("../admin"));
  assert.ok(!isSafeId("a/b"));
  assert.ok(!isSafeId(""));
  assert.ok(!isSafeId(null));
  assert.ok(!isSafeId("x".repeat(65)));
});

test("bottom nav active item per route", () => {
  assert.equal(activeBottomNavKey("/dashboard"), "home");
  assert.equal(activeBottomNavKey("/create-clone"), "home");
  assert.equal(activeBottomNavKey("/clones"), "clones");
  assert.equal(activeBottomNavKey(`/clone/${ID}/edit`), "clones");
  assert.equal(activeBottomNavKey(`/clone/${ID}/details`), "clones");
  assert.equal(activeBottomNavKey(`/clone/${ID}/agent`), "clones");
  assert.equal(activeBottomNavKey(`/clone/${ID}/knowledge/doc-1`), "clones");
  assert.equal(activeBottomNavKey(`/clone/${ID}`), "chat");
  assert.equal(activeBottomNavKey(`/clone/${ID}/call`), "chat");
  assert.equal(activeBottomNavKey("/analytics"), "analytics");
  assert.equal(activeBottomNavKey(`/clone/${ID}/analytics`), "analytics");
  assert.equal(activeBottomNavKey("/profile"), "profile");
  assert.equal(activeBottomNavKey("/explore"), null);
  assert.equal(activeBottomNavKey("/developer/keys"), null);
  assert.equal(activeBottomNavKey("/"), null);
});

test("chat tab links to the last opened chat, else the clones list", () => {
  assert.equal(chatHref(ID), `/clone/${ID}`);
  assert.equal(chatHref(null), "/clones");
  assert.equal(chatHref("../../admin"), "/clones");
  const items = bottomNavItems(ID);
  assert.deepEqual(
    items.map((i) => i.key),
    ["home", "clones", "chat", "analytics", "profile"],
  );
  assert.equal(items.find((i) => i.key === "chat")?.href, `/clone/${ID}`);
  assert.equal(bottomNavItems(undefined).find((i) => i.key === "chat")?.href, "/clones");
});

test("clone id is read only from the chat route", () => {
  assert.equal(cloneIdFromChatPath(`/clone/${ID}`), ID);
  assert.equal(cloneIdFromChatPath(`/clone/${ID}/`), ID);
  assert.equal(cloneIdFromChatPath(`/clone/${ID}/edit`), null);
  assert.equal(cloneIdFromChatPath("/clones"), null);
  assert.equal(cloneIdFromChatPath("/clone/bad%2Fid"), null);
});

test("bottom nav hides on full-height screens and for anonymous users", () => {
  assert.ok(isFullHeightRoute(`/clone/${ID}`));
  assert.ok(isFullHeightRoute(`/clone/${ID}/call`));
  assert.ok(isFullHeightRoute("/c/ayaan"));
  assert.ok(!isFullHeightRoute(`/clone/${ID}/details`));
  assert.ok(!isFullHeightRoute("/dashboard"));

  assert.ok(shouldShowBottomNav("/dashboard", "authenticated"));
  assert.ok(shouldShowBottomNav(`/clone/${ID}/edit`, "authenticated"));
  assert.ok(!shouldShowBottomNav("/dashboard", "anonymous"));
  assert.ok(!shouldShowBottomNav("/dashboard", "loading"));
  assert.ok(!shouldShowBottomNav(`/clone/${ID}`, "authenticated"));
  assert.ok(!shouldShowBottomNav(`/clone/${ID}/call`, "authenticated"));
  assert.ok(!shouldShowBottomNav("/c/ayaan", "authenticated"));
});

test("back button goes to the logical parent", () => {
  assert.equal(parentPath(`/clone/${ID}/edit`), `/clone/${ID}/details`);
  assert.equal(parentPath(`/clone/${ID}/knowledge`), `/clone/${ID}/details`);
  assert.equal(parentPath(`/clone/${ID}/knowledge/doc-1`), `/clone/${ID}/knowledge`);
  assert.equal(parentPath(`/clone/${ID}/analytics`), `/clone/${ID}/details`);
  assert.equal(parentPath(`/clone/${ID}/call`), `/clone/${ID}/details`);
  assert.equal(parentPath(`/clone/${ID}/agent`), `/clone/${ID}/details`);
  assert.equal(parentPath(`/clone/${ID}/agent/executions/exec-1`), `/clone/${ID}/agent`);
  assert.equal(parentPath(`/clone/${ID}/details`), "/clones");
  assert.equal(parentPath(`/clone/${ID}`), "/clones");
  assert.equal(parentPath("/create-clone"), "/dashboard");
  assert.equal(parentPath("/c/ayaan"), "/explore");
  assert.equal(parentPath("/explore"), null);
  assert.equal(parentPath("/explore/categories"), "/explore");
  assert.equal(parentPath("/explore/technology"), "/explore/categories");
  assert.equal(parentPath("/saved-clones"), null);
  assert.equal(parentPath("/organizations"), null);
  assert.equal(parentPath("/organizations/org-1"), "/organizations");
  assert.equal(parentPath("/organizations/org-1/members"), "/organizations/org-1");
  assert.equal(parentPath("/organizations/org-1/settings"), "/organizations/org-1");
  assert.equal(parentPath("/developer"), null);
  assert.equal(parentPath("/developer/keys"), "/developer");
  assert.equal(parentPath("/admin/dashboard"), null);
  assert.equal(parentPath("/admin/users"), "/admin/dashboard");
  assert.equal(parentPath("/admin/system/errors"), "/admin/system");
  for (const top of ["/", "/dashboard", "/clones", "/profile", "/analytics", "/explore", "/billing", "/login"]) {
    assert.equal(parentPath(top), null, top);
  }
});

test("drawer links depend on the user", () => {
  assert.deepEqual(
    drawerLinks(null).map((l) => l.label),
    ["Explore", "Login", "Create Account"],
  );
  assert.deepEqual(
    drawerLinks({ is_admin: false }).map((l) => l.key),
    ["explore", "saved", "organizations", "billing", "developer"],
  );
  assert.deepEqual(
    drawerLinks({ is_admin: true }).map((l) => l.key),
    ["explore", "saved", "organizations", "billing", "developer", "admin"],
  );
});

test("desktop links keep admin in 'More' for admins only", () => {
  assert.ok(!desktopLinks({ is_admin: false }).more.some((l) => l.key === "admin"));
  assert.ok(desktopLinks({ is_admin: true }).more.some((l) => l.key === "admin"));
  assert.ok(desktopLinks(null).primary.some((l) => l.href === "/login"));
  assert.equal(desktopLinks(null).more.length, 0);
});

test("link active matching", () => {
  assert.ok(isLinkActive("/", "/"));
  assert.ok(!isLinkActive("/", "/dashboard"));
  assert.ok(isLinkActive("/developer", "/developer/keys"));
  assert.ok(!isLinkActive("/clones", "/clone/abc"));
  assert.ok(isLinkActive("/admin/dashboard", "/admin/users"));
  assert.equal(activeHref(["/admin/system", "/admin/system/errors"], "/admin/system/errors"), "/admin/system/errors");
  assert.equal(activeHref(["/developer", "/developer/keys"], "/developer/keys"), "/developer/keys");
  assert.equal(activeHref(["/developer", "/developer/keys"], "/developer"), "/developer");
  assert.equal(activeHref(["/developer"], "/explore"), null);
});

test("last chat is stored per user and survives broken storage", () => {
  const storage = memoryStorage();
  assert.equal(readLastChat(storage, "u1"), null);
  assert.ok(writeLastChat(storage, "u1", ID));
  assert.equal(readLastChat(storage, "u1"), ID);
  assert.equal(readLastChat(storage, "u2"), null);
  assert.ok(!writeLastChat(storage, "u1", "../evil"));
  storage.data.set("ahc:last-chat:u1", "javascript:alert(1)");
  assert.equal(readLastChat(storage, "u1"), null);
  clearLastChat(storage, "u1");
  assert.equal(storage.data.size, 0);

  assert.equal(readLastChat(throwingStorage, "u1"), null);
  assert.equal(writeLastChat(throwingStorage, "u1", ID), false);
  assert.doesNotThrow(() => clearLastChat(throwingStorage, "u1"));
  assert.equal(readLastChat(null, "u1"), null);
  assert.equal(readLastChat(storage, null), null);
});

test("mobile titles", () => {
  assert.equal(mobileTitle("/dashboard"), "Home");
  assert.equal(mobileTitle(`/clone/${ID}/edit`), "Edit Clone");
  assert.equal(mobileTitle(`/clone/${ID}/agent`), "AI Agent");
  assert.equal(mobileTitle(`/clone/${ID}/agent/executions/exec-1`), "AI Agent");
  assert.equal(mobileTitle(`/clone/${ID}`), "Chat");
  assert.equal(mobileTitle("/developer/keys"), "Developer");
  assert.equal(mobileTitle("/"), null);
});
