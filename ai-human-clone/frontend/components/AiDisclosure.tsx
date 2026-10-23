import { cn } from "@/lib/utils";

interface AiDisclosureProps {
  className?: string;
}

/** Always-visible notice that the user is talking to an AI, not a real person. */
export function AiDisclosure({ className }: AiDisclosureProps) {
  return (
    <p
      role="note"
      className={cn(
        "flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-accent-soft",
        className,
      )}
    >
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-accent-soft" />
      AI-generated responses based on information provided by the clone owner.
    </p>
  );
}
