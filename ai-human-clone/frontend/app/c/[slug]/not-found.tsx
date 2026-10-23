import Link from "next/link";

import { StatusMessage } from "@/components/StatusMessage";

export default function PublicCloneNotFound() {
  return (
    <StatusMessage title="This AI Clone isn't available" body="The link may be wrong, or the owner made it private.">
      <Link href="/explore" className="inline-flex min-h-11 items-center text-accent-soft hover:underline">Explore public AI Clones</Link>
    </StatusMessage>
  );
}
