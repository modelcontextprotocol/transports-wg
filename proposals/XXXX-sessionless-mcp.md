# SEP-XXXX: Sessionless MCP via Explicit State Handles

- **Status**: Draft
- **Type**: Standards Track
- **Created**: 2026-03-11
- **Author(s)**: Peter Alexander (@pja)
- **Sponsor**: None
- **PR**: https://github.com/modelcontextprotocol/specification/pull/{NUMBER}
- **Related**: [SEP-1442](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1442) (Stateless-by-default MCP)

## Abstract

This proposal removes the protocol-level session concept from MCP entirely, replacing implicit session-scoped state with explicit, server-minted state handles that the model carries and threads through subsequent calls. Where [SEP-1442] makes sessions *optional* by defaulting to stateless operation, this proposal goes one step further and asks whether the opt-in needs to exist at all. The claim is that every legitimate use of session scoping today — application state, mutable tool lists, and resource subscriptions — is better served by explicit identifiers, and that the session abstraction itself introduces rigidity (fixed cardinality, undefined lifetime, uncacheable list endpoints) without corresponding benefit.

Under this proposal, a server that currently scopes a shopping cart to the session instead exposes `create_basket() -> basket_id` and threads that id through `add_item(basket_id, ...)`. The model decides what is shared and what is isolated; list endpoints become cacheable across what used to be session boundaries; and subagent fan-out no longer pays a per-server setup cost: no initialize, no `session/create`, and re-use cached `tools/list`.

[SEP-1442]: https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1442

## Motivation

### What sessions scope today

The current spec is not fully precise about which behaviors are session-bound, but in practice three categories of things are candidates to attach to a session's lifetime:

1. **Application state.** The canonical example is a shopping cart: `add_item()`, `add_item()`, `checkout()`, with the cart existing implicitly per-session. This generalizes to any stateful workflow — a Playwright browser instance, a database transaction, an open file descriptor.

2. **Mutable list endpoints.** `tools/list` (and `resources/list`, `prompts/list`) can legally return different results over a session's lifetime. For example, a server could expose an `enable_admin_tools` tool that mutates what subsequent `tools/list` calls return.

3. **Resource subscriptions.** Subscription lifetime is tied to session lifetime. ([SEP-1442] addresses this separately and it is not re-examined here.)

It is not obvious that any of these *need* a session; the session may simply be the only scoping mechanism the protocol offers, so things accrete onto it.

### Where sessions cause friction

The baseline for comparison throughout this section is **not** the current spec as-is, but a hypothetical near-future in which [SEP-1442] has landed in some form: `initialize` is optional, per-request `_meta` carries what used to be session settings, and servers that want statefulness explicitly opt in via `session/create` / `session/destroy` or similar. That is the world this proposal is arguing against — not the pre-1442 status quo, which both proposals agree needs to change. The question is whether 1442's opt-in stateful path should exist, or whether explicit handles make it unnecessary.

#### Session lifetime is undefined, and servers can't design around it

The spec does not say when a session begins or ends, because it depends on the host application. One chat interface creates a session per conversation; another per application launch. A subagent might share its parent's session or get its own. A page refresh might end the session or not. Different hosts reasonably do different things, and there is no obviously single correct answer that will suffice for any and all MCP applications.

This would be fine if sessions were purely a host concern. But *server authors* are the ones deciding what to scope to the session, and they need to know what "session" means to do that correctly. If I am writing a Playwright server and tying a browser instance to the session, I need to know whether "session" means one user turn, one agent process, or one chat that persists for weeks. The spec cannot tell me, and different hosts give different answers. I am designing against an abstraction whose semantics I do not control.

#### List endpoints cannot be cached across sessions

Because `tools/list` *might* be session-dependent, a client cannot assume a result fetched in one session is valid in the next. Every new session is forced to re-fetch — even when, as in the vast majority of deployments, the server's tool set is fixed at build time and never changes.

This applies to every list endpoint. Each must be treated as potentially session-scoped, so each must be re-fetched per session to be safe.

For hosts that regularly spawn subagents, this is not a marginal cost — it is a multiplier on the hot path. The mere *possibility* that a server is session-scoped forces `O(subagents × servers)` calls to `tools/list`: every subagent, for every server, every time, even if the underlying tool set hasn't changed since the orchestrator first connected. The client cannot skip the call because it cannot know in advance which servers are session-scoped and which aren't. Under this proposal the same workload is `O(servers)` — the orchestrator fetches each list once and every subagent reuses the cached result.

