# Which channel to communicate on

Recommend HTTP over STDIO, with HTTP/2 as the version to investigate. It
appears to be the only option considered with a path to all the
[problem statement's requirements](problem-statement.md).
SDK practicality and the full protocol mapping still need validation before
adopting a wire format.

The options below are ranked by viability for this work. LSP-style headers
remain a potentially viable fallback with reduced HTTP reuse; keeping the
current transports is a viable baseline that defers convergence. Named
endpoints and plain HTTP/1.1 over STDIO do not meet the current requirements.

## Requirements and scope

The replacement must run without a network port, preserve STDIO's connection
access model, reuse HTTP semantics with canonical transport metadata, and
support independently progressing responses and server-initiated messages over
one subprocess connection. It must also define process lifecycle and framing
selection, and remain practical for small servers and SDKs across languages.

The options below compare both the communication channel and the protocol
carried over it. The separate
[negotiation decision](negotiation-decision.md) covers
explicit `stdio-v2` selection and migration.

## Background

At Maintainer Day, the discussion covered keeping the existing transports,
HTTP/2 over STDIO, and Language Server Protocol (LSP) style headers. The next
day's discussion expanded the options.

[Transports WG PR #55](https://github.com/modelcontextprotocol/transports-wg/pull/55)
compares the four replacement options below. It recommends Unix sockets or
Windows named pipes, with LSP-style framing as a fallback if named endpoints
are unacceptable. The subsequent discussion rejected named endpoints because
of their access model and deployment costs.

## Option 1: HTTP/2 over STDIO

**Pros**

- Keeps inherited pipes, with no port, named listener, or endpoint permissions
  to configure. Existing launchers can continue forwarding stdin and stdout.
- Carries HTTP headers, status codes, and streaming bodies, allowing local and
  remote servers to share HTTP behavior and metadata representations.
- Multiplexes independent exchanges over one pipe pair, so a long-lived
  response need not prevent another request from completing. HTTP/2 also
  provides stream flow control and resets. See
  [RFC 9113](https://www.rfc-editor.org/rfc/rfc9113.html#section-5).

**Cons**

- Requires an HTTP/2 stack that can read and write pipes. Frameworks built
  around socket listeners may need adapters or lower-level integration.
- Adds binary framing, header compression, and flow-control machinery to small
  local servers; SDKs should absorb this complexity where possible.
- HTTP/2 over STDIO will not be fully interchangeable with the HTTP/1.1 model
  used in Streamable HTTP examples. At the HTTP layer, aborting an unfinished
  HTTP/1.1 response requires closing its connection; HTTP/2 can reset one
  stream with `RST_STREAM` while other streams continue. See
  [HTTP/1.1 connection closure](https://www.rfc-editor.org/rfc/rfc9112.html#section-9.6)
  and [HTTP/2 stream resets](https://www.rfc-editor.org/rfc/rfc9113.html#section-6.4).
  These mechanisms still need explicit mappings to MCP cancellation; ending
  an HTTP exchange does not by itself guarantee that application work stops.
- Shared HTTP semantics leave nuances to specify: how cancellation races with
  completion, how stream errors differ from connection or process failure,
  and how flow control affects concurrent messages. Server-initiated messages,
  process lifecycle, and startup framing also need a clear mapping.

**Viability: Recommended for investigation; potentially meets all requirements.**
It combines HTTP semantics, concurrent streams, and the existing connection
access model. Cross-language implementation cost and the remaining behavioral
differences both need validation. The goal is greater reuse, with explicitly
defined differences where full compatibility is not possible.

## Option 2: LSP-style headers over STDIO

**Pros**

- Keeps inherited pipes and the existing subprocess launch model.
- Adds a header block and content length to JSON-RPC messages with less
  machinery than a full HTTP stack.
- Can carry metadata outside the JSON body while retaining JSON-RPC request
  correlation and bidirectional messages.

**Cons**

- Header framing does not supply HTTP status codes, response streams, or HTTP
  flow control. These still need separate STDIO rules.
- Streaming results and cancellation would continue to require transport-specific
  handling, limiting shared implementation with Streamable HTTP.
- Changes framing, so still requires migration and startup selection rules.


## Option 3: Keep the current transports

**Pros**

- Preserves existing servers, client configuration, and SDK implementations.
- Retains port-free subprocess communication and its existing lifecycle.

**Cons**

- Every new transport feature still needs separate STDIO and HTTP designs,
  implementations, and tests.
- Metadata duplication and differences in cancellation and streaming remain.


## Option 4: HTTP over Unix sockets or Windows named pipes

**Pros**

- Opens no network port and can reuse HTTP clients, servers, and middleware
  where local endpoint support is available.
- Allows multiple connections, enabling concurrent HTTP/1.1 exchanges without
  custom multiplexing.

**Cons**

- Other processes with sufficient endpoint permissions can connect. Restricting
  access requires permissions or authentication beyond inherited STDIO pipes.
- Unix sockets and Windows named pipes need different platform and runtime
  integration; support is uneven across languages.
- Requires endpoint naming, collision handling, and lifecycle rules.
  Filesystem sockets also need cleanup after failures.
- Existing Docker launch commands that forward STDIO would need endpoint
  exposure across the container boundary, such as a socket mount.

**Viability: Not viable under the current requirements.**
Named endpoints change the required connection access model. The proposed
HTTP/1.1 approach also obtains concurrency through multiple
connections, rather than the required single subprocess connection. HTTP/2
could address that limitation but would retain the named endpoint concerns.

## Option 5: HTTP/1.1 over STDIO

**Pros**

- Preserves inherited pipes and port-free communication.
- Provides HTTP headers and status codes with a text-based wire format.

**Cons**

- One pipe pair supplies one connection. HTTP/1.1 pipelining requires responses
  in request order, so an unfinished streaming response blocks later responses.
  See [RFC 9112](https://www.rfc-editor.org/rfc/rfc9112.html#section-9.3.2).
- Independent concurrent streams would need extra channels or a custom
  multiplexing layer, adding local transport rules and implementation work.
- Still needs HTTP library integration with pipes; using HTTP/1.1 does not
  remove that cost.

**Viability: Not viable as described under the current requirements.**
Plain HTTP/1.1 on one pipe pair cannot provide independently progressing
responses alongside long-lived streams. Additional framing would be a separate
design to assess.

## Recommended Decision

Prototype HTTP/2 over STDIO as the only option considered with a plausible path
to all requirements. Validate it in SDKs across languages, including those
whose HTTP frameworks expect sockets, and measure the cost for small servers.

The prototype should demonstrate concurrent calls alongside streaming results
and server-initiated messages on one pipe pair. Define and test cancellation,
flow control, startup selection, EOF, shutdown, failures, and stderr handling.
Compare cancellation and failure behavior with Streamable HTTP over HTTP/1.1,
and document which differences SDKs can hide and which applications must handle.
Confirm that metadata has one canonical representation and that no listener or
new connection permissions are required.

These checks determine whether HTTP/2 over STDIO is practical enough to adopt.
The recommendation does not yet finalize its wire format.
