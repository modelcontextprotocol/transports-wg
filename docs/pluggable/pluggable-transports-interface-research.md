# Pluggable MCP Transports Across the Official SDKs

## Executive assessment

**Yes. A narrower “pluggable transport” step—keeping MCP messages as JSON-RPC while making the transport/binding replaceable—is both feasible and, after the July 28, 2026 MCP specification, much better aligned with the protocol than SEP-2598 was when it was proposed.** The current specification now explicitly defines a transport as a **binding** that determines framing, delivery, metadata carriage, cancellation, and termination while leaving MCP message semantics unchanged. It explicitly permits custom transports, but requires them to preserve the JSON-RPC message format, MCP message patterns, and the per-request metadata model.

That distinction is the key architectural answer to this research:

> **MCP core semantics → JSON-RPC message model → pluggable binding/transport → actual communication substrate**

`stdio` and Streamable HTTP are simply the two standardized bindings today. A WebSocket, `MessagePort`/`postMessage`, TCP socket, Unix socket, RPC framework, or another communication substrate can occupy the layer beneath the JSON-RPC message model without redefining MCP itself. The specification now says almost exactly this: custom transports may use any channel supporting bidirectional message exchange, while reliable bidirectional byte streams should normally reuse stdio's newline-delimited JSON-RPC framing.

The SDK review produces an unusually strong result: **most of the ten official SDKs already have either an explicit transport interface/protocol or a public transport-injection seam.** Go, Java, C#, PHP, Rust, and Swift expose particularly clear abstractions; Kotlin already ships a WebSocket transport and an in-memory `ChannelTransport`; Python v2 accepts a custom `Transport` directly; TypeScript has public transport injection and a sophisticated internal transport split; Ruby has a client-side custom-transport contract but is less cleanly abstracted on the server side.

My resulting feasibility assessment is:

| SDK | Existing pluggability | Work to establish a stable transport SPI | Assessment |
|---|---|---:|---|
| TypeScript | Public `connect(transport)`; stdio/HTTP/in-memory; modern HTTP internally uses a per-request transport | Clarify/stabilize the v2 SPI and reconcile connection-oriented vs per-exchange APIs | **Low–Medium** |
| Python | `Client` explicitly accepts a custom `Transport`; transport produces streams consumed by `JSONRPCDispatcher` | Client essentially done; server-side binding SPI should converge with modern dispatcher model | **Low–Medium** |
| Java | Public `McpClientTransport`, `McpServerTransportProvider`, `McpTransport`; migration docs explicitly address custom implementors | Mostly documentation/conformance/common semantics | **Low** |
| Kotlin | Multiple interchangeable transports; WebSocket already exists; `ChannelTransport` provides full duplex | Formalize extension contract rather than invent it | **Low** |
| C# | Public `IClientTransport`; factory was deliberately changed toward direct transport injection; stream transports exist | Make client/server SPI semantics consistently documented | **Low** |
| Go | Explicit `mcp.Transport`; `jsonrpc` package is specifically intended for custom-transport implementors | Mostly contract/conformance work | **Very low** |
| PHP | Documentation explicitly says all transports implement `TransportInterface`; server accepts transport via `run()` | Align interface semantics with 2026 stateless binding model | **Low** |
| Ruby | Client docs explicitly permit a user-defined transport with `send_request`; server transports remain more coupled to server/Rack behavior | Introduce a symmetric server-side exchange/binding interface | **Medium** |
| Rust | README explicitly says any `Transport` implementation can be passed to `.serve(..)` | Primarily portability/conformance details | **Very low** |
| Swift | Public `Transport` protocol and documented custom implementation; custom `NetworkTransport` precedent | Mostly common behavioral contract/conformance | **Very low** |

So I would **not** frame this as “refactor ten SDKs to invent a Transport interface.” That overstates the work. A more accurate project is:

**standardize what an MCP SDK transport extension point means, adjust the few SDKs whose public surfaces do not yet cleanly express those semantics, and build a cross-SDK conformance contract for third-party bindings.**

That is a materially smaller and more achievable first step.

## Protocol reality after the 2026 revision

The most important fact for revisiting SEP-2598 is that MCP itself changed substantially after the SEP's April 2026 review.

The July 28, 2026 specification defines a transport as a binding and says protocol semantics are identical across bindings. The binding determines framing and delivery, request-metadata carriage, cancellation, and termination. MCP messages themselves remain UTF-8 JSON-RPC. Standard bindings are stdio and Streamable HTTP; additional custom transports are explicitly permitted.

The current requirements are particularly clear:

* JSON-RPC messages **must** be UTF-8 encoded.
* A binding must carry client requests/notifications to the server and server responses/notifications back to the client.
* All protocol metadata is now principally in the JSON-RPC body.
* A custom transport must preserve JSON-RPC, MCP message patterns, and the per-request metadata model.
* A custom transport should document connection establishment, framing, and cancellation.
* Reliable bidirectional byte-stream transports should normally reuse the newline-delimited stdio framing.

