"use client";

import { cn } from "@/lib/utils";
import type { ConversationListItem } from "@/types/clone";

interface ConversationSidebarProps {
  conversations: ConversationListItem[] | null;
  selectedId: string | null;
  busy: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (conversation: ConversationListItem) => void;
  /** Mobile drawer: closes the sheet. */
  onClose?: () => void;
}

const GROUPS = ["Today", "Yesterday", "Previous 7 days", "Older"] as const;

function groupOf(iso: string, now = new Date()): (typeof GROUPS)[number] {
  const day = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((day(now) - day(new Date(iso))) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  return "Older";
}

export function ConversationSidebar({ conversations, selectedId, busy, onSelect, onNewChat, onDelete, onClose }: ConversationSidebarProps) {
  const grouped = GROUPS.map((group) => ({
    group,
    items: (conversations ?? []).filter((c) => groupOf(c.updated_at) === group),
  })).filter((g) => g.items.length > 0);

  return (
    <nav aria-label="Conversations" className="flex h-full flex-col">
      {onClose && (
        <div className="flex items-center justify-between border-b border-border px-3 py-2 md:hidden">
          <h2 className="text-sm font-semibold">Conversations</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close conversations"
            className="grid h-11 w-11 place-items-center rounded-lg text-lg text-muted hover:text-white"
          >
            ✕
          </button>
        </div>
      )}
      <div className="p-3">
        <button
          type="button"
          onClick={onNewChat}
          disabled={busy}
          className="min-h-11 w-full rounded-xl border border-accent/50 bg-accent/10 px-4 py-2.5 text-sm font-medium text-accent-soft hover:bg-accent/20 disabled:opacity-50"
        >
          + New Chat
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {conversations === null && <p className="px-2 text-xs text-muted">Loading…</p>}
        {conversations?.length === 0 && <p className="px-2 text-xs text-muted">No conversations yet.</p>}
        {grouped.map(({ group, items }) => (
          <div key={group} className="mt-3">
            <p className="px-2 text-[11px] font-medium uppercase tracking-wider text-muted">{group}</p>
            <ul className="mt-1 space-y-0.5">
              {items.map((conversation) => (
                <li key={conversation.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(conversation.id)}
                    disabled={busy}
                    aria-current={conversation.id === selectedId ? "page" : undefined}
                    className={cn(
                      "min-h-11 w-full truncate rounded-lg px-2 py-2 pr-12 text-left text-sm transition disabled:opacity-60 md:min-h-0 md:pr-8",
                      conversation.id === selectedId ? "bg-surface-raised text-white" : "text-gray-300 hover:bg-surface-raised/60",
                    )}
                  >
                    {conversation.title || "New conversation"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(conversation)}
                    disabled={busy}
                    aria-label={`Delete conversation "${conversation.title || "New conversation"}"`}
                    className="absolute right-0 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-lg text-muted hover:text-rose-300 focus:opacity-100 md:right-1 md:h-7 md:w-7 md:opacity-0 md:group-hover:opacity-100"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
