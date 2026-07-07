import type { IngestPayload } from "./types.js";

/** Default request timeout (ms) — a hung or unreachable backend would otherwise
 *  block the CLI indefinitely, since global fetch has no built-in timeout. */
export const DEFAULT_TIMEOUT_MS = 30_000;

/** POST the ingest payload to <endpoint>/ingest using Node 22 global fetch.
 *  Aborts after timeoutMs (default 30s) so an unresponsive backend can't hang
 *  the process forever. Returns the HTTP status code and response body.
 */
export async function sendToBackend(
  endpoint: string,
  payload: IngestPayload,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<{ status: number; body: string }> {
  const url = endpoint.replace(/\/$/, "") + "/ingest";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const body = await response.text();
    return { status: response.status, body };
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(
        `Request to ${url} timed out after ${timeoutMs}ms`
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
