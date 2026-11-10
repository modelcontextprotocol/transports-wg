# SEP-XXXX: HTTP Retrieval and Caching of MCP Lists

- **Status**: Exploratory draft (working group; not an accepted protocol change)
- **Type**: Standards Track
- **Created**: 2026-09-08
- **Author(s)**: TBD
- **Sponsor**: None
- **Related**: SEP-2243 (HTTP Header Standardization), SEP-2549 (TTL for List Results), SEP-2127 (Server Card proposal), [definition versions](XXXX-primitive-digests-companion.md)

> Rough discussion draft. Endpoint syntax and discovery fields below are illustrative, not registered or agreed. Requirements describe a candidate design, not current MCP requirements.

## Abstract

Allow HTTP clients to retrieve MCP primitive lists using optional, discoverable GET representations. This enables ordinary HTTP caching and conditional revalidation using `Cache-Control`, `ETag`, and `If-None-Match`, without requiring caches to interpret JSON-RPC POST bodies.

The existing MCP endpoint remains the server's identity and OAuth protected resource. GET list representations are alternate retrieval forms of that server's lists, not new MCP servers or independent OAuth audiences. Existing POST methods remain available. This proposal does not require a Server Card and does not place private lists in public discovery metadata.

## Motivation and scope

Current Streamable HTTP sends JSON-RPC requests using POST to a single endpoint. SEP-2243 exposes routing information in headers, but does not define GET list retrieval. An `ETag` header alone does not bridge this gap: the `If-None-Match` / `304 Not Modified` revalidation flow applies to GET/HEAD, not POST. POST has limited cacheability, but a cached POST response cannot satisfy a later POST.

This proposal covers only:

- `tools/list`
- `prompts/list`
- `resources/list`
- `resources/templates/list`

It does not expose arbitrary RPC methods through GET, cache tool execution, or define content caching for `resources/read`. Definition versions provide advisory change detection; HTTP ETags validate a list-page representation. These are independent mechanisms.

### Protocol cache identity versus HTTP validators

These mechanisms identify different things:

| Mechanism          | Identifies                                                                                                                     |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Protocol cache key | A logical list result: server, method, parameters/cursor, authorization context, and other supported result-affecting context. |
| HTTP cache key     | A request's method and target URI, with representation variants selected through `Vary`.                                       |
| HTTP ETag          | A version of the selected HTTP representation; it is a validator, not a cache key.                                             |

A protocol-level list key that changes when list contents change is better described as a list validator. It is not automatically an HTTP ETag: an HTTP page representation may include pagination, metadata, or negotiated differences outside that validator's coverage. Reusing a protocol validator as an ETag requires explicitly defining its coverage and satisfying HTTP validator semantics.

The definition-version companion identifies complete definition collections and server instructions, not HTTP page representations. Its advisory digests remain independent of both cache-key mechanisms.

GET is needed here for integration with ordinary HTTP caching infrastructure, not for protocol-level caching itself. MCP-level caching already works over POST and STDIO; a separate protocol-level conditional-list mechanism could also work over those transports without GET.

The Server Card is peripheral: it is one possible discovery location for this optional HTTP mapping, not a cache key, a validator, or a dependency of the caching design.

## Candidate design

### 1. Keep the MCP endpoint; add a GET representation selector

Prefer the same origin and endpoint path, with query parameters selecting the representation:

```http
GET /tenant/acme/mcp?mcp_list=tools HTTP/1.1
Authorization: Bearer <access-token>
MCP-Protocol-Version: <supported-version>
Accept: application/json
```

Illustrative selectors are `tools`, `prompts`, `resources`, and `resource-templates`. An optional `cursor` parameter identifies a subsequent page. GET has no request body. This is an HTTP representation mapping, not a JSON-RPC request sent using GET.

A single MCP endpoint path is retained, but each list/page has a distinct HTTP target URI. Servers route explicitly recognized list GETs separately from POST. An unqualified GET retains the applicable transport-version behavior; older SSE GET support must not be interpreted as list retrieval.

