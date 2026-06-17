#!/usr/bin/env node
/**
 * tools/mock-backend.mjs
 * Dependency-free Node http server on port 8787.
 * Logs POSTed ingest batches and responds 200 OK.
 *
 * Usage:
 *   node tools/mock-backend.mjs
 *   # or: npm run mock
 */

import { createServer } from "node:http";

const PORT = 8787;

const server = createServer((req, res) => {
  // CORS — allow the extension (any origin)
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "content-type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "GET" && req.url === "/") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "mock backend up", port: PORT }));
    return;
  }

  if (req.method === "POST" && req.url === "/ingest") {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      try {
        const payload = JSON.parse(body);
        const posts = payload.posts ?? [];
        const count = posts.length;

        console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
        console.log(`[mock-backend] POST /ingest — ${count} post(s) received`);
        console.log(`[mock-backend] scrapedAt: ${payload.scrapedAt ?? "(missing)"}`);
        console.log(`[mock-backend] extensionVersion: ${payload.extensionVersion ?? "(missing)"}`);

        if (count > 0) {
          console.log("\n[mock-backend] Posts table:");
          const rows = posts.map((p, i) => ({
            "#": i + 1,
            type: p.type ?? "",
            url: (p.url ?? "").slice(0, 60),
            author: p.author ?? "",
            timestamp: p.timestamp ?? "",
            altTexts: (p.altTexts ?? []).length,
            caption: (p.caption ?? "").slice(0, 40),
          }));
          console.table(rows);
        }

        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: true, received: count }));
      } catch (err) {
        console.error("[mock-backend] Failed to parse body:", err.message);
        res.writeHead(400, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: "Invalid JSON" }));
      }
    });
    return;
  }

  res.writeHead(404, { "content-type": "application/json" });
  res.end(JSON.stringify({ error: "Not found" }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`\n[mock-backend] Listening on http://127.0.0.1:${PORT}`);
  console.log("[mock-backend] POST /ingest to receive scraped batches");
  console.log("[mock-backend] GET  / to check status\n");
});
