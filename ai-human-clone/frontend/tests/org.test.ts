import assert from "node:assert/strict";
import test from "node:test";

import {
  assignableRoles,
  canDeactivate,
  canInvite,
  canLeave,
  canManageMember,
  canTransferOwnership,
  canUnassignClone,
  displayName,
  initials,
  inviteLink,
  myRole,
  orgErrorMessage,
  pendingInvitations,
  sortMembers,
} from "../lib/orgRoles.ts";
import type { OrgInvitation, OrgMember, OrgRole } from "../types/organizations.ts";

const org = { owner_id: "u-owner" };

function member(user_id: string, role: OrgRole, extra: Partial<OrgMember> = {}): OrgMember {
  return {
    id: `m-${user_id}`,
    organization_id: "o1",
    user_id,
    role,
    status: "active",
    joined_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    email: `${user_id}@example.com`,
    full_name: null,
    ...extra,
  };
}

const members = [
  member("u-owner", "owner"),
  member("u-admin", "admin"),
  member("u-editor", "editor"),
  member("u-gone", "viewer", { status: "removed" }),
];

test("my role comes from ownership, then from an active membership", () => {
  assert.equal(myRole(org, members, "u-owner"), "owner");
  assert.equal(myRole(org, members, "u-admin"), "admin");
  assert.equal(myRole(org, members, "u-gone"), null);
  assert.equal(myRole(org, members, undefined), null);
  // Owner even without a member row.
  assert.equal(myRole(org, [], "u-owner"), "owner");
});

test("who can give which roles", () => {
  assert.deepEqual(assignableRoles("owner"), ["admin", "editor", "viewer"]);
  assert.deepEqual(assignableRoles("admin"), ["editor", "viewer"]);
  assert.deepEqual(assignableRoles("editor"), []);
  assert.equal(canInvite("admin"), true);
  assert.equal(canInvite("viewer"), false);
});

test("member management follows the backend rules", () => {
  const [owner, admin, editor] = members;
  assert.equal(canManageMember("owner", admin, org), true);
  assert.equal(canManageMember("owner", owner, org), false);
  assert.equal(canManageMember("admin", editor, org), true);
  assert.equal(canManageMember("admin", admin, org), false); // only the owner manages admins
  assert.equal(canManageMember("editor", editor, org), false);
  assert.equal(canManageMember(null, editor, org), false);
});

test("leaving, transferring and deactivating", () => {
  assert.equal(canLeave("owner"), false);
  assert.equal(canLeave("viewer"), true);
  assert.equal(canLeave(null), false);
  assert.equal(canTransferOwnership("owner"), true);
  assert.equal(canTransferOwnership("admin"), false);
  assert.equal(canDeactivate("admin"), false);
});

test("unassigning clones: managers or the clone's owner", () => {
  assert.equal(canUnassignClone("admin", { owner_id: "x" }, "u-admin"), true);
  assert.equal(canUnassignClone("editor", { owner_id: "u-editor" }, "u-editor"), true);
  assert.equal(canUnassignClone("editor", { owner_id: "x" }, "u-editor"), false);
});

test("member order and names", () => {
  assert.deepEqual(sortMembers(members).map((m) => m.user_id), ["u-owner", "u-admin", "u-editor"]);
  assert.equal(displayName(member("a", "viewer", { full_name: "Sara Khan" })), "Sara Khan");
  assert.equal(displayName(member("a", "viewer", { email: null })), "Member a");
  assert.equal(initials(member("a", "viewer", { full_name: "Sara Khan" })), "SK");
  assert.equal(initials(member("a", "viewer", { email: "omar@example.com" })), "O");
});

test("pending invitations exclude answered and expired ones", () => {
  const now = new Date("2026-10-05T00:00:00Z");
  const invitation = (id: string, status: string, expires_at: string): OrgInvitation => ({
    id,
    organization_id: "o1",
    email: `${id}@example.com`,
    invited_by: "u-owner",
    role: "viewer",
    status,
    expires_at,
    accepted_at: null,
    created_at: "2026-10-01T00:00:00Z",
  });
  const list = [
    invitation("live", "pending", "2026-10-10T00:00:00Z"),
    invitation("old", "pending", "2026-10-01T00:00:00Z"),
    invitation("done", "accepted", "2026-10-10T00:00:00Z"),
  ];
  assert.deepEqual(pendingInvitations(list, now).map((i) => i.id), ["live"]);
});

test("invite links and error messages", () => {
  assert.equal(inviteLink("https://app.example.com/", "a b"), "https://app.example.com/invite/a%20b");
  assert.equal(orgErrorMessage(new Error("duplicate_pending")), "There's already a pending invitation for that email address.");
  assert.equal(orgErrorMessage(new Error("Custom problem")), "Custom problem");
  assert.equal(orgErrorMessage(null, "Fallback"), "Fallback");
});