This means **the protocol specification already has the conceptual “pluggable transport” layer**. What is missing is a sufficiently uniform SDK-level SPI through which application and library authors can implement that binding without forking an SDK.

### Why the new stateless protocol makes this much easier

The 2026 specification also removed one of the major complications that existed when SEP-2598 was reviewed: protocol-level sessions.

MCP is now formally stateless. Servers must not infer protocol version, capabilities, client identity, conversation identity, or other protocol context from a connection. Every request carries the required metadata. Long-lived `subscriptions/listen` remains a request/response operation whose response happens to remain open; its state belongs to the request, not the underlying connection.

The July 28 changelog makes the magnitude of this change explicit: protocol sessions and `Mcp-Session-Id` were removed; the `initialize`/`notifications/initialized` handshake was removed for the modern protocol; protocol version and client capabilities now accompany every request; standalone HTTP GET subscriptions were replaced by `subscriptions/listen`; and the protocol moved away from server-initiated JSON-RPC requests toward Multi Round-Trip Requests.

This makes a binding abstraction dramatically cleaner.

A connection no longer needs to mean:

```text
MCP protocol session
    + negotiated identity
    + capabilities
    + conversation state
    + request correlation
    + transport lifecycle
```

Instead, it can mean only:

```text
resource used to carry independent MCP exchanges
```

That is precisely what you want for WebSocket connection pooling, worker/message-port connections, HTTP/2 multiplexing, gRPC channels, local sockets, or RPC-framework-managed channels. The same connection can carry unrelated requests because MCP explicitly forbids treating connection identity as protocol state.

### SEP-2598 should be narrowed rather than resurrected unchanged

SEP-2598 proposed two things together:

1. a public `Transport` interface plus conformance harness in SDK core; and
2. relaxation of the JSON-RPC wire-format requirement so custom transports could transcode MCP into Protobuf, CBOR, or other native representations.

Those are separable ideas, and the second one generated much of the design resistance.

Review discussion raised questions such as whether a native gRPC implementation should need a JSON-RPC request ID at all, whether all transports should support all MCP notifications, whether `initialize` should exist in a stateless transport, and whether response correlation should be exposed through request IDs in a general transport API.

Another objection concerned process rather than architecture: requiring every Tier-1 SDK to expose an interface **and** maintain its own reusable conformance harness would impose substantial cross-SDK maintenance and tier-review burden. Reviewers suggested treating transport support more like an optional extension and putting transport-specific tests in the common conformance ecosystem instead. The SEP also still lacked its required prototype implementation.

Those objections point toward a much better first SEP:

> **Do not change MCP's JSON-RPC representation. Standardize the SDK extension seam for custom bindings that carry existing MCP JSON-RPC.**

That eliminates most of the semantic translation problem.

There is an additional reason not to revive the transcoding part of SEP-2598 unchanged: **the final July 28, 2026 specification now normatively says custom transports must preserve the JSON-RPC message format.**

So today there are really two proposals:

```text
A. Pluggable binding carrying MCP JSON-RPC
   → already compatible with the current specification
   → appropriate first step

B. Alternate MCP encodings / native RPC mappings
   → changes the current normative protocol
   → requires a separate future SEP
```

My recommendation is emphatically **A first, B later if still desirable**.

## Cross-SDK transport architecture

DeepWiki is useful for quickly locating the relevant architectural areas, but for this assessment the important conclusions were checked against the current official specification and repositories. The striking pattern is that the SDKs have independently converged on roughly the architecture you are proposing.

### TypeScript

The TypeScript SDK already makes transport selection explicit at the protocol boundary. A client creates a `Client`, constructs a transport such as `StreamableHTTPClientTransport`, `StdioClientTransport`, or an in-memory transport, and calls `client.connect(transport)`. The documentation explicitly says that downstream client behavior is independent of which transport branch was selected.

Server code also has transport injection on the older/connection-oriented path: `McpServer.connect(transport)` is used with web-standard and Node Streamable HTTP transport implementations.

The interesting complication is v2's modern 2026 HTTP serving path. `createMcpHandler()` classifies each HTTP request and creates a **single-exchange per-request transport** for modern requests. That is architecturally significant: it acknowledges that a current MCP transport is not necessarily a long-lived `start()/send()/onmessage()/close()` connection object.

So TypeScript is not far from pluggability, but it is also evidence that **standardizing the old v1 transport lifecycle verbatim would be a mistake**. The SPI needs to encompass both:

```text
long-lived channel
    stdio
    WebSocket
    MessagePort

request-scoped exchange
    Streamable HTTP
    unary + streaming RPC
    serverless handler
```

The TypeScript SDK's own design guidance says transport lifecycle belongs in the SDK but also requires concrete justification before adding public abstractions, so a transport proposal would be strongest if accompanied by an actual third-party binding such as `MessagePortTransport`.

**Assessment: Low–Medium.** The seam exists; what is needed is to declare the correct v2-compatible third-party SPI rather than simply exporting the historical interface unchanged.

### Python

Python v2 is even more explicit. The high-level `Client` accepts a URL, subprocess, in-memory server, **or custom `Transport` instance**.