Clients use an explicitly advertised retrieval template rather than inventing URLs or stripping query parameters from their configured endpoint. Existing endpoint query parameters must be preserved. Collision rules, duplicate-parameter rejection, encoding, and canonical URL construction need specification before adoption.

Only parameters defined by this mapping are supported. Unknown or repeated selectors are rejected rather than ignored. Requests requiring additional result-affecting context, client interaction, or multi-round-trip processing use POST instead. Initial implementation scope excludes session-dependent lists; session identifiers must not be placed in URLs.

### 2. Discover support without making Server Cards mandatory

A server advertises an optional HTTP-list-retrieval descriptor through the protocol's applicable discovery/capability mechanism. Conceptually it identifies:

- The canonical MCP endpoint / protected-resource identity.
- The supported list methods and protocol versions.
- A retrieval URL template and its parameter mapping.

The exact descriptor field and placement are open questions. Until these are standardized, this draft is not an interoperable extension.

A future Server Card at `.well-known/mcp.json` may carry the same descriptor for discovery before an RPC exchange. The card should advertise where lists can be requested, not publish authenticated list contents. A deployment without a card can advertise through ordinary MCP discovery and gain caching benefits on subsequent retrievals.

A host-level card must bind a descriptor to a specific MCP endpoint. One origin can host many tenants or servers; finding a card at the origin does not establish that all its URLs belong to the configured server. Clients must verify that binding before using a descriptor.

The Server Card is not OAuth Protected Resource Metadata. It does not replace RFC 9728 discovery or authorize forwarding a token. This draft does not register `.well-known/mcp.json`; it depends on alignment with the separate Server Card work if that discovery path is used.

### 3. Return a stable result representation

A successful GET returns `200 OK`, `Content-Type: application/json`, and the corresponding MCP list **result object**, not a JSON-RPC envelope:

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: private, max-age=60, must-revalidate
Vary: Authorization, MCP-Protocol-Version, Accept
ETag: "tools-page-v7"

{
  "tools": [],
  "ttlMs": 60000,
  "cacheScope": "private"
}
```

There is no request-specific JSON-RPC `id` to replay. The ordinary result schema, list visibility rules, and pagination semantics apply. For the same authorization and supported request context, GET and POST must describe the same list.

Each page is independently cacheable and has its own validator. The ETag validates the selected page representation, including relevant metadata and pagination information, not merely the definition collection digest. Strong and weak validators follow HTTP rules; neither is specified here as a particular hash algorithm. No cross-page snapshot guarantee is added.

The GET path does not emit SSE or embedded requests for client input. HTTP errors are not cached under this initial profile; the exact error representation and a distinguishable "use POST" response remain to be defined. An authorization denial must never be interpreted as an empty list.

### 4. Preserve OAuth resource identity and authorization

For an OAuth-protected server whose canonical resource is:

```text
https://example.com/tenant/acme/mcp
```

the OAuth `resource` parameter remains that identifier when fetching:

```text
https://example.com/tenant/acme/mcp?mcp_list=tools
```

The retrieval query is not a new OAuth audience. This association is established by the extension's validated descriptor and server configuration, not by a general rule that clients can remove URL queries. Servers validate token audience against the canonical protected resource and apply the same list permissions as POST. Same-origin placement alone does not establish a shared audience across tenants.

Clients send access tokens in `Authorization`, never in URLs or cursors. No new OAuth grant or blanket discovery scope is introduced. Listing and invoking a primitive remain separately authorized; seeing a cached tool definition never grants permission to call it.

GET endpoints use MCP's existing OAuth challenge and scope-handling rules:

- Missing/invalid credentials produce the appropriate `401` challenge.
- Insufficient scope uses the existing `403` / `insufficient_scope` flow, with minimum required scope guidance.
- Challenges identify the canonical server's RFC 9728 Protected Resource Metadata using `resource_metadata`.
- Clients follow existing authorization-server discovery and validation rules; a card does not override them.

For example, the metadata URL may be `https://example.com/.well-known/oauth-protected-resource/tenant/acme/mcp`. Its `resource` identifies the canonical server, not an individual list page. Metadata fallback must be based on the canonical MCP endpoint rather than treating the retrieval query as a new resource.

