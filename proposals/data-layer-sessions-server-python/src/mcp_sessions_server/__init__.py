"""Reference server package for MCP data-layer sessions proposal."""

from .model import (
    SESSION_EXPERIMENTAL_KEY,
    SESSION_META_KEY,
    Session,
    extract_session_capability,
    extract_session_from_meta,
    generate_session_id,
    inject_session_into_meta,
    session_capability,
)
from .protocol import (
    SessionCreateHints,
    SessionCreateParams,
    SessionCreateRequest,
    SessionCreateResult,
    SessionDeleteParams,
    SessionDeleteRequest,
    SessionDeleteResult,
    SessionResumeParams,
    SessionResumeRequest,
    SessionResumeResult,
)
from .server import SessionServer
from .server_handlers import register_session_handlers
from .store import InMemorySessionStore, SessionStore

__all__ = [
    "Session",
    "SessionServer",
    "SessionStore",
    "InMemorySessionStore",
    "register_session_handlers",
    "SessionCreateRequest",
    "SessionCreateParams",
    "SessionCreateHints",
    "SessionCreateResult",
    "SessionResumeRequest",
    "SessionResumeParams",
    "SessionResumeResult",
    "SessionDeleteRequest",
    "SessionDeleteParams",
    "SessionDeleteResult",
    "generate_session_id",
    "session_capability",
    "extract_session_capability",
    "inject_session_into_meta",
    "extract_session_from_meta",
    "SESSION_META_KEY",
    "SESSION_EXPERIMENTAL_KEY",
]
