# XXXX: Pluggable Transport Interface for MCP SDKs

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-08-20
- **Author(s)**: Kryspin Ziemski (@kziemski), Kurtis Van Gent (@kurtisvg)
- **Sponsor**: None
- **Working Group**: Transports Working Group
- **Target**: Official MCP SDKs
- **Related**: [SEP-2598](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2598)
- **Reference specification**: [MCP Transports — 2026-07-28](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx)

## Abstract

This proposal standardizes a public, replaceable **transport extension point** across official Model Context Protocol SDKs.

The extension point is intentionally narrower than defining a new MCP transport binding. It standardizes the SDK boundary between MCP protocol processing and the mechanism that carries MCP JSON-RPC messages.

A conforming SDK exposes a public transport abstraction through which a third-party transport implementation can:

1. establish or initialize transport resources;
2. send one complete MCP JSON-RPC message;
3. receive one complete MCP JSON-RPC message;
4. associate optional opaque transport-local context with a message when required by the carrier;
5. report transport-level errors; and
6. close or dispose transport resources.

The abstraction MUST preserve MCP JSON-RPC semantics. It does not permit a transport implementation to replace MCP's message model with a native RPC method model.

This proposal does **not** standardize WebSocket, `postMessage`, Cap'n Web, gRPC, QUIC, Unix sockets, or any other carrier as an MCP transport binding. Instead, it creates a consistent SDK extension point through which such carriers can be implemented without modifying the SDK protocol core.

The goal is to make custom JSON-RPC-preserving transports portable as a concept across MCP SDKs while allowing each SDK to retain language-idiomatic APIs.

## Motivation

The MCP transport specification permits custom transports, but the official SDKs do not currently expose a uniformly understood extension boundary for implementing them.

In practice, the SDKs have converged on several related patterns:

- a `Transport` interface carrying typed JSON-RPC messages;
- a `Transport` plus `Connection` abstraction;
- read/write streams carrying message envelopes;
- channels carrying typed JSON-RPC messages;
- byte- or string-oriented transport protocols with JSON-RPC parsing immediately above them.

This convergence makes a cross-SDK semantic contract practical, but differences in naming, lifecycle, message representation, and transport-specific metadata make third-party transport implementations difficult to design consistently.

Some SDK transport abstractions also expose details specific to Streamable HTTP or historical session semantics, such as:

- session IDs;
- HTTP headers;
- request-scoped response streams;
- resumption tokens;
- SSE lifecycle callbacks;
- HTTP request cancellation;
- HTTP status codes.

These properties are useful to particular transport bindings, but they should not be requirements for every custom transport.

A `postMessage` or `MessagePort` transport, for example, should not need to emulate HTTP headers or an MCP session identifier merely to connect to the MCP protocol engine. Similarly, a WebSocket or Unix-domain-socket implementation should not require changes to request dispatch, JSON-RPC correlation, capability handling, tool invocation, or other MCP protocol logic.

A standardized SDK transport extension point would make the following architecture explicit:

```text
┌───────────────────────────────────────────────┐
│             MCP Client / Server               │
│                                               │
│ tools, resources, prompts, tasks, elicitation │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│             MCP Protocol Engine               │
│                                               │
│ JSON-RPC validation and dispatch              │
│ request / response correlation                │
│ protocol metadata                             │
│ MCP lifecycle and capabilities                │
└──────────────────────┬────────────────────────┘
                       │
              MCP JSON-RPC messages
                       │
                       ▼
┌───────────────────────────────────────────────┐
│        Public SDK Transport Extension Point   │
│                                               │
│ start/connect                                 │
│ send(message, context?)                       │
│ receive(message, context?)                    │
│ errors                                        │
│ close/disconnect                              │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
      carrier / transport-binding implementation
```

This is a smaller and more incremental change than SEP-2598. SEP-2598 considered broader transport pluggability, including transports whose native RPC model may not map directly to JSON-RPC. That raises additional questions around request identifiers, notification semantics, cancellation, native RPC errors, and conformance.

This proposal deliberately avoids those questions by keeping MCP JSON-RPC as the semantic boundary.

## Goals

This proposal has the following goals:

