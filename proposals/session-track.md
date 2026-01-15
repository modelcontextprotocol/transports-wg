**Sessions Track: Brief**

**Goal** To decouple session state from the underlying transport connection, allowing for robust, long-lived application state that survives connection drops and scales horizontally across stateless servers.

**Core Principle: Adapted Cookie Semantics**

* **RFC 6265 as a Foundation:** We will use **RFC 6265 (HTTP Cookies)** as a functional starting point to determine necessary adaptations for MCP.  
* **Payload Integration:** Session data will primarily be included as a dedicated field within the JSON-RPC payload. We will look to **SEP-1655** and **SEP-1685** for inspiration on structuring this metadata.

**Key Requirements**

* **Routing Compatibility & Size Constraints:** To allow load balancers to route requests based on session affinity, we may need to copy the session identifier/token into an HTTP header. This introduces strict **size constraints**; the session token must remain small enough to fit within standard header limits (typically \~4KB), prohibiting large state blobs from being stored directly in the token.  
* **Security & Integrity:** Servers utilizing cookies must encrypt or sign the data to prevent client-side tampering. We will evaluate including a standard mechanism for signing/encryption directly in the spec.  
* **Expert Review:** We will consult security experts to review the design for known vulnerabilities common in standard cookie implementations.

**Key Design Decision: Lifecycle Management**

* **Implicit vs. Explicit:** We must decide between allowing lazy initialization (Implicit) versus requiring a formal setup handshake (Explicit).  
  * *Consideration:* The need to **copy or fork** session data (e.g., branching an agent's state) strongly suggests preferring an **Explicit** mechanism (e.g., `session/create`, `session/fork`) to ensure these operations are predictable and race-free.
