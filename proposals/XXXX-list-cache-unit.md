# SEP-XXXX: The Collection as the Cache Unit for List Results

- **Status**: Draft (discussion; not an accepted protocol change)
- **Type**: Standards Track
- **Created**: 2026-10-06
- **Author(s)**: TBD
- **Sponsor**: None
- **Related**: [SEP-2549](https://modelcontextprotocol.io/seps/2549-TTL-for-list-results) (TTL for List Results), [Caching](https://modelcontextprotocol.io/specification/draft/server/utilities/caching), [Pagination](https://modelcontextprotocol.io/specification/draft/server/utilities/pagination), [Definition Tags](XXXX-definition-tags.md)

## Abstract

This SEP changes the cache key for paginated list results so that it no longer includes the `cursor`. The unit a client caches is the complete collection returned by a list method, assembled from however many pages the server chose to send, with a single freshness window. Individual pages are not cached, and a stale collection is re-fetched from the beginning.

No schema changes. `ttlMs` and `cacheScope` keep their types and continue to appear on every page.

## Motivation

The [caching rules](https://modelcontextprotocol.io/specification/draft/server/utilities/caching) identify a cached response by method plus the parameters that affect the result, and name `cursor` as one of those parameters. Each page is therefore a separate cache entry with its own TTL, and the specification acknowledges that there is "no cross-page consistency guarantee" and that "clients may observe duplicates or gaps". A client that needs a consistent list is told to start again without a cursor.

This models pages as if they were independent resources. They are not. A cursor is an opaque position token; the server sets the page size and may change it; and nothing in the protocol gives a page an identity that survives a change to the list. A client cannot reason about a page in isolation, and in practice no client uses one: the model is shown the complete tool list, and a host merges complete lists from every server it is connected to. The thing the client holds, uses, and needs to know the freshness of is the collection.

Per-page caching also produces mixed freshness inside a single list. Page one may be fresh while page three has expired, and re-fetching page three by its cursor against a list that has changed may return a page that no longer fits with page one. The result is a cached list that is neither the old one nor the new one. `notifications/tools/list_changed` already invalidates at the level of the list, not the page, which is the grain this SEP adopts for TTL as well.

Finally, the [definition tags](XXXX-definition-tags.md) proposal defines its tag over the collection and must add rules to reconcile that with per-page caching. Making the collection the cache unit removes that friction.

## Specification

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted as described in [BCP 14](https://www.rfc-editor.org/info/bcp14).

### Cache key

For `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, and any extension list method that adopts `CacheableResult`, the cache key is the method together with the request parameters that affect the result **excluding `cursor`**. A client **MUST NOT** cache a single page as a standalone entry.

`resources/read` and `server/discover` are unchanged.

### Assembling a collection

A client fetches a collection by issuing the list request without a cursor and following `nextCursor` until it is absent. The concatenation of the pages is the collection, and that is what the client caches.

The collection's `ttlMs` is the smallest `ttlMs` of any page received, and `cacheScope` is `private` if any page is `private`. The freshness clock starts when the **first** page was received, so a slow pagination does not extend the window.

### Expiry and refresh

When a cached collection becomes stale, the client **SHOULD** re-fetch from the beginning. A client **MUST NOT** re-issue a cursor from a stale collection to refresh part of it.

If pagination fails partway through (invalid cursor, transport error), the client discards the partial collection. It **MAY** continue to serve a previously cached collection in the meantime, consistent with the existing rule allowing stale responses when re-fetching fails.

### Partial collections

A client that stops paginating early, for example because it only needs the first page to render a picker, holds a partial collection. It **MAY** use it immediately but **MUST NOT** cache it as the collection. It **MAY** cache it marked as partial, in which case any operation that needs the complete list treats the entry as a miss.

### Servers

Servers are unaffected. They continue to return `ttlMs` and `cacheScope` on every page. Servers **SHOULD** return the same `ttlMs` and `cacheScope` on every page of one collection; the current permission to vary `ttlMs` by page becomes moot but is not withdrawn, since the client takes the minimum.

### Interaction with notifications

A `list_changed` notification invalidates the whole cached collection, as today. There is no partial invalidation.

### Interaction with definition tags

If [definition tags](XXXX-definition-tags.md) are adopted, the tag is already defined over the collection. Under this SEP a client compares tags across the pages it is assembling; a mismatch means the list changed mid-pagination and the client starts again. The pagination rules in that proposal reduce to this one sentence.

## Rationale

The alternative is to leave per-page caching in place and ask clients to manage consistency themselves. The specification already does this, and the result is a rule that pages are independently cacheable followed immediately by a warning that they may not be consistent and that a client wanting consistency should ignore the page cache and re-fetch. That is the behavior this SEP makes normative.

Per-page caching would be worthwhile if lists were large enough that re-fetching the whole collection was costly and if a page could be refreshed meaningfully on its own. Neither holds for MCP definition lists. They are small by design, since every tool definition is a cost in the model's context, and a page has no identity that survives a change to the list.

## Backward Compatibility

This changes client behavior only. No wire format changes. A client following this SEP interoperates with every existing server. A server following the old guidance (different `ttlMs` per page) is handled by taking the minimum.

Clients that currently cache per page and re-fetch individual pages will, after this change, re-fetch the whole collection instead. For the list sizes seen in practice this is not a measurable cost.

Companion HTTP proposals that map list pages onto HTTP GET with per-page `ETag` are unaffected: an HTTP validator identifies a transport representation, and this SEP concerns the protocol-level cache a client builds from the assembled result.

## Security Considerations

None beyond the existing caching rules. Taking the most restrictive `cacheScope` across pages means a collection where one page is `private` is never shared.

## Open Questions

- Whether a client should be permitted to serve a complete-but-stale collection while re-paginating, or must block. This draft allows it, matching the existing stale-on-error rule.
- Whether the minimum-`ttlMs` rule should instead be the first page's value, on the grounds that servers are told to keep them equal.
- Whether `resources/list` on servers with very large resource sets is an exception worth carving out. This draft says no: a client that cannot hold the collection should use `resources/templates/list` and `resources/read`.
