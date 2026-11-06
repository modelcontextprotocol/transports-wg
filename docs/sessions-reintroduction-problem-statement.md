
# Problem Statement: Reintroducing "Sessions" (Thread / Conversation IDs)

## Background

MCP historically included sessions: an `Mcp-Session-Id` header on Streamable
HTTP, and an implicit session tied to process lifetime on stdio. In practice the
concept blurred two distinct jobs: transport-level bookkeeping (protocol
version, capability negotiation) and application-level state (a conversation
thread, stateful tool operations). This ambiguity caused problems: wildly
inconsistent lifecycles (per tool call vs. per conversation vs. global),
divergent behavior across transports, and application state coupled to the
connection, which breaks under load balancing and rolling upgrades.

After SEP-2575 (stateless by default) and SEP-2322 (multi round-trip requests)
removed the transport-level need for sessions, the core maintainers
[voted][vote-2536] to remove sessions from the protocol entirely (see the
[decision doc][decision-doc]). The recommended replacement is the **explicit
state handle** pattern: servers return an opaque ID from a tool call
(`create_basket() -> basket_id`) and clients pass it back as a tool argument in
later calls.

Since then, the community has pushed back with scenarios where an identifier
that spans a sequence of requests still seems necessary (see [PR
#2822][pr-2822]). This document frames what we would need to decide to
reintroduce such a concept, likely first as an experimental extension.

[vote-2536]:
    https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2536
[decision-doc]: ./sessions-vs-sessionless-decision.md
[pr-2822]:
    https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2822

## Open Questions

1. **Naming.** "Session" is hopelessly overloaded across networking layers.
   Candidates: Thread ID, Conversation ID, Context ID. What does the name imply
   about semantics?
2. **Who generates the ID?** Client-generated IDs exist on the very first
   request (which matters for routing) and survive client restarts.
   Server-generated IDs let the server control format and validity. Do we pick
   one, or allow both?
3. **Lifecycle.** Is creation explicit (a dedicated request) or implicit (first
   use)? When does it end? How are abandoned threads expired and cleaned up? Is
   the ID ephemeral (dies with the conversation) or durable (a long-lived
   selector that outlives every connection)? Community use cases want both,
   which suggests lifecycle must be spelled out rather than implied.
4. **Scope of impact.** Does the ID only provide execution context to
   `tools/call`? Or may it change the _results_ of `tools/list`,
   `resources/list`, and `prompts/list`? The latter is where prior
   implementations caused caching and synchronization pain, and it reintroduces
   server-side mutable state per thread.
5. **Concurrency.** What happens when parallel requests carry the same ID? When
   an agent delegates to a sub-agent, does the sub-agent get a new ID, a fork of
   the parent's, or the same ID (risking the sub-agent polluting the parent's
   state)?
6. **Optionality.** Is the identifier required of every client, or an opt-in
   capability? If opt-in, what does a server that needs it do when a client
   doesn't send it: reject the request, degrade to per-connection scoping, or
   mint an ID of its own? And where does the server even declare the
   requirement, now that stateless MCP has no initialization handshake to
   negotiate in?

## Use Case Categories

### 1. Infrastructure routing and instance affinity

**TL;DR:** Intermediaries need a stable key, present on every request including
the first, to route related requests to the same backend instance.

_Mentioned by @LucaButBoring (AWS) ([comment][luca-routing]), @bittola
(Microsoft) ([comment][bittola-routing]), and @Agent-Hellboy
([comment][hellboy-routing])._

#### Example

Bedrock AgentCore runs each customer's MCP server in an isolated microVM and
uses `Mcp-Session-Id` as the key that maps requests to a running VM:

```
initialize                        -> cold start: provision microVM A, return ID "vm-abc"
tools/call: query(...)  [vm-abc]  -> routed to warm microVM A
tools/call: query(...)  [no ID]   -> nothing to route on: cold start microVM B
```

Every unkeyed request pays a cold-start latency penalty. The same failure
appears with process-local state: a form-workflow server saw parallel first
calls from a host land on different instances, each instance minted its own
workflow ID, and the conversation ended up with state split across instances. A
stable identifier present on the _first_ request is what prevents this.

#### Potential Alternatives

##### Option A: Non-MCP fix — the client sets a per-conversation header

The host stamps every HTTP request with a header of its own choosing
(AgentCore's `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` is this pattern) and
infrastructure routes on it. Because the client mints the value, it exists on
the very first request — exactly what placement needs:

```
initialize               [X-Conv-Id: conv-7]  -> cold start: provision microVM A
tools/call: query(...)   [X-Conv-Id: conv-7]  -> routed to warm microVM A
tools/call: submit(...)  [X-Conv-Id: conv-7]  -> routed to warm microVM A
```

The limits: nothing standardizes the header name, so every host/gateway pair
needs bespoke configuration; off-the-shelf host applications won't set or
forward nonstandard headers; and it only works when one party owns both ends of
the wire, which MCP customers generally don't.

##### Option B: An initialization tool that mints a state handle

The server exposes a tool the client must call first (`init_conversation() ->
handle`); the handle is passed on every subsequent call and, via
[SEP-2243][sep-2243]'s `x-mcp-header` annotation, mirrored into an
`Mcp-Param-{name}` header a gateway can route on without parsing bodies:

```
initialize                        [no key]                  -> cold start: microVM A
tools/call: init_conversation()   [no key]                  -> handle "h-42"
tools/call: query(handle="h-42")  [Mcp-Param-Handle: h-42]  -> routed to microVM A
```

The limits: the init call itself — and any parallel first calls a host fires at
startup — still arrives unkeyed, which is exactly when placement is decided; the
mirroring applies to `tools/call` only, so `tools/list` and every other method
still arrive unkeyed; and the handle travels through the model between calls,
inheriting the relay-reliability concerns of category 4. Standardizing the tool
and parameter name would spare gateways per-server configuration, but at that
point the design is a session in all but name, relayed by the model instead of
carried by the protocol.

[sep-2243]: https://modelcontextprotocol.io/seps/2243-http-standardization
[luca-routing]:
    https://github.com/modelcontextprotocol/transports-wg/issues/36#issuecomment-4753929263
[bittola-routing]:
    https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2822#issuecomment-4625554258
[hellboy-routing]:
    https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2822#issuecomment-4605717954

### 2. Observability and audit correlation

**TL;DR:** There is no standard field to correlate the requests of one logical
unit of work in logs and audit trails; every deployment invents its own.

_Mentioned by @javapro108 ([comment][javapro108-observability])._

#### Example

A host handling one user task fans out across servers and clients; no
per-request field says the resulting calls belong together:

```
User task: "refund order 7"
  -> MCP server A: tools/call lookup_order(...)    [no correlation field]
  -> MCP server B: tools/call issue_refund(...)    [no correlation field]

Server A log: 14:02:11 tools/call lookup_order
Server B log: 14:02:13 tools/call issue_refund
```

An auditor reconstructing what this task did across the two servers' logs has
no standard field to join on, so every deployment invents a custom header or
argument convention ad hoc.

#### Potential Alternatives

##### Option A: Non-MCP fix — existing telemetry standards

The observability stack already has most of the pieces. The OpenTelemetry
GenAI semantic conventions reserve the exact attribute this category wants:
[`gen_ai.conversation.id`][otel-genai-attrs], "the unique identifier for a
conversation (session, thread)." And MCP has a documented carrier for OTel
context: [SEP-414][sep-414] reserves `traceparent`, `tracestate`, and `baggage`
in `_meta`, on every transport including stdio. Assembled, a host could carry a
conversation ID in W3C Baggage via `_meta`, and servers could record it as
`gen_ai.conversation.id`:

```
tools/call: lookup_order(...)
  _meta: {"baggage": "gen_ai.conversation.id=task-42"}   -> server A logs task-42
tools/call: issue_refund(...)
  _meta: {"baggage": "gen_ai.conversation.id=task-42"}   -> server B logs task-42
```

##### Option B: Log state handles as correlation keys

Where a workflow already flows through an explicit handle, servers could treat
the handle as the log key:

```
tools/call: open_case(order=7)       -> case_id "rc-19"   (logged: rc-19)
tools/call: issue_refund("rc-19")                         (logged: rc-19)
tools/list                           -> takes no arguments; nothing to log
```

[javapro108-observability]:
    https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2822#issuecomment-4643682232
[otel-genai-attrs]:
    https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md
[sep-414]: https://modelcontextprotocol.io/seps/414-request-meta

### 3. Progressive discovery of tools via other tool calls

**TL;DR:** A tool call mutates which tools subsequent `tools/list` requests
return, and that mutated set must be scoped per conversation, not per server.

_Mentioned by @javapro108 ([comment][javapro108-discovery]), with follow-up
analysis from @n0mad-ai ([comment][n0mad-discovery])._

#### Example

An ERP server covering sales, purchasing, finance, and HR has 100+ tools with
complex schemas; loading them all bloats the model's context. Instead, the
server exposes one meta-tool that swaps a small active set in and out as user
intent emerges:

```
User: "Sort out the supplier situation"
tools/list                                       -> [manageTools]
tools/call: manageTools(activate=["find_supplier", "list_purchase_orders"])
tools/list                                       -> [manageTools, find_supplier,
                                                     list_purchase_orders]
```

The scoping problem: two users on the same server, one working in purchasing and
one in finance, must receive different `tools/list` responses simultaneously.
Since `tools/list` carries no arguments, the per-conversation identifier is what
selects which active set a given request sees.

#### Potential Alternatives

##### Option A: Skills-style progressive disclosure

[Agent skills][agent-skills] attack the motivation rather than the mechanism:
instead of a mutating tool set, capability documentation is disclosed
progressively as intent emerges, and "which capability is active" lives in the
model's context; which the host already scopes per conversation naturally. The
[Skills over MCP extension][skills-over-mcp] (experimental) standardizes the
delivery: skills are served as MCP resources (`skill://` URIs) that hosts load
on demand:

```
User: "Sort out the supplier situation"
tools/list                                   -> [erp_query]   (static, small)
resources/read: skill://purchasing/SKILL.md  -> supplier workflow instructions
tools/call: erp_query(...)                   -> guided by the loaded skill
```

The extension could be expanded to include tools as well as resources.


[agent-skills]: https://agentskills.io
[skills-over-mcp]:
    https://github.com/modelcontextprotocol/experimental-ext-skills/blob/main/docs/sep-draft-skills-extension.md
[javapro108-discovery]:
    https://github.com/modelcontextprotocol/transports-wg/issues/36#issuecomment-4714094323
[n0mad-discovery]:
    https://github.com/modelcontextprotocol/transports-wg/issues/36#issuecomment-4725581225

### 4. Multi-step stateful workflows

**TL;DR:** Tool sequences accumulate state across calls, ranging from ephemeral
drafts to durable stores that outlive every connection.

_Mentioned by @n0mad-ai (maintainer of bastra-recall)
([comment][n0mad-workflows]) and @watnab ([comment][watnab-workflows])._

#### Example

A local-first persistent-memory server accumulates durable state (facts,
decisions, preferences) over months, across client restarts and redeploys:

```
# Weeks ago, in a different process:
tools/call: save("decision: project X uses Postgres 16")

# Today, a fresh client with an empty context:
tools/call: recall("project X database")   -> "decision: project X uses Postgres 16"
```

The identifier's only job is to select _which durable namespace_ a call touches;
the state itself lives behind the tool boundary, so the server stays
protocol-stateless. The same shape covers ephemeral variants, such as a server
that keeps multi-step workflow state keyed by an identifier established on an
earlier call.

#### Potential Alternatives

##### Option A: State handles

This is the category the explicit-handle pattern was designed for, and it works
in principle: an earlier call returns an opaque handle (`namespace_id`,
`workflow_id`) that the client passes back as a tool argument in later calls.
Applied to the memory server above:

```
# Weeks ago, in a different process:
tools/call: create_namespace("project-x")   -> ns_id "ns-71"
tools/call: save("ns-71", "decision: project X uses Postgres 16")

# Today, a fresh client with an empty context:
tools/call: recall("ns-71", "project X database")   -> works, if the client
                                                       still has "ns-71"
```

Within one conversation the model's context carries the handle; across
conversations it must be persisted outside the protocol — host configuration,
user memory, or a discovery call like `list_namespaces()`.

[n0mad-workflows]:
    https://github.com/modelcontextprotocol/transports-wg/issues/36#issuecomment-4682882969
[watnab-workflows]:
    https://github.com/modelcontextprotocol/transports-wg/issues/36#issuecomment-4912952888

### 5. Cross-protocol interoperability

**TL;DR:** An identifier minted by another protocol must be accepted and
carried through MCP requests verbatim; MCP has no standard carrier for it.

_Mentioned by @javapro108 ([comment][javapro108-interop])._

#### Example

MCP and A2A are increasingly deployed together in agentic pipelines. A2A
standardizes a workflow identifier
([`contextId`, spec §3.4.1][a2a-spec-341]) that groups related tasks and
messages; MCP has no equivalent, so the identifier dies at the protocol
boundary:

```
A2A task (contextId: ctx-42)
  -> agent calls MCP server A: tools/call lookup_order(...)   [ctx-42 has nowhere to go]
  -> agent calls MCP server B: tools/call issue_refund(...)   [ctx-42 has nowhere to go]
```

Unlike category 2, this cannot be fixed by an internal convention: the ID
originates outside MCP, often outside the deployment's organization, and A2A
attaches semantics beyond correlation — agents MAY use `contextId` to maintain
internal state, conversational history, or LLM context across interactions. A
foreign ID can therefore arrive carrying state-scoping expectations, not just a
label.

#### Potential Alternatives

##### Option A: State Handles 

The state-handle pattern stretches to cover the boundary in both directions.
Where the MCP server wraps the foreign agent, the handle simply _is_ the
foreign context:

```
tools/call: initialize_agent("billing")              -> session_id "ctx-42"
tools/call: send_message("ctx-42", "refund order 7") -> delivered in A2A context ctx-42
```

[javapro108-interop]:
    https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2822#issuecomment-4643682232
[a2a-spec-341]:
    https://a2a-protocol.org/latest/specification/#341-context-identifier-semantics
