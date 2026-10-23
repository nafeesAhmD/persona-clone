// Frontend unit tests run with Node's built-in runner (no extra dependencies):
//   npm test   ->   node --test "tests/**/*.test.ts"
// Test pure logic modules (no React/DOM); import them with a relative path ending in ".ts".
import assert from "node:assert/strict";
import test from "node:test";

test("test runner works", () => {
  assert.equal(1 + 1, 2);
});
