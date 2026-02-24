from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from .model import Session, generate_session_id


@runtime_checkable
class SessionStore(Protocol):
    def create(
        self,
        owner: str | None = None,
        data: dict[str, str] | None = None,
        ttl_seconds: int = 3600,
    ) -> Session: ...

    def get(self, session_id: str) -> Session | None: ...

    def update(self, session: Session) -> Session: ...

    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._owners: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def create(
        self,
        owner: str | None = None,
        data: dict[str, str] | None = None,
        ttl_seconds: int = 3600,
    ) -> Session:
        session_id = generate_session_id()
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        session = Session(id=session_id, expiry=expiry, data=data or {})
        with self._lock:
            self._sessions[session_id] = session
            if owner is not None:
                self._owners.setdefault(owner, set()).add(session_id)
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            self.delete(session_id)
            return None
        return session

    def update(self, session: Session) -> Session:
        with self._lock:
            if session.id not in self._sessions:
                raise KeyError(f"Session {session.id} not found")
            self._sessions[session.id] = session
        return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            for owner_sessions in self._owners.values():
                owner_sessions.discard(session_id)
