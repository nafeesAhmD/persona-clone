/**
 * When is it safe to reload the page to activate a new service worker? (Phase 15)
 * Pure logic: the component describes the focused element and busy flags.
 */

export interface FocusSnapshot {
  /** Lower-case tag name of document.activeElement, e.g. "input", "textarea", "body". */
  tagName: string | null;
  /** input type attribute (for <input>). */
  inputType?: string | null;
  /** Current value (input/textarea) or text content (contenteditable). */
  value?: string | null;
  isContentEditable?: boolean;
}

export interface UpdateSafetyInputs {
  focus: FocusSnapshot;
  /** Some element has data-busy="true" (a form submitting, a recording, a live call). */
  busy: boolean;
  /** Any non-empty textarea/contenteditable on the page (an unsent draft). */
  hasDraft?: boolean;
}

const NON_TEXT_INPUTS = new Set(["button", "submit", "reset", "checkbox", "radio", "range", "color", "file", "image", "hidden"]);

/** Is the user typing something that a reload would lose? */
export function isTyping(focus: FocusSnapshot): boolean {
  const hasContent = (focus.value ?? "").trim().length > 0;
  if (focus.isContentEditable) return hasContent;
  if (focus.tagName === "textarea") return hasContent;
  if (focus.tagName === "input") {
    const type = (focus.inputType ?? "text").toLowerCase();
    return !NON_TEXT_INPUTS.has(type) && hasContent;
  }
  return false;
}

export function isSafeToReload(inputs: UpdateSafetyInputs): boolean {
  return !inputs.busy && !inputs.hasDraft && !isTyping(inputs.focus);
}

export type UpdateStep =
  | "defer" // not safe yet: show "Will update when you're done" and check again later
  | "activate" // safe: tell the waiting worker to SKIP_WAITING, then reload on controllerchange
  | "wait" // SKIP_WAITING already sent: wait for controllerchange
  | "reload"; // the new worker already controls the page (or none is waiting): reload now

export interface UpdateStepInputs {
  /** pageIsSafeToReload() */
  safe: boolean;
  /** A new worker is installed and waiting (not redundant, not yet the controller). */
  workerWaiting: boolean;
  /** SKIP_WAITING was already posted to that worker. */
  skipWaitingSent: boolean;
}

/**
 * Next step after the user tapped "Update now". The waiting worker is activated only once
 * the page is safe to reload: activating earlier would let the old page run on the new
 * worker (which deletes the old build's caches) and switch other tabs while a draft is open.
 */
export function nextUpdateStep({ safe, workerWaiting, skipWaitingSent }: UpdateStepInputs): UpdateStep {
  if (!safe) return "defer";
  if (!workerWaiting) return "reload";
  return skipWaitingSent ? "wait" : "activate";
}
