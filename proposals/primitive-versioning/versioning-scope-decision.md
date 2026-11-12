# Decision: Versioning Scope

- **Status:** Draft; no decision yet
- **Authors:** [Kurtis Van Gent](https://github.com/kurtisvg), [Shaun Smith](https://github.com/evalstate), [Sam Morrow](https://github.com/SamMorrowDrums)
- **Related:** [Problem statement](problem-statement.md), [Definition Tags #57](https://github.com/modelcontextprotocol/transports-wg/pull/57), [Groups #19](https://github.com/modelcontextprotocol/progressive-disclosure-wg/pull/19)

Should MCP support only list-level tags, or per-primitive tags that can also carry list context?

A definition tag identifies an advertised definition or set of definitions. Clients return it with a request so the server can tell what they used to prepare the call. Clients treat tags as opaque. The examples below use tools, but the same choice applies to prompts and resources.

Both options must preserve the tag used to prepare a call, even after the client's cache refreshes. A changed tag does not automatically mean incompatibility: the server can accept the call, accept it with a refresh notice, route it, or reject it before execution.

Tags do not change TTLs, cache keys, or authorization rules. A list tag identifies a collection; an HTTP ETag can identify a particular page. The [caching rules](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching) still apply.

## Option 1: One tag per list

`tools/list` returns one tag for the complete list available to the caller. Suppose the list contains `search` and `publish_report`. Calls to either tool carry the list tag `L1`.

The service adds a required argument to `publish_report`, changing the list tag to `L2`. An old call to either tool still carries `L1`. The server can see that the list changed, but the tag alone does not say whether the called tool changed. To establish that `search` is unchanged, it needs the earlier catalog or an equivalent mapping.

One value captures additions, removals, and changes across the list. It can also identify a common snapshot across pages. The trade-off is that the protocol exposes no independent primitive tag; the server must recover individual definitions from the list reference when it needs them.

This is the scope proposed by [#57](https://github.com/modelcontextprotocol/transports-wg/blob/7c39cdb1a797e1240c9dea1830c05c7e0938a159/proposals/XXXX-definition-tags.md#the-tag-field).

## Option 2: One tag per primitive

Each tool has its own tag, which the client returns when calling it. In the same example, `search` has tag `S1` and `publish_report` has tag `P1`.

Adding the required argument changes `publish_report` to `P2`, while `search` stays at `S1`. The server can compare the tag on a `search` call with its current tag and establish that the definition is unchanged, without looking up an earlier catalog.

This exposes an independent version for each primitive and puts a tag on every entry. A primitive-only tag says nothing about changes elsewhere in the list: `S1` alone cannot reveal whether the client knows about a newly added tool. Per-primitive tags can also include list context, as described below.

## Additional Considerations

### Per-primitive tags can also cover the list

A per-primitive tag can include both revisions, such as `L1-S1`. The client returns it unchanged; the server decodes it or looks up its parts. These labels illustrate the contents, not a proposed wire format.

In the same rollout, `publish_report` changes to `P2` and the list changes to `L2`:

| Call             | Client tag | Current tag | What the server can determine                                      |
| ---------------- | ---------- | ----------- | ------------------------------------------------------------------ |
| `search`         | `L1-S1`    | `L2-S1`     | The tool is unchanged. Accept the call and suggest a list refresh. |
| `publish_report` | `L1-P1`    | `L2-P2`     | The tool changed. Check whether the earlier call can be honored.   |

Adding a new tool would change only the list part of existing tools' tags. A call to any of them could then prompt the client to refresh.

Per-primitive tags can therefore cover list-level behavior as well as individual definitions. Empty lists and page comparisons also need a list tag that the client can access, even when each entry's composite tag is opaque.

The cost is that every complete tag changes whenever the list changes, even if its tool part stays the same. The server must be able to check the parts separately; hashing them together without retaining a mapping loses that detail.

### Tools shared across groups

Groups can contain the same tool while their membership and instructions change independently. The [groups draft in #19](https://github.com/helloeve/experimental-ext-grouping/blob/15b2a5cf919702ae95a591856525486c857b3ea5/seps/0000-progressive-disclosure-groups.md#placement-and-naming) requires identical definitions for shared tools and tells clients to register each tool once. Within a client view, these tools appear in group contents rather than also appearing in `tools/list`.

Suppose groups A and B both contain `search` at `S1`:

| Change                                | Tool tag     | Group tags     |
| ------------------------------------- | ------------ | -------------- |
| Add another tool to A                 | Unchanged    | A changes      |
| Change the shared `search` definition | Becomes `S2` | A and B change |
| Change A's instructions               | Unchanged    | A changes      |
| Remove `search` from A, keep it in B  | Unchanged    | A changes      |

A per-group tag could cover the instructions, definitions, and child-group references returned by `groups/get(name)`. That is a different scope from the directory of summaries returned by `groups/list`, and it needs to identify the particular group.

With collection-only tags, the server would recover the called tool's definition from the earlier group contents or a mapping. With per-primitive tags, `search` can keep the same tag in both groups, while each group has its own tag.

Putting group-specific context inside the shared tool's tag creates a problem: A would return `A1-S1` while B returns `B1-S1`. If those tags are part of the tool definition, the copies differ. Keeping only one also loses the other group's context.

One option is to keep `S1` on the shared tool and carry group references alongside it. A composite tag can still work if its collection part is shared wherever the tool appears. We need to decide how calls identify group context, especially when they rely on instructions from several groups. A matching tool tag alone cannot detect changed group instructions.

## Comparison

The per-primitive option below includes list context where needed.

| Question                                   | List-only tags                                      | Per-primitive tags with list context                       |
| ------------------------------------------ | --------------------------------------------------- | ---------------------------------------------------------- |
| Independent primitive version?             | Not exposed by the protocol.                        | Identified directly.                                       |
| Called tool unchanged after a list change? | Requires the earlier catalog or equivalent mapping. | Compare the primitive part.                                |
| Newly added tool?                          | The list tag changes.                               | The list part changes.                                     |
| Tool shared across groups?                 | Recover its definition from a group tag.            | Share the tool tag; track group context separately.        |
| Bookkeeping?                               | Fewer tags; may need catalog history or mappings.   | A tag per entry; manage collection parts or group context. |

The choice is whether to carry individual definition tags or leave servers to recover that information from collection tags. Per-primitive tags offer both scopes, with more information to issue and track. Neither option alone decides how long to support old definitions or whether a changed definition is compatible.

## Open questions

- **Selected collections:** Which filtered or partially discovered list does a tag cover? A tag does not prove that the client fetched every page.
- **Group context:** Which group tags should a call carry when several groups' instructions influenced it? Where should those references live?
- **Referenced definitions:** Should a group tag cover top-level tools it references or the contents of nested groups? The groups draft treats [nesting as navigation](https://github.com/helloeve/experimental-ext-grouping/blob/15b2a5cf919702ae95a591856525486c857b3ea5/seps/0000-progressive-disclosure-groups.md#nested-groups), so changes need not automatically propagate to every parent.
- **Cost:** How do the extra tags compare with catalog history and mappings for a simple server or a gateway? A gateway that rewrites definitions may need translation under either option.
- **Other primitives:** A resource read may come from a listed resource, a template, or a direct URI. Which definition and discovery context should it identify?