1. Define a common semantic transport contract for official MCP SDKs.
2. Ensure SDK protocol logic can be used with a third-party transport without modifying or forking the protocol implementation.
3. Preserve MCP JSON-RPC messages and message patterns across the transport boundary.
4. Allow transport implementations to carry transport-local metadata without leaking carrier-specific concepts into the generic MCP protocol layer.
5. Remove or isolate HTTP- and session-specific requirements from generic transport abstractions.
6. Permit SDKs to implement the contract using language-idiomatic interfaces, traits, protocols, channels, callbacks, streams, or async iterators.
7. Provide common conformance tests that validate the extension point rather than requiring identical APIs.
8. Make transports such as WebSocket, `postMessage`, `MessagePort`, Unix sockets, named pipes, or RPC tunnels implementable outside the SDK core.
9. Preserve backward compatibility wherever practical.

## Non-Goals

This proposal does not:

1. add a new standard MCP transport binding;
2. standardize WebSocket framing;
3. standardize `postMessage` origin or iframe security rules;
4. standardize gRPC, Cap'n Web, or another native RPC mapping for MCP;
5. permit removal of JSON-RPC semantics from MCP;
6. require all SDKs to expose identically named methods or types;
7. require all transports to support HTTP concepts;
8. require all transports to support historical MCP session semantics;
9. define transport discovery or transport negotiation;
10. define endpoint URI schemes for custom transports;
11. require custom transports to be implemented in the official SDK repositories.

## Terminology

### MCP Protocol Engine

The SDK component responsible for MCP protocol behavior, including JSON-RPC dispatch, request/response correlation, MCP method handling, capabilities, protocol metadata, errors, and other protocol semantics.

### SDK Transport Extension Point

The public SDK API through which an implementation supplies a mechanism for sending and receiving MCP JSON-RPC messages.

The concrete API is language-specific.

### Transport Binding

A specification defining how MCP messages are framed and delivered over a particular carrier.

Examples include stdio and Streamable HTTP.

### Carrier

The underlying communication mechanism used by a transport binding or custom transport implementation, such as:

- process stdin/stdout;
- HTTP;
- WebSocket;
- `Window.postMessage`;
- `MessagePort`;
- TCP;
- Unix domain sockets;
- named pipes;
- QUIC;
- a bidirectional RPC stream.

### Transport Context

Opaque, transport-local information associated with a received or outgoing message.

Transport Context exists to support carrier-level routing or lifecycle requirements without adding carrier-specific properties to the generic MCP message model.

Transport Context is not part of the MCP JSON-RPC message and MUST NOT alter MCP protocol semantics.

### Native RPC Binding

An integration that maps MCP operations into the native method, object, capability, or schema model of another RPC system rather than transporting MCP JSON-RPC messages unchanged at the semantic boundary.

A native RPC binding is outside the scope of this proposal.

## Proposed Standard

### 1. Public replacement point

Each Tier 1 official MCP SDK MUST expose a documented public extension point through which an application can supply a custom transport implementation.

Using a custom transport MUST NOT require:

- patching the SDK protocol dispatcher;
- forking the SDK;
- reimplementing MCP method dispatch;
- reimplementing MCP request/response correlation;
- modifying the JSON-RPC schema;
- pretending to be Streamable HTTP.

An SDK MAY expose separate client and server transport abstractions where that is more idiomatic.

### 2. Message-oriented semantic boundary

At the semantic boundary between the MCP protocol engine and the transport implementation, each send or receive operation MUST represent exactly one complete MCP JSON-RPC message.

A conforming transport extension point MUST preserve:

- JSON-RPC request semantics;
- JSON-RPC response semantics;
- JSON-RPC notification semantics;
- JSON-RPC errors;
- MCP method names;
- MCP parameters;
- MCP result values;
- MCP protocol metadata;
- request identifiers where present in the applicable protocol version.

An SDK SHOULD expose its canonical typed JSON-RPC message type at this boundary when such a type exists.

An SDK MAY expose an encoded UTF-8 JSON value, byte buffer, string, stream item, or language-native JSON value instead when that representation is idiomatic, provided that:

1. a single transport send/receive item corresponds to a single complete MCP JSON-RPC message; and
2. the SDK provides the canonical adapter between that representation and its MCP protocol engine.

The purpose of this requirement is semantic consistency, not identical language APIs.

### 3. Lifecycle

The extension point MUST provide semantic equivalents for:

- **start/connect/open** — acquire transport resources and begin processing;
- **send/write** — submit an MCP JSON-RPC message for delivery;
- **receive/read/on-message** — deliver an MCP JSON-RPC message to the protocol engine;
- **close/disconnect/dispose** — release transport resources and stop processing.

The exact method names and control-flow style are implementation-defined.

For example, all of the following may conform:

```text
start() + send() + onMessage + close()
```

```text
Connect() -> Connection
Connection.Read()
Connection.Write()
Connection.Close()
```

```text
async context manager -> (read_stream, write_stream)
```

