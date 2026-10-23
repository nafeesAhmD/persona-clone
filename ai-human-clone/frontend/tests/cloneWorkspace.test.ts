import assert from "node:assert/strict";
import test from "node:test";

import { failureKind, fillHeight, isNearBottom, isRetryable, sendFailureMessage } from "../lib/chatState.ts";
import {
  ACCEPT_ATTRIBUTE,
  displayFileName,
  filterDocuments,
  isDocumentBusy,
  stripPaths,
  validateUploadFile,
} from "../lib/knowledge.ts";
import { MEMORY_TABS, nextTab } from "../lib/memory.ts";
import { canShareClone, copyLink, shareDataFor, shareOrCopy, type ShareNavigator } from "../lib/share.ts";

// --- Chat ---

test("failureKind uses ApiError.kind when present, else the HTTP status", () => {
  assert.equal(failureKind({ kind: "rate_limit", status: 500 }), "rate_limit");
  assert.equal(failureKind({ status: 429 }), "rate_limit");
  assert.equal(failureKind({ status: 503 }), "unavailable");
  assert.equal(failureKind({ status: 401 }), "auth");
  assert.equal(failureKind({ status: 404 }), "not_found");
  assert.equal(failureKind({ status: 500 }), "server");
  assert.equal(failureKind({ status: 422 }), "invalid");
  assert.equal(failureKind(new Error("network"), false), "offline");
  assert.equal(failureKind(new Error("network"), true), "unavailable");
  assert.equal(failureKind({ kind: "weird" , status: 504 }), "timeout");
});

test("retry is offered only where re-sending can help", () => {
  assert.ok(isRetryable("offline"));
  assert.ok(isRetryable("rate_limit"));
  assert.ok(isRetryable("server"));
  assert.equal(isRetryable("auth"), false);
  assert.equal(isRetryable("forbidden"), false);
  assert.equal(isRetryable("usage_limit"), false);
  assert.match(sendFailureMessage("offline"), /offline/i);
  assert.equal(sendFailureMessage("invalid", "Message too long"), "Message too long");
});

test("isNearBottom: follow new messages only near the end", () => {
  assert.ok(isNearBottom({ scrollTop: 880, scrollHeight: 1500, clientHeight: 600 }));
  assert.equal(isNearBottom({ scrollTop: 200, scrollHeight: 1500, clientHeight: 600 }), false);
});

test("fillHeight follows the visual viewport (iOS keyboard)", () => {
  assert.equal(fillHeight(800, null, 64), 736);
  assert.equal(fillHeight(800, 450, 64), 386); // keyboard open
  assert.equal(fillHeight(800, 900, 64), 736); // never taller than the layout viewport
  assert.equal(fillHeight(300, 200, 64), 240); // a sane minimum
});

// --- Knowledge ---

const MB = 1024 * 1024;

