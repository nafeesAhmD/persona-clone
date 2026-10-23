import assert from "node:assert/strict";
import test from "node:test";

import { safeRelativePath } from "../lib/pwa/paths.ts";
import { isSafeToReload, isTyping, nextUpdateStep } from "../lib/pwa/update.ts";

const idle = { focus: { tagName: "body" }, busy: false };

test("typing detection", () => {
  assert.equal(isTyping({ tagName: "body" }), false);
  assert.equal(isTyping({ tagName: null }), false);
  assert.equal(isTyping({ tagName: "textarea", value: "" }), false, "empty field");
  assert.equal(isTyping({ tagName: "textarea", value: "   " }), false, "whitespace only");
  assert.equal(isTyping({ tagName: "textarea", value: "hello" }), true);
  assert.equal(isTyping({ tagName: "input", inputType: "text", value: "a" }), true);
  assert.equal(isTyping({ tagName: "input", inputType: "email", value: "a@b" }), true);
  assert.equal(isTyping({ tagName: "input", inputType: "checkbox", value: "on" }), false);
  assert.equal(isTyping({ tagName: "input", inputType: "submit", value: "Send" }), false);
  assert.equal(isTyping({ tagName: "div", isContentEditable: true, value: "draft" }), true);
  assert.equal(isTyping({ tagName: "div", isContentEditable: true, value: "" }), false);
});

test("reload is safe only when idle", () => {
  assert.equal(isSafeToReload(idle), true);
  assert.equal(isSafeToReload({ ...idle, busy: true }), false, "form submitting / data-busy");
  assert.equal(isSafeToReload({ ...idle, hasDraft: true }), false, "unsent draft");
  assert.equal(isSafeToReload({ focus: { tagName: "textarea", value: "hi" }, busy: false }), false);
  assert.equal(isSafeToReload({ focus: { tagName: "button" }, busy: false, hasDraft: false }), true);
});

test("offline retry target is a same-site path", () => {
  assert.equal(safeRelativePath("/clone/abc?tab=chat"), "/clone/abc?tab=chat");
  assert.equal(safeRelativePath(null), "/");
  assert.equal(safeRelativePath("https://evil.example"), "/");
  assert.equal(safeRelativePath("//evil.example"), "/");
  assert.equal(safeRelativePath("/\\evil.example"), "/");
  assert.equal(safeRelativePath("/offline"), "/", "never loops back to the offline page");
});

test("update now: the new worker is activated only once the page is safe to reload", () => {
  // A draft is open: nothing is activated yet (other tabs and this page keep the old worker).
  assert.equal(nextUpdateStep({ safe: false, workerWaiting: true, skipWaitingSent: false }), "defer");
  // Draft cleared: activate the waiting worker, then wait for controllerchange.
  assert.equal(nextUpdateStep({ safe: true, workerWaiting: true, skipWaitingSent: false }), "activate");
  assert.equal(nextUpdateStep({ safe: true, workerWaiting: true, skipWaitingSent: true }), "wait");
  // The new worker controls the page (controllerchange, or another tab activated it): reload.
  assert.equal(nextUpdateStep({ safe: true, workerWaiting: false, skipWaitingSent: true }), "reload");
  assert.equal(nextUpdateStep({ safe: true, workerWaiting: false, skipWaitingSent: false }), "reload");
  // The user started typing again before the switch: never reload under them.
  assert.equal(nextUpdateStep({ safe: false, workerWaiting: false, skipWaitingSent: true }), "defer");
});