```text
AsyncSequence + send() + disconnect()
```

```text
ChannelReader + SendMessageAsync()
```

### 4. Transport errors

A transport implementation MUST have a mechanism to report transport-level failures separately from valid MCP JSON-RPC error responses.

Examples of transport-level failures include:

- connection failure;
- malformed carrier framing;
- unexpected EOF;
- WebSocket closure;
- failed process startup;
- network timeout;
- underlying stream failure.

A transport failure MUST NOT be converted into an MCP JSON-RPC error unless an MCP request was successfully received and the MCP protocol implementation determines that a JSON-RPC response is appropriate.

SDKs MAY use exceptions, error return values, failed futures/promises, stream errors, channel completion errors, or callbacks.

### 5. Opaque Transport Context

An SDK SHOULD support optional opaque Transport Context when a transport binding requires carrier-level association between an incoming message and a later outgoing message.

Conceptually:

```text
TransportMessage {
    message: MCP JSON-RPC message
    context?: opaque transport-local value
}
```

The context is intentionally not standardized as a serialized data structure.

The MCP protocol engine MUST treat Transport Context as opaque.

The protocol engine MUST NOT inspect transport-specific fields such as:

- HTTP headers;
- HTTP request objects;
- HTTP response streams;
- WebSocket handles;
- SSE event IDs;
- QUIC stream IDs;
- `MessagePort` objects;
- RPC call handles.

An SDK MAY implement Transport Context using:

- a generic type;
- an opaque object;
- a language-native context value;
- existing message metadata;
- an envelope type;
- an implementation-private association.

An SDK MAY omit explicit Transport Context from its public API if its execution model preserves the required request-to-carrier association internally.

### 6. Transport-specific extensions

Transport-specific functionality SHOULD be represented through optional extension interfaces, capabilities, adapters, or implementation-specific types rather than mandatory members of the generic transport contract.

For example:

```text
Generic Transport
    ├── HTTPTransportExtensions
    ├── ResumableTransportExtensions
    ├── ProcessTransportExtensions
    └── Custom transport-specific API
```

Generic transport implementations MUST NOT be required to implement:

- `SessionId`;
- HTTP request headers;
- HTTP response headers;
- HTTP status codes;
- SSE event IDs;
- resumption tokens;
- per-request HTTP streams;
- process identifiers;
- stderr access.

Existing SDK properties MAY remain temporarily for backward compatibility but SHOULD be deprecated or moved behind an optional transport-specific extension during the next compatible API evolution.

### 7. Protocol semantics remain above transport

The following responsibilities belong to the MCP protocol engine and MUST NOT need to be reimplemented by a custom JSON-RPC-preserving transport:

- JSON-RPC request/response correlation;
- MCP method dispatch;
- tool invocation semantics;
- resource semantics;
- prompt semantics;
- task semantics;
- capability interpretation;
- protocol-version behavior;
- MCP-level errors;
- request metadata semantics;
- JSON-RPC notification handling.

A transport MAY validate framing or decode JSON into the SDK's canonical JSON-RPC type.

A transport MUST NOT reinterpret an MCP method such as `tools/call` as a different semantic operation visible to the MCP protocol engine.

### 8. No requirement for identical SDK APIs

Conformance is behavioral.

This proposal does not require a literal interface with the following source representation:

```text
interface Transport {
    connect()
    send(message, context?)
    receive() -> (message, context?)
    close()
}
```

That pseudo-interface defines the semantic contract only.

SDKs SHOULD preserve established language conventions and existing stable APIs.

### 9. Message-oriented boundary and exchange scoping

Request-scoped carriers (Streamable HTTP, unary-plus-streaming RPC, serverless
invocations) naturally associate each request with its own response stream,
while connection-oriented carriers (stdio, WebSocket, MessagePort) multiplex
many independent exchanges over one connection. These differ in how responses
are delivered, not in what crosses the boundary.

This proposal keeps the semantic unit at the boundary as one complete MCP
JSON-RPC message rather than an exchange object, for two reasons:

1. Request/response correlation is an MCP protocol-engine responsibility (see
   §7). The JSON-RPC request id, which the applicable protocol version
   requires, lets the protocol engine associate responses; the transport must
   not re-implement correlation as a separate boundary parameter.
2. A message-oriented boundary is the common denominator across both carrier
   kinds: a connection-oriented transport carries many messages, and a
   request-scoped transport carries the messages of one exchange.

Request-scoped association is preserved at the boundary in two ways:

- the JSON-RPC request id, carried inside the message, for protocol-level
  correlation; and
