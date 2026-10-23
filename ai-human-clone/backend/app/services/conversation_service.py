"""Conversations and messages. A conversation belongs to exactly one user and
one clone; every lookup checks both, so no one can read or continue someone
else's conversation (404, without revealing that it exists)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.base import ChatTurn
from app.models import CloneProfile, Conversation, Message, User
from app.services.errors import NotFoundError

NOT_FOUND = "Conversation not found"
TITLE_LENGTH = 80


def _title_from(message: str) -> str:
    """A deterministic title from the first question (no extra LLM call)."""
    title = " ".join(message.split())
    return title if len(title) <= TITLE_LENGTH else title[: TITLE_LENGTH - 1].rsplit(" ", 1)[0] + "…"


def get_owned(db: Session, conversation_id: uuid.UUID, user: User) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFoundError(NOT_FOUND)
    return conversation


def get_or_create(
    db: Session, clone: CloneProfile, user: User, conversation_id: uuid.UUID | None, *, source: str = "app"
) -> Conversation:
    if conversation_id is None:
        conversation = Conversation(clone_id=clone.id, user_id=user.id, source=source)
        db.add(conversation)
        db.flush()
        return conversation
    conversation = get_owned(db, conversation_id, user)
    if conversation.clone_id != clone.id:  # someone else's clone id in the URL
        raise NotFoundError(NOT_FOUND)
    return conversation


def list_for(db: Session, clone: CloneProfile, user: User, *, source: str | None = None) -> list[Conversation]:
    query = select(Conversation).where(Conversation.user_id == user.id, Conversation.clone_id == clone.id)
    if source is not None:
        query = query.where(Conversation.source == source)
    return list(db.scalars(query.order_by(Conversation.updated_at.desc())))


def messages_of(db: Session, conversation: Conversation) -> list[Message]:
    return list(
        db.scalars(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)
        )
    )


def add_message(db: Session, conversation: Conversation, role: str, content: str, **metadata) -> Message:
    now = datetime.now(UTC)  # set here: Postgres now() is fixed for the whole transaction
    # Keep created_at strictly increasing inside a conversation. The primary key is a
    # random UUID, so when two inserts land on the same clock tick (a burst of calls, or a
    # coarse OS clock) the "created_at, id" order would otherwise be arbitrary.
    last = db.scalar(select(func.max(Message.created_at)).where(Message.conversation_id == conversation.id))
    if last is not None:
        if last.tzinfo is None:  # SQLite returns naive datetimes
            last = last.replace(tzinfo=UTC)
        if now <= last:
            now = last + timedelta(microseconds=1)
    message = Message(conversation_id=conversation.id, role=role, content=content, created_at=now, **metadata)
    db.add(message)
    conversation.updated_at = now
    if role == "user" and not conversation.title:
        conversation.title = _title_from(content)
    db.commit()
    db.refresh(message)
    return message


def recent_history(
    db: Session, conversation: Conversation, limit: int, *, exclude: uuid.UUID | None = None
) -> list[ChatTurn]:
    """The last `limit` messages as alternating user/assistant turns, oldest first.

    A user message whose answer failed has no reply; consecutive same-role
    messages are merged so the LLM always sees a valid alternation.
    """
    query = select(Message).where(Message.conversation_id == conversation.id)
    if exclude is not None:
        query = query.where(Message.id != exclude)
    rows = list(db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)))

    turns: list[ChatTurn] = []
    for message in reversed(rows):
        if turns and turns[-1]["role"] == message.role:
            turns[-1] = {"role": message.role, "content": f"{turns[-1]['content']}\n\n{message.content}"}
        else:
            turns.append({"role": message.role, "content": message.content})  # type: ignore[typeddict-item]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)  # must start with the user
    if turns and turns[-1]["role"] == "user":
        turns.pop()  # the new question follows; an unanswered one would break alternation
    return turns


def delete(db: Session, conversation: Conversation) -> None:
    db.delete(conversation)
    db.commit()
