/**
 * content.ts — Injected into https://www.instagram.com/direct/*
 * Injects a floating "Scan thread" button, handles popup messages,
 * runs scraper + autoscroll, logs results, and delegates POSTs to background.
 */

import { scrapeThread } from "./scraper.js";
import { loadAllMessages, findMessageContainer } from "./autoscroll.js";
import { buildIngestPayload } from "./payload.js";
import type { Post, PopupCommand, ScanResponse, IngestResponse } from "./types.js";

// Cross-browser API handle
const api = (globalThis as unknown as { browser?: typeof chrome }).browser ?? chrome;

// ── Floating button ──────────────────────────────────────────────────────────

function injectFloatingButton(): void {
  if (document.getElementById("reel-inbox-fab")) return;

  const btn = document.createElement("button");
  btn.id = "reel-inbox-fab";
  btn.textContent = "📥 Scan thread";
  btn.title = "Reel Inbox Scraper — click to scan now";
  Object.assign(btn.style, {
    position: "fixed",
    bottom: "24px",
    right: "24px",
    zIndex: "2147483647",
    padding: "10px 16px",
    borderRadius: "24px",
    border: "none",
    background: "#0095f6",
    color: "#fff",
    fontSize: "14px",
    fontWeight: "600",
    cursor: "pointer",
    boxShadow: "0 2px 12px rgba(0,0,0,0.25)",
    fontFamily: "system-ui, sans-serif",
  });

  btn.addEventListener("click", () => void handleScan(false));
  document.body.appendChild(btn);
}

// ── Scan logic ────────────────────────────────────────────────────────────────

async function handleScan(loadAll: boolean): Promise<ScanResponse> {
  if (loadAll) {
    const container = findMessageContainer();
    if (container) {
      console.log("[ReelInbox] Starting autoscroll to load all messages…");
      const scrollResult = await loadAllMessages(container);
      console.log("[ReelInbox] Autoscroll done:", scrollResult);
    } else {
      console.warn("[ReelInbox] Could not find message container for autoscroll");
    }
  }

  const result = scrapeThread(document);

  // Log summary
  console.group("[ReelInbox] Scan complete");
  console.log(`Posts extracted: ${result.diagnostics.postsExtracted}`);
  console.log(`Duplicates deduped: ${result.diagnostics.deduped}`);
  console.log(`Missing author: ${result.diagnostics.missingAuthor}`);
  console.log(`Missing caption: ${result.diagnostics.missingCaption}`);
  console.log(`Missing timestamp: ${result.diagnostics.missingTimestamp}`);
  if (result.diagnostics.notes.length > 0) {
    console.log("Notes:", result.diagnostics.notes);
  }
  console.table(result.posts);
  console.log("Raw JSON (copy me):", JSON.stringify(result.posts, null, 2));
  console.groupEnd();

  // Persist to storage
  await api.storage.local.set({ lastBatch: { posts: result.posts, ts: new Date().toISOString() } });

  return {
    ok: true,
    postsExtracted: result.diagnostics.postsExtracted,
    deduped: result.diagnostics.deduped,
    diagnostics: result.diagnostics,
  };
}

async function handleSend(): Promise<IngestResponse> {
  const stored = await api.storage.local.get("lastBatch") as { lastBatch?: { posts: Post[]; ts: string } };
  if (!stored.lastBatch || stored.lastBatch.posts.length === 0) {
    return { ok: false, error: "No batch in storage. Run a scan first." };
  }

  const payload = buildIngestPayload(stored.lastBatch.posts);

  const response = await api.runtime.sendMessage({ cmd: "ingest", payload }) as IngestResponse;
  return response;
}

// ── Message listener (from popup) ────────────────────────────────────────────

api.runtime.onMessage.addListener(
  (message: unknown, _sender, sendResponse) => {
    const msg = message as PopupCommand;

    if (msg.cmd === "scanNow") {
      handleScan(false).then(sendResponse).catch((err: Error) => {
        sendResponse({ ok: false, error: err.message });
      });
      return true; // async response
    }

    if (msg.cmd === "loadAllAndScan") {
      handleScan(true).then(sendResponse).catch((err: Error) => {
        sendResponse({ ok: false, error: err.message });
      });
      return true;
    }

    if (msg.cmd === "sendLast") {
      handleSend().then(sendResponse).catch((err: Error) => {
        sendResponse({ ok: false, error: err.message });
      });
      return true;
    }

    return false;
  }
);

// ── Init ──────────────────────────────────────────────────────────────────────

// Wait for body to be available
if (document.body) {
  injectFloatingButton();
} else {
  document.addEventListener("DOMContentLoaded", injectFloatingButton);
}

// Re-inject if Instagram does a SPA navigation (replaces body)
const bodyObserver = new MutationObserver(() => {
  if (document.body && !document.getElementById("reel-inbox-fab")) {
    injectFloatingButton();
  }
});
bodyObserver.observe(document.documentElement, { childList: true, subtree: false });