- opaque Transport Context (see §5) where the carrier must route a response
  back through the correct ingress operation (an HTTP POST, an RPC call, a
  `MessagePort`), without exposing carrier-specific fields to the protocol
  engine.

An SDK MAY offer a higher-level exchange API (for example
`exchange(request) -> AsyncIterable<Response | Notification>`) as an idiomatic
convenience, provided the underlying boundary still satisfies the
message-oriented contract in §2 and §3.

## Transport Versus Native RPC Binding

This proposal distinguishes a JSON-RPC-preserving transport from a native RPC binding.

### In scope

The following is a transport:

```text
MCP protocol
    │
    ▼
MCP JSON-RPC message
    │
    ▼
GrpcTunnelTransport
    │
    ▼
bidirectional gRPC stream carrying the MCP message
```

The gRPC layer may provide:

- HTTP/2;
- TLS/mTLS;
- load balancing;
- observability;
- service discovery;
- multiplexing.

MCP still owns the RPC semantics.

Likewise:

```text
MCP JSON-RPC
    │
    ▼
CapnWebTransport
    │
    ▼
Cap'n Web invocation carrying an MCP message
```

is in scope if the Cap'n Web layer is only carrying MCP messages.

### Out of scope

The following is a native RPC binding:

```text
tools/call
    │
    ▼
nativeRemote.tools.call(...)
```

or:

```text
resources/read
    │
    ▼
GrpcMcp.ResourcesRead(...)
```

where the underlying RPC framework replaces JSON-RPC method, request, response, notification, error, or correlation semantics.

A future proposal MAY define a standard abstraction for native RPC bindings. That proposal would need to address semantic mapping and conformance independently.

## Illustrative Transport Implementations

The following examples are non-normative.

### `PostMessageTransport`

A browser or worker transport could use `postMessage` or `MessagePort`. MCP
messages are UTF-8 JSON-RPC, so a conforming transport sends and receives the
JSON document as a text value rather than a raw structured-clone object, and
enforces an origin/source policy:

```ts
class PostMessageTransport implements Transport {
  constructor(options: {
    port: MessagePort;
    expectedSource?: MessagePort | Window | null;
  }) {
    this.port = options.port;
    this.expectedSource = options.expectedSource;
  }

  async start(): Promise<void> {
    this.port.addEventListener("message", this.handleMessage);
    this.port.start?.();
  }

  async send(message: JSONRPCMessage): Promise<void> {
    // Send the complete MCP JSON-RPC message as a UTF-8 JSON text document.
    this.port.postMessage(JSON.stringify(message));
  }

  async close(): Promise<void> {
    this.port.removeEventListener("message", this.handleMessage);
    this.port.close?.();
  }

  onmessage?: (message: JSONRPCMessage) => void;

  private handleMessage = (event: MessageEvent) => {
    if (this.expectedSource && event.source !== this.expectedSource) {
      return; // drop messages from unvalidated senders
    }
    if (typeof event.data !== "string") {
      return; // require the JSON text representation
    }
    let message: JSONRPCMessage;
    try {
      message = JSON.parse(event.data);
    } catch {
      return; // malformed carrier input; ignore or surface a controlled error
    }
    this.onmessage?.(message);
  };
}
```

The example is illustrative. A `Window.postMessage` variant must additionally
supply a `targetOrigin` and validate the sender origin; a dedicated
`MessagePort` already scopes the channel, so origin policy reduces to
validating the expected peer. Security policy, allowed origins, channel
establishment, and browser framing rules belong to the `postMessage` transport
binding or application, not this proposal.

### `WebSocketTransport`

A WebSocket implementation can carry one complete serialized MCP JSON-RPC message per WebSocket message:

```text
JSONRPCMessage
      │
      ▼
 JSON encode
      │
      ▼
WebSocket message
      │
      ▼
 JSON decode
      │
      ▼
JSONRPCMessage
```

The WebSocket binding would separately define subprotocol negotiation, binary versus text frames, connection establishment, authentication, cancellation, and close behavior.

### RPC tunnel

A generic RPC framework may transport an MCP message as a payload:

```proto
service McpTunnel {
  rpc Connect(stream McpEnvelope) returns (stream McpEnvelope);
}

message McpEnvelope {
  bytes json_rpc = 1;
}
```

This remains an MCP transport because JSON-RPC remains the semantic protocol visible to the MCP engine.

## SDK Alignment

The following table describes the current architectural direction and the smallest expected alignment work. Exact APIs remain owned by each SDK.

