# Problem Statement: HTTP over STDIO

MCP needs a common transport model for local and remote servers. Running HTTP
over STDIO would let local servers reuse HTTP behavior while retaining the
ability to communicate with a subprocess without opening a network port.

## Problem

MCP maintains separate STDIO and Streamable HTTP transports. Each protocol
change must account for both, which adds design, implementation, and testing
work for protocol maintainers and SDK authors.

The differences go beyond how bytes are delivered:

- Cancellation needs separate transport rules. For example, the stateless
  transport work maps cancellation to HTTP stream closure for HTTP and a
  JSON-RPC cancellation notification for STDIO. SDKs must map both mechanisms
  to the same application behavior.
- Metadata needs separate representations because the existing STDIO framing
  has no headers. Protocol version information, for example, appears in MCP
  messages and in the `MCP-Protocol-Version` HTTP header. Duplicating values in
  message fields and headers adds wire overhead and consistency checks.
- Trace context can diverge between headers and message fields.
  [PR #56](https://github.com/modelcontextprotocol/transports-wg/pull/56)
  describes how tracing proxies can update `traceparent` and `tracestate`
  headers without rewriting copies in `params._meta`. The mismatch can break
  trace relationships or trigger header validation errors; keeping both
  copies aligned requires proxies to parse and rewrite JSON-RPC bodies.
  The proposal uses native headers for HTTP and retains `params._meta` for
  existing STDIO, requiring translation when bridging the transports. This
  illustrates the cost of maintaining separate metadata representations.
- Concurrent requests and streamed notifications need transport-specific
  handling. STDIO needs message-level correlation to associate notifications
  with the request that produced them; HTTP can associate them with a response
  stream.
- New features under investigation, such as streaming tool results, would
  require separate transport implementations for STDIO and HTTP. Each would
  need to define how to deliver chunks, signal completion, and handle
  cancellation, adding work to keep their behavior consistent.

These differences make it harder to add features consistently and require
maintainers to specify and test each feature across both transports. SDKs must
maintain separate handling even when the intended application behavior is the
same.

## Local communication requirements

STDIO remains useful because a client can launch a server and communicate
through its inherited input and output pipes. There is no listening endpoint
for other processes to connect to. This is a useful security property, though
it does not isolate the server from the operating system or sandbox its code.

A replacement must:

- Run locally without opening a network port.
- Preserve the existing STDIO security model without significant changes to
  who can connect to the server.
- Reuse HTTP semantics so new protocol features need fewer separate designs
  for local and remote transports, with one canonical representation for
  transport metadata.
- Support concurrent requests and server-initiated messages over one
  subprocess connection, with responses able to progress independently
  alongside long-lived streams.
- Define startup, shutdown, failure, and stderr behavior, including how clients
  distinguish the new framing from existing STDIO servers.
- Remain practical for small servers and SDKs across implementation languages.

The goal is to carry HTTP over STDIO, or another local process channel that
meets these requirements. The choice of channel, HTTP version, and migration
path belongs in the decision documents.
