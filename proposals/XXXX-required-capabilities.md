# SEP-XXXX: Required Capabilities for Tools

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-04-11
- **Author(s)**: Gabriel Zimmerman (@gjz22)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/transports-wg/pull/31

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

The annotation marks when a capability is a *hard* requirement for a
tool to execute.  A tool that can instead operate in *hybrid* mode --
using a capability when the `tools/call` request declares it and
falling back to another mechanism when it does not -- works for every
client and needs no annotation at all.

## Motivation

The motivation for this SEP is to let clients handle capability
requirements gracefully.  Some tools only work if the client supports
a particular capability -- elicitation to ask the user for input, or
an extension such as tasks to run asynchronously -- but today a client
has no way to know which tools those are until it calls one and the
call fails.  This SEP lets a server mark each tool with the
capabilities it requires, so the client can decide up front what to do
with a tool it cannot support -- hide it from the model, show it as
unavailable, or explain to the user what is missing -- instead of
letting the failure surface in the middle of a conversation.

The gap exists because of how capabilities are declared.  Before
SEP-2575, a client declared its capabilities once during
initialization, nominally for the whole session -- but what a session
guaranteed was ambiguous: Streamable HTTP sessions were optional,
stateless and load-balanced deployments often could not see the
initialization capabilities on later requests, and stdio had no
explicit session at all, so many servers simply assumed.  SEP-2575
resolves that ambiguity with per-request capabilities, which makes the
coordination problem explicit: the request that decides which tools
the model sees (`tools/list`) is not the request that needs the
capabilities (`tools/call`).  The server cannot
tell from a `tools/list` request whether a later `tools/call` will
satisfy a tool's requirements, and the tool list gives the client no
way to tell which tools depend on capabilities it lacks.

Concretely, the SEP aims to:

- **Keep unusable tools out of the model's context**, so the model
  does not plan around tools that cannot run.
- **Move capability handling ahead of the tool call**, so the client
  decides how to treat an unsupported tool before the model selects
  it, rather than reacting to a call-time error mid-turn.
- **Preserve per-request capability scoping and cacheable tool
  lists**, rather than treating capabilities as global state or
  making tool lists vary per client.
- **Give the ecosystem one standard mechanism** in place of
  incompatible ad hoc conventions.