| SDK | Current transport boundary | Alignment under this proposal | Expected compatibility |
| --- | --- | --- | --- |
| TypeScript | `Transport` carrying typed `JSONRPCMessage` with lifecycle callbacks | Keep the existing abstraction; isolate HTTP/session-specific `TransportSendOptions` and optional members into transport-specific extensions or opaque context | High; expected to be additive/deprecation-based |
| Python | async transport/context-manager patterns yielding read/write streams of `SessionMessage`; `SessionMessage` already carries JSON-RPC plus metadata | Document the stream-pair/message-envelope contract as the public custom transport extension point; retain Python's stream-oriented API | High; no need to force a callback-style interface |
| Java | `McpTransport` carrying typed JSON-RPC messages with reactive lifecycle/message handling | Define the existing reactive API as a conforming realization; avoid requiring identical connect/receive method names | High if behavioral rather than signature-based |
| Kotlin | `Transport` / abstract transport classes carrying typed JSON-RPC messages | Keep the existing abstraction; move carrier-specific options behind extensions/context where necessary | High |
| C# | `ITransport` / client transport abstractions using typed JSON-RPC and channels/readers | Treat channel-based receive and async send as conforming; isolate `SessionId` or HTTP-specific behavior | High |
| Go | `Transport.Connect()` returning a `Connection` with typed JSON-RPC `Read`, `Write`, and `Close` | Use as a reference semantic model; move historical `SessionID()` out of the minimal generic connection contract when compatibility permits | Very high |
| PHP | `TransportInterface` with lifecycle callbacks, strings, and context arrays | Keep public interface; standardize that each send/receive item is one complete MCP JSON-RPC message and define context as transport-local; optionally add typed JSON-RPC adapters | Moderate-high |
| Ruby | transport base abstractions around JSON/Hash messages and transport-owned processing | Formalize/document a stable custom transport contract and keep idiomatic callbacks/queues/loops; introduce a message envelope only if needed | Moderate-high |
| Rust | `Transport` trait with typed transmit/receive JSON-RPC message types and transport error type | Treat the existing trait as conforming; do not add context or connect methods unless required by a concrete binding | Very high |
| Swift | `Transport` protocol using `Data`, async receive streams, connect/disconnect | Preserve the byte-oriented protocol; provide/document the canonical one-message JSON-RPC adapter at the protocol boundary; optionally add a typed higher-level transport protocol later | High |

## SDK-Specific Guidance

### TypeScript

The existing TypeScript `Transport` interface is close to the intended reference abstraction.

The SDK SHOULD:

1. preserve `start`, `send`, `onmessage`, `onerror`, `onclose`, and `close`;
2. preserve `JSONRPCMessage` as the generic message boundary;
3. avoid adding additional Streamable HTTP concerns to the generic interface;
4. migrate HTTP-specific send options to an HTTP extension or opaque context;
5. keep compatibility aliases or deprecated optional fields until the next appropriate breaking release.

A third-party custom transport should only need the shared protocol package and transport interface, not the Streamable HTTP implementation.

### Python

Python SHOULD retain its stream-oriented architecture.

A conforming Python extension point may remain equivalent to:

```python
async with transport(...) as (read_stream, write_stream):
    ...
```

where stream items are `SessionMessage` values containing an MCP JSON-RPC message and optional metadata.

`SessionMessage.metadata` is a natural realization of Transport Context, provided transport-specific metadata remains opaque to generic protocol code.

The proposal SHOULD NOT require Python to replace AnyIO streams with a callback-oriented `Transport` interface.

### Java

Java SHOULD preserve its reactive programming model.

A reactive stream, sink, handler, `Mono`, or `Flux` based receive/send lifecycle satisfies this proposal when:

- the extension point is public;
- one logical item corresponds to one MCP JSON-RPC message;
- a custom transport can be installed without changing protocol dispatch.

If adding new abstract methods to `McpTransport` would break third-party implementations, the SDK SHOULD prefer default methods, sub-interfaces, adapters, or documentation of the existing semantic equivalence.

### Kotlin

Kotlin's existing `Transport` model already closely matches the desired contract.

Kotlin SHOULD keep typed JSON-RPC messages at the transport boundary and SHOULD isolate carrier-specific send options from the generic transport contract.

### C#

The C# SDK MAY continue to represent incoming transport messages through a `ChannelReader<JsonRpcMessage>` or equivalent asynchronous stream and outgoing messages through `SendMessageAsync`.

A literal `ReceiveAsync()` method is not required.

Session or HTTP properties SHOULD be optional extensions rather than requirements for arbitrary `ITransport` implementations.

