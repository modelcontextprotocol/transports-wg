from __future__ import annotations

from typing import Literal

from mcp.types import RequestParams, Result

try:
    from mcp.types._types import MCPModel  # type: ignore[attr-defined]
except Exception:
    try:
        from mcp.types import MCPModel  # type: ignore[attr-defined]
    except Exception:
        from pydantic import BaseModel as MCPModel


class SessionCreateHints(MCPModel):
    label: str | None = None
    data: dict[str, str] | None = None


class SessionCreateParams(RequestParams):
    hints: SessionCreateHints | None = None


class SessionCreateRequest(MCPModel):
    method: Literal["session/create"] = "session/create"
    params: SessionCreateParams | None = None


class SessionCreateResult(Result):
    id: str
    expiry: str | None = None
    data: dict[str, str] | None = None


class SessionResumeParams(RequestParams):
    id: str


class SessionResumeRequest(MCPModel):
    method: Literal["session/resume"] = "session/resume"
    params: SessionResumeParams


class SessionResumeResult(Result):
    id: str
    expiry: str | None = None
    data: dict[str, str] | None = None


class SessionDeleteParams(RequestParams):
    id: str


class SessionDeleteRequest(MCPModel):
    method: Literal["session/delete"] = "session/delete"
    params: SessionDeleteParams


class SessionDeleteResult(Result):
    deleted: bool
