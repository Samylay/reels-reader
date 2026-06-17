/**
 * payload.ts — PURE module, no chrome.* APIs.
 * Builds the ingest request body from scraped posts.
 */

import type { Post, IngestPayload } from "./types.js";

const EXTENSION_VERSION = "0.1.0";

/**
 * Build the payload to POST to the backend /ingest endpoint.
 * Pure function — no side effects, fully unit-testable.
 */
export function buildIngestPayload(posts: Post[]): IngestPayload {
  return {
    posts,
    scrapedAt: new Date().toISOString(),
    extensionVersion: EXTENSION_VERSION,
  };
}
