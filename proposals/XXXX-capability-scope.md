# SEP-XXXX: Global Capability Scope for Per-Request Client Capabilities

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-04-11
- **Author(s)**: Gabriel Zimmerman (@gjz22)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/transports-wg/pull/{NUMBER}

## Abstract

[SEP-1442](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1442)
introduces per-request client capabilities, where the client declares
its supported capabilities in the `_meta` field of each request rather
than negotiating them once during initialization.  However, that
proposal does not specify the *scope* of those capabilities: whether a
capability declared on one request should be assumed to hold for other
requests, or whether each request's capabilities are independent.

This proposal specifies that per-request client capabilities SHOULD be
treated as **globally scoped**.  When a client declares capabilities on
any request, the server SHOULD assume those same capabilities apply to
all requests from that client.  This is critical because some request
types (notably `tools/list`) need to make decisions based on what
capabilities will be available during other request types (notably
`tools/call`).

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
      "modelcontextprotocol.io/clientCapabilities": {
        "elicitation": {}
      }
    }
  }
}
```

Now, what should happen when a client calls `tools/list`?  The server
needs to decide whether to include `deploy_to_production` in the list.
If the client does not support elicitation, this tool cannot function
correctly -- it would fail at the login step because it has no way to
authenticate the user.

```json5
// tools/list request -- what capabilities will tools/call have?
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        // The client declares capabilities here, but the server
        // needs to know what capabilities tools/call will have,
        // not what tools/list has.
      }
    }
  }
}
```

Without a defined scope for capabilities, the server does not have
enough information to know whether to return a tool with a required
capability to the client.  And if the server does return the tool,
the client does not have the information to know whether it actually
has the capabilities needed to execute it.

### Server-Side Capability Filtering

Servers may want to adapt their behavior based on client capabilities in
several ways:

1. **Filtering**: Remove tools that require unsupported capabilities.
   A server might hide tools that use elicitation from clients that
   don't support it.

2. **Substitution**: Offer degraded alternatives when full capabilities
   aren't available.  For example, a `research` tool that uses
   elicitation to refine its query with the user could be replaced with
   a simpler `lookup` tool that takes a fixed query, for clients that
   don't support elicitation.

3. **Parameterized adaptation**: Decide based on sub-fields of a
   capability rather than just whether the capability is present.  For
   example, the client's `sampling` capability might include a `tools`
   sub-field indicating whether the client can handle tool use during
   sampling:

```json5
// Client A: sampling with tool use
{
  "modelcontextprotocol.io/clientCapabilities": {
    "sampling": {
      "tools": {}
    }
  }
}

// Client B: sampling without tool use
{
  "modelcontextprotocol.io/clientCapabilities": {
    "sampling": {}
  }
}
```

A server might make different filtering or substitution decisions for
the two clients based on this sub-field -- not just on whether
`sampling` is present at all.

All of these patterns require the server to know, at `tools/list` time,
what capabilities will be available at `tools/call` time.

## Specification

### Global Capability Scope

When a client sends per-request capabilities (as defined in SEP-1442),
the following rules apply:

1. A client **SHOULD** send the same `clientCapabilities` object on every
   request.  The capabilities declared represent the client's overall
   capability set, not capabilities specific to the request type.

2. A server that receives capabilities on any request **SHOULD** assume
   that those capabilities apply to all requests from that client.
   Specifically, if a server receives capabilities on a `tools/list`
   request, it **SHOULD** use those capabilities to determine which tools
   to return, assuming the same capabilities will be present on
   subsequent `tools/call` requests.

3. If a client's capabilities change (e.g., a user enables or disables
   a feature), the client **SHOULD** re-issue applicable list requests
   (e.g., `tools/list`, `resources/list`) with the updated capabilities
   rather than relying on cached results.  This ensures the server can
   return results that reflect the new capability set.

4. A server **MUST NOT** assume capabilities are available if the client
   has not declared them on any request.  The absence of capabilities
   is always a safe default.

### Schema

No schema changes beyond those in SEP-1442 are required.  This proposal
defines the *semantics* of the existing `clientCapabilities` field, not
new fields.  The `clientCapabilities` field in `_meta` is used as defined
in SEP-1442:

```typescript
export interface Request {
  method: string;
  params?: {
    _meta?: {
      "modelcontextprotocol.io/clientCapabilities"?: ClientCapabilities;
      // ... other meta fields
    };
    // ...
  };
}
```

### Server Behavior

When a server receives a request with `clientCapabilities`, it **SHOULD**
use the capabilities on that request to determine its response.  The
server does not need to store capabilities across requests -- consistent
with SEP-1442's stateless design, each request is self-contained.  The
server can simply trust that the capabilities declared on a `tools/list`
request will also be declared on subsequent `tools/call` requests.

1. For `tools/list` requests, the server **SHOULD** use the capabilities
   on the request to filter or adapt the returned tool list.  For example:

```json5
// tools/list request from a client that supports elicitation
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "elicitation": {},
        "sampling": {}
      }
    }
  }
}

