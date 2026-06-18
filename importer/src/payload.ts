import type { Post, IngestPayload } from "./types.js";

/** Build the payload that gets POSTed to the backend /ingest endpoint. */
export function buildIngestPayload(posts: Post[]): IngestPayload {
  return {
    posts,
    importedAt: new Date().toISOString(),
    source: "data-download",
  };
}
