"""Phase 13 Organizations API Tests - Minimal (no DB required, tests imports and structure)."""
import sys
import pytest

# Test that all org modules import correctly
def test_org_models_import():
    import sys
    sys.path.insert(0, r'C:\Users\sk\Desktop\cloneme\ai-human-clone\backend')
    from app.models.teams import (
        Organization,
        OrganizationMember,
        OrganizationInvitation,
        CloneMemberPermission,
        OrganizationSubscription,
        OrganizationAuditLog,
    )
    from app.models.notification import Notification
    assert Organization is not None
    assert OrganizationMember is not None
    assert OrganizationInvitation is not None
    assert CloneMemberPermission is not None
    assert OrganizationSubscription is not None
    assert OrganizationAuditLog is not None
    assert Notification is not None


def test_org_schemas_import():
    import sys
    sys.path.insert(0, r'C:\Users\sk\Desktop\cloneme\ai-human-clone\backend')
    from app.org.schemas.org import (
        OrganizationCreate,
        OrganizationUpdate,
        OrganizationRead,
        OrganizationMemberRead,
        OrganizationMemberUpdate,
        OrganizationInvitationCreate,
        OrganizationInvitationRead,
        InvitationAccept,
        InvitationDecline,
        OwnershipTransfer,
        CloneMemberPermissionUpdate,
        CloneMemberPermissionRead,
    )
    assert OrganizationCreate is not None


def test_org_authz_import():
    import sys
    sys.path.insert(0, r'C:\Users\sk\Desktop\cloneme\ai-human-clone\backend')
    from app.org.authz.permissions import (
        has_organization_role,
        has_clone_role,
        require_organization_member,
        require_organization_admin,
        require_organization_editor,
        require_organization_owner,
        require_clone_access,
        require_clone_editor,
        require_clone_owner,
    )
    assert has_organization_role is not None


def test_org_services_import():
    import sys
    sys.path.insert(0, r'C:\Users\sk\Desktop\cloneme\ai-human-clone\backend')
    from app.org.services import invitation, features, decorators, notifications
    from app.org.services.rate_limit import (
        org_creation_limit,
        invitation_send_limit,
        invitation_accept_limit,
        member_change_limit,
        ownership_transfer_limit,
    )
    assert invitation is not None
    assert features is not None
    assert decorators is not None
    assert notifications is not None
    assert org_creation_limit is not None


def test_org_routes_import():
    import sys
    sys.path.insert(0, r'C:\Users\sk\Desktop\cloneme\ai-human-clone\backend')
    from app.org.routes import (
        organizations,
        members,
        invitations,
        usage,
        subscription,
        memory,
        analytics,
        notifications,
    )
    # Check each has router
    for name, mod in [
        ('organizations', organizations),
        ('members', members),
        ('invitations', invitations),
        ('usage', usage),
        ('subscription', subscription),
        ('memory', memory),
        ('analytics', analytics),
        ('notifications', notifications),
    ]:
        assert hasattr(mod, 'router'), f"{name} missing router"
        assert len(mod.router.routes) > 0, f"{name} has no routes"


def test_org_router_import():
    import sys
    sys.path.insert(0, r'C:\Users\sk\Desktop\cloneme\ai-human-clone\backend')
    from app.org.routes import router
    assert hasattr(router, 'router')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])