// Response: includes tools that require elicitation
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "deploy_to_production",
        "description": "Deploy a service to production (requires login)",
        "inputSchema": { /* ... */ }
      },
      {
        "name": "research",
        "description": "Research a topic, refining the query via user prompts",
        "inputSchema": { /* ... */ }
      }
    ]
  }
}
```

```json5
// tools/list request from a client that does NOT support elicitation
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "sampling": {}
      }
    }
  }
}

// Response: deploy_to_production is filtered out (no way to log in),
// and research is substituted with lookup (no way to refine the query).
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "lookup",
        "description": "Quick lookup for a fixed query",
        "inputSchema": { /* ... */ }
      }
    ]
  }
}
```

2. For `tools/call` and other requests that may trigger server-initiated
   requests, the server **SHOULD** verify that the capabilities on the
   current request match its expectations.  If a required capability is
   missing, the server **SHOULD** return an error rather than silently
   failing:

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
      "modelcontextprotocol.io/clientCapabilities": {
        "sampling": {}
        // Note: no "elicitation" -- but the tool requires it
      }
    }
  }
}

// Error response
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32602,
    "message": "Tool 'deploy_to_production' requires elicitation capability (for login)"
  }
}
```

### Interaction with Tasks

When capabilities are globally scoped, they extend naturally to
task-based workflows.  If a client declares capabilities on a
`tools/call` request that results in a task, the server **SHOULD** expect
those same capabilities to be available when the task produces
server-initiated requests (e.g., elicitation requests during task
execution).

```json5
// Initial tools/call that creates a task
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "long_running_analysis",
    "arguments": { "dataset": "sales_q1" },
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "elicitation": {},
        "sampling": {},
        "tasks": {
          "list": {},
          "cancel": {}
        }
      }
    }
  }
}

// Later: task produces an elicitation request.
// The server can expect elicitation support because the client
// declared it globally.
```

## Rationale

### Why Global Scope

Global scope is the simplest model that solves the cross-request
capability problem.  It requires no new protocol machinery -- the client
simply sends the same capabilities on every request, and the server
treats them as a consistent view of the client's abilities.

This approach has several advantages:

1. **Simplicity**: Easy to understand and implement.  Clients send the
   same capabilities object on every request.  Servers use the
   capabilities on each request directly, with no cross-request state.

2. **Server-side filtering**: The server can make complex adaptation
   decisions centrally, including parameterized filtering based on
   capability sub-fields.

3. **Consistency**: The tool list returned by `tools/list` always
   matches what the client can actually execute via `tools/call`.

4. **Compatibility with stateless design**: In a stateless server, each
   request carries the full capability set, so any server instance can
   make the correct decision without shared state.

### Alternatives Considered

#### Alternative 1: Tool-Level Capability Annotations

In this approach, `tools/list` would return capability requirements
alongside each tool, and the client would filter tools locally.

```json5
// tools/list response with capability annotations
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "deploy_to_production",
        "description": "Deploy a service to production",
        "inputSchema": { /* ... */ },
        "requiredCapabilities": {
          "elicitation": {}
        }
      },
      {
        "name": "research",
        "description": "Research a topic, refining the query via user prompts",
        "inputSchema": { /* ... */ },
        "requiredCapabilities": {
          "elicitation": {}
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

The client would then match its own capabilities against
`requiredCapabilities` and filter:

```json5
// Client without elicitation would see:
// - get_weather (no requirements)
// But NOT deploy_to_production or research (both require elicitation)
```

**Advantages:**
- Tools are always visible to all clients; clients can show
  unavailable tools as disabled rather than hidden.
- Transparency: a client sees the full set of tools the server
  provides, along with the capabilities each one requires.  This lets
  users and developers understand what they could implement (e.g.,
  adding elicitation support) to unlock additional tools, rather than
  silently not knowing that other tools exist.
- No assumption about capability consistency across requests.
- Keeps capabilities truly scoped to individual requests, preserving
  per-request flexibility.  This matters if the protocol ever adds
  capabilities to requests that don't currently use them.  For example,
  if elicitation were added to `tools/list` (say, to let the user
  choose which categories of tools to include), a client using global
  scope would have to accept elicitation for both listing and calling
  tools, with no way to opt into one without the other.  With
  tool-level annotations, capabilities remain per-request, so the
  client can support elicitation on `tools/call` but not `tools/list`
  (or vice versa) without conflict.
- Substitution can be partially addressed by adding a
  `whenCapabilitiesUnavailable` attribute to tools.  A server could
  annotate a fallback tool that should only be used when the primary
  tool's required capabilities are absent, allowing the client to
  handle substitution locally:

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
        "requiredCapabilities": {
          "elicitation": {}
        }
      },
      {
        "name": "lookup",
        "description": "Quick lookup for a fixed query",
        "inputSchema": { /* ... */ },
        "whenCapabilitiesUnavailable": {
          "elicitation": {}
        }
        // This tool is only offered when the client does NOT
        // support elicitation -- it substitutes for research.
      }
    ]
  }
}
```

