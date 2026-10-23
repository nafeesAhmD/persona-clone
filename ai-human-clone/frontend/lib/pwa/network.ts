/** Network status constants shared by the PWA layer and screens (pure). */

export const OFFLINE_MESSAGE = "You are offline. Some features may be unavailable.";

/**
 * Window event fired once when the browser comes back online (after the offline
 * banner was shown). Screens that loaded data with useEffect can listen and reload
 * with GET requests. Never re-send POST/PATCH/DELETE in response to it.
 */
export const BACK_ONLINE_EVENT = "ahc:back-online";