More importantly, the implementation makes the separation visible. A custom `Transport` is entered as an asynchronous context manager and produces read/write streams; those streams are handed to `JSONRPCDispatcher`. In other words:

```text
custom Transport
       ↓
read/write message streams
       ↓
JSONRPCDispatcher
       ↓
MCP session/client behavior
```

The transport is therefore already separated from JSON-RPC dispatch.

Python also has an in-process modern path that bypasses serialization and connects dispatchers directly, which is another useful architectural clue: **JSON-RPC serialization belongs at the remote-binding boundary, not inside MCP business logic.**

The remaining issue is symmetry. The client custom-transport contract is clear; a fully general server-side third-party binding should have an equally direct way to deliver an independent incoming exchange to the modern server dispatcher without having to imitate Streamable HTTP or a legacy session loop.

**Assessment: Low–Medium**, with most work on a clean server-facing binding API rather than on the client.

### Java

Java is essentially already there.

The SDK has `McpTransport`, `McpClientTransport`, and `McpServerTransportProvider` concepts. Its 2.0 migration guide explicitly addresses developers implementing custom `McpClientTransport` or `McpServerTransportProvider`, including how transport implementations advertise supported protocol versions.

Official code and examples use transport types independently of clients and servers, and server/client variants are intentionally separate because their hosting responsibilities differ.

That client/server split is worth preserving. A server transport frequently owns a listener or framework adapter; a client transport is usually a dialer. Forcing them into one syntactically identical interface adds little value.

**Assessment: Low.** Java needs convergence on a common MCP binding contract and tests, not a fundamental refactor.

### Kotlin

Kotlin is perhaps the best concrete evidence that “nonstandard MCP transport behind the same SDK” is already practical.

Its current repository lists stdio, Streamable HTTP, legacy SSE, **WebSocket**, and an in-process `ChannelTransport`. A client creates a transport and passes it to `client.connect(transport)`. `ChannelTransport` provides a full-duplex connection over Kotlin coroutine channels.

The WebSocket transport is particularly important to your question: **one official SDK has already demonstrated that MCP protocol handling does not inherently depend on Streamable HTTP.** The transport layer can be exchanged while the MCP client/server model remains intact.

The caution is that parts of Kotlin's documentation still describe handshake/session-era MCP concepts while the latest core specification is stateless. That is a migration issue, not an argument against the architecture; a new cross-SDK transport contract should be defined against the 2026 binding semantics rather than copying legacy session assumptions.

**Assessment: Low.**

### C#

C# has already gone through almost exactly the API design discussion SEP-2598 implies.

An earlier SDK issue proposed changing `McpClientFactory.CreateAsync()` to receive an `IClientTransport` directly, with each transport owning its own configuration type. The proposed shape was:

```csharp
CreateAsync(
    IClientTransport transport,
    McpClientOptions? clientOptions = null,
    ...)
```

and `StdioClientTransport` would implement `IClientTransport`. The discussion specifically recognized that transport state should be shifted toward per-client/session objects where possible.

Current transport documentation also includes generic stream-based client/server transports in addition to HTTP and stdio, making arbitrary .NET `Stream` implementations usable as the underlying I/O mechanism.

That already enables a large family of adapters without changing MCP: named pipes, custom sockets, encrypted streams, multiplexers, or a WebSocket abstraction presented as an appropriate stream/message adapter.

**Assessment: Low.**

### Go

Go is the clearest “already solved” implementation.

The official README says servers run over an `mcp.Transport`, clients connect through one, and explicitly states that the SDK's separate `jsonrpc` package exists **for users implementing their own transports**.

The Go transport abstraction is also deliberately lightweight. The current `Transport` interface centers on `Connect(ctx)`, which returns a connection; lifecycle belongs primarily to the resulting connection rather than being forced onto the reusable transport factory. A proposal to add `Close()` directly to `Transport` was closed as not planned.

That is a good design reference:

```text
Transport
   = way to establish/open an MCP carrier

Connection / Exchange
   = stateful resource returned by that operation
```

It prevents a transport configuration/factory object from becoming synonymous with a specific MCP session—a particularly useful property now that MCP itself is stateless.

**Assessment: Very low.** Go should probably be one of the reference SDKs for the proposed design.

### PHP

PHP documentation explicitly states: **“All transports implement the `TransportInterface`.”** A server accepts a transport through `Server::run($transport)`, with stdio and Streamable HTTP as concrete implementations.

The client similarly constructs either `StdioTransport` or `HttpTransport` and passes it to `Client::connect()`.

PHP's HTTP stack also illustrates another important principle: transport-specific concerns such as PSR-7 request handling, CORS, DNS-rebinding protection, HTTP protocol-version headers, body limits, and HTTP middleware belong in the HTTP transport implementation, not in the MCP protocol dispatcher.

The main work is therefore updating the semantics of `TransportInterface` and implementations to the newer stateless protocol where required, not creating the extension seam itself.

**Assessment: Low.**

### Ruby

Ruby is the largest architectural gap, although even here the client side already supports custom transports.

