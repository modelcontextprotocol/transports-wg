from __future__ import annotations

from collections.abc import Callable

from mcp.server.lowlevel.server import Server

from .model import inject_session_into_meta
from .protocol import (
    SessionCreateRequest,
    SessionCreateResult,
    SessionDeleteRequest,
    SessionDeleteResult,
    SessionResumeRequest,
    SessionResumeResult,
)
from .server import SessionServer


def register_session_handlers(
    low_level_server: Server,
    session_server: SessionServer,
    get_owner: Callable[..., str | None] | None = None,
) -> None:
    async def handle_session_create(req: SessionCreateRequest) -> SessionCreateResult:
        owner = get_owner() if get_owner else None
        hints = req.params.hints if req.params and req.params.hints else None
        data = dict(hints.data) if hints and hints.data else {}
        if hints and hints.label:
            data.setdefault("label", hints.label)

        session = session_server.create_session(owner=owner, data=data if data else None)
        meta = inject_session_into_meta(session)
        return SessionCreateResult(
            id=session.id,
            expiry=session.expiry,
            data=session.data if session.data else None,
            **{"_meta": meta},
        )

    low_level_server.request_handlers[SessionCreateRequest] = handle_session_create

    async def handle_session_resume(req: SessionResumeRequest) -> SessionResumeResult:
        session = session_server.resume_session(req.params.id)
        if session is None:
            raise ValueError(f"Session not found: {req.params.id}")
        meta = inject_session_into_meta(session)
        return SessionResumeResult(
            id=session.id,
            expiry=session.expiry,
            data=session.data if session.data else None,
            **{"_meta": meta},
        )

    low_level_server.request_handlers[SessionResumeRequest] = handle_session_resume

    async def handle_session_delete(req: SessionDeleteRequest) -> SessionDeleteResult:
        existing = session_server.store.get(req.params.id)
        if existing is not None:
            session_server.store.delete(req.params.id)
            deleted = True
        else:
            deleted = False
        meta = inject_session_into_meta(None)
        return SessionDeleteResult(deleted=deleted, **{"_meta": meta})

    low_level_server.request_handlers[SessionDeleteRequest] = handle_session_delete
