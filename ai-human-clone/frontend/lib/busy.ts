/**
 * "Something is in progress" tracking, so a PWA update never reloads the page in the
 * middle of an action. Counts changes being sent to the API (POST/PATCH/PUT/DELETE,
 * uploads, streamed answers), recordings and live calls.
 *
 *   const done = beginBusy();  ...  done();   // done() is safe to call twice
 */

let active = 0;

export function beginBusy(): () => void {
  active += 1;
  let finished = false;
  return () => {
    if (finished) return;
    finished = true;
    active = Math.max(0, active - 1);
  };
}

export function isBusy(): boolean {
  return active > 0;
}

/** Tests only. */
export function resetBusy(): void {
  active = 0;
}
