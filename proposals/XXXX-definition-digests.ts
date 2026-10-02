/**
 * Informative TypeScript reference for SEP-XXXX: Definition Digests.
 *
 * XXXX-definition-digests.md is authoritative. This file shows the two
 * additions the SEP makes to the 2026-07-28 schema and nothing else. It
 * does not validate runtime behavior.
 *
 * Base types are shown inline rather than imported, so the fragment reads
 * standalone. They match schema/2026-07-28/schema.ts in
 * modelcontextprotocol/modelcontextprotocol.
 */

/* ---- Base types, unchanged, for context ---- */

interface MetaObject {
  [key: string]: unknown;
}

interface Result {
  _meta?: ResultMetaObject;
  resultType: "complete" | "input_required";
  [key: string]: unknown;
}

/* ResultMetaObject is extended below (Addition 3). */

/* ---- Addition 1: `digest` on CacheableResult ---- */

/**
 * A result that supports client-side caching hints.
 *
 * The SEP adds `digest`. Every result type that already extends
 * CacheableResult (server/discover, the four list methods, resources/read,
 * and extension lists such as skills/list) inherits it with no further
 * schema change.
 */
export interface CacheableResult extends Result {
  /** Freshness hint in milliseconds, analogous to Cache-Control max-age. @minimum 0 */
  ttlMs: number;
  /** Who may share the cached response. */
  cacheScope: "public" | "private";
  /**
   * An opaque, deterministic identifier for what this result describes,
   * with the envelope removed (`resultType`, `_meta`, `ttlMs`, `cacheScope`,
   * `digest`, `nextCursor`). For a list, it covers the complete collection
   * the caller can see, not the page in hand. It changes whenever the
   * definitions do.
   *
   * What it covers is fixed by the method that produced the result, so the
   * method is not repeated here. Servers omit it on resources/read.
   *
   * Clients MUST treat it as opaque and compare only for equality.
   */
  digest?: string;
}

/* ---- Addition 2: `knownDigests` on request `_meta` ---- */

/**
 * A method that produces a digest. Methods are unique, so extension list
 * methods (e.g. "skills/list") need no further naming rule.
 */
export type DigestMethod =
  | "server/discover"
  | "tools/list"
  | "prompts/list"
  | "resources/list"
  | "resources/templates/list"
  | (string & {});

/**
 * Digests a client is working from, keyed by the method that produced each
 * one. Any request may carry this.
 */
export type KnownDigests = { [method in DigestMethod]?: string };

export interface RequestMetaObject extends MetaObject {
  // Existing fields (progressToken, protocolVersion, clientInfo, ...) unchanged.

  /**
   * Hints, not preconditions. A server MAY ignore them, honor them by
   * serving the request under the definitions a digest describes, or reject
   * the request as stale. A rejection MUST happen before operation-specific
   * validation and before any side effect.
   *
   * Clients SHOULD only send digests received from the same server in the
   * same authorization context. Key naming follows the `_meta` rules; the
   * `io.modelcontextprotocol/` prefix is proposed, not yet allocated.
   */
  "io.modelcontextprotocol/knownDigests"?: KnownDigests;
}

/* ---- Addition 3: `staleDigests` on result `_meta` ---- */

export interface ResultMetaObject extends MetaObject {
  // Existing fields (serverInfo, ...) unchanged.

  /**
   * Methods whose known digest did not match the current definitions. The
   * request was still served; the client SHOULD re-fetch these before its
   * next dependent operation but MUST NOT treat this result as an error or
   * retry the request. MUST NOT include current digests.
   *
   * Servers that honor a stale digest SHOULD set this so that honoring is
   * distinguishable from ignoring.
   */
  "io.modelcontextprotocol/staleDigests"?: DigestMethod[];
}

/* ---- Error data on a digest mismatch ---- */

/**
 * `data` for the digest-mismatch JSON-RPC error, used when the server will
 * not serve the request against the digests it was given. The numeric code
 * is not yet allocated. Same list and same rule as the result `_meta` key:
 * name the methods, never the current digests.
 */
export interface DigestMismatchErrorData {
  staleDigests: DigestMethod[];
}
