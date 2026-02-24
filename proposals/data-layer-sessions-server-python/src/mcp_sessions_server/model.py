from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SESSION_META_KEY = "mcp/session"
SESSION_EXPERIMENTAL_KEY = "session"

@dataclass
class Session:
    id: str
    expiry: str | None = None
    data: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id}
        if self.expiry is not None:
            result["expiry"] = self.expiry
        if self.data:
            result["data"] = dict(self.data)
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        return cls(id=d["id"], expiry=d.get("expiry"), data=d.get("data", {}))

    def is_expired(self) -> bool:
        if self.expiry is None:
            return False
        try:
            expiry_dt = datetime.fromisoformat(self.expiry)
            now = datetime.now(timezone.utc)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            return now > expiry_dt
        except ValueError:
            return False


def generate_session_id(prefix: str = "sess-") -> str:
    return f"{prefix}{secrets.token_hex(8)}"


def session_capability(features: list[str] | None = None) -> dict[str, dict[str, Any]]:
    cap: dict[str, Any] = {}
    if features:
        cap["features"] = features
    return {SESSION_EXPERIMENTAL_KEY: cap}


def extract_session_capability(
    experimental: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if experimental is None:
        return None
    cap = experimental.get(SESSION_EXPERIMENTAL_KEY)
    if cap is None:
        return None
    return cap


def inject_session_into_meta(
    session: Session | None, existing_meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    meta = dict(existing_meta) if existing_meta else {}
    meta[SESSION_META_KEY] = None if session is None else session.to_dict()
    return meta


def extract_session_from_meta(meta: dict[str, Any] | None) -> Session | None | bool:
    if meta is None:
        return None
    if SESSION_META_KEY not in meta:
        return None
    value = meta[SESSION_META_KEY]
    if value is None:
        return False
    return Session.from_dict(value)
