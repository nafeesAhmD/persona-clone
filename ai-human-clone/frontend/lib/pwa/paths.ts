/** Same-site relative path check (no "//host" or "/\\host" open redirects). Pure. */
export function safeRelativePath(value: string | null | undefined, fallback = "/"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return fallback;
  if (value === "/offline" || value.startsWith("/offline?")) return fallback;
  return value;
}
