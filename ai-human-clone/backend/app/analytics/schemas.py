from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Range = Literal["today", "yesterday", "7d", "30d", "90d", "custom"]


class AnalyticsOverview(BaseModel):
    total_conversations: int = 0
    total_messages: int = 0
    total_unique_sessions: int = 0
    total_public_sessions: int = 0
    total_documents: int = 0
    total_memories: int = 0
    total_voice_requests: int = 0
    total_avatar_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float | None = None
    total_usage_events: int = 0


class DailyActivity(BaseModel):
    date: date
    conversations: int = 0
    messages: int = 0
    sessions: int = 0
    views: int = 0
    voice_requests: int = 0
    avatar_requests: int = 0
    errors: int = 0


class PopularQuestion(BaseModel):
    question: str
    count: int


class DocumentUsage(BaseModel):
    document_id: str
    title: str
    usage_count: int


class KnowledgeAnalytics(BaseModel):
    most_used_documents: list[DocumentUsage] = []
    documents_never_used: list[DocumentUsage] = []
    total_document_searches: int = 0
    average_retrieval_score: float | None = None
    knowledge_grounded_responses: int = 0
    no_knowledge_responses: int = 0


class MemoryAnalytics(BaseModel):
    total_memories: int = 0
    approved_memories: int = 0
    candidate_memories: int = 0
    rejected_memories: int = 0
    archived_memories: int = 0
    memories_used: int = 0
    most_used_memory_types: dict[str, int] = {}


class PublicAnalytics(BaseModel):
    public_views: int = 0
    unique_sessions: int = 0
    conversations: int = 0
    messages: int = 0
    average_session_messages: float | None = None
    voice_requests: int = 0
    avatar_requests: int = 0
    rate_limit_hits: int = 0
    errors: int = 0
    daily: list[DailyActivity] = []


class VoiceAnalytics(BaseModel):
    transcription_requests: int = 0
    successful_transcriptions: int = 0
    failed_transcriptions: int = 0
    tts_requests: int = 0
    successful_tts: int = 0
    failed_tts: int = 0
    total_audio_duration: float | None = None
    average_processing_time: float | None = None


class AvatarAnalytics(BaseModel):
    avatar_requests: int = 0
    completed_videos: int = 0
    failed_videos: int = 0
    cancelled_videos: int = 0
    average_generation_time: float | None = None
    total_video_duration: float | None = None


class PerformanceMetrics(BaseModel):
    average_response_time: float | None = None
    p50_response_time: float | None = None
    p95_response_time: float | None = None
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_count: int = 0
    claude_errors: int = 0
    qdrant_errors: int = 0
    database_errors: int = 0
    voice_errors: int = 0
    avatar_errors: int = 0


class ProviderStats(BaseModel):
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    average_duration: float | None = None
    input_usage: float | None = None
    output_usage: float | None = None
    estimated_cost: float | None = None


class ProvidersAnalytics(BaseModel):
    claude: ProviderStats = ProviderStats()
    embedding: ProviderStats = ProviderStats()
    stt: ProviderStats = ProviderStats()
    tts: ProviderStats = ProviderStats()
    lipsync: ProviderStats = ProviderStats()


class KnowledgeGap(BaseModel):
    topic: str
    count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class AIInsights(BaseModel):
    summary: str
    top_topics: list[str] = []
    growth_observations: list[str] = []
    knowledge_gaps: list[str] = []
    recommendations: list[str] = []
