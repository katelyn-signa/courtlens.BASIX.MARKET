"""Development-grade access control and the documented authN/authZ integration point.

TRUST BOUNDARY (read this): production authentication is NOT implemented. What exists:
  * an optional shared API key (``API_KEY``) checked in constant time on /api/v1/* routes;
  * an *unverified* ``X-Actor-Id`` header used only to label audit events.
Anyone who can reach the API and knows the key can claim any actor id. Replace
``authenticate`` (e.g. with OIDC/JWT validation) and ``authorize`` (role checks) before any
real deployment; every route already depends on ``require_permission(...)``.
"""

import re
import secrets
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Header, Request

from app.core.exceptions import AuthenticationError, PermissionDeniedError

_ACTOR_RE = re.compile(r"^[A-Za-z0-9_.@:\-]{1,100}$")

# Permission names used by the routers (hook for role-based rules).
CASES_READ, CASES_WRITE = "cases:read", "cases:write"
DOCUMENTS_READ, DOCUMENTS_WRITE = "documents:read", "documents:write"
ANALYSIS_READ, ANALYSIS_RUN = "analysis:read", "analysis:run"
REVIEWS_READ, REVIEWS_WRITE = "reviews:read", "reviews:write"
AUDIT_READ = "audit:read"
SYSTEM_READ = "system:read"


@dataclass(frozen=True)
class Actor:
    id: str
    authenticated: bool


def authenticate(request: Request, x_api_key: Optional[str], x_actor_id: Optional[str]) -> Actor:
    """Integration point #1: establish who is calling."""
    expected = request.app.state.settings.api_key_value
    if expected is not None:
        if not x_api_key or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
            raise AuthenticationError()
    actor_id = x_actor_id if x_actor_id and _ACTOR_RE.match(x_actor_id) else "anonymous-dev"
    return Actor(id=actor_id, authenticated=expected is not None)


def authorize(actor: Actor, permission: str) -> bool:
    """Integration point #2: may this actor do this? Baseline: yes (no roles yet)."""
    return True


def require_permission(permission: str) -> Callable[..., Actor]:
    def dependency(request: Request, x_api_key: Optional[str] = Header(default=None),
                   x_actor_id: Optional[str] = Header(default=None)) -> Actor:
        actor = authenticate(request, x_api_key, x_actor_id)
        if not authorize(actor, permission):
            raise PermissionDeniedError()
        return actor
    return dependency
