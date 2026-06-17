/**
 * popup.ts — Extension popup UI controller.
 */

import type { PopupCommand, ScanResponse, IngestResponse } from "./types.js";

const api = (globalThis as unknown as { browser?: typeof chrome }).browser ?? chrome;

function setStatus(msg: string, type: "info" | "success" | "error"): void {
  const el = document.getElementById("status")!;
  el.textContent = msg;
  el.className = `status ${type}`;
}

function setCounts(text: string): void {
  const el = document.getElementById("counts")!;
  el.textContent = text;
}

function setAllDisabled(disabled: boolean): void {
  for (const id of ["btn-load-all", "btn-scan-now", "btn-send-last"]) {
    (document.getElementById(id) as HTMLButtonElement).disabled = disabled;
  }
}

async function getActiveTab(): Promise<chrome.tabs.Tab | null> {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  return tabs[0] ?? null;
}

async function sendToContent(cmd: PopupCommand): Promise<ScanResponse | IngestResponse | null> {
  const tab = await getActiveTab();
  if (!tab?.id) {
    setStatus("No active tab found", "error");
    return null;
  }

  // Check we're on an IG DM page
  if (!tab.url?.includes("instagram.com/direct/")) {
    setStatus("Navigate to an Instagram DM thread first", "error");
    return null;
  }

  return new Promise((resolve) => {
    api.tabs.sendMessage(tab.id!, cmd, (response) => {
      if (api.runtime.lastError) {
        setStatus(`Error: ${api.runtime.lastError.message ?? "Unknown error"}`, "error");
        resolve(null);
        return;
      }
      resolve(response as ScanResponse | IngestResponse);
    });
  });
}

async function handleScan(loadAll: boolean): Promise<void> {
  setStatus(loadAll ? "Loading all messages…" : "Scanning…", "info");
  setAllDisabled(true);

  try {
    const cmd: PopupCommand = loadAll ? { cmd: "loadAllAndScan" } : { cmd: "scanNow" };
    const result = await sendToContent(cmd);

    if (!result) return;

    const r = result as ScanResponse;
    if (r.ok) {
      setStatus(`Scan complete!`, "success");
      setCounts(
        `${r.postsExtracted} posts found, ${r.deduped} duplicates removed. ` +
        `Missing: author=${r.diagnostics.missingAuthor}, caption=${r.diagnostics.missingCaption}, ` +
        `timestamp=${r.diagnostics.missingTimestamp}`
      );
    } else {
      setStatus(`Scan failed`, "error");
    }
  } finally {
    setAllDisabled(false);
  }
}

async function handleSendLast(): Promise<void> {
  setStatus("Sending last batch…", "info");
  setAllDisabled(true);

  try {
    const result = await sendToContent({ cmd: "sendLast" });
    if (!result) return;

    const r = result as IngestResponse;
    if (r.ok) {
      setStatus(`Sent! Status: ${r.status ?? "ok"}`, "success");
    } else {
      setStatus(`Send failed: ${r.error ?? `HTTP ${r.status}`}`, "error");
    }
  } finally {
    setAllDisabled(false);
  }
}

document.getElementById("btn-load-all")!.addEventListener("click", () => void handleScan(true));
document.getElementById("btn-scan-now")!.addEventListener("click", () => void handleScan(false));
document.getElementById("btn-send-last")!.addEventListener("click", () => void handleSendLast());
document.getElementById("options-link")!.addEventListener("click", (e) => {
  e.preventDefault();
  api.runtime.openOptionsPage();
});