**Initial restriction:** retrieval templates use the configured MCP endpoint's origin and path. Clients do not automatically follow list redirects or forward bearer tokens to another endpoint. Cross-origin CDN URLs and independently hosted list services are deferred; they require explicit trust and audience semantics. A reverse-proxy CDN behind the existing origin is still possible.

Authorization and representation selection happen **before** conditional validation. An invalid token or denied caller receives an authorization error, not `304`, even if the supplied ETag matches something previously visible. Validators must not reveal another caller's list state.

### 5. Define conservative HTTP caching rules

The initial profile separates two cases:

| Representation                                     | Proposed HTTP policy                  |
| -------------------------------------------------- | ------------------------------------- |
| Caller-dependent or access-gated list              | `private, max-age=N, must-revalidate` |
| Explicitly public, safe for anonymous distribution | `public, max-age=N, must-revalidate`  |
| Representation that must not be stored             | `no-store`                            |

For fresh successful responses, `N` is no greater than `floor(ttlMs / 1000)`. Zero or absent TTL yields `max-age=0`; validators can still avoid retransmitting an unchanged body. A server may choose a stricter policy. This initial profile does not authorize stale serving after expiry, even where protocol-level caching would permit it.

`cacheScope: "public"` alone is not an instruction to an ordinary HTTP cache. Public HTTP caching requires an explicit server opt-in and content safe to redistribute without per-request authorization. In particular, an identical list that still requires an access check is not eligible for this draft's public profile. Otherwise a cache hit could bypass that check. Private is the default.

Private caches are partitioned by canonical server, full retrieval URL, protocol version, representation-affecting context, and authorization context. Different access tokens use different private cache entries, consistent with the MCP cache-scope rules. `Cache-Control: private` prohibits shared caching but does not itself partition a user-agent cache; use `Vary: Authorization` and explicit authorization-aware client storage. Raw tokens must not appear in cache logs or persistent cache-key diagnostics.

Servers include `Vary` for every supported result-affecting request header, including `MCP-Protocol-Version` and, where relevant, `Accept`, `Accept-Encoding`, or `Origin`. Unmodeled context must not silently influence cacheable responses. This profile excludes cookie-dependent list selection.

HTTP freshness uses `Date`, `Age`, and RFC 9111 calculations. A client receiving a cached HTTP response must not start a new full `ttlMs` interval merely because it has just received the body. The HTTP adapter carries the remaining freshness into any MCP-level cache. A successful revalidation updates freshness using HTTP rules and applicable updated headers, not by blindly restarting an old body TTL.

A private fresh cache hit does not contact the server. Consequently this design cannot promise immediate permission-revocation visibility. Clients discard private entries on logout or authorization-context changes and do not use them with expired credentials. Servers needing an authorization check on every retrieval use `private, no-cache` or `no-store`; actual primitive operations always enforce current permissions independently.

### 6. Conditional retrieval

```http
GET /tenant/acme/mcp?mcp_list=tools HTTP/1.1
Authorization: Bearer <access-token>
MCP-Protocol-Version: <supported-version>
Accept: application/json
If-None-Match: "tools-page-v7"
```

After authorization and variant selection, an unchanged representation can produce:

```http
HTTP/1.1 304 Not Modified
ETag: "tools-page-v7"
Cache-Control: private, max-age=60, must-revalidate
Vary: Authorization, MCP-Protocol-Version, Accept
```

Examples omit routine headers such as `Date`. Servers and caches follow RFC 9110/9111 requirements for 304 metadata. A 304 has no response body. The client reuses only the corresponding stored representation; without one it retries unconditionally. A changed representation returns 200 with the new body and validator.

