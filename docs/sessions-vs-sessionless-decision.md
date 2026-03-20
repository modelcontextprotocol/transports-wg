# **Decision Document: To App Session, or Not to App Session?** 

## **Background**

### **Sessions in MCP**

Currently, the Model Context Protocol (MCP) utilizes sessions to manage
client-server connections, but this concept blurs the line between two very
distinct use cases:

* **Transport-Level Use Cases:** Using sessions to track protocol versioning,
  capability negotiation (e.g., does this server support sampling?). 
* **Application-Level Use Cases:** Using sessions to track logical state, such
  as a specific user context, a continuous conversation thread, or stateful tool
  operations.

### **Why Sessions Need to Change**

The current implementation of sessions is highly ambiguous, leading to the
following problems/issues:

* **Inconsistent Lifecycles:** Some clients create a new session for *every
  single tool call*, others create one per *conversation*, some use one for *all
  conversations*, and others manage them without any clear boundaries. There are
  no strict guarantees around what sessions provide or how long they persist.  
* **Transport Divergences:** On STDIO, sessions are implicitly tied to the
  process lifecycle. On HTTP, sessions are optional, and their absence could
  mean the server is stateless *or* that the previous state was simply lost.  
* **Coupling of State to Connection:** Application state, client capabilities,
  and protocol versions are heavily coupled to the connection. This leads to
  operational hazards like the "Rolling Upgrade" problem (where updating a
  load-balanced server drops the connection and wipes the user's logical state)
  and multiplexing failures.

### **Resolving Transport-Level Sessions**

To resolve the ambiguities at the transport level, the working group is moving
toward a stateless transport architecture. The need for transport-level sessions
is being removed via two core SEPs:

* [**SEP-1442**](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1442)**:**
  Moves all data to a "per request" basis, eliminating the need to store
  transport state between calls.  
* [**SEP-2322**](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2322)**:**
  Allows for elicitation and sampling requests without relying on sessions to
  align them.

## **The Problem Statement**

With transport-level sessions resolved by SEP-1442 and SEP-2322, we are left
with a critical architectural decision regarding **Application-Level Sessions**.

The open question the working group must decide on is: **"Should the protocol
support application sessions (or not)?"**

Developers building agents and tools frequently need a way to track logical
state across multiple turns of a conversation. However, it is currently unclear
whose responsibility it is to maintain that state. We must decide whether to
standardize a formal session concept at the data/application layer, or
completely remove the concept of sessions from the protocol and push the
responsibility of tracking state references entirely to the client via explicit
state handles.

## **Use Cases for Application Sessions**

To understand the need for application-level state, we can look at a few
progressive examples of how tools currently rely on state across multiple turns
of a conversation. Below are the **solution-neutral logical flows** for these
interactions.

### **Simple Counter / Accumulator**

The most basic form of application state is a simple accumulator where a server
remembers previous interactions. For example, a `count()` tool that increments
every time it is called by the same user or within the same conversational
thread.

**Logical Flow:**

```
User: "Start counting"
tool/call: count()  -> Returns 0 
tool/call: count()  -> Returns 1 
tool/call: count()  -> Returns 2
```

### **E-Commerce / Shopping Cart**

In more complex workflows, tools require a specific sequence of operations where
state is built up over time. An e-commerce agent, for instance, needs to add
multiple items to a shopping cart across several distinct tool calls before
finally executing a checkout operation.

**Logical Flow:**

```
User: "I want to buy shoes and socks"
tool/call: add_item("shoes")
tool/call: add_item("socks")
tool/call: checkout()  -> Processes order for [shoes, socks]
```

### **Progressive Discovery of Tools**

Some tools are deliberately hidden to prevent overwhelming the LLM's context
window or to enforce security gates. State allows an agent to call a tool that
"unlocks" deeper capabilities or different toolsets dynamically for the
remainder of the interaction.

**Logical Flow:**

```
User: "Query the production database"
tool/call: list_tools()               -> Returns: [connect]
tool/call: execute_query("SELECT 1")  -> ERROR: Tool not found
tool/call: connect($DATABASE_URI)     -> Success
tool/call: list_tools()               -> Returns: [execute_query, list_tables, ...]
tool/call: list_tables()              -> Success
```

### **Object Creation / Multi-step Provisioning**

When creating complex resources, an agent may need to iteratively build a
configuration before executing the final creation step. This requires holding a
"draft" state across multiple actions.

**Logical Flow:**

```
User: "Provision a new VM with 16GB RAM"
tool/call: init_vm("web-server")      -> Success
tool/call: set_ram(16)                -> Success
tool/call: set_cpu(4)                 -> Success
tool/call: deploy_vm()                -> Success
```

## **Proposed Solutions**

The working group is split between two primary proposals for handling these
application-level use cases.

### **Option A: Adding Data Layer Sessions**

**Link:** [Transports-WG PR
\#20](https://github.com/modelcontextprotocol/transports-wg/pull/20)

**Outline:** Instead of relying on the transport layer (HTTP/STDIO) to manage
sessions, this proposal introduces explicit, standardized session constructs at
the *Data Layer*. The protocol would explicitly define how to initialize,
maintain, and terminate application contexts independent of the underlying
transport connection.

**Implementation Example (Implicit Tool State):** With data layer sessions, the
session ID is negotiated once and passed in the protocol envelope. Because the
server inherently knows which session is making the request, the tool signatures
themselves remain clean and rely on implicit state.

```
# The session is explicitly negotiated at the data layer
session_create(context="user_123") 

# 1. Simple Counter
count()                     # Returns 0
count()                     # Returns 1

# 2. Shopping Cart
add_item("shoes")           # Adds to the session's cart
add_item("socks")
checkout()

# 3. Capability Unlocking (Database)
list_tools()                # Returns: [connect]
connect($DATABASE_URI)      # State mutates silently for this session
list_tools()                # Returns: [connect, execute_query, list_tables, ...]

# 4. Object Creation (VM Provisioning)
init_vm("web-server")       # Context stored in session
set_ram(16)
set_cpu(4)
deploy_vm()
```

#### Advantages:

* **Lower implementation burden:** Removing the need for the agent to manage
  state, meaning accuracy is programmatic vs deterministic.

#### Disadvantages:

* **Protocol Complexity:** Retains the concept of state within the protocol
  definition, requiring servers to manage state lifecycles, TTLs (Time to Live),
  and garbage collection.

#### Open Questions

As we weigh the advantages and disadvantages of both proposals, multi-agent
orchestration presents a significant unresolved challenge:

* **Sub-Agent Orchestration:** It is currently unclear how sessions or state
  should be handled when a primary agent delegates work to a sub-agent.  Should
  a sub-agent instantiate a completely **new session**? Should it receive a
  **copy/fork** of the parent agent's session so it has the necessary context
  but cannot mutate the parent's state? Or should they share the exact same
  `session_id` (which risks the sub-agent polluting the parent's context with
  unintended operations)?

### **Option B: Sessionless MCP via Explicit State Handles**

**Link:** [Transports-WG PR \#25](https://github.com/modelcontextprotocol/transports-wg/pull/25)

**Outline:** Do not add sessions to the protocol at all. Instead, encourage a
completely stateless protocol where servers return "explicit state handles"
(e.g., tokens, cursors, or context IDs) in their tool responses. The client is
strictly responsible for storing this handle and passing it back as an argument
in subsequent related requests.

**Implementation Example (Explicit State Handles):** With explicit handles,
there are no sessions. The client explicitly requests a state handle (like a
basket ID or access token) and must manually inject it back into subsequent tool
arguments.

```
# 1. Simple Counter
counter = create_counter()  # returns { "counter_id": "cnt_123" }
count(counter)              # Returns 0
count(counter)              # Returns 1

# 2. Shopping Cart
basket = create_basket()    # returns { "basket_id": "bsk_a1b2c3" }
add_item(basket, "shoes")
add_item(basket, "socks")
checkout(basket)

# 3. Capability Unlocking (Database)
db = connect($DATABASE_URI)               # returns { "connection_id": "db_prod_1" }
list_tables(db)
execute_sql(db)                         

# 4. Object Creation (VM Provisioning)
vm = init_vm("web-server")                # returns { "draft_id": "vm_draft_99" }
set_ram(vm, 16)
set_cpu(vm, 4)
deploy_vm(vm)
```

**Advantages:**

* **Minimal Complexity:** Protocol complexity is minimal, requiring no
  additional changes. 

**Disadvantages:**

* **Breaking Change:** If applications are using sessions today for application
  state, it would require developers to update their tools and clients to use
  explicit state handles instead. 
