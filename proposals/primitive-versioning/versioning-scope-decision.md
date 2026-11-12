# Decision: Versioning Scope

- **Status:** Draft; no decision yet
- **Authors:** [Kurtis Van Gent](https://github.com/kurtisvg), [Shaun Smith](https://github.com/evalstate), [Sam Morrow](https://github.com/SamMorrowDrums)
- **Related:** [Problem statement](problem-statement.md), [Definition Tags #57](https://github.com/modelcontextprotocol/transports-wg/pull/57), [Groups #19](https://github.com/modelcontextprotocol/progressive-disclosure-wg/pull/19)

Should MCP support only collection tags, or also tags for individual primitives?

A definition tag identifies the advertised definitions used to prepare a request. Clients treat tags as opaque and return them to the server. Option 1 identifies the collection. Option 2 also identifies the called primitive, while keeping collection context for additions, empty lists, and pagination. The choice of fields remains open.

Both options must keep the tags used to prepare a call, even if a background refresh runs while the call waits for approval. A mismatch does not necessarily mean incompatibility: the server can accept, accept with a refresh notice, route, or reject before execution. A match confirms only the definitions covered by the tag; permission checks still apply.

Collection tags let clients detect pages from different catalog states across any transport. An HTTP ETag validates an HTTP representation, which may be just one page. Neither option changes the [caching rules](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching).

## Option 1: Collection-only tags

`tools/list` returns tag `L1` for the complete list available to the caller. Suppose that list contains `search` and `publish_report`. Calls to either tool carry `L1`. Clients keep one tag per collection snapshot, regardless of how many tools it contains.

The service adds a required argument to `publish_report`, changing the list to `L2`. An old call to either tool still carries `L1`. The server knows the list changed, but needs the earlier catalog or an equivalent mapping to establish that `search` is unchanged.

This matters during a rolling deployment. A new instance may know only `L2` and have no record of `L1`. It cannot use that list tag alone to distinguish an unchanged `search` from one whose advertised meaning changed. [#57's rollout example](https://github.com/modelcontextprotocol/transports-wg/blob/7c39cdb1a797e1240c9dea1830c05c7e0938a159/proposals/XXXX-definition-tags.md#rolling-deployment) suggests ignoring unknown tags to avoid repeated rejection. That avoids a retry loop, but skips the definition check.

This is the scope proposed by [#57](https://github.com/modelcontextprotocol/transports-wg/blob/7c39cdb1a797e1240c9dea1830c05c7e0938a159/proposals/XXXX-definition-tags.md#the-tag-field). Its `knownTags` map carries the collection and discovery tags the client holds. Requests carry no individual primitive tag.

## Option 2: Per-primitive tags with collection context

Each tool has its own tag. In the same example, `search` has `S1` and `publish_report` has `P1`. Collection context is still available; primitive-only tags would miss additions and cannot identify an empty list.

Adding the required argument changes `publish_report` to `P2`, while `search` stays at `S1`. A new instance can compare `S1` with its current definition without knowing the old catalog. This requires unchanged definitions to have the same tag across instances. A mismatch such as `P1` versus `P2` still needs a compatibility decision.

A `tools/call` or `prompts/get` would carry the invoked primitive's tag plus collection or group context. It would not send every primitive tag in the client's cache. Which group tags to include remains open, so that context is not necessarily a fixed-size map.

There is more data in discovery responses: one tag per tagged entry. For example, a 64-character hex tag adds about 73 bytes per entry in compact JSON, or 730 kB for 10,000 entries before compression. That matters more for short resource descriptors than large tool schemas. This estimate assumes separate primitive and collection tags; a composite value may be longer.

## Additional Considerations

### Per-primitive tags can also cover the list

Option 2 can carry the primitive and collection references in one string or separate fields. A composite tag such as `L1-S1` lets the server inspect both parts while the client returns it unchanged.

In the same rollout, `publish_report` changes to `P2` and the list changes to `L2`:

| Call             | Client tag | Current tag | What the server can determine                                        |
| ---------------- | ---------- | ----------- | -------------------------------------------------------------------- |
| `search`         | `L1-S1`    | `L2-S1`     | The tool is unchanged; it can accept the call and suggest a refresh. |
| `publish_report` | `L1-P1`    | `L2-P2`     | The tool changed; it must decide whether to honor the earlier call.  |

Adding a tool changes the list reference. If a tool is removed, the list mismatch can also prompt a refresh before tool lookup. It does not prove the missing name ever belonged to that list; distinguishing removal from an invented name may still require history.

A composite tag does not remove the need to expose the collection tag on empty lists or for client-side page comparisons. It also changes every entry's full tag whenever the list changes. Hashing both parts together without a mapping would lose the ability to check them separately.

### Lists that vary by caller and service

A server that filters 500 tools by each caller's permissions may have many different list tags for one release. Keeping earlier catalogs or rebuilding the caller's complete list on every call can be costly, although servers may cache or share those catalogs.

A primitive tag lets the server check just the invoked definition. That avoids enumerating the whole list for this check; it does not make authorization or collection freshness checks free. [#57](https://github.com/modelcontextprotocol/transports-wg/blob/7c39cdb1a797e1240c9dea1830c05c7e0938a159/proposals/XXXX-definition-tags.md#rationale) also notes that computing a collection tag may cost more than the call itself.

At a gateway, a deployment in backend A can change the combined list while backend B's tools stay unchanged. Primitive tags let B, or the gateway, check B's definition directly. A gateway that rewrites names or schemas still needs a mapping to the definitions its backends serve.

### Tools shared across groups

In [Groups #19](https://github.com/modelcontextprotocol/progressive-disclosure-wg/blob/15b2a5cf919702ae95a591856525486c857b3ea5/seps/0000-progressive-disclosure-groups.md#placement-and-naming), `groups/list` returns summaries. `groups/get(name)` fetches a group's instructions, scoped definitions, and child-group references. Scoped tools are omitted from `tools/list`, but can appear in several groups with identical definitions. Clients register each tool once.

Suppose groups A and B both contain `search` at `S1`:

| Change                                | Tool tag     | Group tags     |
| ------------------------------------- | ------------ | -------------- |
| Add another tool to A                 | Unchanged    | A changes      |
| Change the shared `search` definition | Becomes `S2` | A and B change |
| Change A's instructions               | Unchanged    | A changes      |
| Remove `search` from A, keep it in B  | Unchanged    | A changes      |

Collection-only tags would identify the group contents, from which the server could recover a tool definition. Per-primitive tags let `search` keep `S1` in both groups.

A group-specific composite tag complicates that sharing: A would return `A1-S1` and B would return `B1-S1`. If stored inside the tool definition, those tags make the copies differ. A common catalog component could keep the copies identical, but an edit elsewhere in that catalog would change the tool's tag too.

Keeping `S1` on the tool and carrying group references alongside it lets each group change independently. Group context also matters when a call relies on instructions from several groups, including groups that contain no tools.

Both options need a way to identify each group: #57's method-keyed `knownTags` map cannot distinguish two `groups/get(name)` results by method alone.

### Prompts, resources, and discovery

A prompt call can carry the tag of its named prompt, much like a tool call. A resource read may instead come from a listed resource, a URI template, or an unlisted URI supplied by a tool or user. A template tag could identify the definition used to build the URI, but the request also needs to identify that template. A direct URI may have no discovered definition to tag. These tags identify definitions, not resource contents.

`server/discover` instructions can affect calls without belonging to an individual primitive. If covered, they need a response-level tag under either option, as #57 proposes.

## Comparison

The table compares the supported scopes; it does not require a particular encoding for Option 2.

| Question                                   | Collection-only tags                               | Per-primitive tags with collection context                         |
| ------------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------ |
| New instance receives an unknown list tag? | Cannot isolate the called definition's change.     | Can compare its current primitive tag, if stable across instances. |
| Caller-specific lists?                     | Checking freshness may require the selected list.  | Can check the invoked definition separately from list freshness.   |
| Added or removed tools?                    | Collection tags signal a refresh.                  | Collection context provides the same signal.                       |
| Discovery payload?                         | One tag per collection response.                   | Also a tag per tagged primitive entry.                             |
| Request payload?                           | Collection and discovery tags.                     | Also the invoked primitive's tag; group context may vary.          |
| Paused calls?                              | Save the collection tags used to prepare the call. | Save those tags and the invoked primitive's tag.                   |
| Shared tools across groups?                | Recover definitions from group tags.               | Share primitive tags; retain group context.                        |

## Open questions

- **Collection scope:** How should tags cover filtered or partially discovered catalogs?
- **Adoption:** #57 makes tags optional. Should collection and primitive tags remain independently optional, letting servers start with collection-only support?
- **Group context:** Which group tags should a call carry, and how should they be keyed? Should they cover referenced tools or nested contents? The groups draft treats [nesting as navigation](https://github.com/modelcontextprotocol/progressive-disclosure-wg/blob/15b2a5cf919702ae95a591856525486c857b3ea5/seps/0000-progressive-disclosure-groups.md#nested-groups), so changes need not propagate to every parent.
- **Field layout and coverage:** Where should each reference go, which definition fields should it cover, and how should resource reads identify a source template?
- **Cost and retention:** What must a simple server or gateway compute and retain under each option? How long should old definitions remain usable?
