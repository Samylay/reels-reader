import { parseArgs } from "node:util";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseExport } from "./parse.js";
import { buildIngestPayload } from "./payload.js";
import { sendToBackend } from "./send.js";
import type { Post } from "./types.js";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    thread: { type: "string" },
    send: { type: "string" },
    out: { type: "string" },
    limit: { type: "string" },
  },
});

const exportDir = positionals[0];
if (!exportDir) {
  console.error(
    "Usage: tsx src/cli.ts <export-dir> [--thread <substr>] [--send <endpoint>] [--out <file>] [--limit <n>]"
  );
  process.exit(1);
}

const absoluteDir = resolve(exportDir);

console.log(`\nParsing export: ${absoluteDir}`);
if (values.thread) console.log(`Thread filter:  ${values.thread}`);

const { posts: allPosts, stats } = parseExport(absoluteDir, values.thread);

let posts = allPosts;
if (values.limit) {
  const n = parseInt(values.limit, 10);
  if (!isNaN(n) && n > 0) {
    posts = posts.slice(0, n);
    console.log(`\nLimited to first ${n} posts.`);
  }
}

// ── Summary report ──────────────────────────────────────────────────────────
console.log("\n─────────────────────────────────────────");
console.log("IMPORT SUMMARY");
console.log("─────────────────────────────────────────");
console.log(`Files scanned : ${stats.filesScanned}`);
console.log(`Posts found   : ${stats.postsFound}`);
console.log(`Deduped       : ${stats.deduped}`);
console.log(`  Reels       : ${stats.reels}`);
console.log(`  /p/ (image) : ${stats.posts_p}`);
console.log(`Unique posts  : ${posts.length}`);

console.log("\nPer-thread breakdown:");
for (const [slug, count] of Object.entries(stats.threads)) {
  console.log(`  ${slug}: ${count} post(s)`);
}

if (stats.notes.length > 0) {
  console.log("\nNotes:");
  for (const note of stats.notes) {
    console.log(`  • ${note}`);
  }
}

// ── Post preview table ───────────────────────────────────────────────────────
const preview = posts.slice(0, 5);
if (preview.length > 0) {
  console.log("\nFirst posts (up to 5):");
  console.log(
    "  " +
      ["URL".padEnd(60), "TYPE".padEnd(10), "AUTHOR".padEnd(20), "TIMESTAMP"].join(" | ")
  );
  console.log("  " + "─".repeat(110));
  for (const p of preview) {
    const url = p.url.slice(0, 58).padEnd(60);
    const type = p.type.padEnd(10);
    const author = (p.author || "(none)").padEnd(20);
    const ts = p.timestamp;
    console.log(`  ${url} | ${type} | ${author} | ${ts}`);
    if (p.caption) {
      console.log(`    Caption: ${p.caption.slice(0, 80)}${p.caption.length > 80 ? "…" : ""}`);
    }
  }
}

// ── Write JSON output ────────────────────────────────────────────────────────
const outFile = values.out ?? "./posts.json";
const payload = buildIngestPayload(posts);

try {
  writeFileSync(outFile, JSON.stringify(payload, null, 2), "utf8");
  console.log(`\nWrote ${posts.length} post(s) to ${outFile}`);
} catch (err) {
  console.error(`Failed to write ${outFile}: ${String(err)}`);
}

// ── Optional POST to backend ─────────────────────────────────────────────────
if (values.send) {
  console.log(`\nPOSTing to ${values.send}/ingest …`);
  try {
    const result = await sendToBackend(values.send, payload);
    console.log(`HTTP ${result.status}: ${result.body.slice(0, 200)}`);
  } catch (err) {
    console.error(`Send failed: ${String(err)}`);
    process.exit(1);
  }
}
