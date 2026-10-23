/**
 * Install-prompt decisions (Phase 15). Pure logic so it can be unit-tested.
 */

export const INSTALL_DISMISS_KEY = "ahc:install-dismissed-at";
/** After "Not now", the install card stays hidden this long. */
export const INSTALL_SNOOZE_MS = 30 * 24 * 60 * 60 * 1000;

export interface StandaloneInputs {
  /** matchMedia("(display-mode: standalone)").matches (also fullscreen / minimal-ui). */
  displayModeStandalone: boolean;
  /** iOS Safari's non-standard navigator.standalone. */
  navigatorStandalone?: boolean;
  /** An "appinstalled" event was seen in this session. */
  appInstalled?: boolean;
}

export function isStandalone(inputs: StandaloneInputs): boolean {
  return inputs.displayModeStandalone || inputs.navigatorStandalone === true || inputs.appInstalled === true;
}

/** iPhone / iPad Safari (where there is no beforeinstallprompt; the user adds via Share). */
export function isIosSafari(userAgent: string, maxTouchPoints = 0): boolean {
  const iPhoneOrIPad = /iPad|iPhone|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
  if (!iPhoneOrIPad) return false;
  // Other iOS browsers (Chrome, Firefox, Edge, in-app webviews) can't add to the home screen the same way.
  return /Safari\//.test(userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS|GSA\/|FBAN|FBAV|Instagram|Line\//.test(userAgent);
}

/** Parse the stored dismissal timestamp; anything invalid counts as "never dismissed". */
export function parseDismissedAt(raw: string | null | undefined): number | null {
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function isSnoozed(dismissedAt: number | null, now: number, snoozeMs = INSTALL_SNOOZE_MS): boolean {
  if (dismissedAt === null) return false;
  if (dismissedAt > now) return true; // clock went backwards: stay quiet rather than nag
  return now - dismissedAt < snoozeMs;
}

export type InstallOffer = "none" | "prompt" | "ios-hint";

export interface InstallInputs {
  standalone: boolean;
  /** A beforeinstallprompt event was captured. */
  hasDeferredPrompt: boolean;
  iosSafari: boolean;
  dismissedAt: number | null;
  now: number;
  /** Page views in this session; the card is not shown on the very first one. */
  pageViews: number;
}

/** Which install UI (if any) to show. */
export function installOffer(inputs: InstallInputs): InstallOffer {
  if (inputs.standalone) return "none";
  if (isSnoozed(inputs.dismissedAt, inputs.now)) return "none";
  if (inputs.pageViews < 2) return "none";
  if (inputs.hasDeferredPrompt) return "prompt";
  if (inputs.iosSafari) return "ios-hint";
  return "none";
}