Relevant MCP list-change notifications invalidate the client's matching cached pages. This does not purge third-party caches. After invalidation, clients require HTTP revalidation rather than accepting a still-fresh intermediary copy. No new public-CDN purge protocol is introduced.

## Compatibility and non-goals

- GET retrieval is optional; POST list methods remain required and unchanged.
- Clients without this extension continue using POST and MCP-level TTL caching.
- Unsupported retrieval mappings fall back to POST. Authorization failures are handled as authorization failures, not bypassed by trying another URL.
- This changes Streamable HTTP's GET behavior only for explicitly selected list representations.
- STDIO and other transports are unaffected.
- This does not depend on or replace definition versions, and defines no digest-header mirroring.
- A full REST mapping of MCP, resource-content retrieval, cross-origin list hosting, and session-scoped GET caching are out of scope.

## Security considerations

Existing Streamable HTTP Origin validation and localhost protections apply to GET too. Browser support must define CORS handling for `Authorization`, `MCP-Protocol-Version`, and `If-None-Match`, and expose `ETag` and `WWW-Authenticate` as needed. CORS is not authorization, and credentialed private responses must not use wildcard-origin access.

Lists can contain sensitive descriptions, schemas, names, and URIs. Private responses must not be published in Server Cards or shared caches. Cursors are opaque pagination identifiers, not credentials or authorization grants; avoid embedding sensitive information because URLs commonly appear in logs. ETags must not encode credentials or unnecessary user identifiers.

GET list retrieval must be safe and must not execute primitives or initiate interactive workflows. Discovery URLs are untrusted input: retain MCP's existing SSRF protections and do not let discovery redirect credentials to another server or tenant. CDN deployments must enforce the private/public distinction rather than treating every GET as publicly cacheable.

## Open questions before this becomes a concrete SEP

1. **Discovery home:** which capability/discovery field advertises the descriptor, and how does it align with Server Card work without making cards mandatory?
2. **URL design:** same-path query selectors versus advertised sibling paths? Query selectors minimize routing/audience changes but need collision rules for existing endpoint queries.
3. **Server identity:** how is the descriptor's binding to the canonical MCP endpoint verified across multi-tenant cards and existing resource-identity conventions?
4. **Representation:** plain list result with `application/json`, or a dedicated media type? How should HTTP errors and explicit POST fallback be represented?
5. **Request context:** which current list parameters and metadata can safely be mapped, and how is unsupported context detected before attempting GET?
6. **Authorization/cache interaction:** is this conservative public-distribution rule sufficient, and should `private, no-cache` be the default for all authenticated lists?
7. **Freshness:** specify adapter behavior for body `ttlMs` versus HTTP headers, especially when policy changes on a 304 without a new body.
8. **Versioning:** define introduction/version negotiation and interaction with older SSE GET transports; finalize CORS requirements and HEAD support.

## Suggested validation

Test GET/POST list equivalence; pagination and cursor errors; query-key collisions; version and authorization variant isolation; correct 200/304 behavior; authorization before 304; token refresh/logout; public versus private CDN behavior; HTTP Age handling; notifications forcing revalidation; tenant-specific metadata discovery; rejection of cross-origin templates/redirects; unchanged legacy POST and SSE behavior.

## References

- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html), especially §§9.3.3, 13.1.2, and 15.4.5.
- [RFC 9111: HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111.html), especially authenticated responses, cache keys, freshness, and validation.
- [RFC 8707: OAuth Resource Indicators](https://www.rfc-editor.org/rfc/rfc8707.html).
- [RFC 9728: OAuth Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728.html).
- [MCP draft authorization](https://modelcontextprotocol.io/specification/draft/basic/authorization).
- [SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243), [SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549), and [Server Card proposal SEP-2127](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2127). Server Card is referenced as proposal work, not an assumed deployed standard.