The repository documents that callers may supply their own client transport provided it has the expected `send_request(request:)` behavior, taking a complete JSON-RPC request and returning the raw JSON-RPC response. The documentation explicitly names WebSocket and stdio as possible custom implementations.

Server transports, however, are much more concrete. `StdioTransport` owns its read loop and is constructed with a server; `StreamableHTTPTransport` is directly a Rack application and dispatches into the server.

That is workable for built-in transports but less attractive as a third-party SPI because it couples:

```text
hosting framework
+ transport lifecycle
+ message delivery
+ MCP server dispatch
```

A proper server binding interface should invert that dependency so the transport delivers an incoming MCP exchange into a server handler rather than embedding the server inside every transport implementation.

**Assessment: Medium.** Ruby is the SDK where a deliberate server-side refactor would add the most value.

### Rust

Rust already states the desired design in almost exactly the requested language:

> a transport moves JSON-RPC messages between client and server, and any `Transport` implementation can be supplied to `.serve(..)`.

The SDK ships stdio, child-process, Streamable HTTP, and worker/in-process transports behind Cargo features.

This is therefore already a genuine public transport SPI.

One implementation concern for a browser-oriented `PostMessageTransport` is Rust/Wasm portability: transport implementations must avoid trait bounds or executor assumptions that unnecessarily require multithreaded `Send` futures where a browser's local event loop cannot satisfy them. That is an implementation-level issue, not a protocol limitation.

**Assessment: Very low** for generic pluggability; browser/Wasm variants may require targeted ergonomic work.

### Swift

Swift likewise already exposes a public `Transport` protocol and provides complete documentation showing a user-defined:

```swift
public actor MyCustomTransport: Transport {
    func connect() async throws
    func disconnect() async
    func send(_ data: Data) async throws
    func receive() -> AsyncThrowingStream<Data, Error>
}
```

The repository also includes an in-memory transport and a custom `NetworkTransport` using Apple's networking framework, in addition to stdio and HTTP.

That is effectively the experiment SEP-2598 needed: a transport can already be replaced without changing the Swift MCP client/server APIs.

**Assessment: Very low.**

### What the ten SDKs collectively show

There is no fundamental cross-language blocker.

The APIs currently cluster into three patterns:

| Pattern | SDK examples | Shape |
|---|---|---|
| Raw/message-stream transport | Python, Swift, Rust | transport sends/receives JSON-RPC messages or streams |
| Transport → connection | Go, parts of Java/C# | reusable transport establishes a stateful carrier |
| Framework/request adapter | TypeScript modern HTTP, PHP HTTP, Ruby Rack | each external request becomes an MCP exchange |

All three are legitimate. The mistake would be requiring every language to expose **identical methods**.

The cross-SDK requirement should therefore specify **behavior**, not syntax.

## A transport interface that fits every SDK

The right abstraction is slightly more precise than the historical idea of a generic bidirectional socket.

I recommend defining an **MCP Binding SPI** whose public language-specific name may remain `Transport`, but whose normative unit is an **exchange**.

### The logical model

For modern MCP, the fundamental operation is:

```text
MCP request
   │
   │  contains protocol metadata
   ▼
┌───────────────────────────┐
│ Transport / Binding       │
│                           │
│ establish carrier         │
│ frame request             │
│ send request              │
│ receive response stream   │
│ implement cancellation    │
└───────────────────────────┘
   │
   ├── zero or more related notifications
   │
   └── final JSON-RPC response
```

A normal request may produce no intermediate notifications. A long-running operation may produce progress/log notifications followed by the result. `subscriptions/listen` is the same abstraction with a very long response stream. This follows the 2026 request-scoped model directly.

A useful conceptual client API is therefore:

```typescript
interface McpClientTransport {
    open(): Promise<void>;

    exchange(
        request: JsonRpcRequest,
        options?: ExchangeOptions
    ): AsyncIterable<JsonRpcResponse | JsonRpcNotification>;

    sendNotification(
        notification: JsonRpcNotification
    ): Promise<void>;

    close(): Promise<void>;
}
```

This is **illustrative**, not a recommendation that every SDK adopt these exact methods.

The important semantics are:

```text
exchange()
    accepts a complete MCP JSON-RPC request
    does not receive "requestId" separately
    returns/yields messages belonging to that exchange
    ends when the final response is delivered
    exposes cancellation through the exchange/caller's cancellation primitive
```

The request ID remains part of the JSON-RPC message because the current protocol requires it, but **it should not become an extra transport abstraction parameter**. That satisfies the spirit of the SEP-2598 review concern: a transport API should not make protocol code manually correlate a separate `requestId` argument with an external channel.

For a server, the inverse is more natural:

```typescript
interface McpServerTransport {
    serve(
        handler: (exchange: IncomingExchange) => Promise<void>
    ): Promise<void>;

    close(): Promise<void>;
}

interface IncomingExchange {
    readonly request: JsonRpcRequest;
    readonly transportContext?: unknown;

    send(message: JsonRpcResponse | JsonRpcNotification): Promise<void>;
}
```

