from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True)
class IdentityContext:
    actor: str
    role: str


@dataclass(slots=True)
class AuthorizationContext:
    token_scope: str
    actor: str | None = None
    role: str | None = None


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    code: str = ""
    message: str = ""


class ControlPlanePolicyEngine:
    def __init__(self, route_role_policies: Mapping[str, list[str]]) -> None:
        self.route_role_policies = {
            str(route_key): [str(role) for role in roles]
            for route_key, roles in route_role_policies.items()
        }

    def authorize_route(
        self,
        *,
        route_policy_key: str,
        identity: IdentityContext | None,
        token_scope: str,
    ) -> tuple[AuthorizationContext | None, PolicyDecision]:
        allowed_roles = self.route_role_policies.get(route_policy_key, [])
        if allowed_roles:
            if identity is None:
                return None, PolicyDecision(
                    allowed=False,
                    code="missing_identity",
                    message="Headers 'X-Control-Plane-Actor' and 'X-Control-Plane-Role' are required for this route.",
                )
            if identity.role not in allowed_roles:
                return None, PolicyDecision(
                    allowed=False,
                    code="forbidden_role",
                    message=f"Role '{identity.role}' is not permitted for route policy '{route_policy_key}'.",
                )
            return AuthorizationContext(token_scope=token_scope, actor=identity.actor, role=identity.role), PolicyDecision(True)
        if identity is not None:
            return AuthorizationContext(token_scope=token_scope, actor=identity.actor, role=identity.role), PolicyDecision(True)
        return AuthorizationContext(token_scope=token_scope), PolicyDecision(True)

    def validate_payload(
        self,
        *,
        route_policy_key: str,
        authorization: AuthorizationContext | None,
        payload: Mapping[str, Any],
    ) -> PolicyDecision:
        if route_policy_key == "approve_release":
            requested_role = str(payload.get("role", "") or "").strip()
            if requested_role and authorization is not None and authorization.role not in {"control-plane-admin", "release-manager"}:
                if authorization.role != requested_role:
                    return PolicyDecision(
                        allowed=False,
                        code="forbidden_approval_role",
                        message=(
                            f"Role '{authorization.role}' cannot submit an approval for role '{requested_role}'."
                        ),
                    )
        return PolicyDecision(True)
