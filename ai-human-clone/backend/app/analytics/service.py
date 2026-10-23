from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from app.analytics.metrics import parse_range
from app.analytics.schemas import (
    AIInsights,
    AnalyticsOverview,
    AvatarAnalytics,
    DailyActivity,
    KnowledgeAnalytics,
    KnowledgeGap,
    MemoryAnalytics,
    PerformanceMetrics,
    PopularQuestion,
    ProvidersAnalytics,
    ProviderStats,
    PublicAnalytics,
    VoiceAnalytics,
)
from app.models import (
    AnalyticsEvent,
    AvatarVideoJob,
    CloneMemory,
    CloneProfile,
    Conversation,
    Document,
    Message,
    PublicChatSession,
    UsageEvent,
    ErrorEvent,
)


class AnalyticsService:
    def __init__(self, db: Session, clone_id: str):
        self.db = db
        self.clone_id = clone_id

    def overview(self, range_str: str | None = None, start_date: date | None = None, end_date: date | None = None) -> AnalyticsOverview:
        start, end = parse_range(range_str, start_date, end_date)
        q = self.db.query

        total_conversations = q(func.count(Conversation.id)).filter(Conversation.clone_id == self.clone_id).filter(Conversation.created_at >= start, Conversation.created_at < end).scalar() or 0
        total_messages = q(func.count(Message.id)).join(Conversation).filter(Conversation.clone_id == self.clone_id).filter(Message.created_at >= start, Message.created_at < end).scalar() or 0
        total_unique_sessions = q(func.count(distinct(AnalyticsEvent.session_id))).filter(AnalyticsEvent.clone_id == self.clone_id, AnalyticsEvent.session_id.isnot(None)).filter(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end).scalar() or 0
        total_public_sessions = q(func.count(PublicChatSession.id)).filter(PublicChatSession.clone_id == self.clone_id).filter(PublicChatSession.created_at >= start, PublicChatSession.created_at < end).scalar() or 0
        total_documents = q(func.count(Document.id)).filter(Document.clone_id == self.clone_id).scalar() or 0
        total_memories = q(func.count(CloneMemory.id)).filter(CloneMemory.clone_id == self.clone_id).scalar() or 0
        total_voice = q(func.count(AnalyticsEvent.id)).filter(AnalyticsEvent.clone_id == self.clone_id).filter(AnalyticsEvent.event_type.in_(["voice_transcription", "voice_response", "tts_request"])).filter(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end).scalar() or 0
        total_avatar = q(func.count(AnalyticsEvent.id)).filter(AnalyticsEvent.clone_id == self.clone_id).filter(AnalyticsEvent.event_type.in_(["avatar_generation", "avatar_video_completed"])).filter(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end).scalar() or 0
        successful = q(func.count(AnalyticsEvent.id)).filter(AnalyticsEvent.clone_id == self.clone_id, AnalyticsEvent.success == True).filter(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end).scalar() or 0
        failed = q(func.count(AnalyticsEvent.id)).filter(AnalyticsEvent.clone_id == self.clone_id, AnalyticsEvent.success == False).filter(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end).scalar() or 0
        usage = q(func.count(UsageEvent.id)).filter(UsageEvent.clone_id == self.clone_id).filter(UsageEvent.created_at >= start, UsageEvent.created_at < end).scalar() or 0
        avg_resp = q(func.avg(AnalyticsEvent.duration_ms)).filter(AnalyticsEvent.clone_id == self.clone_id, AnalyticsEvent.duration_ms.isnot(None)).filter(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end).scalar()
        return AnalyticsOverview(
            total_conversations=total_conversations,
            total_messages=total_messages,
            total_unique_sessions=total_unique_sessions,
            total_public_sessions=total_public_sessions,
            total_documents=total_documents,
            total_memories=total_memories,
            total_voice_requests=total_voice,
            total_avatar_requests=total_avatar,
            successful_requests=successful,
            failed_requests=failed,
            average_response_time=float(avg_resp) if avg_resp else None,
            total_usage_events=usage,
        )