Again, the exact language API should vary. Java may continue using `McpServerTransportProvider`; Go may return a `Connection`; Rust may model the exchange through traits and streams; Python may use async context managers; Ruby may use duck typing.

### Why one universal `send()/onmessage` interface is not ideal

A traditional transport interface such as:

```text
start
send(message)
onmessage(message)
close
```

works beautifully for stdio, WebSocket, or MessagePort.

It is less natural for modern Streamable HTTP because each MCP request owns its own HTTP response stream. The TypeScript SDK's current modern path demonstrates this directly by creating a per-request, single-exchange transport.

Likewise, it is less natural for:

```text
gRPC unary request + server stream
HTTP/2 request stream
serverless invocation
message queue request/reply
RPC framework invocation
```

An **exchange-aware API can implement both models**, whereas a pure socket interface forces request-oriented transports to pretend they are connections.

Internally:

```text
WebSocketTransport.exchange(request)
    assign/send JSON-RPC request
    route incoming frames by JSON-RPC id
    yield matching notifications/response

StdioTransport.exchange(request)
    write line
    route incoming lines by JSON-RPC id
    yield matching messages

HttpTransport.exchange(request)
    POST request
    yield SSE messages / JSON response

GrpcCarrierTransport.exchange(request)
    call RPC
    put JSON-RPC document in payload
    yield streamed JSON-RPC documents

MessagePortTransport.exchange(request)
    postMessage(JSON.stringify(request))
    route MessageEvents by JSON-RPC id
```

That is a clean common denominator.

### Connection should not equal MCP session

The interface should also explicitly state:

> **A transport connection is an I/O resource, not MCP protocol state.**

That follows the 2026 specification's statelessness requirements. Servers cannot infer client capabilities, protocol version, task identity, conversation identity, or authorization state merely because requests arrived over the same connection.

This single rule makes pooling safe conceptually:

```text
             ┌─ MCP request A
WebSocket ───┼─ MCP request B
connection   ├─ subscriptions/listen
             └─ MCP request C
```

provided the binding correctly multiplexes the independent exchanges.

It likewise permits:

```text
request A → gRPC channel 1
request B → gRPC channel 2
request C → gRPC channel 1
```

without changing MCP semantics.

### Keep transport metadata opaque to the protocol core

The current specification says all **protocol** metadata lives in the JSON-RPC body, while bindings may mirror information into envelope metadata such as HTTP headers. The body remains authoritative.

Therefore the generic SPI should not contain fields such as:

```text
httpStatus
requestHeaders
responseHeaders
stderr
sseEventId
webSocketCloseCode
grpcMetadata
origin
messagePort
```

Those belong in transport-specific context or configuration.

A generic escape hatch such as:

```text
TransportContext / TransportMetadata / NativeContext
```

can expose framework integration without making HTTP concepts part of MCP.

PHP's HTTP middleware stack and TypeScript's HTTP request context demonstrate why this separation matters: HTTP-specific security, CORS, headers, authentication challenges, body limits, and framework request types have legitimate uses, but they are properties of that binding rather than properties of an MCP tool call.

### Separate transport conformance from SDK tier conformance

SEP-2598's proposal that every Tier-1 SDK maintain a reusable transport conformance harness attracted reasonable pushback because it multiplies implementation and review burden across languages.

A cleaner arrangement would be:

```text
MCP core conformance
    tests MCP semantics

Binding conformance profile
    tests JSON-RPC preservation
    tests request/response association
    tests streaming notifications
    tests cancellation
    tests malformed JSON-RPC
    tests concurrent requests
    tests subscriptions/listen
    tests per-request metadata
    tests teardown/error propagation

SDK adapter
    declares which binding profiles it passes
```

The important change is that the **test vectors and expected behavior should be centralized**, even if thin language-specific drivers are required.

A third-party WebSocket package could then say:

```text
MCP WebSocket Binding Profile: PASS
TypeScript adapter: PASS
Go adapter: PASS
Rust adapter: PASS
```

without making WebSocket itself mandatory for every Tier-1 SDK.

That preserves the ecosystem flexibility the SEP reviewers wanted while still making “custom transport” mean something testable.

## PostMessage, WebSocket, Cap’n Web, and RPC frameworks

This narrower model opens the exact use cases in the question, but there is an important distinction between **carrying JSON-RPC through another system** and **replacing JSON-RPC with that system's native RPC model**.

### PostMessageTransport

A `PostMessageTransport` is one of the cleanest possible first reference implementations, particularly in TypeScript.

Browser `MessagePort` is already message-framed and bidirectional. Conceptually:

```text
MCP Client
   │
   │ JSON.stringify(JSON-RPC)
   ▼
MessagePort.postMessage()
   │
   ▼
iframe / Worker / extension / embedded app
   │
   │ JSON.parse()
   ▼
MCP Server
```

For strict conformity with the current MCP transport wording, the safest representation would be a **JSON text string containing the MCP JSON-RPC message**, rather than relying on structured-clone serialization of an arbitrary JavaScript object. MCP requires JSON-RPC messages and says they must be UTF-8 encoded; keeping the actual JSON document intact removes ambiguity about whether structured-clone objects constitute the required wire representation.

