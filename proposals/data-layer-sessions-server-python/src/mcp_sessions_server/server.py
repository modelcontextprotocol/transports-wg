from __future__ import annotations

import logging
from typing import Any

from .model import (
    Session,
    extract_session_capability,
    extract_session_from_meta,
    inject_session_into_meta,
    session_capability,
)
from .store import InMemorySessionStore, SessionStore

logger = logging.getLogger(__name__)


class SessionServer:
    def __init__(
        self,
        store: SessionStore | None = None,
        features: list[str] | None = None,
        default_ttl_seconds: int = 3600,
    ) -> None:
        self._store = store or InMemorySessionStore()
        self._features = features or ["create", "resume", "delete"]
        self._default_ttl = default_ttl_seconds

    @property
    def store(self) -> SessionStore:
        return self._store

    def get_experimental_capabilities(self) -> dict[str, dict[str, Any]]:
        return session_capability(self._features if self._features else None)

    def client_supports_sessions(
        self, experimental: dict[str, dict[str, Any]] | None
    ) -> bool:
        return extract_session_capability(experimental) is not None

    def extract_request_session(self, meta: dict[str, Any] | None) -> Session | None:
        extracted = extract_session_from_meta(meta)
        if extracted is False or extracted is None:
            return None
        stored = self._store.get(extracted.id)
        if stored is None:
            logger.info("Rejected unknown/expired session: %s", extracted.id)
            return None
        return stored

    def create_session(
        self,
        owner: str | None = None,
        data: dict[str, str] | None = None,
        ttl_seconds: int | None = None,
    ) -> Session:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        return self._store.create(owner=owner, data=data, ttl_seconds=ttl)

    def resume_session(self, session_id: str) -> Session | None:
        return self._store.get(session_id)

    def prepare_response_meta(
        self,
        session: Session,
        existing_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return inject_session_into_meta(session, existing_meta)

    def prepare_revocation_meta(
        self,
        session_id: str | None = None,
        existing_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if session_id is not None:
            self._store.delete(session_id)
        return inject_session_into_meta(None, existing_meta)

    def get_or_create_session(
        self,
        meta: dict[str, Any] | None,
        owner: str | None = None,
        default_data: dict[str, str] | None = None,
    ) -> tuple[Session, bool]:
        session = self.extract_request_session(meta)
        if session is not None:
            return session, False
        return self.create_session(owner=owner, data=default_data), True
