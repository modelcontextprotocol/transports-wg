# Investigation: Generalized Payload-to-Header Mapping for MCP

**Contributors:** @kurtisvg 
**Status:** 🚧 WIP   
**Last Updated:  Mar 3, 2026**

## Problem Statement

The current draft of the HTTP Header Standardization SEP introduces a mechanism
to expose critical routing information to network intermediaries (like load
balancers and API gateways) without requiring deep packet inspection.

Currently, this design takes a **schema-bound approach**. It allows server
authors to elevate specific tool parameters into HTTP headers by adding an
`x-mcp-header` annotation directly within a tool's `inputSchema`. This solution
is highly targeted, leveraging the existing extensibility of JSON Schema to
surface specific tool execution arguments.

The Working Group has requested an investigation into a **payload-bound
approach**: creating a generalized, protocol-wide mechanism that would allow
*any* arbitrary field from the JSON-RPC payload to be elevated into an HTTP
header. This would expand the capability beyond tool arguments to include:

* Arguments for Prompts.  
* Variables for Resource Templates.  
* Arbitrary properties such as within the top-level `_meta` object (e.g.,
  standardizing `_meta.tenant_id` to `Mcp-Header-Tenant-Id`).

The purpose of this document is to evaluate whether this generalized approach
can be standardized without introducing unreasonable complexity, and to outline
the design constraints and alternative implementations.

## Design Challenges & Constraints

Shifting from a targeted schema annotation to a generalized payload-to-header
mapping engine introduces several structural and lifecycle challenges for the
MCP protocol.

### Limited to Primitives

Applying header mapping to arbitrary JSON-RPC requests necessitates a stateful
protocol design, which our current goal is to eliminate.

* To elevate an arbitrary field (like `_meta.tenant_id`) across any request, the
  client needs a global set of mapping rules. If the server dictates these rules
  (e.g., during an `initialize` phase), the client is forced to maintain this
  global state and evaluate it before every subsequent outbound request.  
* Consequently, we are practically constrained to acting on specific primitives
  with a concrete schema where we can specify the mapping syntax. By attaching
  mapping rules directly to a primitive's definition (like a Tool's
  `inputSchema` returned from `tools/list`), the client predictably knows how to
  format the specific execution request (`tools/call`) for that item without
  relying on global protocol state.

### Defining a Generalized Mapping Syntax 

If we abandon schemas entirely to support arbitrary fields (like `_meta`), the
specification must standardize a path-evaluation syntax.

* The protocol would need to adopt and enforce support for a querying language
  like JSON Pointer or a restricted JSONPath subset (e.g., mapping
  `$._meta.routing.tenantId` to an `MCP-Header-Tenant-Id`).  
* This significantly increases the implementation complexity for all MCP client
  SDKs, which would now need to include a universally consistent path-evaluation
  engine to process outgoing requests.

### Security Considerations

We considered the security implications of a generalized payload-to-header
mapping engine. Ultimately, we concluded that this approach does not introduce
fundamentally new security vulnerabilities.

Because the custom headers simply mirror data that is already present within the
encrypted JSON-RPC request body, no new secrets are transmitted over the wire.
Furthermore, network infrastructure and compliance standards generally treat
HTTP headers as sensitive or PII.

## Proposed Alternative Designs & Trade-offs

### Option A: Tool-Only Schema Annotations (Current Approach)

*This is the current SEP draft approach.* Header mapping is strictly limited to
`tools/call` parameters using the `x-mcp-header` extension within a tool's
`inputSchema`.

**Example Tool Definition:**

```json
{
  "name": "execute_query",
  "description": "Executes a query in a specific region.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "region": {
        "type": "string",
        "description": "The AWS region",
        "x-mcp-header": "Region"
      },
      "query": {
        "type": "string"
      }
    },
    "required": ["region", "query"]
  }
}
```

*Client Output:* When calling this tool with `{"region": "us-east-1"}`, the
client automatically appends the header: `MCP-Header-Region: us-east-1`.

* **Pros:**  
  * Minimal changes to core MCP specification (JSON Schema natively supports
    `x-` extensions).  
  * Low implementation complexity for client and server SDKs.  
* **Cons:**  
  * Asymmetric scope. It does not support Prompts, Resources, or top-level
    JSON-RPC fields like `_meta`.

### Option B: Updating Prompts & Resources

Achieve parity across specific primitives by updating the core protocol to
support explicit header mapping fields.

**Example 1: Prompt Definition**

Currently, Prompts use a simple `arguments` array. We would need to update the
`PromptArgument` interface to include an optional `mcpHeader` field.

```json
{
  "name": "code_review",
  "description": "Review code for a specific tenant.",
  "arguments": [
    {
      "name": "tenant_id",
      "description": "The customer tenant ID",
      "required": true,
      "mcpHeader": "Tenant-Id" 
    },
    {
      "name": "source_code",
      "description": "The code to review",
      "required": true
    }
  ]
}
```

*Client Output:* When fetching this prompt with `{"tenant_id": "acme-corp"}`,
the client appends the header: `MCP-Param-Tenant-Id: acme-corp`.

**Example 2: Templated Resource Definition** 

Currently, Resource Templates only define a `uriTemplate` string (e.g.,
`file:///{tenant}/config.json`). They do not have an arguments array. To map a
URI variable to a header, we would need to redesign the core Resource Template
object to include a structured `variables` list.

```json
{
  "name": "Tenant Configuration",
  "uriTemplate": "file:///{tenant}/config.json",
  "variables": [
    {
      "name": "tenant",
      "description": "The isolated tenant environment",
      "mcpHeader": "Resource-Tenant"
    }
  ]
}

```

*Client Output:* When a client reads `file:///acme-corp/config.json`, the client
parses the URI against the template, extracts the `tenant` variable, and appends
the header: `MCP-Header-Resource-Tenant: acme-corp`.

**Pros:**

*  Achieves conceptual consistency across all executable MCP primitives (Tools,
   Prompts, Resources).

**Cons:** 

* Requires inventing new data structures (like the `variables` array for
  Resource Templates) solely to support a transport-layer feature.  
* Still fails to provide a generalized solution for arbitrary, top-level
  JSON-RPC fields like `_meta`.

### Option C: Generalized Path Mapping 

Instead of modifying parameter schemas, generalized mapping rules are attached
as sidecar metadata to specific Tool, Prompt, or Resource definitions. This uses
the JSON Pointer (RFC 6901) standard to safely extract arbitrary fields.

**Example Tool Definition:**

```json
{
  "name": "execute_query",
  "inputSchema": {
    "type": "object",
    "properties": {
      "region": { "type": "string" }
    }
  },
  "httpHeaders": [
    {
      "path": "/_meta/tenantId",
      "header": "MCP-Header-Tenant"
    },
    {
      "path": "/params/arguments/region",
      "header": "MCP-Header-Region"
    }
  ]
}

```

*Client Output:* When the client calls `execute_query`, it evaluates the JSON
Pointers against the outgoing request payload and appends the resulting headers.

* **Pros:**  
  * **Solves the Discovery Paradox:** Clients discover the rules during
    `tools/list` or `prompts/list`.  
  * **Highly Flexible:** Can extract arbitrary fields like `_meta.tenantId`,
    which Option A and B cannot do.  
  * **Separation of Concerns:** Keeps the core `inputSchema` pure, avoiding
    mixing transport routing details into semantic schemas.  
* **Cons:**  
  * **Ecosystem Parity:** Requires standardizing JSON Pointer across all language SDKs to ensure parsing consistency.  
  * **Breaks Co-location:** The definition of a parameter and its routing
    behavior are separated, creating a synchronization burden for developers.
