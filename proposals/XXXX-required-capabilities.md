# SEP-XXXX: Required Capabilities for Tools

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-04-11
- **Author(s)**: Gabriel Zimmerman (@gjz22)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/transports-wg/pull/{NUMBER}

## Abstract

[SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2575)
introduces per-request client capabilities, where the client declares
its supported capabilities in the `_meta` field of each request rather
than negotiating them once during initialization.  However, that
proposal does not address a coordination problem between requests: some
request types (notably `tools/list`) need to make decisions based on
what capabilities will be available during other request types (notably
`tools/call`).

This proposal specifies that servers declare the capabilities each tool
requires by annotating the tool with a
`io.modelcontextprotocol/requiredCapabilities` field in the tool's
`_meta`.  Clients match their own capabilities against these
annotations and decide how to handle tools whose requirements they do
not meet -- filtering them out, presenting them as unavailable, or
surfacing a clear error if they are invoked.

The annotation marks *hard* requirements.  A tool that can instead
operate in **hybrid mode** -- using a capability when the `tools/call`
request declares it and falling back to another mechanism when it does
not -- works for every client and needs no annotation at all.

## Motivation

### The Cross-Request Capability Problem

Per-request capabilities create an ambiguity when one request's behavior
depends on the capabilities available in a different request.  The most
concrete example is the relationship between `tools/list` and
`tools/call`.

Consider a server that provides a tool called `deploy_to_production`.
This tool uses elicitation to prompt the user to log in before
proceeding:

```json5
// tools/call request
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "deploy_to_production",
    "arguments": { "service": "api-gateway", "version": "2.1.0" },
    "_meta": {
      "io.modelcontextprotocol/clientCapabilities": {
        "elicitation": {}
      }
    }
  }
}
```

A tool that uses a capability this way can be designed in one of two
ways:

1. **Hybrid mode**: the tool uses the capability when it is declared
   on the `tools/call` request and falls back to another mechanism
   when it is not.  For example, `deploy_to_production` could fall
   back to returning a login URL in its tool result and asking the
   caller to retry once authenticated, instead of prompting
   interactively via elicitation.  This generalizes to any capability:
   a tool that runs as a long-lived task when the client supports the
   tasks extension could fall back to executing synchronously.
   Hybrid tools work for every
   client, and per-request capabilities (SEP-2575) already give them
   everything they need to adapt at call time.

2. **Hard requirement**: the tool has no reasonable fallback.  If
   `deploy_to_production` has no out-of-band login flow, then without
   elicitation it simply cannot authenticate the user.

Hard requirements are the case this proposal addresses.  What should
happen when a client that does not support elicitation calls
`tools/list`?  The hard-requirement version of `deploy_to_production`
cannot function for that client -- it would fail at the login step.
But under SEP-2575 alone, nothing in the `tools/list` exchange tells
either party about this mismatch:

```json5
// tools/list request -- what capabilities will tools/call have?
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/clientCapabilities": {
        // The client declares capabilities here, but these describe
        // tools/list itself -- not what tools/call will have.
      }
    }
  }
}
```

Without some form of cross-request coordination, the server does not
have enough information to know whether a tool it returns will actually
work for the client, and the client does not have the information to
know whether it has the capabilities needed to execute the tools it
receives.

### How the Problem Surfaces

When the mismatch goes undetected until `tools/call` time, it manifests
in two damaging ways:

1. **Errors propagate to users who know nothing about MCP.**  When the
   model invokes a tool whose required capability the client lacks, the
   server returns an error such as `Tool 'deploy_to_production'
   requires elicitation capability`.  To the end user -- who has never
   heard of MCP, capabilities, or elicitation -- this is meaningless
   jargon surfacing in the middle of their conversation.  They cannot
   act on it, and cannot even tell whether they did something wrong,
   the application is broken, or the tool is broken.