If there were no sessions — if list endpoints were purely a function of the server deployment — clients could cache them freely and invalidate only on an explicit signal (TTL expiry, or a `notifications/tools/list_changed` message). A subagent could inherit its parent's cached lists at zero cost.

#### Subagent fan-out pays per-session cost

An orchestrator agent spawning subagents is a common and growing pattern. If subagents get their own sessions — and there are isolation reasons they might — each spawn pays a per-server cost. [SEP-1442] removes the `initialize` handshake from that cost, which helps. But a `session/create` message is being proposed as the explicit replacement, and the forced `tools/list` re-fetch described above still applies regardless.

The cost per subagent is roughly `O(connected servers)` session-create messages plus `O(connected servers)` list re-fetches, even when most subagents never touch most servers. For an orchestrator spawning many short-lived subagents, this can amount to more protocol traffic than the actual tool calls.

#### Cardinality is forced, and no single scope works for everything

Session state has a cardinality of exactly one per session. The model gets one cart, one browser, one whatever. It cannot have two, and it cannot have zero.

Where this bites is when different pieces of state want different scopes. Consider an orchestrator that spawns several subagents to independently research products to buy. They all want to add to the *same* shopping cart — that's the point, they're collaborating on one order. But each subagent wants its *own* browser state for research — they're browsing different sites in parallel and shouldn't clobber each other.

There is no session boundary that gives you both:

| Session model               | Cart (want: shared) | Browser (want: isolated) |
|-----------------------------|:-------------------:|:------------------------:|
| Subagents share parent's    | ✓ shared           | ✗ shared (clobbers)     |
| Subagents get their own     | ✗ isolated         | ✓ isolated              |

The session is a single scope, and the state the model is trying to manage wants more than one.

With explicit IDs this simply is not a problem. The orchestrator calls `create_basket()` once, passes the resulting `basket_id` to each subagent, and each subagent separately calls `create_browser()` for its own `browser_id`. The model decides what is shared and what is isolated, per piece of state, rather than having one scope imposed on everything.

#### No way to initialize session state

Sessions begin empty. If state needs setup before it is usable, that setup has to happen through follow-up tool calls, which means the model has to know to make them and pay the round-trip for each.

For a shopping cart this is minor — carts naturally start empty. But consider a kubectl-style server that runs commands against a fleet of clusters, where the session state is "which cluster." There is no safe default. If the server manages staging and prod, defaulting to either is a landmine — the first `apply` goes to whichever one the server happened to pick. The session *must* be initialized before any operation is safe, but there is no mechanism to do that at creation time; the model has to know to call a `set_cluster()` tool first, and nothing stops it from forgetting.

With an explicit ID, initialization is a parameter: `create_context(cluster="staging-us-west") -> ctx_id`. Setup goes where parameters go, and the state cannot exist in an uninitialized form. Notably, kubectl itself already works exactly this way — `kubectl config use-context` is a handle-shaped operation, not a session-shaped one.

#### State is locked inside a scope the user cannot name

A cart created in one chat is invisible to another chat. If a user wants to resume work in a new conversation, hand something off to a different agent, or share state with a colleague, the session model gives them no handle to do it with. The state exists, but nothing can refer to it from outside.

## Specification

### Summary of changes

1. **Remove the session concept from the protocol.** There is no `session/create`, no `session/destroy`, and no `Mcp-Session-Id` header. The protocol is sessionless at every layer. (This supersedes the opt-in stateful path that [SEP-1442] retained.)

2. **List endpoints are session-independent.** The result of `tools/list`, `resources/list`, and `prompts/list` MUST NOT depend on per-connection, per-conversation, or prior-tool-call state. Lists can still change over time — a user upgrades their plan, a server ships new tools — but those changes happen at `(deployment, auth)` granularity, where they can be cache-managed and invalidated, rather than at session granularity, where they cannot. Caching mechanics are specified in separate work.

3. **Stateful workflows use explicit handles.** With sessions gone, servers that need to maintain state across tool calls do so by returning an identifier from a creation tool and accepting it as a parameter on subsequent calls. This is not a protocol-level construct — from the protocol's perspective a handle is just a string in a tool result and a string in a tool argument — but it is the natural replacement pattern, and guidance for doing it well is given below.

### Explicit state handles

#### Pattern

Where a server would previously have relied on implicit session-scoped state:

```
add_item("shoes")
add_item("socks")
checkout()
```