`MessageChannel`/`MessagePort` is preferable to treating global `window.postMessage()` as an unrestricted bus because it naturally gives each side a dedicated endpoint. Where `window.postMessage()` is used directly, origin/source validation must be treated as part of the transport's security contract.

An exchange implementation would be small:

```typescript
class MessagePortTransport {
    constructor(private readonly port: MessagePort) {}

    async send(message: JsonRpcMessage) {
        this.port.postMessage(JSON.stringify(message));
    }

    // message event:
    // 1. require string
    // 2. JSON.parse
    // 3. validate JSON-RPC
    // 4. dispatch to matching exchange
}
```

This would be an excellent SEP prototype because it demonstrates genuine value unavailable from stdio/HTTP while requiring **zero changes to MCP semantics**.

It also enables important deployment structures:

```text
browser host ── MessagePort ── MCP implementation in Worker

browser host ── postMessage ── sandboxed iframe MCP application

VS Code / Electron renderer ── IPC/MessagePort ── MCP host

extension content context ── message bridge ── privileged MCP context
```

### WebSocketTransport

WebSocket is equally straightforward as a JSON-RPC-preserving binding.

Kotlin already ships WebSocket support alongside the standard transports, explicitly describing it as full-duplex and low-latency.

The natural framing is:

```text
one WebSocket text message
        =
one UTF-8 JSON-RPC document
```

That avoids introducing an unnecessary newline parser because WebSocket already provides message boundaries.

The binding must define:

```text
connection establishment
authentication
maximum message size
request multiplexing
cancellation semantics
connection closure
reconnection behavior
```

as required by the custom-transport section of the MCP specification.

A single WebSocket can multiplex many independent MCP requests. Request association remains internal to the binding by reading the JSON-RPC IDs; application-level MCP code need not know anything about the socket.

This is therefore **not speculative**: Kotlin already demonstrates it, and the other SDKs' transport seams are sufficient to implement equivalents.

### “cpanweb” appears to mean Cap'n Web

The closest relevant technology to the term in the question is **Cap'n Web**, Cloudflare's JavaScript-native object-capability RPC system.

Cap'n Web is particularly interesting here because it independently has the same transport-pluggability instinct: it works over HTTP, WebSocket, and `postMessage()` and allows additional transports.

But Cap'n Web is **not JSON-RPC**.

Its protocol uses its own JSON-based expression/array representation, is fully bidirectional, maintains import/export capability tables, and specifies a stream of discrete Cap'n Web RPC messages. WebSocket or `MessagePort` provides the message framing, while HTTP uses newline-separated Cap'n Web protocol messages.

Therefore two integrations must be distinguished.

#### Cap'n Web as an outer carrier

This can fit the proposed first step:

```text
MCP JSON-RPC document
       │
       ▼
Cap'n Web method:
    sendMcp(jsonText)
       │
       ▼
Cap'n Web transport
    WebSocket/postMessage/HTTP
       │
       ▼
sendMcp(jsonText)
       │
       ▼
MCP JSON-RPC dispatcher
```

The JSON-RPC MCP message remains intact. Cap'n Web merely transports the string or bytes.

This is conceptually compatible with the pluggable-binding idea, although it adds two layers of RPC framing and may not be worth the overhead unless Cap'n Web is already the application's communication fabric.

#### MCP mapped natively onto Cap'n Web RPC

For example:

```text
MCP tools/list
      ↓ translated to
capnwebApi.listTools()

MCP tools/call
      ↓ translated to
capnwebApi.callTool(...)
```

is different.

Here MCP JSON-RPC has disappeared, and Cap'n Web's native RPC protocol has become the actual representation. Under the current July 2026 MCP specification, that should **not** be presented merely as a custom MCP transport because custom transports must preserve JSON-RPC.

That kind of semantic mapping is much closer to the broader version of SEP-2598 and would require reopening the question of alternate representations.

This is precisely why separating the two projects is valuable.

### gRPC and other RPC frameworks

The same distinction applies to gRPC.

A JSON-RPC-preserving gRPC carrier can be designed as something like:

```protobuf
message McpMessage {
  bytes json_rpc_utf8 = 1;
}

service McpTransport {
  rpc Exchange(McpMessage) returns (stream McpMessage);
}
```

Then:

```text
JSON-RPC request
      ↓
protobuf envelope containing exact JSON bytes
      ↓
HTTP/2 / gRPC
      ↓
protobuf envelope
      ↓
same JSON-RPC messages
```

The RPC framework supplies:

```text
connection management
TLS
service discovery
load balancing
HTTP/2 multiplexing
backpressure
stream lifecycle
deadlines
```

while MCP remains responsible for:

```text
JSON-RPC message shape
MCP methods
MCP metadata
MCP results/errors
MCP notifications
```

That is a strong use case for the proposed binding SPI.

