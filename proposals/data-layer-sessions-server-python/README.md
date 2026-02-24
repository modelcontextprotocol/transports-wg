# MCP Data-Layer Sessions (Server Reference Package)

Small, self-contained reference package for the **server-side** of the
experimental MCP data-layer sessions proposal.

This package demonstrates:

- capability advertisement (`experimental.session`)
- extracting/validating incoming `_meta["mcp/session"]`
- issuing and revoking session cookies via response `_meta`
- explicit lifecycle handlers (`session/create`, `session/resume`, `session/delete`)

It is intended for proposal review and inspection, not production use.

## Layout

```text
src/mcp_sessions_server/
  __init__.py
  model.py
  store.py
  server.py
  protocol.py
  server_handlers.py
```