It instead exposes an explicit creation tool that returns a handle, and threads that handle through subsequent calls:

```
basket = create_basket()            # returns { "basket_id": "bsk_a1b2c3" }
add_item(basket, "shoes")
add_item(basket, "socks")
checkout(basket)
```

This is not a new pattern. `create_google_doc()` returns a doc ID; `gh pr create` returns a PR number; `open(2)` returns a file descriptor. None of these need a protocol session. The server owns the state, the client holds a name for it, and authorization is checked on every call.

#### Guidance for servers

None of the following is normative — handles are a tool-design pattern, not a protocol feature, and servers are free to shape them however fits their domain. That said, the pattern works best when a few things hold:

- **Handles are opaque.** A handle that encodes internal structure (`cart_user42_2026-03-11`) invites clients to parse it or models to guess it. A handle that's just `bsk_a1b2c3` does not.
- **Possession is not authorization.** Validate `(handle, auth_context)` on every call. Handles will end up in chat logs, in copy-paste buffers, in subagent prompts; treating them as bearer tokens is a footgun. See [Security Implications](#security-implications).
- **Durability is documented in the tool description.** Handles outlive connections by design, so "the state lasts until the connection closes" is no longer an answer. Put the actual policy in the `create_*` tool's description — "returns a basket_id; baskets expire after 24h idle" — so it's in front of the model at the moment it decides to create state. A policy buried in server docs is a policy the model never sees.
- **Expired handles return useful errors.** When a tool receives a handle for state that has expired or been destroyed, the error should say so plainly — "basket bsk_a1b2c3 has expired" rather than "invalid argument" or a generic 404. A model that gets a clear expiry error can recover by calling `create_*` again; a model that gets an opaque error will retry the same broken call or give up.
- **Creation takes parameters.** `create_context(cluster="staging")` is better than `create_context()` followed by `set_cluster(ctx, "staging")`. One round-trip instead of two, and the state can't exist half-configured.
- **There's a way to clean up.** A `destroy_*(handle)` tool lets well-behaved models release resources. A `list_*()` tool lets a model recover after losing track of what it created. Neither is required, but both help.

#### Guidance for clients

From the client's perspective, a handle is an ordinary string that showed up in a tool result. The main thing the client can do to help is make sure that string survives context compaction — if the conversation gets summarized and the handle is in the discarded portion, the state is effectively orphaned. Clients that track tool-call results across compaction boundaries handle this already; clients that don't will want to. [First-class state handles](#first-class-state-handles) sketches a way to make this systematic rather than best-effort.

### Session-independent list endpoints

With sessions removed, list endpoints no longer have a session to vary against. The result of `tools/list`, `resources/list`, and `prompts/list` MUST NOT depend on connection state, conversation state, or the history of prior tool calls on the same connection.

This is not an immutability requirement. Lists are free to change over time — a user upgrades their plan and gains tools, a server deploys a new version, an admin grants a role. What matters is the *granularity* at which they change: a list change is visible to every caller at the same `(deployment, auth)` scope, not to just the one session that happened to call `enable_admin_tools()`. Two concurrent conversations with the same auth context see the same list; a subagent sees what its orchestrator sees; a re-fetch after a page refresh sees what the fetch before the refresh saw (modulo an actual change having happened in the meantime).

That granularity is what makes caching tractable. A cache keyed on `(deployment, auth)` can be invalidated when something at that scope changes; a cache that also has to account for per-session mutation cannot be invalidated short of re-fetching per session, which is to say it cannot be cached. The concrete mechanics of how clients and servers coordinate on freshness — TTLs, validators, change signals — are being specified in separate work and are out of scope here. This SEP establishes the scope; that work establishes the coordination.

For servers that genuinely want tool-call-driven tool exposure — `enable_admin_tools()` and similar — see [Tools Returning Tools](#tools-returning-tools) for a possible future direction that doesn't route through list mutation.

One consequence of the deployment-scoped guarantee is that servers can no longer mutate `tools/list` as a side effect of tool calls — the `enable_admin_tools()`-mutates-the-list pattern is out. In practice this is rarely used, and for the same effect servers can expose all tools unconditionally at the `tools/list` level and enforce authorization at call time (the same posture the auth-scoped MAY above already permits). A more structured replacement — tools that return additional tool definitions in their result — is a plausible future direction but is not proposed here; see [Tools Returning Tools](#tools-returning-tools).

## Rationale

### Why remove sessions rather than just default them off?

[SEP-1442] already does the heavy lifting of making MCP work behind load balancers and without sticky routing. The argument for going further is that the existence of the opt-in shapes the ecosystem even when it's rarely taken:

- **The mere existence of the opt-in forces the `O(subagents × servers)` cost on everyone.** A client cannot cache `tools/list` across session boundaries unless it knows the server doesn't opt into session-scoped mutation — and it can't know that in advance. So the client re-fetches, every session, every server, even though approximately zero servers actually opt in. This is the big-O inefficiency from the Motivation section restated: it's not caused by sessions being *used*, it's caused by sessions being *possible*. Defaulting them off doesn't help; only removing them does.
- **Server authors reach for the session because it's there.** The spec offering session-scoped state as a primitive nudges people toward it for workflows that would be better served by explicit IDs. Removing it forces the better pattern.
- **Simplicity compounds.** Every concept in the protocol is a concept SDK authors implement, docs explain, and new users learn. A protocol with fewer primitives is easier to implement correctly.

### Why explicit IDs are strictly more expressive

The session gives exactly one scope per connection. Explicit IDs give as many scopes as the model chooses to create, and each can be shared or isolated independently. Anything expressible with a session is expressible with a single ID the model creates at the top of the conversation; the converse does not hold.

### Comparison to alternatives

| Approach                        | Cacheable lists | Flexible cardinality | Fan-out cost | Nameable state | Complexity |
|---------------------------------|:---------------:|:--------------------:|:------------:|:--------------:|:----------:|
| Current spec (sessions)         | ✗              | ✗ (exactly 1)       | High         | ✗             | Medium     |
| SEP-1442 (opt-in sessions)      | ✗¹             | ✗ (0 or 1)          | Medium       | ✗             | Medium     |
| This proposal (explicit IDs)    | ✓              | ✓ (any)             | Zero²        | ✓             | Low        |

¹ A client cannot know in advance whether a given server will opt into sessions, so lists must still be treated as potentially session-scoped.
² Zero *protocol-layer* cost. The model still pays for the `create_*` tool call, but only for state it actually uses, and only once regardless of how many subagents later share the handle.

### Anticipated objections

#### "Garbage collection: when does the server free `basket_abc123`?"

Sessions at least gave a lifecycle signal — session ends, state is freed. Without that, the model might forget to call `destroy_basket()`, and state leaks.

The counter is that sessions do not actually deliver this in practice. Chat conversations persist indefinitely; sessions do not cleanly end. Stateless HTTP servers behind load balancers never see a connection-close. Servers are already TTL-ing or leaking today — and notably, the current proposals for explicit session management are *themselves* adding TTLs, which is a concession that session-end alone does not solve the problem.

Explicit IDs with a documented durability policy ("baskets expire after 24h idle") is the same mechanism, just honest about what is doing the work.

#### "Models have to carry the IDs forward"

With implicit session state, the model never tracks an identifier — the server does. With explicit IDs, the model is responsible for threading `basket_abc123` through every relevant call. Two failure modes: hallucinating a slightly-wrong ID, or the ID falling out of context when the conversation is compacted.

The concern is real but likely overstated. Models already carry opaque identifiers across conversations constantly — file paths, URLs, commit hashes, PR numbers, UUIDs returned from prior tool calls. It is one of the things they are reliably good at, and each model generation is better at it. Compaction is the harder case, but it is a general problem for any long-horizon state; if the compactor is dropping live tool-call results, session-scoped state doesn't save you either — the model will have forgotten what's *in* the cart just as surely as it forgets the cart's ID. The [first-class state handles](#first-class-state-handles) follow-on sketches a direct mitigation.

#### "IDs become bearer tokens in chat history"

If `basket_id` can be pasted anywhere, isn't that an unauthenticated capability sitting in the user's chat log?

Only if the server treats possession of the ID as authorization. It shouldn't, and this proposal's server requirements say it MUST NOT. The ID is a *name*; the server checks `(id, auth_context)` on every call. Google Doc IDs sit in URLs and browser history; access is controlled by ACL, not ID secrecy. Same principle here.

#### "This removes an existing concept — it's a breaking change"

Sessions are in the spec today; removing them breaks anyone relying on them.

In practice the blast radius appears small. Very few servers use session-scoped state in the way the spec permits. The main population that does is stdio servers, and they are already relying on an *implicit* session — the process lifetime — rather than anything the protocol explicitly provides. For those, migrating to explicit IDs means adding a `create_*` tool and threading the handle: work, but mechanical work. The harder question is whether there is a migration window or a clean break; see [Backward Compatibility](#backward-compatibility).

## Backward Compatibility

This is a **breaking change** for servers that rely on protocol-level session state. The migration path depends on server category:

**Stdio servers using process-lifetime state.** These are the most common stateful servers today, and they are *not* broken by this proposal in their default deployment: the process lifetime still exists, and a server that keeps a single in-memory browser instance per process continues to work with a stdio client that spawns one process. What changes is that such a server cannot be transparently moved to an HTTP transport without adding explicit handle management — but that was already effectively true.

**HTTP servers using `Mcp-Session-Id`.** These are rare and must migrate to explicit handles. The migration is mechanical: replace the session-scoped state map with a handle-keyed state map, add a `create_*` tool, add the handle as a parameter to stateful tools.

**Clients.** Clients become *simpler*: they no longer need to track session identifiers, negotiate session creation, or worry about whether a given server is stateful. List-endpoint caching moves from "unsafe" to "encouraged."

Rollout is a clean break: sessions are removed in the next spec version, with no deprecation window. Servers that currently rely on session-scoped state simply stay on the current protocol version until they have migrated to explicit handles. Protocol version negotiation already handles mixed-version deployments — a client that supports both versions will speak the old protocol to an unmigrated server and the new one to everyone else. This avoids shipping a version where clients have to support both modes simultaneously, which would defeat the caching win (a client cannot cache list endpoints if *any* connected server might be session-scoped).

## Security Implications

### Handles are names, not capabilities

The main security consideration introduced by this SEP is that handles will end up in places session IDs never did — chat logs, subagent prompts, copy-paste buffers, potentially other users' screens. A server that treats possession of a handle as authorization has turned a name into a bearer token, and every one of those surfaces becomes a leak. The safe posture is the same one Google Doc IDs and GitHub PR numbers take: the ID identifies the resource, and the auth context on the request decides whether you can touch it. Servers that validate `(handle, auth_context)` on every call are fine regardless of where the handle has been.

This is guidance, not a protocol requirement — the protocol doesn't know what a handle is and can't enforce anything about how servers treat them. But it's the guidance that matters most.

## Open Questions

- **Handle durability metadata.** Should the `create_*` result include machine-readable durability info (a `ttl` field, a `destroy_at` timestamp) so the client can surface it to the user, or is a documented server-side policy sufficient?

## First-Class State Handles

*(Possible follow-on — not part of this SEP, noted here as where the path leads.)*

Everything above treats a handle as an opaque string. If the protocol instead gave handles a distinct type — with create/read/destroy semantics the client can reason about — hosts could build real UX on top:

- Show created handles in a sidebar; warn before abandoning ephemeral state; offer cleanup on conversation delete. Allow dragging state objects into new chats for re-use.
- Re-surface live handles to the model after context compaction, directly addressing the "model forgets the ID" objection. If the host knows which strings are state handles, it can preserve them across a compaction boundary the way it cannot preserve arbitrary tool output.
- Let servers ship a visualization for their state, in the same spirit as MCP Apps shipping UI for tool interactions — a basket handle renders as a live cart preview, a browser handle renders as a page thumbnail.

The sessionless change on its own is mostly simplification. This is where a user-visible win might live.

## Tools Returning Tools

*(Possible follow-on — not part of this SEP.)*

This SEP closes off one avenue for dynamic tool exposure: a server can no longer have `enable_admin_tools()` mutate what `tools/list` returns, because `tools/list` is now deployment-scoped. The workaround within this SEP's bounds is to expose everything at list time and enforce at call time, which works but means the full tool surface is always in the model's context.

A cleaner replacement would be to let a tool call return additional tool definitions as part of its result — `enable_admin_tools()` doesn't mutate a list, it hands back the admin tools directly. The client scopes those however it likes (per-conversation, per-subagent-tree), and the server still validates authorization at call time. This would also compose nicely with the handle pattern: `create_browser()` could return both a `browser_id` *and* the tools that operate on browsers, so a model that never creates a browser never has those tools in context at all.

That's a separate piece of work with its own schema and scoping questions, and is not proposed here.

## Reference Implementation

TBD.

An illustrative migration of a session-scoped Playwright server to explicit `create_browser(headless: bool) -> browser_id` / `destroy_browser(browser_id)` handles would be a useful artifact for the WG to evaluate the ergonomic cost.

