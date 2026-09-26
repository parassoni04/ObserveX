"""
ObserveX Server — Authorization Package.

Provides RBAC and multi-tenant isolation:
- device_access: Check if a user can access a specific device
- tenant_guard: Centralized org-scoping for all queries
"""
from server.authorization.device_access import check_device_access, get_accessible_device_ids
from server.authorization.tenant_guard import TenantGuard, require_admin, require_same_org

__all__ = [
    "check_device_access",
    "get_accessible_device_ids",
    "TenantGuard",
    "require_admin",
    "require_same_org",
]