**Disadvantages:**
- Capability requirements may be complex and parameterized.  A tool
  might require `sampling` with specific sub-capabilities, or
  experimental capabilities with non-trivial structures.  Defining a
  matching algorithm that works across all current and future
  capabilities is difficult.
- Even with `whenCapabilitiesUnavailable`, the substitution logic is
  limited.  The server cannot dynamically decide how to adapt -- it
  can only pre-declare static substitution rules.  Only the server
  knows whether a tool without elicitation should be hidden, replaced
  with an alternative, or offered with degraded functionality, and
  that decision may depend on runtime context that cannot be expressed
  in static annotations.
- Every client must implement the matching logic for both
  `requiredCapabilities` and `whenCapabilitiesUnavailable`, leading
  to inconsistencies across implementations.
- Does not account for capabilities that interact.  A tool might require
  elicitation OR sampling (not both), or might behave differently
  depending on which is available.
- Centralizing filtering logic on the server keeps clients simple and
  avoids duplicating adaptation logic across every client
  implementation.  This approach moves that complexity to the client.

#### Alternative 2: Related Request Capabilities

In this approach, a request can declare not only its own capabilities,
but also the capabilities the client will provide on *related* requests
that the current request needs to reason about.  This would be
expressed through a new `relatedRequestCapabilities` field in `_meta`,
parallel to `clientCapabilities`, keyed by the related method name.

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
      "modelcontextprotocol.io/clientCapabilities": {
        // Capabilities for tools/list itself (may be empty today)
      },
      "modelcontextprotocol.io/relatedRequestCapabilities": {
        "tools/call": {
          "elicitation": {},
          "sampling": { "tools": {} }
        },
        "tasks/get": {
          "elicitation": {}
        }
      }
    }
  }
}
```

The server can then filter the tool list based on the capabilities
that will be available on `tools/call`, without assuming those
capabilities apply to `tools/list` itself.

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
- All filtering can still be done server-side, preserving the
  centralized adaptation benefits of the primary proposal.
- Capabilities are explicit about which request they apply to,
  avoiding the ambiguity of assuming one request's capabilities hold
  for another.
- Supports true per-request capability scoping without losing the
  cross-request coordination needed for list filtering.  A client can
  declare different capabilities for different request types if its
  support actually varies by method.

**Disadvantages:**
- Significantly increases the complexity of each request.  Clients
  must construct and maintain a map of related request capabilities,
  and servers must parse and interpret that map.
- Hard for client users to get right without SDK support.  If an SDK
  does not centralize capability declaration, users must manually
  include the correct capabilities for each related request type on
  every outgoing request, which is error-prone.
- The set of "related" request types is not obvious and may evolve
  over time.  As new methods are added to the protocol, the rules for
  which requests are related to which must be documented and kept up
  to date.
- Larger request payloads for a marginal benefit in most cases --
  typical clients will declare the same capabilities for all related
  request types, making the global-scope model equivalent but simpler.

#### Alternative 3: Targeted Capability Scope

In this approach, capabilities declared on a request apply to the
results and side effects of that specific request and any operations
derived from it, rather than globally.

For example, if a client sends capabilities on a `tools/call` request,
those capabilities would apply to server-initiated requests that occur
*within the context of that tool call* (such as elicitation or sampling
requests triggered by the tool), but would NOT be assumed to apply to
unrelated requests.

```json5
// tools/call with capabilities scoped to this call
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "deploy_to_production",
    "arguments": { "service": "api-gateway" },
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "elicitation": {}
      }
    }
  }
}
// The server knows it can send elicitation requests within this
// tool call's context.