test("upload accept attribute lists extensions and MIME types for mobile pickers", () => {
  for (const part of [".pdf", ".docx", ".txt", "application/pdf", "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]) {
    assert.ok(ACCEPT_ATTRIBUTE.split(",").includes(part), part);
  }
});

test("validateUploadFile: type, empty and size checks (with a configurable max)", () => {
  assert.equal(validateUploadFile({ name: "cv.pdf", size: 1000, type: "application/pdf" }), null);
  assert.equal(validateUploadFile({ name: "notes.TXT", size: 10 }), null);
  assert.match(validateUploadFile({ name: "photo.jpg", size: 10, type: "image/jpeg" })!, /Unsupported/);
  // No extension (some Android pickers): the MIME type decides.
  assert.equal(validateUploadFile({ name: "document", size: 10, type: "application/pdf" }), null);
  assert.match(validateUploadFile({ name: "document", size: 10, type: "image/png" })!, /Unsupported/);
  assert.match(validateUploadFile({ name: "a.pdf", size: 0 })!, /empty/);
  assert.match(validateUploadFile({ name: "a.pdf", size: 11 * MB })!, /10 MB/);
  assert.equal(validateUploadFile({ name: "a.pdf", size: 11 * MB }, 20), null);
  assert.match(validateUploadFile({ name: "a.pdf", size: 6 * MB }, 5)!, /5 MB/);
});

test("file system paths are never shown", () => {
  assert.equal(displayFileName("C:\\fakepath\\cv.pdf"), "cv.pdf");
  assert.equal(displayFileName("/storage/emulated/0/Download/cv.pdf"), "cv.pdf");
  assert.equal(displayFileName(null), "");
  assert.equal(stripPaths("Could not read /app/storage/uploads/abc/cv.pdf: bad file"), "Could not read [file]: bad file");
  assert.equal(stripPaths("Failed at C:\\data\\uploads\\x.docx"), "Failed at [file]");
  assert.equal(stripPaths("No text found"), "No text found");
});

test("document search and busy detection", () => {
  const docs = [
    { title: "My CV", original_filename: "cv.pdf", file_type: "pdf" },
    { title: "Projects", original_filename: null, file_type: null },
  ];
  assert.equal(filterDocuments(docs, "").length, 2);
  assert.deepEqual(filterDocuments(docs, "proj").map((d) => d.title), ["Projects"]);
  assert.deepEqual(filterDocuments(docs, "CV.PDF").map((d) => d.title), ["My CV"]);
  assert.ok(isDocumentBusy({ status: "processing", indexing_status: "not_indexed" }));
  assert.ok(isDocumentBusy({ status: "ready", indexing_status: "indexing" }));
  assert.equal(isDocumentBusy({ status: "ready", indexing_status: "indexed" }), false);
});

// --- Memory ---

test("memory tabs: pending/approved/rejected/archived with keyboard navigation", () => {
  assert.deepEqual(MEMORY_TABS.map((t) => t.status), ["candidate", "approved", "rejected", "archived"]);
  assert.equal(MEMORY_TABS[0].label, "Pending");
  assert.equal(nextTab("candidate", "ArrowRight"), "approved");
  assert.equal(nextTab("archived", "ArrowRight"), "candidate");
  assert.equal(nextTab("candidate", "ArrowLeft"), "archived");
  assert.equal(nextTab("rejected", "Home"), "candidate");
  assert.equal(nextTab("approved", "End"), "archived");
  assert.equal(nextTab("approved", "Enter"), null);
});

// --- Sharing ---

test("only public or unlisted clones with public chat can be shared", () => {
  assert.equal(canShareClone({ visibility: "private", public_chat_enabled: true }), false);
  assert.equal(canShareClone({ visibility: "public", public_chat_enabled: false }), false);
  assert.ok(canShareClone({ visibility: "public", public_chat_enabled: true }));
  assert.ok(canShareClone({ visibility: "unlisted", public_chat_enabled: true }));
  assert.equal(canShareClone(null), false);
});

test("shareOrCopy: Web Share when available, copy-link fallback, dismissal is not an error", async () => {
  const data = shareDataFor("Sara", "https://example.test/c/sara");
  const copied: string[] = [];
  const clipboard = { writeText: async (text: string) => void copied.push(text) };

  const shared: unknown[] = [];
  const withShare: ShareNavigator = { share: async (d) => void shared.push(d), clipboard };
  assert.equal(await shareOrCopy(withShare, data), "shared");
  assert.equal(shared.length, 1);

  assert.equal(await shareOrCopy({ clipboard }, data), "copied");
  assert.deepEqual(copied, ["https://example.test/c/sara"]);

  const dismissed: ShareNavigator = {
    share: async () => {
      throw Object.assign(new Error("closed"), { name: "AbortError" });
    },
    clipboard,
  };
  assert.equal(await shareOrCopy(dismissed, data), "dismissed");

  const refused: ShareNavigator = {
    share: async () => {
      throw Object.assign(new Error("no"), { name: "NotAllowedError" });
    },
    clipboard,
  };
  assert.equal(await shareOrCopy(refused, data), "copied");

  const cannot: ShareNavigator = { share: async () => undefined, canShare: () => false, clipboard };
  assert.equal(await shareOrCopy(cannot, data), "copied");

  assert.equal(await shareOrCopy({}, data), "failed");
  assert.equal(await copyLink(undefined, data.url), "failed");
});
