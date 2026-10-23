"""Organization feature access helpers - integrates with billing plans."""
from __future__ import annotations

from app.billing.plans import DEFAULT_PLANS


def _plan_to_features(plan: dict) -> dict:
    limits = plan.get("limits", {})
    features = plan.get("features", {})
    return {
        "max_members": limits.get("clones", 5) * 2,
        "max_clones": limits.get("clones", 5),
        "monthly_messages": limits.get("chat_messages", 1000),
        "knowledge_storage_mb": limits.get("knowledge_mb", 100),
        "voice_minutes_monthly": limits.get("voice_requests", 100) // 2,
        "avatar_video_seconds_monthly": limits.get("avatar_requests", 10) * 30,
        "advanced_analytics": features.get("advanced_analytics", False),
        "voice_clone": features.get("voice_clone", False),
        "avatar_video": features.get("avatar_video", False),
        "public_clone": features.get("public_clone", False),
        "api_access": features.get("advanced_analytics", False),
        "custom_branding": False,
        "sso": False,
    }


_ORG_FEATURES_CACHE = {p["slug"]: _plan_to_features(p) for p in DEFAULT_PLANS}


def get_org_plan_name(db, organization_id) -> str:
    """Get the plan slug for an organization."""
    from app.models.billing import Plan
    from app.models.teams import OrganizationSubscription

    sub = db.query(OrganizationSubscription).filter(
        OrganizationSubscription.organization_id == organization_id,
        OrganizationSubscription.status == "active"
    ).first()
    if not sub:
        return "free"
    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        return "free"
    return plan.slug


def get_org_limits(db, organization_id) -> dict:
    """Get limits for an organization based on its plan."""
    plan_name = get_org_plan_name(db, organization_id)
    return _ORG_FEATURES_CACHE.get(plan_name, _ORG_FEATURES_CACHE["free"])


def get_org_features(db, organization_id) -> dict:
    """Get feature flags for an organization."""
    return get_org_limits(db, organization_id)


def check_org_feature(db, organization_id, feature: str) -> bool:
    """Check if organization has a specific feature enabled."""
    features = get_org_features(db, organization_id)
    return features.get(feature, False)


def count_org_messages(db, organization_id, days: int = 30, clone_id=None) -> int:
    """Messages in the last `days` days across the organization's clones (or one of them).

    Messages belong to conversations, and conversations to clones."""
    from datetime import UTC, datetime, timedelta

    from app.models.clone_profile import CloneProfile
    from app.models.conversation import Conversation
    from app.models.message import Message

    since = datetime.now(UTC) - timedelta(days=days)
    query = (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(CloneProfile, Conversation.clone_id == CloneProfile.id)
        .filter(CloneProfile.organization_id == organization_id, Message.created_at >= since)
    )
    if clone_id is not None:
        query = query.filter(CloneProfile.id == clone_id)
    return query.count()


def check_org_limit(db, organization_id, limit: str) -> tuple[bool, int, int]:
    """Check if organization is within a specific limit.
    Returns (within_limit, current_usage, limit_value).
    """
    from app.models.clone_profile import CloneProfile
    from app.models.teams import OrganizationMember

    limits = get_org_limits(db, organization_id)
    limit_value = limits.get(limit, 0)

    if limit == "max_members":
        current = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == "active"
        ).count()
        return current < limit_value, current, limit_value

    if limit == "max_clones":
        current = db.query(CloneProfile).filter(
            CloneProfile.organization_id == organization_id
        ).count()
        return current < limit_value, current, limit_value

    if limit == "monthly_messages":
        current = count_org_messages(db, organization_id, days=30)
        return current < limit_value, current, limit_value

    # For storage, voice, avatar - return within limit for now
    # Would need additional tracking tables for precise counts
    return True, 0, limit_value