// A separate tools/call with different capabilities
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "summarize_document",
    "arguments": { "url": "https://example.com/report.pdf" },
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "sampling": {}
        // No elicitation -- this call doesn't need it
      }
    }
  }
}
// The server knows NOT to send elicitation requests within this
// tool call's context.
```

For `tools/list`, the client would need to declare intended capabilities
for the calls it plans to make, and the server would filter based on
those:

```json5
// tools/list with an explicit scope declaration
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/list",
  "params": {
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "elicitation": {},
        "sampling": {}
      }
    }
  }
}
// The server returns tools that match these capabilities,
// since the client is indicating it can provide these
// capabilities on tools/call.
```

**Advantages:**
- More precise: clients can vary capabilities per request.  A resource-
  constrained client might enable sampling for some calls but not others.
- Enables future optimizations where the server allocates resources
  only for the capabilities actually needed per request.

**Disadvantages:**
- Requests are not actually request-scoped in practice.  Because some
  requests (like `tools/list`) must reflect the capabilities of other
  requests (like `tools/call`), groups of related requests end up
  sharing the same capability scope anyway.  Determining which
  requests belong to which group -- and how one request's capabilities
  map onto another's -- is not simple, and the rules for this mapping
  would need to be defined for every pair of related request types.
- Capability transfer rules become complex.  If `tools/call` produces
  a task, do the capabilities transfer to the task?  What about
  nested operations -- if a task triggers a sub-task, do capabilities
  propagate?  Each level of indirection requires a new rule.
- Harder to reason about.  Developers must track which capabilities
  apply to which operations, increasing the cognitive load and the
  risk of bugs.
- Makes server-side filtering more complex.  The server must track
  per-request capabilities rather than a single global set.

#### Alternative 4: Fail at Call Time

In this approach, no cross-request capability coordination is
attempted.  `tools/list` returns every tool the server provides,
regardless of client capabilities, and the server only checks
capabilities when a tool is actually invoked via `tools/call`.  If
the client does not support a capability the tool requires, the
`tools/call` simply fails with an error.

```json5
// tools/list returns everything, regardless of client capabilities
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      { "name": "deploy_to_production", /* ... */ },
      { "name": "research", /* ... */ },
      { "name": "get_weather", /* ... */ }
    ]
  }
}

// Later, the client calls a tool without the required capability
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "deploy_to_production",
    "arguments": { "service": "api-gateway" },
    "_meta": {
      "modelcontextprotocol.io/clientCapabilities": {
        "sampling": {}
        // No elicitation
      }
    }
  }
}

// Error response
{
  "jsonrpc": "2.0",
  "id": 2,
  "error": {
    "code": -32602,
    "message": "Tool 'deploy_to_production' requires elicitation capability (for login)"
  }
}
```

**Advantages:**
- Maximum simplicity: no capability scoping rules are required at
  all.  The server does not need to filter or adapt its tool list
  based on client capabilities.
- No assumption about cross-request consistency -- each request is
  evaluated on its own merits.
- Trivial to implement: servers already need to validate capabilities
  at call time anyway, so this is effectively the status quo with no
  additional mechanism.

**Disadvantages:**
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
- Wastes tokens and time.  The agent spends effort reasoning about
  tools it cannot actually use, and the user waits for a failure
  that could have been prevented by filtering upfront.
- Poor user experience.  From the user's perspective, the agent
  appears to "choose" a tool it cannot use, which looks like a bug
  in the agent rather than a protocol-level mismatch.

## Backward Compatibility

This proposal is additive to SEP-1442 and does not introduce breaking
changes.  It defines behavioral expectations (SHOULD-level) for how
servers interpret the `clientCapabilities` field that SEP-1442
introduces.

Servers that do not implement capability-based filtering will continue
to work -- they will simply return all tools regardless of client
capabilities, and capability mismatches will be caught at `tools/call`
time (or not at all, if the tool happens not to need the missing
capability).

Clients that already send consistent capabilities on every request
(which is the expected common case) require no changes.

## Security Implications

### Capability Downgrade

If a client sends different capabilities on different requests (either
intentionally or due to a bug), the server may return a tool list that
does not match the capabilities the client actually provides on
`tools/call`.  For example, a client might receive
`deploy_to_production` in a `tools/list` response (because it declared
elicitation support) but then omit elicitation on the actual
`tools/call`.  Servers **SHOULD** validate capabilities on each
`tools/call` request and return an error if a required capability is
missing, rather than assuming the `tools/list` capabilities still hold.

### Information Disclosure via Tool List

Capability-based filtering means that different clients see different
tool lists.  This is generally desirable, but servers should be aware
that the *absence* of a tool in a `tools/list` response reveals
information about the client's capabilities to any observer.  This is
unlikely to be a practical concern, but servers handling sensitive tools
should consider whether tool visibility itself is sensitive.
