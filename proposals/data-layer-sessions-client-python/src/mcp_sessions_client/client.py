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

logger = logging.getLogger(__name__)


class SessionClient:
    """In-memory cookie jar for data-layer sessions."""

    def __init__(self) -> None:
        self._session: Session | None = None
        self._server_has_sessions = False
        self._server_has_create = False
        self._server_has_resume = False
        self._server_has_delete = False

    @property
    def session(self) -> Session | None:
        return self._session

    def get_experimental_capabilities(self) -> dict[str, dict[str, Any]]:
        return session_capability()

    def check_server_capabilities(
        self, experimental: dict[str, dict[str, Any]] | None
    ) -> bool:
        cap = extract_session_capability(experimental)
        self._server_has_sessions = cap is not None
        features = cap.get("features", []) if cap else []
        self._server_has_create = "create" in features
        self._server_has_resume = "resume" in features
        self._server_has_delete = "delete" in features
        return self._server_has_sessions

    def prepare_request_meta(
        self, existing_meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._session is None:
            return dict(existing_meta) if existing_meta else {}
        return inject_session_into_meta(self._session, existing_meta)

    def process_response_meta(self, meta: dict[str, Any] | None) -> Session | None:
        extracted = extract_session_from_meta(meta)
        if extracted is False:
            logger.info("Session revoked by server")
            self._session = None
        elif extracted is not None:
            self._session = extracted
        return self._session

    def build_create_request_params(
        self,
        label: str | None = None,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        hints: dict[str, Any] = {}
        if label is not None:
            hints["label"] = label
        if data is not None:
            hints["data"] = data
        return {"hints": hints} if hints else {}

    def build_resume_request_params(self, session_id: str) -> dict[str, Any]:
        return {"id": session_id}

    def build_delete_request_params(self, session_id: str | None = None) -> dict[str, Any]:
        sid = session_id or (self._session.id if self._session else None)
        if sid is None:
            raise ValueError("No session_id provided and no session in jar")
        return {"id": sid}

    def process_create_or_resume_result(self, result: dict[str, Any]) -> Session:
        meta = result.get("_meta") or result.get("meta")
        session = self.process_response_meta(meta)
        if session is None:
            raise ValueError(
                "session/create or session/resume response is missing _meta.mcp/session. "
                "Servers MUST populate _meta.mcp/session on these responses."
            )
        return session

    def process_delete_result(self, result: dict[str, Any]) -> bool:
        meta = result.get("_meta") or result.get("meta")
        self.process_response_meta(meta)
        return bool(result.get("deleted", False))

    def set_session(self, session: Session | None) -> None:
        self._session = session