There is a subtle standards point here. The current specification clearly permits custom communication channels while requiring the JSON-RPC message representation to be preserved. An opaque RPC envelope containing the exact UTF-8 JSON-RPC document is therefore much more defensible than translating each JSON-RPC field into a native Protobuf service model; a future binding specification should make this encapsulation case explicit so implementors do not have to infer where “envelope” ends and “message format” begins.

By contrast, this:

```protobuf
rpc ListTools(ListToolsRequest) returns (ListToolsResponse);
rpc CallTool(CallToolRequest) returns (CallToolResponse);
```

with no JSON-RPC document transported is the kind of native gRPC mapping that generated the SEP-2598 review debate about request IDs and unsupported MCP features.

It may be useful, but it is a **different protocol representation**, not merely a replaceable binding under today's specification.

### The general rule

A very useful line can therefore be drawn:

| Mechanism | First-step pluggable transport? | Why |
|---|---|---|
| WebSocket carrying JSON-RPC text | **Yes** | Changes framing/channel only |
| MessagePort carrying JSON-RPC text | **Yes** | Changes delivery mechanism only |
| TCP/Unix socket carrying newline JSON-RPC | **Yes** | Explicitly encouraged by current spec |
| Named pipe carrying stdio framing | **Yes** | Reliable byte-stream binding |
| gRPC stream carrying opaque JSON-RPC documents | **Yes, with binding clarification advisable** | RPC framework is outer carrier |
| NATS/AMQP request-reply carrying JSON-RPC documents | **Potentially yes** | Needs well-defined exchange/cancellation/ordering rules |
| Cap'n Web call carrying an opaque MCP JSON document | **Yes in principle** | Cap'n Web is carrier, MCP remains JSON-RPC |
| Native Cap'n Web method mapping of MCP | **No, not under current custom-transport rule** | Replaces JSON-RPC representation |
| Native typed gRPC MCP service | **No, not as merely a custom transport today** | Transcodes MCP away from JSON-RPC |
| CBOR/Protobuf representation of MCP messages | **No under current spec** | Exactly the requirement SEP-2598 proposed changing |

That boundary is, in my view, the most important design simplification available now.

## Adoption path and recommendation

The strongest path forward is **not** a broad SEP saying “anything may be an MCP transport.” The current specification already says custom transports are possible. What is needed is a much narrower cross-SDK contract that makes the existing permission usable.

### Define an SDK Binding SPI rather than a new protocol transport

The proposal should establish approximately the following normative expectations:

**An MCP SDK should provide a public extension point through which a third-party binding can deliver and receive complete MCP JSON-RPC messages without implementing or forking MCP protocol dispatch.**

The binding extension point should:

```text
MUST accept/deliver complete MCP JSON-RPC messages

MUST preserve per-request protocol metadata in those messages

MUST support the MCP request/response message patterns required by
the protocol versions it advertises

MUST define cancellation and termination behavior

MUST permit long-lived request response streams such as
subscriptions/listen

MUST NOT require connection identity to represent MCP session state

MUST NOT expose HTTP- or stdio-specific concepts in its generic contract

SHOULD hide request correlation inside the transport/exchange
implementation rather than expose a separate request-id parameter

MAY expose transport-specific/native context through a separate,
opaque extension mechanism

MAY pool or multiplex physical connections

MAY be connection-oriented, request-oriented, or in-process
```

These requirements are derived directly from the current binding and statelessness rules rather than inventing new protocol semantics.

### Do not require a single identical API across languages

The SDK findings strongly argue against prescribing:

```text
interface Transport {
    start()
    send()
    onMessage
    close()
}
```

everywhere.

Instead, define semantic roles:

```text
                 MCP protocol core
                        │
                 Exchange abstraction
                        │
        ┌───────────────┴────────────────┐
        │                                │
 Client binding/dialer          Server binding/listener
        │                                │
   Transport-specific implementation
```

Each SDK can express this idiomatically:

```text
TypeScript       Promise / AsyncIterable
Python           async context manager / streams
Java             interfaces / publishers
Kotlin           suspend functions / Flow / Channel
C#               Task / IAsyncEnumerable
Go               Transport → Connection
PHP              interface + PSR-oriented adapters
Ruby             duck-typed object / Enumerator
Rust             traits / Stream
Swift            protocol / AsyncThrowingStream
```

Cross-SDK interoperability depends on the **wire behavior**, not on matching method names.

### Use PostMessage as the first prototype

A TypeScript `MessagePortTransport` would be an unusually effective prototype because it proves all of the architectural claims while remaining small:

```text
@modelcontextprotocol/core
        │
        ├── standard stdio
        ├── standard Streamable HTTP
        │
        └── external @mcp/transport-messageport
                       │
                       └── MessagePort / Worker / iframe
```

It would exercise:

```text
third-party package boundaries
JSON-RPC message validation
transport injection
bidirectional delivery
parallel requests
long-lived subscriptions
cancellation
closure
browser security
no HTTP assumptions
no process assumptions
```

and unlike a native gRPC implementation, it would not reopen the alternate-serialization debate.

Kotlin's existing WebSocket implementation can simultaneously function as evidence that the same conceptual extension works outside TypeScript.

### Use Go and Rust as reference SPI implementations

