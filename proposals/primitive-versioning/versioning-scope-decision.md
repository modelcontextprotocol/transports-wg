# Decision: Versioning Scope

- **Status:** Draft; no decision yet
- **Authors:** [Kurtis Van Gent](https://github.com/kurtisvg), [Shaun
  Smith](https://github.com/evalstate), [Sam
  Morrow](https://github.com/SamMorrowDrums)
- **Related:** [Problem statement](problem-statement.md), [Definition Tags
  #57](https://github.com/modelcontextprotocol/transports-wg/pull/57)

A definition tag lets a client identify the advertised definitions it used to
prepare a request. Should clients identify only the collection they discovered,
or also the individual primitive they intend to use?

Both options retain collection context so servers can signal additions and
removals. Clients treat tags as opaque values. Collection-only tags need server
history or mappings to identify changes to individual primitives. Primitive
tags add discovery data and client bookkeeping. Field layout remains open.

## What a match means

Tags are compared for the same service and primitive or collection, in the
relevant caller context. Matching tags must identify the same covered
definitions. For primitive tags to let a new instance recognize an unchanged
tool, they must also stay stable across replicas and unrelated deployments.
Deterministic content hashes or shared revision identifiers could provide both
properties. Local counters risk assigning the same tag to different definitions;
release-wide identifiers change tags even for unchanged primitives.

A match establishes agreement only on what the tag covers. Coverage needs to
account for advertised meaning, including descriptions that change an
argument's units. A tag cannot detect behavior changes that the server leaves
unadvertised. Permissions still need checking.

A mismatch does not establish incompatibility. A new optional argument may
leave old calls valid, even though the definition changed. Supporting those
calls requires a compatibility policy under either option.

## Option 1: Collection tags only

`tools/list` returns `L1` for the complete list available to the caller,
containing `search` and `publish_report`. Calls to either tool carry `L1`.

The service adds a required argument to `publish_report`, changing the list to
`L2`. A call carrying `L1` shows that the collection differs. To establish that
`search` is unchanged, the server needs an earlier catalog, a compatibility
index, or another way to interpret `L1`. Servers can share or precompute that
information; they need not rebuild old catalogs on every call.

A new instance that knows only `L2` cannot make that distinction from `L1`
alone. [#57's rollout
example](https://github.com/modelcontextprotocol/transports-wg/blob/7c39cdb1a797e1240c9dea1830c05c7e0938a159/proposals/XXXX-definition-tags.md#rolling-deployment)
suggests ignoring unknown tags to avoid repeated rejection. That avoids the
rejection loop but skips the definition check.

This is the scope proposed by
[#57](https://github.com/modelcontextprotocol/transports-wg/blob/7c39cdb1a797e1240c9dea1830c05c7e0938a159/proposals/XXXX-definition-tags.md#the-tag-field).
Its `knownTags` map carries collection and discovery tags, with no individual
primitive tag.

## Option 2: Primitive tags plus collection context

Each primitive has its own tag. In the same example, `search` has `S1` and
`publish_report` has `P1`. Adding the required argument changes `P1` to `P2`,
while `search` stays at `S1`.

An instance can recognize `S1` without knowing the old catalog. A mismatch
between `P1` and `P2` still requires a compatibility decision. Recognizing
`S1` also does not settle whether other instructions used to prepare the call
can still be honored.

A `tools/call` or `prompts/get` would carry the invoked primitive's tag and
collection or group context. It would not send every primitive tag in the
client's cache. Collection tags still cover additions and empty lists; which
group tags accompany a call remains open.

Discovery responses grow by one tag per tagged entry. A 64-character hex value
in a `tag` field adds about 73 bytes per entry in compact JSON, or 730 kB for
10,000 entries before compression. This is an example, not a required encoding.

## Comparison

| Concern | Collection tags only | Primitive tags plus collection context |
| --- | --- | --- |
| Unknown collection tag, unchanged tool | Needs information about the old collection to recognize the unchanged tool. | Can compare the stable primitive tag directly. |
| Changed primitive | Needs a compatibility decision or a compatible implementation. | Same. |
| Added or removed primitives | Collection tags can signal a refresh. | Same. |
| Discovery payload | One tag per collection response. | Also one tag per tagged primitive. |
| Request payload | Collection and discovery tags. | Also the invoked primitive's tag; group context may grow. |
| Client bookkeeping | Preserve collection context for each prepared call. | Also preserve the primitive's tag and its association with the definition. |
| Supporting old calls | May retain catalogs, compatibility indexes, or old implementations. | Recognizing an unchanged primitive needs no old catalog. Changed primitives and other context may still need history or old implementations. |

Primitive tags allow finer checks, but do not provide individual retrieval or
delta fetching. Under either option, refreshing may still require fetching a
whole list.

## Cases that affect the choice

### Missing or ignored tags

Server publication, client participation, and server enforcement are separate
choices. A server may advertise a tag and later receive a call without one.
That request does not identify which definition the client used.

Both options need to distinguish a missing tag from a supplied tag that cannot
be honored. Accepting an untagged request, or ignoring a supplied tag, provides
no guarantee from this mechanism that the operation honors the client's
definition.

### Prepared calls and execution

A client must preserve the tags used to prepare a call, including while it
waits for approval. A background cache refresh must not attach newer tags to
the old call.

When enforcing tags, the service must honor the referenced definitions, route
to an implementation that can, or reject before execution. A successful result
with a refresh notice must not cause the client to repeat the operation.
Rejection can prompt a refresh, but the client may need to rebuild the call,
replan, or stop.

Neither option guarantees progress during an incompatible rollout. Recognizing
a mismatch does not create a compatible backend or make repeated retries useful.

### Collection references and composite tags

Primitive and collection references could use separate fields or one opaque
string. With a composite value such as `L1-S1`, the server could compare the
parts while the client returns the value unchanged. Hashing the parts together
would lose that ability unless the server retained a mapping.

A composite value changes whenever either part changes. The collection
reference must also remain available for empty lists and page comparisons.

A collection mismatch can prompt a refresh when a tool is missing. It does not
prove that the missing name belonged to the earlier collection; distinguishing
removal from an invented name may still require history.

### Caller-specific lists and gateways

A server that filters 500 tools by each caller's permissions may have many
collection tags for one release. Checking a primitive tag avoids building the
whole list just to compare the invoked definition. Collection freshness checks
still have their own cost. Either design may benefit from cached catalogs or
shared indexes.

At a gateway, a deployment in backend A can change the combined list while
backend B's tools stay unchanged. Primitive tags let B or the gateway compare
B's definition directly. If the gateway rewrites names or schemas, it needs a
mapping to the backend definitions.

The check must apply to the implementation that executes the call. Checking a
gateway's catalog and then dispatching to an incompatible backend does not
protect execution. The backend must check the reference, or the gateway must
ensure that the selected backend can honor it.

### Shared tools and group instructions

In [Groups
#19](https://github.com/modelcontextprotocol/progressive-disclosure-wg/blob/15b2a5cf919702ae95a591856525486c857b3ea5/seps/0000-progressive-disclosure-groups.md#placement-and-naming),
`groups/get(name)` returns instructions, scoped definitions, and child-group
references. A scoped tool can appear in several groups with an identical
definition, and clients register it once.

Suppose groups A and B both contain `search` at `S1`:

| Change | Primitive tag | Group tags |
| --- | --- | --- |
| Add another tool to A | Unchanged | A changes |
| Change the shared `search` definition | Becomes `S2` | A and B change |
| Change A's instructions | Unchanged | A changes |
| Remove `search` from A, keep it in B | Unchanged | A changes |

Separate primitive tags let `search` keep `S1` in both groups. Embedding
group-specific composites such as `A1-S1` and `B1-S1` in the tool definition
would make those copies differ. Keeping group references alongside the
primitive avoids that conflict.

However, a call carrying `S1` and `A1` can reach a server with `S1` and `A2`.
The group may have gained an unrelated tool or changed instructions that affect
the call. The primitive match cannot distinguish those cases. Group history or
separate instruction references could resolve the difference. Otherwise, a
server enforcing that context must reject if it cannot establish compatibility.

Both options need a rule for which group references a call carries. Fetching a
group does not mean its instructions were used, and instructions from a group
with no tools can still affect a call. Each reference also needs a group
identity: #57's method-keyed map cannot distinguish two `groups/get(name)`
results. Nested groups are navigation references, so their contents need not
be included in every parent's tag.

### Prompts, resources, and skills

A prompt call can carry its named prompt's tag. A resource read may come from
a listed descriptor, a URI template, or a URI supplied directly by a tool or
user. A template reference must identify both the template and its version.
A direct URI may have no discovered definition to tag.

Definition tags do not directly verify resource contents. However, [skill
manifests](https://skills.extensions.modelcontextprotocol.io/specification/beta/skills#integrity-and-verification)
contain file digests. A tag covering a manifest can identify changes to those
entries; the Skills extension still governs verification of retrieved files.

`server/discover` instructions can affect calls without changing any primitive.
If covered, they need a separate reference under either option.

### Pagination and overlapping refreshes

A collection tag can expose pages from different catalog states, provided each
page belongs to the state its tag identifies. Equal tags alone do not ensure a
complete traversal: changing page order can still cause gaps or duplicates.
The design needs rules for consistent traversal and recovery from a mismatch.

Opaque tags support equality checks, not ordering. They cannot tell a client
which of two refresh responses is newer. Clients need a rule to prevent
overlapping refreshes from overwriting one another; request ordering alone
cannot establish which replica has the latest catalog.

Both options preserve the existing [freshness and cache-scope
rules](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching).
Checks on tagged pages would add consistency rules.

## Relationship to HTTP ETags

HTTP separates cache validation from execution preconditions.
`If-None-Match` supports conditional retrieval; `If-Match` checks a precondition
before execution and uses strong comparison for supplied ETags. Weak ETags
cannot satisfy that comparison. An advisory definition tag therefore does not
provide the same contract as an enforced precondition. See [RFC 9110,
Section 13.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1).

An ETag describes a selected HTTP representation, which may be one catalog
page. It does not automatically identify a tool definition or several groups.
Values in an `If-Match` list are alternatives for the target resource, not
conditions on separate resources. An HTTP binding would need to define that
mapping.

ETag implementations also illustrate two pitfalls:

- **Replica differences:** [Apache file
  ETags](https://httpd.apache.org/docs/2.4/mod/core.html#fileetag) can depend on
  timestamps and inode numbers. Such inputs can differ across replicas serving
  the same content. Definition tags need the stability described above.
- **Representation changes:** [Apache
  compression](https://httpd.apache.org/docs/2.4/mod/mod_deflate.html#deflatealteretag)
  can rewrite ETags. Definition tags should survive transport encoding changes,
  while an HTTP validator may need to change.

Tags also do not replace cache keys. Caller and capability differences still
need correct cache selection, just as HTTP uses request matching and
[`Vary`](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.1).

## Open questions

- **Coverage:** Which definition fields affect tags, including metadata and
  localized text? How are caller-specific variants identified?
- **Collection scope:** What does a tag cover for filtered or partial catalogs?
- **Server publication:** May servers omit tags or offer collection tags alone?
- **Client participation:** Which clients must return advertised tags, and how
  are legacy clients handled?
- **Enforcement:** Must servers check supplied tags? May they require tags for
  an operation, and how are these guarantees and requirements communicated?
- **Context:** Which group and discovery references accompany a call? Are
  instruction changes checked separately from membership changes?
- **Compatibility:** Who decides whether an older definition can be honored,
  and how long should support remain available?

The scope choice should establish what clients can identify and what servers
can infer. Exact fields, tag generation, error codes, and transport bindings
belong in the proposal.
