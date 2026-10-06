# SEP-XXXX: Definition Tags

- **Status**: Draft (discussion; not an accepted protocol change)
- **Type**: Standards Track
- **Created**: 2026-09-04
- **Author(s)**: TBD
- **Sponsor**: None
- **Related**: [PR #45](https://github.com/modelcontextprotocol/transports-wg/pull/45), [SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549), [SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension) (skills)
- **Schema fragment**: [`XXXX-definition-tags.ts`](XXXX-definition-tags.ts)

## Abstract

This SEP lets MCP Servers supply a *definition tag* with their CacheableResults: an opaque string that changes whenever the definitions in the result do.

Clients must return tags to the MCP Server, which can serve the call, serve it and flag that definitions have changed, or reject it if the tag is not serviceable.

The mechanism is advisory. Servers choose whether to supply tags and what to do with the ones they receive.

Extensions that define their own lists (`skills/list` for example) can participate using the same structure.

## Motivation

Hosts that cache Tool Lists can call tools after the Server has changed them. The `2026-07-28` specification `ttlMs` adds a "freshness hint, not a guarantee" and notes that:

> Servers MAY change the underlying data before TTL expires.

Tool definitions can change for many reasons; deployments, permissions, feature flags and user settings. Hosts can make tool call requests against stale schemas. Often standard validation will catch mismatches, but in pathological cases description and argument semantics may change and the model may issue tool calls that weren't intended.

The tag mechanism gives a server four options:
- **Ignore:** the request is handled exactly as today.
- **Honor:** the request is served against the definitions the tag describes, so in-flight call sequences and tasks finish against the tool set they started with.
- **Honor and signal:** as above, and the response tells the client to refresh when convenient.
- **Reject:** an error says which definitions are stale, before anything runs.

*Authors note: "Honor" may be difficult or SDK dependent, since the server must hold more than one request shape for the same tool or prompt identity.*

The mechanism works alongside the existing `ttlMs` hint. Clients may choose more aggressive caching strategies based on optimistic calling.

### Use Cases

The scenarios below describe how this feature is expected to be used.

**Server**

- **Deployments.** During a rolling deploy, successive requests from one client can land on new and old instances. With tags, an instance that receives a request built against the other version's definitions can honor it, flag it, or reject it before anything runs, instead of silently misinterpreting the arguments.

- **Versioning.** A server that wants to evolve its tool surface can keep more than one definition set live and use the known tag to select the one a client is working from. Clients migrate to the new set when they refresh, rather than the moment it is deployed.

- **Task draining.** A long-running task or multi-step call sequence may span a definition change that would break it midway. Honoring the tag the sequence started with lets the server finish the work against the original definitions, then retire them once nothing depends on them.

**Client**

- **Lazy initialization.** A client can reconnect and start calling tools from its cached definitions immediately, without a `tools/list` round trip. If the definitions have moved on, the server says so and the client refreshes only then. Existing optimistic cache mechanisms risk tool definition drift.

- **On-demand refresh.** A client can use its cached definitions optimistically and let the server tell it when they are out of date. Staleness is caught at the point of use rather than at the end of the `ttlMs` window, with no polling or subscription needed.

- **Clearer errors.** Without tags, a schema change surfaces as an argument validation failure that the model has no way to reason about. A tag rejection names the stale method instead, so the client refreshes and retries rather than treating it as a model error.

- **Long-lived clients.** A client can keep using the same server for weeks or months without subscribing to change notifications. The tags it sends on each call are enough for the server to tell it when a refresh is needed.

**Pattern: progressive disclosure via a search tool**

- A server can expose a small initial tool set with a `search` (or similar discovery) tool, enabling further tools based on what the client searches for. The search result carries `staleTags: ["tools/list"]`, which tells the client the catalogue has grown; it refreshes and the newly unlocked tools become available to the model, with no extra protocol machinery.

## Specification

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted as described in [BCP 14](https://www.rfc-editor.org/info/bcp14).

### The `tag` field

`CacheableResult` gains one optional field, `tag`, carrying the result's definition tag. The rest of this document says "tag" for short:

```ts
export interface CacheableResult extends Result {
  ttlMs: number;
  cacheScope: "public" | "private";
  /**
   * An opaque, deterministic identifier for the definitions this result
   * describes. Changes whenever they do.
   */
  tag?: string;
}
```

A result carries at most one tag. It covers the result payload with the envelope removed: everything except `resultType`, `_meta`, `ttlMs`, `cacheScope`, `tag`, and `nextCursor`. For a list, it covers the complete collection the caller can see, not the page in hand. The tag is identified by the method that produced it:

| Method | Tag covers |
|---|---|
| `server/discover` | `instructions`, `capabilities`, and `supportedVersions` together |
| `tools/list` | the complete tool list |
| `prompts/list` | the complete prompt list |
| `resources/list` | the complete resource list (descriptors, not contents) |
| `resources/templates/list` | the complete template list |
| `resources/read` | nothing; servers omit the field |
| an extension list, e.g. `skills/list` | as the extension defines |

An extension that defines a list operation and mirrors `ttlMs` and `cacheScope`, as `skills/list` does, **SHOULD** mirror `tag` the same way. A skills tag covers the catalog entries, not the files they point to, which already carry their own content digests.

A tag **MUST** be deterministic and collision-resistant. Adding, removing, or changing a definition changes it. Ordering, page size, cursors, and TTL do not. An empty collection still has a tag.

Clients **MUST** treat tags as opaque strings and compare them only for equality.

A server **MUST** compute a tag using the same authorization and tool-selection context it uses to produce the result it sits on.

```json
{
  "resultType": "complete",
  "tools": [],
  "ttlMs": 60000,
  "cacheScope": "private",
  "tag": "sha256:..."
}
```

### Pagination

The [caching rules](https://modelcontextprotocol.io/specification/draft/server/utilities/caching) cache each page separately, keyed by cursor, with its own TTL and no cross-page consistency guarantee. The tag describes the *collection*, not the page.

- A server **SHOULD** return the same tag on every page. A server paging live data returns the tag as of each page, which may differ.
- A client **MUST NOT** combine pages with different tags. On a mismatch, whether between pages or from the server, it discards every page for that collection and starts again without a cursor.
- A re-fetched page whose tag matches the pages already held **MAY** be treated as re-validating them, including any whose TTL has lapsed.

### Sending known tags

A client **MAY** tell the server which tags it is working from, in any request `_meta`, as a map from the method that produced each tag to the tag:

```ts
export interface KnownTags {
  "server/discover"?: string;
  "tools/list"?: string;
  "prompts/list"?: string;
  "resources/list"?: string;
  "resources/templates/list"?: string;
  /** Extension list methods, e.g. "skills/list". */
  [method: string]: string | undefined;
}

export interface RequestMetaObject extends MetaObject {
  // Existing fields unchanged.
  "io.modelcontextprotocol/knownTags"?: KnownTags;
}
```

For example, the parameters of a `tools/call` request might look like this (other required `_meta` fields are omitted):

```json
{
  "name": "search",
  "arguments": { "query": "datasets" },
  "_meta": {
    "io.modelcontextprotocol/knownTags": {
      "tools/list": "sha256:...",
      "server/discover": "sha256:..."
    }
  }
}
```

Known tags are hints, not preconditions. No capability flag is required. The `server/discover` tag is relevant to any operation, since instructions shape how the model uses everything else.

A client **MAY** send every tag it holds, and **SHOULD** send at least the `server/discover` tag and the tag for the list the operation depends on (see [Relevance](#relevance)). Sending all of them costs a few hundred bytes and lets the server tell the client about changes to lists the request did not use.

### Handling known tags

A server that receives known tags on `tools/call`, `prompts/get`, `resources/read`, or an extension's equivalent has four choices:

- **Ignore.** The request is handled exactly as it would be without hints.
- **Honor.** If the server still holds the definitions a known tag describes, it **MAY** serve the request under those definitions. This lets call sequences and tasks finish against the tool set they started with.
- **Honor and signal.** As above, but the server names the stale methods in result `_meta` so the client knows to refresh. The client **SHOULD** do so when convenient (for example after the model returns an `END_TURN` stop reason) and **MUST NOT** treat the result as an error or retry the request.
- **Reject.** If a known tag does not match and the server will not honor it, the server rejects the request as stale.

Signal and reject carry the same list, `staleTags`: the methods whose tags did not match, never the current tags. In a result it goes in `_meta`; in a rejection it goes in error `data`.

```ts
export interface ResultMetaObject extends MetaObject {
  // Existing fields unchanged.
  "io.modelcontextprotocol/staleTags"?: string[];
}
```

```json
{ "_meta": { "io.modelcontextprotocol/staleTags": ["tools/list"] } }
```

```json
{ "staleTags": ["tools/list", "skills/list"] }
```

#### Relevance

A server **MUST** only reject a request for a tag that is relevant to it. Stale tags that are not relevant **MAY** be named in `staleTags` on the result, but never cause a rejection. A stale `prompts/list` tag does not fail a `tools/call`.

| Operation | Relevant tags |
|---|---|
| any | `server/discover` |
| `tools/call` | `tools/list` |
| `prompts/get` | `prompts/list` |
| `resources/read` | `resources/list`, `resources/templates/list` |
| an extension operation | as the extension defines |

A server **SHOULD** validate the tag before operation-specific validation and execution so that a changed schema is reported as stale rather than invalid arguments.

A standard error code needs to be allocated before this SEP is finalized; this draft does not propose a numeric code or an HTTP status.

A client receiving this error **SHOULD** refresh the affected definitions and then decide whether the operation still makes sense. Refreshing means fetching from the server: the client **MUST NOT** copy a new tag without also fetching the definitions.

## Rationale

**One tag per collection, not per primitive.** An earlier draft attached a tag to every primitive and made the check mandatory. That design could not detect newly added primitives, and it required every replica behind an endpoint to honor any tag the server had advertised. One tag per collection is simpler to compute and compare, and covers additions and removals. The cost is coarseness: any change to a collection invalidates requests against it, even if the specific tool the client wants is unchanged. It is still enough for draining, because a server that honors an old tag holds the whole old snapshot; it does not need a history per tool.

**The list is the definitions.** In MCP a list result does not point at tools, prompts, or templates to be fetched separately; it contains them in full. The complete definition a client will ever hold is the entry in the list. A tag on the list therefore covers exactly what the client works from, and a change to a tool's arguments is a change to the list because there is nowhere else for it to appear. There is no lower-level object to version, and nothing to re-fetch but the list itself.

**Not one tag for the whole server, either.** A single tag over everything would be simpler still, but tools, prompts, and resources are separate capabilities, each with its own `list_changed` notification, its own `CacheableResult`, and its own fetch. A resource list that changes every few seconds would force a client to re-fetch a tool list that changes once a quarter, and an extension list would be folded into a value it does not control. Per-list tags sit where the protocol already notifies and caches.

Resources are the exception that shows the rule. `resources/list` returns descriptors, and the content a client actually uses is fetched by URI and may be individually subscribed. The list is a set of references rather than the definitions themselves, which is why `resources/read` carries no tag and remains an open question below.

**A field on `CacheableResult`.** `ttlMs` says how long a result may be held and `cacheScope` says who may share it. The tag says what the result is, and is the thing a client checks when the TTL turns out not to have been a guarantee. Those three belong together, and every result that already carries the first two is one that this SEP wants to tag. The schema permits the field today: `Result` has an open index signature, and no result type forbids additional properties, so a server can emit `tag` now and a later schema change simply names it.

**Keyed by method.** A result carries one tag and the method says what it covers, so there is nothing to negotiate about structure on the response side. `server/discover` tags what discovery returns; a client that wants to know whether tools changed asks `tools/list`, which it was going to do anyway. The method only appears as a key when the client sends tags back, where a single request can vouch for several things at once. Methods are already unique, so `skills/list` or any future extension list joins the map without a naming rule, and one `staleTags` list covers everything.

**The cost of checking.** Checking a single request means computing the tag of the whole collection, which can cost more than serving the request itself: a server that normally builds only the one tool being called must now build them all. Servers can limit this by supplying tags only where the complete collection is cheap to build, and ignoring hints elsewhere. Clients help by sending tags only when they hold one, so unchecked requests keep their existing cost.

**Naming.** Earlier drafts called this a *digest*. The skills extension already uses `digest` for a verifiable content hash of a file, which a client may recompute and check; this value is the opposite, an opaque string compared only for equality, so it needs a different name. "Version" was avoided because the schema already uses it for `Implementation.version`, `supportedVersions`, and protocol revisions, and because it suggests an ordering that tags do not have. In prose it is a *definition tag*; on the wire it is just `tag`, `knownTags`, and `staleTags`, since the method that produced it already says what it covers.

**Independent of HTTP caching.** A tag identifies definitions, while an ETag identifies an HTTP representation of a particular page. Keeping them separate lets this SEP work over any transport, and lets a companion HTTP retrieval proposal define ETags on its own terms.

## Backward Compatibility

This SEP adds optional fields and does not change the behavior of existing requests. Clients can ignore the tag. Servers can ignore known tags, including after supplying them. Implementations that do not recognize the new fields continue to work as they do today.

## Security Implications

A tag carries the same confidentiality and authorization context as the definitions it describes. For example, a tool list may be identical for many users while instructions name the individual user; the `server/discover` result is then private to that user even though the `tools/list` result might not be. Tags grant no access. They do not prove that a server's implementation is unchanged, only its advertised definitions, and a server that honors an old tag still enforces current permissions.

The same care applies to the cache scope of a result carrying a tag. A result may be marked `public` only if every caller would receive the same result, not merely if it contains no user data. For example, an anonymous caller asking for the tool list might receive three tools, while a signed-in caller making the same request should receive five, because two of the tools require sign-in. The anonymous list contains no user data, but it is not public: if the two callers share a cache, the signed-in caller is served the shorter list without reaching the server, and their known tags then fail to match.

## Reference Implementation

The [HF MCP server](https://github.com/huggingface/hf-mcp-server) implements the response field, the request map (under the application key `huggingface.co/known-digests`), and the rejection path as described here. It predates the rename from "digest" to "tag" and still uses the earlier wire names (`digest`, `staleDigests`).

- It tags `tools/list` and `server/discover` (instructions only, so far), and checks known tags on `tools/call` only.
- A mismatch is rejected before tool lookup, argument validation, or execution, with the application error code `-32987` (outside JSON-RPC's reserved range) and `data: { "staleDigests": [...] }`. Unknown keys and non-string hints are ignored.
- Tags are supplied only where the complete tool list is cheap to build: anonymous requests and requests for a named, fixed set of tools. Other requests get no tag, their hints are ignored, and they keep the existing single-tool fast path. Tagged results also carry `private` TTL cache hints; anonymous lists are not `public`, because they omit tools that require sign-in.
- Tools are sorted by name, each tool's own `_meta` is included, and canonicalized JSON is hashed with SHA-256. Result-envelope metadata is excluded. For testing, a deploy-wide or runtime salt changes every tag without changing definitions, forcing clients through the mismatch path.

Client integration in [fast-agent](https://github.com/evalstate/fast-agent) is in progress. It is optimistic: it sends known tags with each call and refreshes definitions when a call is rejected.

### Testing Plan

Implementations should test:

- Tags are deterministic, and change when definitions change.
- Empty collections have tags, and absent instructions differ from empty instructions.
- Tags are unaffected by ordering, page size, cursor, and TTL.
- Every page of a snapshot listing carries the same tag; a change mid-pagination is reflected on later pages.
- A client discards all pages when any page disagrees, and when the server reports a mismatch.
- Existing result fields and `_meta` are preserved.
- Tags are isolated between callers with different authorization contexts.
- Requests are handled normally when hints are absent or ignored.
- When checking is enabled, stale requests are rejected before any side effect.
- When honoring is enabled, a request carrying an old tag runs against the old definitions, and one carrying an unknown tag is rejected.
- When signaling, the result names the stale methods and no tags; the client uses the result and refreshes before its next dependent call.
- Methods the server does not tag, extension methods, and malformed hints do not cause a rejection.
- A stale tag that is not relevant to the operation is signaled, not rejected.
- After a mismatch, the client refreshes from the server rather than from a still-fresh cached list.

## Open Questions

- Whether `resources/read` should ever carry a tag (of its contents), and if so how a client would send it back, since its cache key includes the `uri` and `KnownTags` is keyed by method alone.
- Whether a re-fetched page whose tag matches should be allowed to re-validate pages whose TTL has lapsed. This draft says **MAY**. It is the only place the tag affects freshness, and it is what makes per-page re-fetch useful; without it a client would re-fetch every expired page in turn to learn nothing new.
- Whether `server/discover` should be able to carry the list tags as well as its own, so a client can learn that nothing changed without re-listing. This draft says no, to keep one tag per result; the cost is one extra round trip per collection after reconnect.
- Whether the `server/discover` tag should cover `supportedVersions` and `capabilities` along with `instructions`. This draft says yes, on the rule that a tag covers the payload minus the envelope, so the same rule serves extension results.
- How long a server that honors old tags should keep them, and whether it should say so. This draft leaves it to the server.
- How the skills extension (or any extension whose listing may be deliberately partial) should define its tag, given that "the complete set the caller can see" is then the set the server chooses to enumerate.
- The canonicalization, and which definition fields a tag covers (for example, whether a tool's own `_meta` is included).
- Whether servers must provide a consistent snapshot across pages or may require clients to restart.
- The standard error code for a tag mismatch.
