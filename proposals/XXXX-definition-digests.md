# SEP-XXXX: Definition Digests

- **Status**: Draft (discussion; not an accepted protocol change)
- **Type**: Standards Track
- **Created**: 2026-09-04
- **Author(s)**: TBD
- **Sponsor**: None
- **Related**: [PR #45](https://github.com/modelcontextprotocol/transports-wg/pull/45), [SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549), [SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension) (skills)
- **Schema fragment**: [`XXXX-definition-digests.ts`](XXXX-definition-digests.ts)

## Abstract

This SEP lets MCP Servers supply a digest with their CacheableResults.

Clients can return digests to the MCP Server, which can serve the call, serve it and flag that definitions have changed, or reject it if the digest is not serviceable.

The mechanism is advisory. Servers choose whether to supply digests and what to do with the ones they receive.

Extensions that define their own lists (`skills/list` for example) can participate using the same structure.

## Motivation

Hosts that cache Tool Lists can call tools after the Server has changed them. The `2026-07-28` specification `ttlMs` adds a "freshness hint, not a guarantee" and notes that:

> Servers MAY change the underlying data before TTL expires.

Tool definitions can change for many reasons; deployments, permissions, feature flags and user settings. Hosts can make tool call requests against stale schemas. Often standard validation will catch mismatches, but in pathological cases description and argument semantics may change and the model may issue tool calls that weren't intended.

The digest mechanism gives a server four options:
- **Ignore:** the request is handled exactly as today.
- **Honor:** the request is served against the definitions the digest describes, so in-flight call sequences and tasks finish against the tool set they started with.
- **Honor and signal:** as above, and the response tells the client to refresh when convenient.
- **Reject:** an error says which definitions are stale, before anything runs.

*Authors note: "Honor" may be difficult or SDK dependent, since the server must hold more than one request shape for the same tool or prompt identity.*

The mechanism works alongside the existing `ttlMs` hint. Clients may choose more aggressive caching strategies based on optimistic calling.

## Specification

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted as described in [BCP 14](https://www.rfc-editor.org/info/bcp14).

### The `digest` field

`CacheableResult` gains one optional field:

```ts
export interface CacheableResult extends Result {
  ttlMs: number;
  cacheScope: "public" | "private";
  /**
   * An opaque, deterministic identifier for the definitions this result
   * describes. Changes whenever they do.
   */
  digest?: string;
}
```

A result carries at most one digest. It covers the result payload with the envelope removed: everything except `resultType`, `_meta`, `ttlMs`, `cacheScope`, `digest`, and `nextCursor`. For a list, it covers the complete collection the caller can see, not the page in hand. The digest is identified by the method that produced it:

| Method | Digest covers |
|---|---|
| `server/discover` | `instructions`, `capabilities`, and `supportedVersions` together |
| `tools/list` | the complete tool list |
| `prompts/list` | the complete prompt list |
| `resources/list` | the complete resource list (descriptors, not contents) |
| `resources/templates/list` | the complete template list |
| `resources/read` | nothing; servers omit the field |
| an extension list, e.g. `skills/list` | as the extension defines |

An extension that defines a list operation and mirrors `ttlMs` and `cacheScope`, as `skills/list` does, **SHOULD** mirror `digest` the same way. A skills digest covers the catalog entries, not the files they point to, which already carry their own digests.

A digest **MUST** be deterministic and collision-resistant. Adding, removing, or changing a definition changes it. Ordering, page size, cursors, and TTL do not. An empty collection still has a digest.

Clients **MUST** treat digests as opaque strings and compare them only for equality.

A server **MUST** compute a digest using the same authorization and tool-selection context it uses to produce the result it sits on.

```json
{
  "resultType": "complete",
  "tools": [],
  "ttlMs": 60000,
  "cacheScope": "private",
  "digest": "sha256:..."
}
```

### Pagination

The [caching rules](https://modelcontextprotocol.io/specification/draft/server/utilities/caching) cache each page separately, keyed by cursor, with its own TTL and no cross-page consistency guarantee. The digest describes the *collection*, not the page.

- A server **SHOULD** return the same digest on every page. A server paging live data returns the digest as of each page, which may differ.
- A client **MUST NOT** combine pages with different digests. On a mismatch, whether between pages or from the server, it discards every page for that collection and starts again without a cursor.
- A re-fetched page whose digest matches the pages already held **MAY** be treated as re-validating them, including any whose TTL has lapsed.

### Sending known digests

A client **MAY** tell the server which digests it is working from, in any request `_meta`, as a map from the method that produced each digest to the digest:

```ts
export interface KnownDigests {
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
  "io.modelcontextprotocol/knownDigests"?: KnownDigests;
}
```

For example, the parameters of a `tools/call` request might look like this (other required `_meta` fields are omitted):

```json
{
  "name": "search",
  "arguments": { "query": "datasets" },
  "_meta": {
    "io.modelcontextprotocol/knownDigests": {
      "tools/list": "sha256:...",
      "server/discover": "sha256:..."
    }
  }
}
```

Known digests are hints, not preconditions. No capability flag is required. The `server/discover` digest is relevant to any operation, since instructions shape how the model uses everything else.

### Handling known digests

A server that receives known digests on `tools/call`, `prompts/get`, `resources/read`, or an extension's equivalent has four choices:

- **Ignore.** The request is handled exactly as it would be without hints.
- **Honor.** If the server still holds the definitions a known digest describes, it **MAY** serve the request under those definitions. This lets call sequences and tasks finish against the tool set they started with.
- **Honor and signal.** As above, but the server names the stale methods in result `_meta` so the client knows to refresh. The client **SHOULD** do so when convenient (for example after the model returns an `END_TURN` stop reason) and **MUST NOT** treat the result as an error or retry the request.
- **Reject.** If a known digest does not match and the server will not honor it, the server rejects the request as stale.

Signal and reject carry the same list, `staleDigests`: the methods whose digests did not match, never the current digests. In a result it goes in `_meta`; in a rejection it goes in error `data`.

```ts
export interface ResultMetaObject extends MetaObject {
  // Existing fields unchanged.
  "io.modelcontextprotocol/staleDigests"?: string[];
}
```

```json
{ "_meta": { "io.modelcontextprotocol/staleDigests": ["tools/list"] } }
```

```json
{ "staleDigests": ["tools/list", "skills/list"] }
```

A server **SHOULD** validate the digest before operation-specific validation and execution so that a changed schema is reported as stale rather than invalid arguments.

A standard error code needs to be allocated before this SEP is finalized; this draft does not propose a numeric code or an HTTP status.

A client receiving this error **SHOULD** refresh the affected definitions and then decide whether the operation still makes sense. Refreshing means fetching from the server: the client **MUST NOT** copy a new digest without also fetching the definitions.

## Rationale

**One digest per collection, not per primitive.** An earlier draft attached a digest to every primitive and made the check mandatory. That design could not detect newly added primitives, and it required every replica behind an endpoint to honor any digest the server had advertised. One digest per collection is simpler to compute and compare, and covers additions and removals. The cost is coarseness: any change to a collection invalidates requests against it, even if the specific tool the client wants is unchanged. It is still enough for draining, because a server that honors an old digest holds the whole old snapshot; it does not need a history per tool.

**A field on `CacheableResult`.** `ttlMs` says how long a result may be held and `cacheScope` says who may share it. The digest says what the result is, and is the thing a client checks when the TTL turns out not to have been a guarantee. Those three belong together, and every result that already carries the first two is one that this SEP wants to digest. The schema permits the field today: `Result` has an open index signature, and no result type forbids additional properties, so a server can emit `digest` now and a later schema change simply names it.

**Keyed by method.** A result carries one digest and the method says what it covers, so there is nothing to negotiate about structure on the response side. `server/discover` digests what discovery returns; a client that wants to know whether tools changed asks `tools/list`, which it was going to do anyway. The method only appears as a key when the client sends digests back, where a single request can vouch for several things at once. Methods are already unique, so `skills/list` or any future extension list joins the map without a naming rule, and one `staleDigests` list covers everything.

**The cost of checking.** Checking a single request means computing the digest of the whole collection, which can cost more than serving the request itself: a server that normally builds only the one tool being called must now build them all. Servers can limit this by supplying digests only where the complete collection is cheap to build, and ignoring hints elsewhere. Clients help by sending digests only when they hold one, so unchecked requests keep their existing cost.

**Independent of HTTP caching.** A digest identifies definitions, while an ETag identifies an HTTP representation of a particular page. Keeping them separate lets this SEP work over any transport, and lets a companion HTTP retrieval proposal define ETags on its own terms.

## Backward Compatibility

This SEP adds optional fields and does not change the behavior of existing requests. Clients can ignore the digest. Servers can ignore known digests, including after supplying them. Implementations that do not recognize the new fields continue to work as they do today.

## Security Implications

A digest carries the same confidentiality and authorization context as the definitions it describes. For example, a tool list may be identical for many users while instructions name the individual user; the `server/discover` result is then private to that user even though the `tools/list` result might not be. Digests grant no access. They do not prove that a server's implementation is unchanged, only its advertised definitions, and a server that honors an old digest still enforces current permissions.

The same care applies to the cache scope of a result carrying a digest. A result may be marked `public` only if every caller would receive the same result, not merely if it contains no user data. For example, an anonymous caller asking for the tool list might receive three tools, while a signed-in caller making the same request should receive five, because two of the tools require sign-in. The anonymous list contains no user data, but it is not public: if the two callers share a cache, the signed-in caller is served the shorter list without reaching the server, and their known digests then fail to match.

## Reference Implementation

The [HF MCP server](https://github.com/huggingface/hf-mcp-server) implements the response field, the request map (under the application key `huggingface.co/known-digests`), and the rejection path as described here. It began with a keyed map in result `_meta`; moving to the top-level `digest` field took under an hour and six files, most of them tests. No SDK change was needed: the SDK's handler return types accept the extra field without a cast, and its result schemas are loose objects, so `digest` passes validation on both sides and the TypeScript client sees it. It does not yet honor or signal. Listings are unpaginated.

- It digests `tools/list` and `server/discover` (instructions only, so far), and checks known digests on `tools/call` only.
- A mismatch is rejected before tool lookup, argument validation, or execution, with the application error code `-32987` (outside JSON-RPC's reserved range) and `data: { "staleDigests": [...] }`. Unknown keys and non-string hints are ignored.
- Digests are supplied only where the complete tool list is cheap to build: anonymous requests and requests for a named, fixed set of tools. Other requests get no digest, their hints are ignored, and they keep the existing single-tool fast path. Digested results also carry `private` TTL cache hints; anonymous lists are not `public`, because they omit tools that require sign-in.
- Tools are sorted by name, each tool's own `_meta` is included, and canonicalized JSON is hashed with SHA-256. Result-envelope metadata is excluded. For testing, a deploy-wide or runtime salt changes every digest without changing definitions, forcing clients through the mismatch path.

Client integration in [fast-agent](https://github.com/evalstate/fast-agent) is in progress. It is optimistic: it sends known digests with each call and refreshes definitions when a call is rejected.

### Testing Plan

Implementations should test:

- Digests are deterministic, and change when definitions change.
- Empty collections have digests, and absent instructions differ from empty instructions.
- Digests are unaffected by ordering, page size, cursor, and TTL.
- Every page of a snapshot listing carries the same digest; a change mid-pagination is reflected on later pages.
- A client discards all pages when any page disagrees, and when the server reports a mismatch.
- Existing result fields and `_meta` are preserved.
- Digests are isolated between callers with different authorization contexts.
- Requests are handled normally when hints are absent or ignored.
- When checking is enabled, stale requests are rejected before any side effect.
- When honoring is enabled, a request carrying an old digest runs against the old definitions, and one carrying an unknown digest is rejected.
- When signaling, the result names the stale methods and no digests; the client uses the result and refreshes before its next dependent call.
- Methods the server does not digest, extension methods, and malformed hints do not cause a rejection.
- After a mismatch, the client refreshes from the server rather than from a still-fresh cached list.

## Open Questions

- Whether `resources/read` should ever carry a digest (of its contents), and if so how a client would send it back, since its cache key includes the `uri` and `KnownDigests` is keyed by method alone.
- Whether a re-fetched page whose digest matches should be allowed to re-validate pages whose TTL has lapsed. This draft says **MAY**. It is the only place the digest affects freshness, and it is what makes per-page re-fetch useful; without it a client would re-fetch every expired page in turn to learn nothing new.
- Whether `server/discover` should be able to carry the list digests as well as its own, so a client can learn that nothing changed without re-listing. This draft says no, to keep one digest per result; the cost is one extra round trip per collection after reconnect.
- Whether `server/discover` should digest `supportedVersions` and `capabilities` along with `instructions`. This draft says yes, on the rule that a digest covers the payload minus the envelope, so the same rule serves extension results.
- How long a server that honors old digests should keep them, and whether it should say so. This draft leaves it to the server.
- How the skills extension (or any extension whose listing may be deliberately partial) should define its digest, given that "the complete set the caller can see" is then the set the server chooses to enumerate.
- The canonicalization, and which definition fields a digest covers (for example, whether a tool's own `_meta` is included).
- Whether servers must provide a consistent snapshot across pages or may require clients to restart.
- The standard error code for a digest mismatch.