2. **The model plans multi-step work toward a tool it cannot use, wasting tokens.**
   A model plans around the tool list it is given.
   Consider an incident-response flow where the model plans two steps:
   first fetch the details of an incident to determine what needs to
   be queried, then run a `long_running_query_job` tool -- a
   task-based tool (see
   [Extension Capabilities: Tasks](#extension-capabilities-tasks)) --
   to execute that query.  If the client does not support the tasks
   extension, the second tool can never work, but nothing in the tool
   list says so.  The model spends turns and tokens completing the
   first step, then hits the wall at the second.  At best, it
   recognizes the limitation and responds that it retrieved the
   incident details but has no ability to run the query.  If instead
   the call is attempted and the error is thrown, the response is
   unpredictable: the model may retry, surface the raw error to the
   user (failure mode 1), or confabulate around the failure.  Either
   way, the work invested toward an unusable goal is wasted.

Upfront filtering prevents both: a tool the client cannot support
never enters the model's context, so the model plans only with tools
that can actually run, and no capability error ever reaches the user.

### Capability-Aware Tool Adaptation

The fix is to filter: a tool that hard-requires a capability the
client does not support should never be blindly offered to the model.
The central design decision in this SEP is *where* that filtering
happens.  In **server-side filtering**, the client tells the server on
`tools/list` what capabilities its subsequent requests (such as
`tools/call`) will have, and the server returns a tool list tailored
to them.  In **client-side filtering** (this proposal), the server
annotates each tool with its requirements, returns the same tool list
to everyone, and the client filters locally.  Each has real
advantages.

#### Advantages of Server-Side Filtering

- **Arbitrarily complex filtering logic.**  The server can apply logic
  that static annotations cannot express: capabilities that interact
  (a tool that can use either of two capabilities and needs at least
  one), decisions
  that depend on runtime context, or requirements that vary by
  argument.  A declarative annotation format has to anticipate every
  such pattern; server code does not.
- **Centralization.**  The adaptation logic is written once, on the
  server, instead of being reimplemented (with inevitable
  inconsistencies) in every client.  Servers also already filter the
  tool list based on the authenticated user (which tools this user is
  authorized to see), so server-side capability filtering keeps *all*
  filtering in a single place rather than splitting it between server
  and client.

#### Advantages of Client-Side Filtering

- **Caching.**  The `tools/list` response is identical for every
  client, so a cached tool list does not need to incorporate the
  client's capability set into its cache key.  This matters for
  clients that cache tool lists across sessions and for servers that
  want to serve `tools/list` from static content, but it is
  particularly important for simplifying MCP proxy servers: a proxy
  can cache one tool list and serve it to all downstream clients,
  instead of maintaining a separate cached variant per capability set
  and matching each downstream client to the right one.  There is
  active interest in caching `tools/list` results -- see
  [SEP-2549: TTL for List Results](https://modelcontextprotocol.io/seps/2549-TTL-for-list-results)
  -- and capability-independent responses keep that caching simple.
  With server-side filtering, every distinct capability set is a
  distinct cacheable variant, and a client whose capabilities change
  must invalidate and re-fetch.
- **Flexibility in how the client responds.**  The client is not
  limited to hiding a tool.  It can present it as disabled, explain
  which capability would unlock it, or even keep the tool available
  and error out on invocation with a message telling the user that the
  client doesn't have that capability.  Server-side filtering removes
  the tool before the client ever sees it, foreclosing all of these
  options.
- **Transparency.**  Clients, users, and developers see the full set
  of tools the server provides along with what each one requires.
  This makes it discoverable what implementing an additional
  capability (e.g., elicitation) would unlock, rather than silently
  hiding functionality.
- **No cross-request capability declarations.**  Capabilities remain
  truly scoped to individual requests, as SEP-2575 intends.  For
  server-side filtering to work, the `tools/list` request must somehow
  carry the capabilities of *other* requests -- for example by
  explicitly declaring the capabilities of each related method on
  every request (see Alternative 1) -- which adds request complexity
  and coordination rules that per-tool annotations avoid entirely.

Client-side filtering does carry a structural downside: filtering now
happens in two places.  Servers commonly already filter the tool list
server-side based on the authenticated user (which tools this
particular user is permitted to see), and this proposal adds a second,
client-side filtering step based on capabilities.  With server-side
capability filtering, both concerns would live in one place, on the
server.  This proposal accepts the split because the two filters answer
different questions -- *authorization* (may this user use the tool?) is
inherently server knowledge, while *capability* (can this client run
the tool?) is inherently client knowledge -- but implementers should be
aware that the complete effective tool set is the intersection of both.

#### Why This SEP Chooses Client-Side

This proposal adopts client-side filtering as the primary mechanism
because the caching and flexibility benefits accrue to every
deployment, while the extra expressiveness of server-side filtering is
needed only by servers with unusually dynamic adaptation logic.  The
call-time validation requirement ensures correctness even when a
client's local handling is imperfect, and a server with needs that
static annotations cannot express can still adapt its behavior inside
the tool implementation itself -- hybrid mode being the common case.

## Specification

### The `requiredCapabilities` Meta Field

A server **MAY** declare the client capabilities a tool depends on by
including a `io.modelcontextprotocol/requiredCapabilities` field in the
tool's `_meta`.  The value has the same shape as the
`ClientCapabilities` object: each key names a required capability, and
nested objects name required sub-capabilities.

```json5
// tools/list response with capability annotations
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "deploy_to_production",
        "description": "Deploy a service to production (requires login)",
        "inputSchema": { /* ... */ },
        "_meta": {
          "io.modelcontextprotocol/requiredCapabilities": {
            "elicitation": {}
          }
        }
      },
      {
        "name": "analyze_dataset",
        "description": "Analyze a dataset, using sub-agents with tool use",
        "inputSchema": { /* ... */ },
        "_meta": {
          "io.modelcontextprotocol/requiredCapabilities": {
            "sampling": {
              "tools": {}
            }
          }
        }
      },
      {
        "name": "get_weather",
        "description": "Get current weather",
        "inputSchema": { /* ... */ }
        // No requiredCapabilities -- works for all clients
      }
    ]
  }
}
```

The absence of the annotation means the tool has no capability
requirements and works for all clients.

### Client Matching Behavior

A client that understands this annotation **SHOULD** match its own
capabilities against each tool's `requiredCapabilities`.  A tool's
requirements are satisfied when every capability key in the annotation
is present in the client's capabilities, applied recursively to nested
sub-capability objects.  For example, a requirement of
`{ "sampling": { "tools": {} } }` is satisfied by a client capability
of `{ "sampling": { "tools": {} } }` but not by `{ "sampling": {} }`.

When a tool's requirements are not satisfied, the client decides how to
respond.  Reasonable options include:

- **Filter**: omit the tool from the set offered to the model.
- **Disable**: surface the tool in the UI as unavailable, along with
  the capabilities that would unlock it.
- **Allow with error**: keep the tool available and, if it is invoked,
  fail with a message telling the user that the client lacks the
  required capability.

This choice is deliberately left to the client, which knows its own UX
best.

### Hybrid Tools Need No Annotation

The annotation marks hard requirements only.  A hybrid-mode tool --
one that uses a capability when the `tools/call` request declares it
and falls back to another mechanism when it does not -- **SHOULD NOT**
declare that capability in `requiredCapabilities`.  Such a tool works
for every client; annotating it would cause clients to unnecessarily
filter or disable it.

### Extension Capabilities: Tasks

Because `requiredCapabilities` has the same shape as
`ClientCapabilities`, it covers extension capabilities with no
additional mechanism: extension requirements appear under the
`extensions` key, using the extension's identifier, exactly as the
client declares them.  Tasks -- now an extension rather than a core
protocol feature -- is the motivating example.  A long-running tool
that can only execute as a task should not be offered to clients that
do not support the tasks extension:

```json5
// tools/list response: a tool that must run as a task
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "long_running_analysis",
        "description": "Analyze a dataset; may take several minutes",
        "inputSchema": { /* ... */ },
        "_meta": {
          "io.modelcontextprotocol/requiredCapabilities": {
            "extensions": {
              "io.modelcontextprotocol/tasks": {}
            }
          }
        }
      }
    ]
  }
}
```

A client that does not support the tasks extension handles this like
any other unmet requirement: filter the tool out, present it as
unavailable, or allow it and error on invocation.

The recursive matching rule applies inside `extensions` as well: if an
extension defines sub-fields in its settings object, a tool can
require them, and requirements can combine core and extension
capabilities.  (The tasks extension currently defines no settings, so
its capability is always the empty object.)  For example, a tool that
runs as a task and elicits user input mid-task would declare:

```json5
"io.modelcontextprotocol/requiredCapabilities": {
  "elicitation": {},
  "extensions": {
    "io.modelcontextprotocol/tasks": {}
  }
}
```

This requirement is satisfied by a client declaring:

```json5
"io.modelcontextprotocol/clientCapabilities": {
  "elicitation": {},
  "extensions": {
    "io.modelcontextprotocol/tasks": {}
  }
}
```

but not by a client that supports tasks without elicitation, or
elicitation without the tasks extension.

### Server Validation at Call Time

Client-side filtering is advisory: a client may not understand the
annotations, or may deliberately allow a tool it cannot fully support.
The core specification already requires that a server **MUST NOT**
rely on capabilities the client has not declared, and that it return a
`MissingRequiredClientCapabilityError` (`-32021`) whose
`data.requiredCapabilities` lists the missing capabilities.  A server
therefore validates the per-request capabilities on each `tools/call`
and fails fast rather than silently misbehaving.  The tool annotation
deliberately shares its name and shape with that error's
`requiredCapabilities` field: the list-time annotation and the
call-time error report the same information.

```json5
// tools/call without required elicitation capability
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "deploy_to_production",
    "arguments": { "service": "api-gateway", "version": "2.1.0" },
    "_meta": {
      "io.modelcontextprotocol/clientCapabilities": {
        // Note: no "elicitation" -- but the tool requires it
      }
    }
  }
}

// Error response: MissingRequiredClientCapabilityError
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32021,
    "message": "Tool 'deploy_to_production' requires elicitation capability (for login)",
    "data": {
      "requiredCapabilities": {
        "elicitation": {}
      }
    }
  }
}
```

For a client that filters based on the annotations, such an error is
also a staleness signal: if the client believed its capabilities
satisfied the tool's requirements, its cached tool list no longer
reflects what the server actually requires.  A filtering client
**SHOULD** treat a `tools/call` failure due to insufficient
capabilities as a signal to re-issue `tools/list` and obtain the
updated annotations.

### Schema

No changes to the base schema are required: `Tool` already carries an
open `_meta` field.  This proposal defines one well-known,
Model Context Protocol-specific meta field on tools:

```typescript
export interface Tool {
  name: string;
  description?: string;
  inputSchema: { /* ... */ };
  _meta?: {
    /**
     * Capabilities the client must support for this tool to
     * function correctly.
     */
    "io.modelcontextprotocol/requiredCapabilities"?: ClientCapabilities;
    // ... other meta fields
  };
}
```

Using a `_meta` field under the `io.modelcontextprotocol/` prefix keeps
the annotation additive and invisible to implementations that predate
this proposal, consistent with how SEP-2575 carries
`clientCapabilities` itself.

## Rationale

Annotating tools with their required capabilities is the smallest
mechanism that solves the cross-request capability problem: the
`tools/list` exchange itself carries everything the client needs to
know about what `tools/call` will require, without either party
assuming that capabilities declared on one request apply to another.

The annotation lives in the tool's `_meta` under the
`io.modelcontextprotocol/` prefix rather than as a new top-level tool
field.  This keeps the proposal purely additive, mirrors how SEP-2575
transports `clientCapabilities`, and allows the mechanism to evolve
without schema churn (see
[Modifications Not Included](#modifications-not-included)).

The main costs, relative to server-side filtering, are that clients
must implement the matching logic and that the server cannot
substitute one tool for another based on client capabilities -- a tool
can only degrade internally via hybrid mode.
[Capability-Aware Tool Adaptation](#capability-aware-tool-adaptation)
discusses why these costs are acceptable.

### Alternatives Considered

The following matrix compares the primary proposal (tool-level
required-capability annotations) with the two alternative coordination
mechanisms across the goals that motivated this SEP.

| Goal | Required Capabilities (Primary) | Alt 1: Related Request Capabilities | Alt 2: No Capability Coordination |
|---|---|---|---|
| **Solves cross-request capability problem** (e.g. `tools/list` reflects what `tools/call` will support) | Yes: client matches its own capabilities against per-tool annotations | Yes, explicitly: the client declares the capabilities of related methods on each request | No: mismatches surface as call-time failures |
| **Filtering** | Yes: client filters locally | Yes: server filters using the related-request capabilities | No |
| **Substitution** (swap one tool for a lower-functionality alternative) | Partial: hybrid-mode tools degrade internally at call time; distinct fallback tools remain visible to all clients (see the `whenCapabilitiesUnavailable` modification under [Modifications Not Included](#modifications-not-included)) | Yes: server can freely substitute based on capabilities and runtime context | No: the client never sees the substitution opportunity |
| **Parameterized adaptation** (decisions based on capability sub-fields) | Limited: client-side matching on nested sub-fields is error-prone | Yes: server has full access to the capability object | No |
| **Tool list cacheable without capability cache key** | Yes: identical response for all clients | No: each declared related-capability set yields a different list | Yes: identical response for all clients |
| **Client chooses how to respond** (hide, disable, allow-and-error) | Yes | No: filtered tools are invisible to the client | No: only call-time failure |
| **Transparency to the client** (client sees all tools the server provides) | Yes, with their requirements | No: filtered tools are invisible to the client | Yes, but without requirement information |
| **Preserves per-request capability scoping** | Yes: annotations are independent of request capabilities | Yes: capabilities are explicitly keyed by method | Yes |
| **Simplicity for client implementers** | Medium: must implement matching for `requiredCapabilities` | Low without SDK support: must attach a map of related-request capabilities to each outgoing request | High: nothing to do |
| **Simplicity for server implementers** | Medium: must declare capability requirements for every tool | Medium: must parse and apply related-request capabilities | High: validate at call time only |
| **Request payload overhead** | Low: requests carry nothing new; annotations add modestly to `tools/list` responses | High: every request carries capabilities for multiple related methods | None |
| **Compatibility with SEP-2575 stateless design** | Yes: each request is self-contained | Yes: each request is self-contained | Yes: each request is self-contained |

#### Alternative 1: Related Request Capabilities

In this approach, a request declares not only its own capabilities,
but also the capabilities the client will provide on *related*
requests that the current request needs to reason about.  This would
be expressed through a new `relatedRequestCapabilities` field in
`_meta`, parallel to `clientCapabilities`, keyed by the related method
name.

For example, when calling `tools/list`, the client can declare the
capabilities it will provide on `tools/call` and `tasks/*` requests:

```json5
// tools/list with related request capabilities
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/clientCapabilities": {
        // Capabilities for tools/list itself (may be empty today)
      },
      "io.modelcontextprotocol/relatedRequestCapabilities": {
        "tools/call": {
          "elicitation": {},
          "extensions": {
            "io.modelcontextprotocol/tasks": {}
          }
        },
        "tasks/get": {
          "elicitation": {}
        }
      }
    }
  }
}
```

The server can then filter the tool list server-side based on the
capabilities that will be available on `tools/call`, without assuming
those capabilities apply to `tools/list` itself.

For this approach to be practical, SDKs would need to provide a way
for client users to declare all of their capabilities per request type
up front (for example, at client construction time).  The SDK could
then automatically attach the appropriate
`relatedRequestCapabilities` to each outgoing request based on which
other request types are relevant.  Without this kind of SDK support,
getting this right would be very difficult for client users -- they
would need to manually track which request types are related to which
and remember to include the right capabilities each time.

**Advantages:**
- All the server-side filtering benefits described in
  [Capability-Aware Tool Adaptation](#capability-aware-tool-adaptation)
  -- arbitrarily complex filtering logic and centralized adaptation --
  plus dynamic replacement of one tool with another and reliable
  server-side matching of capability sub-fields.
- Capabilities are explicit about which request they apply to,
  preserving true per-request scoping without losing cross-request
  coordination.  A client can declare different capabilities for
  different request types if its support actually varies by method.
- The tool list returned by `tools/list` always matches what the
  client can actually execute.

**Disadvantages:**
- Caching becomes capability-dependent: any cache of `tools/list`
  results must include the declared related-capability set in its
  cache key, and capability changes force re-fetching.  This
  complicates MCP proxy servers in particular, which could otherwise
  serve one cached tool list to all downstream clients.
- Filtered tools are invisible, so the client cannot show them as
  disabled, explain what would unlock them, or choose to allow them
  and fail gracefully.
- Significantly increases the complexity of each request.  Clients
  must construct and maintain a map of related-request capabilities,
  and servers must parse and interpret that map.  Without SDK support
  that centralizes capability declaration, client users must manually
  include the correct capabilities for each related request type on
  every outgoing request, which is error-prone.
- The set of "related" request types is not obvious and may evolve
  over time.  As new methods are added to the protocol, the rules for
  which requests are related to which must be documented and kept up
  to date.
- Larger request payloads for marginal benefit in most cases --
  typical clients support the same capabilities for all request
  types, and per-tool annotations convey the same information with no
  per-request overhead.

#### Alternative 2: No Capability Coordination

In this approach -- the status quo under SEP-2575 alone -- no
cross-request capability coordination is attempted.  `tools/list`
returns every tool the server provides with no annotations, and the
server only checks capabilities when a tool is actually invoked via
`tools/call`.  If the client does not support a capability the tool
requires, the call simply fails with an error.

**Advantages:**
- Maximum simplicity: no annotations, no scoping rules, no matching
  logic.  Servers already need to validate capabilities at call time,
  so this requires no additional mechanism.
- Tool lists are identical for all clients and trivially cacheable.

**Disadvantages:**
- Exhibits both failure modes described in
  [How the Problem Surfaces](#how-the-problem-surfaces): raw
  capability errors reach end users who know nothing about MCP, and
  the model wastes tokens planning multi-step work toward tools that
  cannot run.
- Hard for agents to recover from failures gracefully.  An agent may
  have invested several turns building up context and planning an
  approach that relies on a specific tool, only to have that tool
  fail when it finally invokes it.  The agent may not know how to
  recover -- it may not have an alternative plan, and backtracking
  several turns is expensive and often impossible.
- Does not allow for substitution.  The server cannot offer a
  fallback tool (e.g., `lookup` when elicitation is unavailable, as a
  substitute for `research`) because the client never sees the
  substitution opportunity -- it just sees the primary tool, tries to
  use it, and fails.

### Modifications Not Included

The following are not alternative coordination mechanisms but
modifications of the primary proposal that were considered and not
included, to keep the proposal simple.  The first is a different
placement of the annotation; the second is an additional annotation
that could be revisited as a follow-up if practice shows the need.

#### Top-Level Tool Field Instead of `_meta`

Rather than carrying the annotation in `_meta`, `requiredCapabilities`
could be defined as a top-level field on the `Tool` type:

```json5
{
  "name": "deploy_to_production",
  "description": "Deploy a service to production (requires login)",
  "inputSchema": { /* ... */ },
  "requiredCapabilities": {
    "elicitation": {}
  }
}
```

This was considered, but placing the field in `_meta` under the
`io.modelcontextprotocol/` prefix was deemed better:

- It requires no change to the base `Tool` schema, keeping the
  proposal purely additive and letting implementations adopt it
  without a schema version bump.
- It mirrors how SEP-2575 transports `clientCapabilities` itself, so
  the capability machinery lives consistently in `_meta` on both
  sides of the exchange.
- It allows the mechanism to evolve (or be superseded) without
  deprecating a top-level schema field.

A top-level field would be marginally more discoverable in the schema
and slightly less verbose, but those benefits do not outweigh the
compatibility advantages of `_meta`.

#### Fallback Tools via `whenCapabilitiesUnavailable`

An earlier draft of this proposal included a second annotation,
`io.modelcontextprotocol/whenCapabilitiesUnavailable`, marking a tool
as a fallback intended only for clients that do *not* satisfy the
listed capabilities.  This would allow static substitution to be
performed client-side:

```json5
// tools/list response with substitution annotations
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "research",
        "description": "Research a topic, refining the query via user prompts",
        "inputSchema": { /* ... */ },
        "_meta": {
          "io.modelcontextprotocol/requiredCapabilities": {
            "elicitation": {}
          }
        }
      },
      {
        "name": "lookup",
        "description": "Quick lookup for a fixed query",
        "inputSchema": { /* ... */ },
        "_meta": {
          "io.modelcontextprotocol/whenCapabilitiesUnavailable": {
            "elicitation": {}
          }
        }
        // This tool is only intended for clients that do NOT
        // support elicitation -- it substitutes for research.
      }
    ]
  }
}
```

A client satisfying the listed capabilities would hide the fallback
(the primary tool is available instead); a client not satisfying them
would offer it.

This was excluded from the proposal for several reasons:

- It requires clients to implement *inverse* matching in addition to
  the ordinary matching rule, doubling the logic this SEP asks of
  clients.
- Its semantics get murky quickly: multiple fallbacks for one
  primary, chains of fallbacks, and clients that partially satisfy
  the listed capabilities all need rules that the simple annotation
  cannot express.
- Hybrid mode covers much of the need with no protocol machinery at
  all: a single tool that degrades internally at call time is usually
  a better design than a pair of tools stitched together by
  annotations.

Servers that want distinct fallback tools today can expose them to all
clients with descriptions indicating when each applies.

## Backward Compatibility

This proposal is additive to SEP-2575 and does not introduce breaking
changes.  The annotations are carried in the tool's existing `_meta`
field under the `io.modelcontextprotocol/` prefix, so:

- Clients that do not understand the annotations ignore them and see
  the same behavior as today (Alternative 2): all tools are visible,
  and capability mismatches surface as call-time errors.
- Servers that do not annotate their tools lose nothing: their tools
  are treated as having no capability requirements, and call-time
  validation still applies.

## Security Implications

### Client Filtering Is Advisory

Client-side matching is a usability mechanism, not an enforcement
mechanism.  A client may ignore the annotations (by choice or by not
implementing them) and invoke a tool whose requirements it does not
meet.  Servers **MUST NOT** rely on `requiredCapabilities` annotations
being honored; they **SHOULD** validate the capabilities declared on
each `tools/call` request and return an error when a required
capability is missing.

### Uniform Tool Lists

Because every client receives the same annotated tool list, servers no
longer produce per-client tool lists, and a `tools/list` response
reveals nothing about any particular client's capabilities.  The
annotations do reveal which capabilities each tool uses internally
(e.g., that a tool performs elicitation); servers handling sensitive
tools should consider whether that is information they are comfortable
publishing to all clients.