Go and Rust are useful second reference points because both already explicitly treat transport as an extension seam.

Go's SDK says its `jsonrpc` package exists for custom transports and cleanly separates `Transport` from the resulting connection.

Rust says directly that any `Transport` implementation may be passed to `.serve(..)`.

A cross-SDK proposal built around **TypeScript + Go + Rust**, rather than merely one SDK, would demonstrate that the contract survives:

```text
dynamic typed event-driven runtime
garbage-collected systems language
ownership/trait-based systems language
```

before asking every official SDK to conform.

### Then align the other SDKs incrementally

The adoption work is primarily convergence:

| SDK | Recommended first change |
|---|---|
| TypeScript | Publicly document/stabilize the transport/binding SPI that bridges normal connections and modern single-exchange serving. |
| Python | Promote the existing client `Transport` concept and add an equally clean modern server-binding entry point. |
| Java | Document existing `McpClientTransport`/server provider APIs as the official third-party binding SPI and run common conformance vectors. |
| Kotlin | Treat existing WebSocket/Channel abstractions as the reference for custom transports and align semantics with 2026 stateless MCP. |
| C# | Formalize `IClientTransport` plus the corresponding server transport semantics as the extension surface. |
| Go | Largely no architectural change; document as a reference model. |
| PHP | Promote existing `TransportInterface` as third-party SPI and remove legacy session assumptions from the modern binding profile. |
| Ruby | Introduce a server-side binding/exchange contract so custom servers do not have to embed the MCP server inside a Rack/stdio-style transport. |
| Rust | Largely no architectural change; ensure executor/Wasm constraints do not unnecessarily block browser transports. |
| Swift | Largely no architectural change; document conformance requirements for custom `Transport` implementations. |

Those conclusions follow the existing SDK interfaces rather than requiring ten independent redesigns.

### The important architectural boundary

The resulting architecture would look like this:

```text
                         MCP application API
                                │
                    tools / resources / prompts
                                │
                        MCP protocol engine
                                │
                  MCP JSON-RPC message objects
                                │
                     Public Binding / Transport SPI
                                │
       ┌─────────────┬──────────┼───────────┬──────────────┐
       │             │          │           │              │
     stdio     Streamable     WebSocket   MessagePort   RPC carrier
                 HTTP                                    │
                                                        ├─ gRPC
                                                        ├─ Cap'n Web
                                                        ├─ custom IPC
                                                        └─ message bus
```

With a critical rule at the bottom:

```text
                    ╔════════════════════════╗
                    ║ JSON-RPC stays intact ║
                    ╚════════════════════════╝
```

That boundary gives MCP transport pluggability **without making every alternate network technology a new MCP protocol**.

### Bottom line

The answer to the central question is therefore **yes, with one design correction**:

**Expose a replaceable MCP binding/transport seam, but standardize it around independent JSON-RPC exchanges rather than around Streamable HTTP or around a generic persistent socket.**

That approach is feasible across all ten SDKs because most already contain the necessary abstraction. Go, Java, C#, PHP, Rust, Swift, Kotlin, and Python provide especially strong existing foundations; TypeScript has the right injection points but needs its modern per-request model reflected in the public extension story; Ruby requires the most server-side decoupling.

**WebSocket and PostMessage/MessagePort are natural conforming examples.** Kotlin's existing WebSocket support already demonstrates the former, while the latter is particularly well suited to browser, worker, iframe, Electron, and extension environments.

**An RPC framework can also sit underneath this seam**, provided it acts as a carrier for the existing MCP JSON-RPC document. A gRPC stream carrying opaque UTF-8 JSON-RPC payloads fits the proposed first step far better than a typed Protobuf re-expression of every MCP operation.

**Cap'n Web can similarly wrap MCP JSON-RPC, and it is especially interesting because it already supports HTTP, WebSocket, and `postMessage()`. But mapping MCP directly onto Cap'n Web's native object-capability calls would cross the line from “pluggable binding” into “alternate MCP representation,” because Cap'n Web has its own RPC protocol rather than JSON-RPC.**

Most importantly, the July 28, 2026 stateless MCP redesign removed much of the connection/session coupling that made SEP-2598 difficult to reason about in April. Requests now carry their own protocol context, long-lived streams belong to requests rather than sessions, and transport connections are explicitly not protocol state.

So the most viable successor to SEP-2598 is not:

> “Allow arbitrary alternative encodings and require every Tier-1 SDK to implement a universal transport abstraction.”

It is:

> **“Define an SDK-level Binding SPI for carrying unchanged MCP JSON-RPC over custom communication mechanisms; make exchange scoping, cancellation, streaming, and per-request metadata the common semantics; let each SDK expose that SPI idiomatically; and validate third-party bindings with centralized conformance vectors.”**

That is narrow enough to implement now, compatible with the current MCP specification, substantially already implemented across the official SDK family, and sufficient to unlock `PostMessageTransport`, WebSocket transports, JSON-RPC-over-gRPC, local IPC, and other RPC/framework carriers without waiting for MCP to standardize each one individually.