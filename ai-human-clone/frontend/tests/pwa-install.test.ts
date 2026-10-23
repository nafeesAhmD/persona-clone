import assert from "node:assert/strict";
import test from "node:test";

import {
  INSTALL_SNOOZE_MS,
  installOffer,
  isIosSafari,
  isSnoozed,
  isStandalone,
  parseDismissedAt,
} from "../lib/pwa/install.ts";

const NOW = 1_800_000_000_000;
const base = { standalone: false, hasDeferredPrompt: true, iosSafari: false, dismissedAt: null, now: NOW, pageViews: 2 };

test("standalone detection uses any of the signals", () => {
  assert.equal(isStandalone({ displayModeStandalone: false }), false);
  assert.equal(isStandalone({ displayModeStandalone: true }), true);
  assert.equal(isStandalone({ displayModeStandalone: false, navigatorStandalone: true }), true);
  assert.equal(isStandalone({ displayModeStandalone: false, appInstalled: true }), true);
});

test("dismissal timestamp parsing is defensive", () => {
  assert.equal(parseDismissedAt(null), null);
  assert.equal(parseDismissedAt(""), null);
  assert.equal(parseDismissedAt("garbage"), null);
  assert.equal(parseDismissedAt("-5"), null);
  assert.equal(parseDismissedAt(String(NOW)), NOW);
});

test("snooze lasts at least 30 days", () => {
  assert.ok(INSTALL_SNOOZE_MS >= 30 * 24 * 3600 * 1000);
  assert.equal(isSnoozed(null, NOW), false);
  assert.equal(isSnoozed(NOW - 1000, NOW), true);
  assert.equal(isSnoozed(NOW - 29 * 24 * 3600 * 1000, NOW), true);
  assert.equal(isSnoozed(NOW - 31 * 24 * 3600 * 1000, NOW), false);
  assert.equal(isSnoozed(NOW + 60_000, NOW), true, "future timestamp (clock skew) stays quiet");
});

test("install offer decisions", () => {
  assert.equal(installOffer(base), "prompt");
  assert.equal(installOffer({ ...base, standalone: true }), "none", "already installed");
  assert.equal(installOffer({ ...base, pageViews: 1 }), "none", "not on the first page view");
  assert.equal(installOffer({ ...base, dismissedAt: NOW - 1000 }), "none", "snoozed");
  assert.equal(installOffer({ ...base, hasDeferredPrompt: false }), "none", "nothing to offer");
  assert.equal(installOffer({ ...base, hasDeferredPrompt: false, iosSafari: true }), "ios-hint");
  assert.equal(installOffer({ ...base, hasDeferredPrompt: false, iosSafari: true, standalone: true }), "none");
});

test("iOS Safari detection", () => {
  const iphoneSafari =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
  const iphoneChrome =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0 Mobile/15E148 Safari/604.1";
  const ipadDesktopMode =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15";
  const android =
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36";
  assert.equal(isIosSafari(iphoneSafari), true);
  assert.equal(isIosSafari(iphoneChrome), false);
  assert.equal(isIosSafari(ipadDesktopMode, 5), true, "iPadOS reports as Mac but has touch");
  assert.equal(isIosSafari(ipadDesktopMode, 0), false, "real Mac Safari");
  assert.equal(isIosSafari(android), false);
});
