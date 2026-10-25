"""Roles and what each may do.

The demo sign-in uses one shared password and a role choice (Admin or User). The role is stored in the signed
session cookie. Each sign-in also gets a random session ID, which becomes the owner of the documents uploaded in
that session (Users may delete only their own documents; Admins may delete any).
"""

from __future__ import annotations

from dataclasses import dataclass

ADMIN, USER = "Admin", "User"
ROLES = (ADMIN, USER)

PERMISSIONS = {
    "extract": {ADMIN, USER},  # upload, review, correct, export, History
    "delete_any": {ADMIN},
    "manage_settings": {ADMIN},  # Settings page, presets, limits
}


@dataclass(frozen=True)
class User:
    id: str
    role: str
    is_authenticated: bool = True

    @property
    def name(self) -> str:
        return self.role

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS.get(permission, set())

    def can_delete(self, owner: str) -> bool:
        return self.can("delete_any") or (bool(owner) and owner == self.id)

    def to_session(self) -> dict:
        return {"id": self.id, "role": self.role}

    @classmethod
    def from_session(cls, data: dict) -> "User | None":
        if not isinstance(data, dict) or data.get("role") not in ROLES or not data.get("id"):
            return None
        return cls(id=str(data["id"]), role=data["role"])


class AnonymousUser:
    is_authenticated = False
    is_admin = False
    id = role = name = ""

    def can(self, permission: str) -> bool:
        return False

    def can_delete(self, owner: str) -> bool:
        return False
