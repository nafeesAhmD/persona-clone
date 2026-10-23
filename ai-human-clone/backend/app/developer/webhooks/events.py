"""The events a webhook can subscribe to. Payload data holds ids, types, counts and
statuses only: never message text, prompts, documents, secrets or file paths."""

EVENTS = (
    "clone.created",
    "clone.updated",
    "conversation.created",
    "message.completed",
    "voice.completed",
    "avatar.completed",
    "usage.limit_reached",
    "subscription.updated",
)

EVENT_DESCRIPTIONS = {
    "clone.created": "A clone was created.",
    "clone.updated": "A clone's settings were changed.",
    "conversation.created": "Someone started a new conversation with a clone.",
    "message.completed": "A clone finished an answer (chat, streaming or voice).",
    "voice.completed": "A voice chat turn finished (transcription, answer and speech).",
    "avatar.completed": "A talking-avatar video finished rendering.",
    "usage.limit_reached": "A monthly developer API limit was reached.",
    "subscription.updated": "A subscription's status changed.",
}

# Sent only by "Send test event"; it can't be subscribed to.
TEST_EVENT = "webhook.test"


def unknown_events(events: list[str]) -> list[str]:
    return [event for event in events if event not in EVENTS]
