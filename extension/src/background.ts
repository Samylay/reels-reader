/**
 * background.ts — Service worker / background script.
 * Receives ingest commands from content script and POSTs to the backend.
 * Must run in extension context (not page context) so page CSP cannot block it.
 */

import type { BackgroundCommand, IngestResponse } from "./types.js";

const DEFAULT_ENDPOINT = "http://localhost:8787";

// Cross-browser API handle
const api = (globalThis as unknown as { browser?: typeof chrome }).browser ?? chrome;

async function getEndpoint(): Promise<string> {
  const stored = await api.storage.local.get("endpoint") as { endpoint?: string };
  return stored.endpoint ?? DEFAULT_ENDPOINT;
}

api.runtime.onMessage.addListener(
  (message: unknown, _sender, sendResponse) => {
    const msg = message as BackgroundCommand;

    if (msg.cmd === "ingest") {
      (async () => {
        const endpoint = await getEndpoint();
        try {
          const resp = await fetch(`${endpoint}/ingest`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(msg.payload),
          });

          const result: IngestResponse = {
            ok: resp.ok,
            status: resp.status,
          };
          sendResponse(result);
        } catch (err) {
          const result: IngestResponse = {
            ok: false,
            error: err instanceof Error ? err.message : String(err),
          };
          sendResponse(result);
        }
      })();
      return true; // async response
    }

    return false;
  }
);
