/**
 * Sharing a clone link (pure; tested in tests/share.test.ts). Only public or unlisted
 * clones with public chat on have a link worth sharing: a private clone's link is never offered.
 */

export type ShareVisibility = "private" | "public" | "unlisted";

export function canShareClone(settings: { visibility: ShareVisibility; public_chat_enabled: boolean } | null | undefined): boolean {
  return Boolean(settings && settings.visibility !== "private" && settings.public_chat_enabled);
}

export interface ShareData {
  title: string;
  text: string;
  url: string;
}

/** The parts of `navigator` used here (so it can be faked in tests). */
export interface ShareNavigator {
  share?: (data: ShareData) => Promise<void>;
  canShare?: (data: ShareData) => boolean;
  clipboard?: { writeText: (text: string) => Promise<void> };
}

export type ShareOutcome = "shared" | "copied" | "dismissed" | "failed";

export function shareDataFor(cloneName: string, url: string): ShareData {
  return {
    title: `${cloneName} · AI Clone`,
    text: `Chat with ${cloneName}'s AI Clone (an AI representation, not the real person).`,
    url,
  };
}

/** Whether the native share sheet (Web Share API) can be used for this data. */
export function hasNativeShare(nav: ShareNavigator | undefined, data: ShareData): boolean {
  if (!nav || typeof nav.share !== "function") return false;
  try {
    return typeof nav.canShare === "function" ? nav.canShare(data) : true;
  } catch {
    return false;
  }
}

/**
 * Opens the native share sheet when available, otherwise copies the link.
 * Closing the share sheet ("AbortError") is not an error.
 */
export async function shareOrCopy(nav: ShareNavigator | undefined, data: ShareData): Promise<ShareOutcome> {
  if (nav && hasNativeShare(nav, data)) {
    try {
      await nav.share!(data);
      return "shared";
    } catch (error) {
      if ((error as { name?: string } | null)?.name === "AbortError") return "dismissed";
      // e.g. NotAllowedError: fall back to copying.
    }
  }
  return copyLink(nav, data.url);
}

export async function copyLink(nav: ShareNavigator | undefined, url: string): Promise<ShareOutcome> {
  if (!nav?.clipboard?.writeText) return "failed";
  try {
    await nav.clipboard.writeText(url);
    return "copied";
  } catch {
    return "failed";
  }
}
