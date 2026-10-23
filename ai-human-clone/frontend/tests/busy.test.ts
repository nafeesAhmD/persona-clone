import assert from "node:assert/strict";
import test from "node:test";

import { beginBusy, isBusy, resetBusy } from "../lib/busy.ts";

test("busy while any action is running, idle when all are done", () => {
  resetBusy();
  assert.equal(isBusy(), false);
  const upload = beginBusy();
  const recording = beginBusy();
  assert.equal(isBusy(), true);
  upload();
  assert.equal(isBusy(), true);
  recording();
  assert.equal(isBusy(), false);
});

test("finishing twice doesn't hide another running action", () => {
  resetBusy();
  const first = beginBusy();
  const second = beginBusy();
  first();
  first();
  assert.equal(isBusy(), true);
  second();
  assert.equal(isBusy(), false);
});