### Go

Go's `Transport` and `Connection` split is an example of an idiomatic realization:

```go
type Transport interface {
    Connect(context.Context) (Connection, error)
}

type Connection interface {
    Read(context.Context) (jsonrpc.Message, error)
    Write(context.Context, jsonrpc.Message) error
    Close() error
}
```

This proposal does not require that exact shape in other SDKs.

Historical or binding-specific properties such as `SessionID()` SHOULD NOT be part of the minimum transport contract once compatibility permits their removal.

### PHP

PHP MAY continue to expose encoded JSON strings and context arrays.

The SDK SHOULD document that:

1. a `send` call contains one complete MCP JSON-RPC message;
2. each receive callback represents one complete MCP JSON-RPC message;
3. the context parameter is transport-local and opaque to generic MCP protocol code.

A typed message adapter MAY be added without removing the existing string API.

HTTP status codes, Fibers, session identifiers, and HTTP lifecycle concepts SHOULD remain implementation-specific.

### Ruby

Ruby SHOULD define a stable public contract for custom transports around its existing transport base class or module.

The contract MAY remain Hash/JSON-oriented rather than introducing a rigid typed message hierarchy.

The important requirement is that custom transports can deliver and receive complete MCP JSON-RPC messages without owning MCP protocol dispatch.

### Rust

Rust's typed `Transport` trait is already strongly aligned with the proposal.

The SDK SHOULD avoid changing the trait solely to add a literal `connect()` method if transport construction or conversion already represents connection establishment.

Similarly, opaque context SHOULD NOT be added to the base trait unless a concrete transport requires it. A wrapper/envelope trait or transport-specific extension can be used when needed.

### Swift

Swift MAY retain `Data` as the low-level transport representation.

To make the replacement point unambiguous, the SDK SHOULD document or expose the canonical adapter that converts between exactly one `Data` value and exactly one MCP JSON-RPC message before protocol dispatch.

A future additive `JSONRPCTransport` protocol MAY provide a typed layer without breaking existing implementations.

## Conformance

Conformance MUST validate behavior, not identical source APIs.

A language-agnostic transport extension-point conformance suite SHOULD be defined.

Each Tier 1 SDK SHOULD provide an **in-memory conformance transport** implementing its public extension point.

The test harness SHOULD verify at least the following.

### Required tests

1. **Third-party replacement**
   - The test transport is supplied through public API only.
   - No protocol dispatcher code is modified.

2. **Request delivery**
   - A valid MCP JSON-RPC request crosses the transport boundary unchanged semantically.

3. **Response delivery**
   - The corresponding JSON-RPC response crosses the transport boundary unchanged semantically.

4. **Notification delivery**
   - A valid notification can cross the boundary without requiring request/response behavior.

5. **Error response**
   - A valid JSON-RPC error remains a protocol message and is not reported as a transport failure.

6. **Transport failure**
   - A carrier failure is surfaced through the SDK's transport-error mechanism.

7. **Close**
   - Closing the transport releases resources and terminates receive processing.

8. **No HTTP dependency**
   - The conformance transport does not provide HTTP headers, status codes, SSE streams, or an HTTP session identifier.

9. **Protocol reuse**
   - Existing MCP method dispatch is used unchanged over the custom transport.

10. **Opaque context**
    - If the SDK exposes Transport Context, the protocol layer preserves the association required to send a carrier-level response while treating the context as opaque.