The SEP does not change how tools that can adapt to a missing
capability behave (see
[Hard Requirements vs. Hybrid Tools](#hard-requirements-vs-hybrid-tools)),
does not replace call-time validation by the server, and does not
address filtering tools by user authorization.

### The Cross-Request Capability Problem

Consider a server that provides a tool called `deploy_to_production`,
which uses elicitation to prompt the user to log in before deploying.
When the client invokes the tool, it declares elicitation support on
that `tools/call` request:

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

But the model only learns the tool exists from an earlier, separate
`tools/list` request, and the capabilities on that request describe
`tools/list` itself, not what later calls will support:

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

If the client does not support elicitation, `deploy_to_production`
cannot work for it -- it would fail at the login step.  Yet under
SEP-2575 alone, nothing in this exchange tells the server to leave the
tool out, or tells the client that the tool needs elicitation.

### Hard Requirements vs. Hybrid Tools

Not every tool that uses a capability has this problem.  Such a tool
can be designed in one of two ways:

1. **Hybrid mode**: the tool uses the capability when it is declared
   on the `tools/call` request and falls back to another mechanism
   when it is not.  For example, `deploy_to_production` could fall
   back to returning a login URL in its tool result and asking the
   caller to retry once authenticated, instead of prompting
   interactively via elicitation.  Likewise, a tool that runs as a
   long-lived task when the client supports the tasks extension could
   fall back to executing synchronously.  Hybrid tools work for every
   client, and per-request capabilities (SEP-2575) already give them
   everything they need to adapt at call time.
2. **Hard requirement**: the tool has no reasonable fallback.  If
   `deploy_to_production` has no out-of-band login flow, then without
   elicitation it simply cannot authenticate the user.

Only hard requirements need coordination between `tools/list` and
`tools/call`, and they are the case this SEP addresses.

### How the Problem Surfaces

When the mismatch goes undetected until `tools/call` time, it manifests
in two damaging ways:

1. **The harness discovers the mismatch only reactively, after the
   model has already committed to the tool.**  When the model invokes
   a tool whose required capability the client lacks, the server
   returns a `MissingRequiredClientCapabilityError` (`-32021`) whose
   `data.requiredCapabilities` lists what is missing (see
   [Server Validation at Call Time](#server-validation-at-call-time)).
   This is a JSON-RPC protocol error, not a tool execution error: the
   specification only permits (**MAY**), rather than recommends,
   passing protocol errors to the model, and the structured `data`
   lets the harness recognize the condition and handle it gracefully
   -- for example, telling the user the tool is not available in this
   client rather than echoing raw capability jargon.  But however well
   the harness handles it, the handling is reactive.  The LLM call
   that selected the tool and generated its arguments was unnecessary:
   its tokens and latency were spent producing a call that could never
   succeed.  And the harness is left to improvise mid-turn with no
   good option -- tell the user the request cannot be completed, hand
   the error back to the model and hope it recovers, or drop the call
   silently.
2. **The model plans multi-step work toward a tool it cannot use, wasting tokens.**
   A model plans around the tool list it is given.  Consider an
   incident-response flow where the model plans two steps: first fetch
   the details of an incident to determine what needs to be queried,
   then run a `long_running_query_job` tool -- a task-based tool (see
   [Extension Capabilities: Tasks](#extension-capabilities-tasks)) --
   to execute that query.  If the client does not support the tasks
   extension, the second tool can never work, but nothing in the tool
   list says so.  The model spends turns and tokens completing the
   first step, then hits the wall at the second.  At best, it
   recognizes the limitation and responds that it retrieved the
   incident details but has no ability to run the query.  If instead
   the call is attempted and the harness passes the `-32021` error
   back to the model (failure mode 1), the response is unpredictable:
   the model may retry, relay the error to the user, or confabulate
   around the failure.  Either way, the work invested toward an
   unusable goal is wasted.

Upfront filtering prevents both: a tool the client cannot support
never enters the model's context, so the model plans only with tools
that can actually run, no LLM call is spent selecting a tool that
cannot succeed, and the harness decides how to present the missing
capability before the conversation starts rather than in the middle
of a turn.

### Why Standardize This in the Protocol

Even without this SEP, implementers will not leave this problem
unsolved -- they will build their own ad hoc mechanisms to filter
tools whose required capabilities the client lacks, whether by using
approaches like the alternatives discussed in this document or
something else entirely.  Because none of these conventions is
standardized, implementations converge on them independently, with no
interoperability guarantee, and may have to change them as the
protocol's use of capabilities evolves.  Standardizing a single
mechanism now, while the ecosystem is still young, gives
implementations a well-defined target to converge on instead.

### Where to Filter: Server-Side vs. Client-Side

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
  one), decisions that depend on runtime context, or requirements that
  vary by argument.  A declarative annotation format has to anticipate every
  such pattern; server code does not.
- **Capability-tailored tool definitions.**  Beyond including or
  excluding a tool, the server can customize the tool definition
  itself to the declared capabilities.  For example, the description
  can tell the model that the tool will prompt the user for input
  when elicitation is available, or that it runs as a long-lived task
  when the client supports the tasks extension, and say something
  different (or expose a different input schema) when it does not.
  With client-side filtering every client receives the same
  definition, so a hybrid tool's description has to cover all of its
  behaviors at once.
- **Centralization.**  The adaptation logic is written once, on the
  server, instead of being reimplemented (with inevitable
  inconsistencies) in every client.  Servers also already filter the
  tool list based on the authenticated user (which tools this user is
  authorized to see), so server-side capability filtering keeps *all*
  filtering in a single place rather than splitting it between server
  and client.

#### Advantages of Client-Side Filtering

- **Caching.**  The `tools/list` response does not depend on the
  client's capabilities, so a cached tool list does not need to
  incorporate the client's capability set into its cache key.  The
  response may still vary by user identity or authorization, but that
  axis is already expressed by SEP-2549's `cacheScope`
  (`"public"` / `"private"`); extensions add no separate axis, since
  they are declared within the client's capabilities
  (`capabilities.extensions`).  Server-side capability filtering would
  add a second, independent axis that `cacheScope` cannot express --
  `"private"` alone is insufficient, because the same user can connect
  from clients with different capabilities.  This matters for
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
  every request (see Alternative 1a) -- which adds request complexity
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
[Where to Filter: Server-Side vs. Client-Side](#where-to-filter-server-side-vs-client-side)
discusses why these costs are acceptable.

### Alternatives Considered

The following matrix compares the primary proposal (tool-level
required-capability annotations) against the alternative coordination
mechanisms -- two variants of server-side filtering (Alternatives 1a
and 1b) and no coordination at all (Alternative 2) -- across the goals
that motivated this SEP.

| Goal | Required Capabilities (Primary) | Alt 1a: Related Request Capabilities | Alt 1b: Global Capability Scope | Alt 2: No Capability Coordination |
| --- | --- | --- | --- | --- |
| **Solves cross-request capability problem** (e.g. `tools/list` reflects what `tools/call` will support) | Yes: client matches its own capabilities against per-tool annotations | Yes, explicitly: the client declares the capabilities of related methods on each request | Yes, implicitly: the same capabilities are assumed to hold on every request | No: mismatches surface as call-time failures |
| **Filtering** | Yes: client filters locally | Yes: server filters using the related-request capabilities | Yes: server filters the returned tool list | No |
| **Substitution** (swap one tool for a lower-functionality alternative) | Partial: hybrid-mode tools degrade internally at call time; distinct fallback tools remain visible to all clients (see the `whenCapabilitiesUnavailable` modification under [Modifications Not Included](#modifications-not-included)) | Yes: server can freely substitute based on capabilities and runtime context | Yes: server can freely substitute based on capabilities and runtime context | No: the client never sees the substitution opportunity |
| **Parameterized adaptation** (decisions based on capability sub-fields) | Limited: client-side matching on nested sub-fields is error-prone | Yes: server has full access to the capability object | Yes: server has full access to the capability object | No |
| **Capability-tailored tool definitions** (e.g. description or schema varies with the capabilities provided) | No: every client receives the same definition; hybrid tools must describe all behaviors at once | Yes: server tailors definitions to the related-request capabilities | Yes: server tailors definitions to the capabilities on `tools/list` | No: no basis for knowing what `tools/call` will support |
| **Tool list cacheable without capability cache key** | Yes: identical response for all clients | No: each declared related-capability set yields a different list | No: each capability set yields a different list | Yes: identical response for all clients |
| **Client chooses how to respond** (hide, disable, allow-and-error) | Yes | No: filtered tools are invisible to the client | No: filtered tools are invisible to the client | No: only call-time failure |
| **Transparency to the client** (client sees all tools the server provides) | Yes, with their requirements | No: filtered tools are invisible to the client | No: filtered tools are invisible to the client | Yes, but without requirement information |
| **Preserves per-request capability scoping** | Yes: annotations are independent of request capabilities | Yes: capabilities are explicitly keyed by method | No: capabilities are assumed global, not scoped to the declaring request | Yes |
| **Simplicity for client implementers** | Medium: must implement matching for `requiredCapabilities` | Low without SDK support: must attach a map of related-request capabilities to each outgoing request | High: send the same capabilities on every request; no matching or per-method map to maintain | High: nothing to do |
| **Simplicity for server implementers** | Medium: must declare capability requirements for every tool | Medium: must parse and apply related-request capabilities | High: use the capabilities on each request directly | High: validate at call time only |
| **Request payload overhead** | Low: requests carry nothing new; annotations add modestly to `tools/list` responses | High: every request carries capabilities for multiple related methods | Low: a single `clientCapabilities` object, same on every request | None |
| **Compatibility with SEP-2575 stateless design** | Yes: each request is self-contained | Yes: each request is self-contained | Yes: each request is self-contained, though correctness depends on the client's consistency across requests | Yes: each request is self-contained |

#### Alternative 1: Server-Side Filtering

Both mechanisms below have the server filter or adapt the
`tools/list` response using capabilities the client is expected to
provide on `tools/call` (and other related requests), rather than
having the client filter against per-tool annotations.  They differ in
how the server learns what those capabilities will be: Alternative 1a
has the client declare them explicitly, keyed by method; Alternative
1b has the server assume the capabilities on any request hold for all
requests.  Both share the same two disadvantages relative to
client-side filtering -- capability-dependent caching and invisible
filtered tools -- and the following two subsections sketch possible
mitigations for each before the mechanisms themselves are described.

##### Mitigating the Cache-Key Problem: Tool Versioning

The caching disadvantage could be mitigated by a **future** tool
versioning mechanism, out of scope for this SEP and tracked
separately.  If `tools/list` responses carried an ETag in the sense of
HTTP conditional requests, a server doing capability-based filtering
could mint a distinct ETag for each capability-conditioned variant of
the tool list -- for example, one ETag for the list visible to a
client that supports only elicitation, and a different ETag for a
client that also supports sampling.  The server, not the cache, would
then determine the effective cache key: a cache (including an MCP
proxy) could store each variant under its ETag and serve the right one
through an ordinary conditional-request flow (`If-None-Match` /
`304 Not Modified`), rather than needing to construct a cache key from
the client's full declared capability set itself.

This mitigation assumes tool versioning exists as a protocol
mechanism, which it does not today -- it would need to be proposed as
its own track.  It also requires the server to maintain more than one
active tool-list version at a time (at least one per distinct
capability-conditioned variant it serves), which is additional
server-side complexity beyond simply always returning the same list.

##### Mitigating the Transparency Problem: Filtered Tool Metadata

The transparency disadvantage -- that filtered tools are invisible to
the client -- could be partially mitigated by having the server report
what it filtered out, and why.  For example, `tools/list` could
include a `_meta` field such as
`io.modelcontextprotocol/filteredTools`, listing the tools omitted
from the `tools` array because the client's declared capabilities did
not satisfy their requirements, each entry carrying a `reasonFiltered`
field describing what was missing:

```json5
// tools/list response with filtered-tool metadata
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [ /* ... visible tools ... */ ],
    "_meta": {
      "io.modelcontextprotocol/filteredTools": [
        {
          "name": "deploy_to_production",
          "reasonFiltered": "Requires elicitation capability (for login)"
        }
      ]
    }
  }
}
```

This restores much of the transparency that server-side filtering
otherwise sacrifices: a client (or its UI) can still discover which
additional tools exist and what capability would unlock them, even
though the tools themselves remain absent from the callable list.  It
does not close the gap entirely, since a filtered tool's full
definition (its `inputSchema`, description, and so on) is still
withheld.  It also effectively asks the server to publish the same
kind of per-tool capability-requirement information that this
proposal's `requiredCapabilities` annotation carries -- just inverted
(naming what is missing rather than what is required) and delivered
only for the tools a given client cannot see.

##### Alternative 1a: Related Request Capabilities

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
  [Where to Filter: Server-Side vs. Client-Side](#where-to-filter-server-side-vs-client-side)
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
  serve one cached tool list to all downstream clients.  (See
  [Mitigating the Cache-Key Problem: Tool Versioning](#mitigating-the-cache-key-problem-tool-versioning)
  above for a possible future mitigation.)
- Filtered tools are invisible, so the client cannot show them as
  disabled, explain what would unlock them, or choose to allow them
  and fail gracefully.  (See
  [Mitigating the Transparency Problem: Filtered Tool Metadata](#mitigating-the-transparency-problem-filtered-tool-metadata)
  above for a possible mitigation.)
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

##### Alternative 1b: Global Capability Scope

In this approach, per-request client capabilities are treated as
**globally scoped**: a client sends the same
`io.modelcontextprotocol/clientCapabilities` object on every request,
and a server that receives capabilities on any request assumes those
same capabilities apply to all requests from that client.  In
particular, the server uses the capabilities on a `tools/list` request
to filter or adapt the returned tool list, trusting that the same
capabilities will be present on subsequent `tools/call` requests:

```json5
// tools/list request from a client that does NOT support elicitation
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/clientCapabilities": {
        "sampling": {}
      }
    }
  }
}

// Response: deploy_to_production is filtered out, since the client
// cannot log in.
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "get_weather",
        "description": "Get current weather",
        "inputSchema": { /* ... */ }
      }
    ]
  }
}
```

If a client's capabilities change, it re-issues applicable list
requests with the updated capabilities rather than relying on cached
results.  The server still validates capabilities on each
`tools/call`, since a client (buggy or otherwise) may declare
different capabilities than it did on `tools/list`.

**Advantages:**

- All the server-side filtering benefits described in
  [Where to Filter: Server-Side vs. Client-Side](#where-to-filter-server-side-vs-client-side)
  -- arbitrarily complex filtering logic and centralized adaptation --
  plus dynamic replacement of one tool with another and reliable
  server-side matching of capability sub-fields.
- The simplest possible mechanism for clients: send the same
  capabilities object on every request, with no per-method map to
  construct and no matching logic to implement.
- The tool list returned by `tools/list` always matches what the
  client can actually execute.

**Disadvantages:**

- Caching becomes capability-dependent: any cache of `tools/list`
  results must include the client's capability set in its cache key,
  and capability changes force re-fetching.  This complicates MCP
  proxy servers in particular, which could otherwise serve one cached
  tool list to all downstream clients.  (See
  [Mitigating the Cache-Key Problem: Tool Versioning](#mitigating-the-cache-key-problem-tool-versioning)
  above for a possible future mitigation.)
- Filtered tools are invisible, so the client cannot show them as
  disabled, explain what would unlock them, or choose to allow them
  and fail gracefully.  (See
  [Mitigating the Transparency Problem: Filtered Tool Metadata](#mitigating-the-transparency-problem-filtered-tool-metadata)
  above for a possible mitigation.)
- Redefines SEP-2575's per-request capabilities as de facto global
  state.  If the protocol ever adds capability use to a request type
  that doesn't currently have it (e.g., elicitation during
  `tools/list`), a client cannot support the capability on one request
  type but not another without conflict.
- Relies on an assumption of cross-request consistency that the
  server cannot verify at list time -- exactly the kind of ad hoc
  convention that
  [Why Standardize This in the Protocol](#why-standardize-this-in-the-protocol)
  argues implementers will reach for on their own, absent a
  standardized mechanism.

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
  [How the Problem Surfaces](#how-the-problem-surfaces): the harness
  learns of a mismatch only from a call-time `-32021` error, after an
  LLM call has already been spent selecting the tool, and the model
  wastes tokens planning multi-step work toward tools that cannot
  run.
- Leaves the coordination problem for implementers to solve
  informally rather than through a standardized mechanism -- see
  [Why Standardize This in the Protocol](#why-standardize-this-in-the-protocol).
  Implementers filling the gap with ad hoc conventions, whether drawn
  from the alternatives discussed in this document or invented
  independently, gain no interoperability guarantee and may need to
  change them as the protocol's use of capabilities evolves.
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
