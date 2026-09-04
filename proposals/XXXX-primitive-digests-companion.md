# SEP-XXXX: Per-Primitive Digests and Conditional Requests

- **Status**: Draft (working-group companion)
- **Type**: Standards Track
- **Created**: 2026-09-04
- **Author(s)**: TBD
- **Sponsor**: None
- **Related**: [PR #45](https://github.com/modelcontextprotocol/transports-wg/pull/45), [SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) (TTL caching)

## Abstract

Deployments can change primitive definitions while clients still hold valid cached lists, causing requests to use an outdated contract. Servers may optionally advertise deterministic per-primitive digests, and clients may return them to require execution against the corresponding definition or rejection before execution. This opt-in mechanism supplements existing TTL caching without requiring subscriptions, HTTP caching, or additional capability negotiation.

This proposal does not yet define GET retrieval semantics for integration with standard HTTP ETag caching infrastructure. The original proposal describes `ETag` / `If-None-Match` revalidation with `304 Not Modified`, but does not define GET endpoints for list retrieval; that transport mapping remains separate work.

## Motivation

TTL is a freshness hint, not a promise that definitions will remain unchanged until expiry. A request-time precondition closes that gap without requiring a persistent notification stream. Definition changes may result from deployments, permission changes, or feature flags. This companion simplifies the [original proposal](XXXX-deterministic-primitive-surface-digest.md) while retaining per-primitive digests and making the supplied precondition enforceable.

## Specification

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted as described in [BCP 14](https://www.rfc-editor.org/info/bcp14).

### Optional adoption

Servers **MAY** implement this mechanism and **MAY** emit digests for some or all of the primitives they expose. Clients **MAY** ignore digests and continue using ordinary requests and existing TTL caching. Neither side is required to opt in, and digest absence does not disable caching.

Emitting a digest advertises support for conditional requests using that primitive; no separate capability flag is needed. A server emitting digests **MUST** implement the conditional-request rules below, including rejection of unknown or no-longer-supported digests. These guarantees apply at the addressed server endpoint, not just the replica that returned the list.

Unless stated otherwise, the requirements below apply when a server implements this mechanism or a client elects to use it. They do not require adoption.

### Per-primitive digest

A server opting in **MAY** include `io.modelcontextprotocol/digest`, a string, in a primitive object's own `_meta` in successful, complete list results:

| List method | Object carrying the digest | Conditional operation |
| --- | --- | --- |
| `tools/list` | `Tool` | `tools/call` |
| `prompts/list` | `Prompt` | `prompts/get` |
| `resources/list` | `Resource` | `resources/read` |
| `resources/templates/list` | `ResourceTemplate` | `resources/read` for a URI instantiated from that template |

The digest **MUST** identify that primitive's caller-visible definition, including schemas, annotations, and other definition fields, **excluding the primitive object's top-level `_meta`**. It identifies the definition, not tool output, rendered prompt content, or resource contents. Changes solely within the excluded `_meta` do not change the digest.

The digest **MUST** be deterministic and collision-resistant: identical definitions across replicas produce the same digest, and changed definitions produce a different digest except for a cryptographic hash collision. It **MUST NOT** depend on list ordering, pagination, TTLs, cursors, or unrelated primitives.

Servers **SHOULD** compute it as `sha256:` followed by the lowercase hexadecimal SHA-256 hash of the [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) canonical JSON encoding of the primitive object with its top-level `_meta` removed. Servers **MAY** use another computation satisfying the same requirements. Clients **MUST** treat the value as opaque and compare only for equality; they do not compute or parse it.

Clients choosing to use a digest **MUST** retain it with the cached definition it identifies, not adopt a new digest without the corresponding definition. An empty list carries no primitive digest; no aggregate list digest is introduced.

### Conditional requests

A client that received a digest for a primitive **MAY** include it as `io.modelcontextprotocol/expectedDigest`, a string, in the request `_meta` of the conditional operations above. Receiving a digest does not oblige the client to send it. It is the digest of the particular definition the client used, not a digest of the containing list.

For `resources/read`, the supplied digest refers either to the listed resource descriptor or to the resource template used to construct the requested URI. The server **MUST** verify that the identified descriptor or template applies to that URI; a matching digest for an unrelated primitive does not satisfy the precondition.

After ordinary request-envelope and authorization checks, a server implementing this mechanism and receiving `expectedDigest` **MUST** either:

1. Handle the request according to the applicable primitive definition identified by the supplied digest; or
2. Reject the request with `DigestChangedError` **before executing the operation**.

The server **MUST** resolve the digest before validating operation-specific inputs against the selected definition, so schema drift is not mistaken for invalid arguments against a different definition.

How the server honors a digest is implementation-defined. Retaining older definitions is not required: a server **MAY** accept only the target primitive's current digest. An unknown, inapplicable, or no-longer-supported digest **MUST** produce `DigestChangedError`, not execution followed by a warning. Ordinary validation and authorization errors remain available.

Requests without the field retain ordinary MCP behavior, even when the server advertised a digest. A client **MUST NOT** assume conditional enforcement for a primitive whose digest the server has not advertised. Servers that do not implement this mechanism may ignore the metadata under existing MCP rules.

### Refresh-required error

`DigestChangedError` is a JSON-RPC error, not a tool result with `isError: true`. Its response `id` **MUST** match the request, and its error code **MUST** be `DIGEST_CHANGED`. No method-specific error data is required: the error instructs the client to refresh, not to adopt a replacement digest in isolation.

> **Allocation pending:** `DIGEST_CHANGED` needs a code from MCP's protocol-defined error range before this proposal is finalized. No numeric allocation is asserted by this draft.

Over Streamable HTTP, the server **MUST** return this rejection as HTTP `409 Conflict` with an `application/json` JSON-RPC error body. On stdio, it uses the same JSON-RPC error without an HTTP status. This defines an error mapping, not HTTP caching or conditional-header semantics.

A client receiving this error **MUST** refresh the affected definition through its list method before retrying the rejected operation. It **SHOULD** reconsider the request against the refreshed definition and bound refresh/retry attempts. A retry **MUST** use a new JSON-RPC request ID. It **MUST NOT** automatically drop the digest to bypass the rejection.

### TTL and cache scope

Existing [TTL and cache-scope rules](https://modelcontextprotocol.io/specification/draft/server/utilities/caching) remain unchanged. A digest rejection requires refresh before retrying even when the cached list's TTL has not expired; successful conditional execution **MUST NOT** extend that TTL. Each digest follows its containing list result's cache scope, including restrictions on sharing private results across authorization contexts.

## Rationale

Per-primitive digests keep conditional requests independent of unrelated definition changes and list pagination. They do not detect newly added primitives; list freshness remains governed by TTL and optional change notifications. The digest travels in JSON-RPC metadata, so neither HTTP caching nor new headers are needed.

Server routing, connection draining, and support for older primitive versions are implementation choices, not protocol requirements. A participating server can always reject a digest it cannot honor. This proposal does not add response-side digests to operation results, HTTP validators, or resource-content revalidation.

## Backward Compatibility

The change adds optional metadata and a defined error. Supporting a protocol revision containing this SEP does not require emitting digests or using conditional requests. Servers that do not opt in omit digests; clients that do not opt in can ignore them. Existing TTL caching and requests without `expectedDigest` continue unchanged.

Older or non-participating servers may ignore unknown request metadata. Clients **MUST NOT** assume enforcement solely from a protocol version or from sending `expectedDigest`; they need a digest advertised under this mechanism. A deployment advertising digests must honor that promise across replicas handling conditional requests, rather than silently routing them to implementations that ignore the precondition.

## Security Implications

A digest does not grant access or preserve revoked permissions. Existing authorization and request-validation rules remain authoritative. Digests have the same confidentiality as their containing list results and are not proof of server integrity: unchanged definitions do not guarantee unchanged implementation behavior.

## Reference Implementation and Conformance

Reference implementation: TBD. A prototype and conformance scenarios are required before finalization.

Optional adoption must be tested: servers emitting no digests remain conformant, mixed lists may contain primitives with and without digests, and clients may ignore advertised digests. Feature-specific conformance scenarios apply to servers opting in and clients exercising conditional requests, not to non-participants.

For participating implementations, tests should cover all four list types, deterministic hashes, `_meta` exclusion, independence from pagination and unrelated primitives, empty lists, resource/template targeting, matching and rejected requests, rejection before side effects, schema-validation ordering, refreshing within an unexpired TTL, new retry IDs, private cache scoping, and unchanged behavior when the request omits a digest. A server fixture may demonstrate honoring an older digest, but retaining older versions is not required.
