"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { StatusMessage } from "@/components/StatusMessage";
import { ApiError, type ApiErrorKind } from "@/lib/api";
import { defaultMessage } from "@/lib/pwa/errors";

interface ApiErrorStateProps {
  error: unknown;
  /** What was being loaded, e.g. "clone". */
  thing?: string;
  onRetry?: () => void;
}

const buttonClass =
  "inline-flex min-h-11 items-center justify-center rounded-lg px-4 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft";
const primaryClass = `${buttonClass} bg-accent text-ink hover:bg-accent/90`;
const secondaryClass = `${buttonClass} border border-border text-accent-soft hover:bg-surface-raised`;

function kindOf(error: unknown): ApiErrorKind {
  if (error instanceof ApiError) return error.kind;
  return "server";
}

/** Only messages written for users (ApiError) are shown; anything else gets a generic text. */
function safeMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

/**
 * One consistent screen for API failures: offline, timeout, unreachable server,
 * maintenance, expired session, forbidden, not found, rate/usage limits and errors.
 */
export function ApiErrorState({ error, thing = "page", onRetry }: ApiErrorStateProps) {
  const router = useRouter();
  const pathname = usePathname();
  const kind = kindOf(error);

  const retry = onRetry && (
    <button type="button" onClick={onRetry} className={primaryClass}>
      Try again
    </button>
  );
  const back = (
    <button
      type="button"
      onClick={() => (window.history.length > 1 ? router.back() : router.push("/dashboard"))}
      className={secondaryClass}
    >
      Go back
    </button>
  );
  const actions = (...items: React.ReactNode[]) => <div className="flex flex-wrap justify-center gap-3">{items}</div>;

  switch (kind) {
    case "auth":
      return (
        <StatusMessage title="Please log in again" body="Your session has ended.">
          <Link href={`/login?next=${encodeURIComponent(pathname || "/dashboard")}`} className={primaryClass}>
            Log in again
          </Link>
        </StatusMessage>
      );
    case "forbidden":
      return (
        <StatusMessage title="Not available" body={safeMessage(error, `You can't access this ${thing}.`)}>
          <Link href="/dashboard" className={secondaryClass}>
            Back to dashboard
          </Link>
        </StatusMessage>
      );
    case "not_found":
      return (
        <StatusMessage title={`This ${thing} doesn't exist`} body="It may have been deleted, or the link is wrong.">
          <Link href="/dashboard" className={secondaryClass}>
            Back to dashboard
          </Link>
        </StatusMessage>
      );
    case "offline":
      return (
        <StatusMessage title="You are offline" body={defaultMessage("offline")}>
          {actions(<span key="r">{retry}</span>, <span key="b">{back}</span>)}
        </StatusMessage>
      );
    case "timeout":
      return (
        <StatusMessage title="This is taking too long" body={defaultMessage("timeout")}>
          {actions(<span key="r">{retry}</span>, <span key="b">{back}</span>)}
        </StatusMessage>
      );
    case "network":
      return (
        <StatusMessage title="Can't reach the server" body="Check your connection, or try again in a moment.">
          {actions(<span key="r">{retry}</span>, <span key="b">{back}</span>)}
        </StatusMessage>
      );
    case "maintenance":
      return (
        <StatusMessage title="Down for maintenance" body={safeMessage(error, defaultMessage("maintenance"))}>
          {actions(<span key="r">{retry}</span>)}
        </StatusMessage>
      );
    case "unavailable":
      return (
        <StatusMessage title="Temporarily unavailable" body={safeMessage(error, defaultMessage("unavailable"))}>
          {actions(<span key="r">{retry}</span>, <span key="b">{back}</span>)}
        </StatusMessage>
      );
    case "rate_limit":
      return (
        <StatusMessage title="Slow down a little" body={safeMessage(error, defaultMessage("rate_limit"))}>
          {actions(<span key="r">{retry}</span>)}
        </StatusMessage>
      );
    case "usage_limit":
      return (
        <StatusMessage title="Usage limit reached" body={safeMessage(error, defaultMessage("usage_limit"))}>
          {actions(<span key="b">{back}</span>)}
        </StatusMessage>
      );
    default:
      return (
        <StatusMessage title={`Could not load this ${thing}`} body={safeMessage(error, "Something went wrong.")}>
          {actions(<span key="r">{retry}</span>, <span key="b">{back}</span>)}
        </StatusMessage>
      );
  }
}
