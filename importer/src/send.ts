import type { IngestPayload } from "./types.js";

/** POST the ingest payload to <endpoint>/ingest using Node 22 global fetch.
 *  Returns the HTTP status code.
 */
export async function sendToBackend(
  endpoint: string,
  payload: IngestPayload
): Promise<{ status: number; body: string }> {
  const url = endpoint.replace(/\/$/, "") + "/ingest";
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.text();
  return { status: response.status, body };
}