11. **Concurrent requests**
    - Multiple overlapping requests resolve to their correct responses even when responses arrive out of order.
    - A transport MUST NOT lose request/response correlation when a carrier multiplexes independent exchanges — a failure mode observed in a production RPC-carrier transport that kept a single pending-response association ([cloudflare/agents#1540](https://github.com/cloudflare/agents/issues/1540)).

### Recommended tests

The following SHOULD be verified where the SDK and the applicable protocol revision support them:

- **Cancellation** — the carrier's cancellation mechanism realizes MCP cancellation rules without stranding underlying request resources.
- **Malformed input** — non-MCP data may be ignored; malformed values claiming to be JSON-RPC produce a controlled error rather than crashing the transport.
- **Backpressure** — a slow receiver cannot silently overwrite earlier messages; queue behavior is documented.
- **Extension fields** — unknown `_meta` and extension fields survive the carrier unchanged, avoiding transports that reserialize only known schema fields.
- **Protocol-version behavior** — unsupported protocol versions fail predictably and supported versions are forwarded correctly.
- **Long-lived response streams** — a long-lived request/response operation such as `subscriptions/listen` completes over the custom transport where the applicable protocol revision supports it.

### Optional interoperability fixture

The working group MAY define a shared, language-agnostic fixture containing canonical JSON-RPC request, response, notification, and error examples, plus the concurrent-request and long-lived-stream scenarios above.

The fixture SHOULD test semantic equivalence without requiring a specific programming language representation, so each SDK can drive it through its own idiomatic harness rather than maintaining a separate per-SDK conformance suite.

## Reference Implementation

The reference work for this proposal SHOULD include two layers.

### 1. In-memory conformance transport

Every SDK should have or add a minimal in-memory implementation exercising the public extension point.

This validates the abstraction itself without introducing network behavior.

### 2. Non-core custom transport example

At least one SDK SHOULD provide a proof-of-concept custom transport outside its Streamable HTTP and stdio implementations.

A TypeScript `PostMessageTransport` or `MessagePortTransport` is a strong candidate because it demonstrates a carrier with none of the following:

- HTTP methods;
- HTTP headers;
- SSE;
- MCP HTTP sessions;
- process stdin/stdout.

A WebSocket transport is another suitable proof of concept.

The proof of concept does not become a standard MCP transport merely by implementing the SDK extension point.

## Backward Compatibility

This proposal is intended to be backward compatible.

Existing stdio and Streamable HTTP behavior is unchanged.

Existing SDK transport APIs SHOULD remain source-compatible where practical.

Where a generic transport interface currently exposes carrier-specific members, SDKs SHOULD use one or more of:

1. optional extension interfaces;
2. adapters;
3. default implementations;
4. deprecated compatibility properties;
5. a new additive transport abstraction;
6. removal only during an otherwise appropriate major release.

This proposal does not require an SDK to remove a stable API solely to achieve immediate conformance.

An existing transport can conform through an adapter.

## Security Considerations

Making transports easier to replace creates additional opportunities for unsafe transport implementations. This proposal does not weaken the security requirements of any standard MCP transport.

Custom transport authors are responsible for documenting and enforcing the security model of their carrier.

Examples include:

### Browser messaging

`postMessage` transports should consider:

- target-origin restrictions;
- source-window validation;
- `MessagePort` ownership;
- iframe sandboxing;
- message validation;
- confused-deputy risks.

### WebSocket

WebSocket transports should consider:

- origin validation where applicable;
- authentication;
- TLS;
- cross-site WebSocket hijacking;
- proxy behavior;
- frame and message limits.

### Local IPC

Unix sockets and named pipes should consider:

- filesystem or pipe permissions;
- local privilege boundaries;
- peer identity;
- socket path substitution.

### RPC tunnels

gRPC, Cap'n Web, or other RPC tunnels should consider:

- authentication;
- authorization;
- endpoint identity;
- metadata propagation;
- capability leakage;
- intermediary behavior.

Transport Context MUST be treated as untrusted unless the transport's security model establishes otherwise.

Transport Context MUST NOT implicitly grant MCP authorization merely because it was supplied by the carrier.

## Alternatives Considered

### 1. Standardize WebSocket directly

Rejected as the first step.

WebSocket is one useful carrier but does not solve the broader SDK extension-point inconsistency.

A clean SDK transport interface makes WebSocket implementable without requiring it to become a core MCP binding.

### 2. Adopt the full scope of SEP-2598

Not proposed here.

SEP-2598 explored broader pluggability, including transport or RPC systems whose semantics may differ from JSON-RPC.

That broader scope raises questions that are unnecessary for JSON-RPC-preserving carriers.

This proposal intentionally standardizes the smaller common denominator first.

### 3. Require identical `Transport` interfaces in every language

Rejected.

The SDKs use different concurrency and resource-management models.

Forcing Java reactive APIs, Python streams, Rust traits, Go connections, C# channels, and Swift async sequences into one literal signature would create unnecessary breaking changes and non-idiomatic APIs.

Behavioral conformance provides the useful interoperability property.

### 4. Keep transport APIs entirely SDK-specific

Rejected.

Although custom transports are protocol-valid today, the absence of a common public extension contract makes third-party transports harder to implement, document, test, and port across SDKs.

### 5. Move all transport metadata into JSON-RPC `_meta`

Rejected.

Carrier-level routing handles, streams, ports, request objects, and connection objects are not protocol metadata and often cannot or should not be serialized.

Transport Context remains local and opaque.

### 6. Define a native gRPC or Cap'n Web abstraction now

Deferred.

Native RPC mappings are a separate protocol-binding problem.

They should not block standardization of the JSON-RPC-preserving extension point already approximated by most SDKs.

## Implementation Plan

### Phase 1: semantic contract

- [ ] Agree on the behavioral requirements in this proposal.
- [ ] Inventory the public transport replacement point in every Tier 1 SDK.
- [ ] Identify carrier-specific leakage in each generic transport abstraction.
- [ ] Agree on the role of opaque Transport Context.

### Phase 2: per-SDK alignment

- [ ] TypeScript: isolate HTTP-specific generic transport options where practical.
- [ ] Python: document/formalize the stream-pair `SessionMessage` extension contract.
- [ ] Java: document the reactive transport API as a conforming realization and add adapters only where required.
- [ ] Kotlin: document existing `Transport` conformance and isolate binding-specific options.
- [ ] C#: document channel/async semantics and isolate session-specific members.
- [ ] Go: document `Transport`/`Connection` as a conforming realization and plan removal or isolation of session-specific members.
- [ ] PHP: document one-message send/receive semantics and opaque context behavior; add typed adapter if useful.
- [ ] Ruby: formalize the public custom transport replacement contract.
- [ ] Rust: document existing trait conformance; avoid unnecessary signature changes.
- [ ] Swift: document the JSON-RPC adapter boundary over the existing `Data` transport protocol.

### Phase 3: conformance

- [ ] Add an in-memory custom-transport conformance implementation to each Tier 1 SDK.
- [ ] Add shared semantic test fixtures.
- [ ] Verify request, response, notification, close, and transport-failure behavior.
- [ ] Verify the custom implementation does not require HTTP/session members.

### Phase 4: proof of concept

- [ ] Implement `PostMessageTransport` or `MessagePortTransport` in TypeScript as a non-core example.
- [ ] Optionally implement a WebSocket transport using the same public extension point.
- [ ] Document how an RPC tunnel can carry MCP JSON-RPC without becoming a native RPC binding.

## Open Questions

1. Should the generic concept be named `Transport`, `MessageTransport`, or `JSONRPCTransport` in specification prose?
2. Should Transport Context be a SHOULD-level capability or merely an allowed implementation technique?
3. Should a common transport-capabilities vocabulary be introduced later for features such as resumability or per-request cancellation?
4. Should the conformance fixture cover backward-compatible protocol revisions that include historical session behavior?
5. Should reference custom transports live in SDK repositories, a transport-examples repository, or independent packages?
6. Should a future proposal define package naming or discovery conventions for third-party transports?
7. Should native RPC bindings receive a distinct governance term such as `Protocol Binding` or `RPC Binding` to prevent confusion with message-preserving transports?

## Rationale

The official SDKs are already close enough to a common transport abstraction that standardization can be incremental rather than disruptive.

The useful cross-language invariant is not a particular interface signature. It is the existence of a stable public boundary where:

```text
MCP protocol logic
        │
        ▼
one complete MCP JSON-RPC message
        │
        ▼
replaceable transport implementation
```

By standardizing this boundary first, MCP gains a practical foundation for transport experimentation without prematurely standardizing every carrier or solving native-RPC semantic mapping.

This enables third-party transports such as:

- `PostMessageTransport`;
- `MessagePortTransport`;
- `WebSocketTransport`;
- Unix socket transport;
- named-pipe transport;
- QUIC-based transport;
- gRPC JSON-RPC tunnel;
- Cap'n Web JSON-RPC tunnel.

The same extension point also creates a clean place to evaluate future transport bindings through implementations before promoting any one carrier into the MCP core specification.

## References

- [MCP Transports Working Group proposals](https://github.com/modelcontextprotocol/transports-wg/tree/main/proposals)
- [MCP Transport specification — 2026-07-28](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx)
- [SEP-2598: Pluggable transports](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2598)
- [SEP-1352: Add gRPC as a transport](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1352)
- [TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Java SDK](https://github.com/modelcontextprotocol/java-sdk)
- [Kotlin SDK](https://github.com/modelcontextprotocol/kotlin-sdk)
- [C# SDK](https://github.com/modelcontextprotocol/csharp-sdk)
- [Go SDK](https://github.com/modelcontextprotocol/go-sdk)
- [PHP SDK](https://github.com/modelcontextprotocol/php-sdk)
- [Ruby SDK](https://github.com/modelcontextprotocol/ruby-sdk)
- [Rust SDK](https://github.com/modelcontextprotocol/rust-sdk)
- [Swift SDK](https://github.com/modelcontextprotocol/swift-sdk)
- [Cap'n Web](https://github.com/cloudflare/capnweb)
