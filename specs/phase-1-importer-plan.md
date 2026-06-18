# Phase 1 (revised) — Importer for Instagram Data Download

The live build spec for Step 1, replacing `specs/phase-1-plan.md` (extension, shelved). Read
`CLAUDE.md`, `specs/architecture.md`, and `specs/decisions.md` first — especially the decision
"Input via official Data Download, not live scraping" for why this exists.

## Goal

A small **Node + TypeScript CLI** that reads Instagram's official "Download Your Information"
**Messages** export (JSON) from a local folder, extracts every shared post, and emits the post
list in the shape the backend already expects — optionally POSTing it to `/ingest`.

**Done when:** given a real export folder, it prints a correct post list (reels + posts,
deduped, captions/authors/timestamps populated, text correctly decoded) and can POST that batch
to the local mock backend; typecheck + unit tests pass.

Scope boundary: it parses a local file only. It NEVER contacts Instagram, fetches media, or
summarizes. Non-destructive.

## Input format (Instagram "Download Your Information", JSON)

The user selects **Messages**, format **JSON**, unzips it. Layout (path varies by export
version — handle both):
```
<export>/your_instagram_activity/messages/inbox/<thread_slug>/message_1.json   (newer)
<export>/messages/inbox/<thread_slug>/message_1.json                            (older)
```
Each `message_*.json` (there can be several per thread: `message_1.json`, `message_2.json`, …):
```jsonc
{
  "participants": [{ "name": "samy.lay" }, ...],
  "messages": [
    {
      "sender_name": "samy.lay",
      "timestamp_ms": 1714525200000,
      "share": {
        "link": "https://www.instagram.com/reel/ABC123def/",
        "share_text": "optional caption/quote text",
        "original_content_owner": "creator_handle"   // not always present
      }
    },
    { "sender_name": "...", "timestamp_ms": ..., "content": "plain text message" }  // ignore
  ]
}
```
Only messages with a `share.link` that is an Instagram post permalink are posts. Ignore text
messages, reactions, calls, etc.

> **Known quirk — double-encoded text.** Instagram exports JSON strings as UTF-8 bytes
> re-escaped through Latin-1 (e.g. an emoji shows as `ð...`, `é` as `Ã©`). Fix each
> user-facing string by reinterpreting it: `Buffer.from(s, "latin1").toString("utf8")`. Guard:
> if the result contains the replacement char `�`, keep the original.

## File layout

```
importer/
  package.json
  tsconfig.json            # TS6, strict, NodeNext
  src/
    types.ts               # Post (must match architecture.md model) + IngestPayload
    encoding.ts            # fixMojibake(s) — the latin1→utf8 reinterpretation, guarded
    parse.ts               # PURE: parseExport(dir) -> { posts, stats } ; classifyUrl, normalize
    payload.ts             # PURE: buildIngestPayload(posts) -> { posts, importedAt, source }
    send.ts                # POST payload to <endpoint>/ingest (fetch, Node 22 global)
    cli.ts                 # arg parsing (node:util parseArgs), orchestration, console report
  test/
    parse.test.ts
    encoding.test.ts
    fixtures/export/your_instagram_activity/messages/inbox/
        self_xxx/message_1.json     # reel share + post share + duplicate + plain text msg + mojibake caption
        other_yyy/message_1.json     # a share in another thread (for --thread filtering test)
  README.md
  .gitignore               # node_modules, *.log, posts.json
```

Zero or near-zero runtime deps: use Node built-ins (`node:fs`, `node:path`, `node:util`
`parseArgs`, global `fetch`). Recursive directory walk by hand — do NOT add a glob dependency.
Dev deps (pin LATEST — verify each with `npm view <pkg> version`): `typescript`, `tsx`
(to run TS directly), `vitest`, plus `@types/node`.

## Data shape (must match `extension/src/types.ts` / architecture.md)

```ts
export type PostType = "reel" | "carousel" | "image";
export interface Post {
  url: string;        // normalized https://www.instagram.com/<reel|p>/<code>/
  type: PostType;
  author: string;     // "@handle" or ""
  caption: string;    // decoded share_text, or ""
  timestamp: string;  // ISO 8601 from timestamp_ms
  altTexts: string[]; // ALWAYS [] from this source (export has no alt text) — see architecture note
}
export interface IngestPayload { posts: Post[]; importedAt: string; source: "data-download"; }
```

## parse.ts behavior

- `parseExport(rootDir)`: recursively find every `message_*.json` whose path contains
  `inbox/`. For each, parse, iterate `messages`, keep those with a valid `share.link`.
- `normalizeUrl(link)`: accept `/reel/`, `/reels/`, `/p/`, `/tv/`; produce
  `https://www.instagram.com/<reel|p>/<code>/`. Map `reels`→`reel`, `tv`→`reel` (video). Return
  null for non-post links (profiles, external) — skip those.
- `classifyType`: `/reel/` (incl. reels, tv) → `"reel"`. `/p/` → `"image"` as a **placeholder**
  (the export can't distinguish carousel vs single image; the backend reclassifies when it
  fetches). Record this in stats.notes.
- author: `@` + `share.original_content_owner` if present, else "". Decode via fixMojibake.
- caption: `fixMojibake(share.share_text)` if present, else "".
- timestamp: `new Date(timestamp_ms).toISOString()`.
- **Dedup by normalized URL** across all threads/files; count dups in stats.
- Track per-thread counts (thread slug = the inbox subfolder name) so the user can see where
  posts came from and optionally filter.
- Never throw on a malformed file — record a note and continue.
- Returns `{ posts, stats: { filesScanned, threads: {slug: count}, postsFound, deduped, reels, posts_p, notes[] } }`.

## cli.ts

```
tsx src/cli.ts <export-dir> [options]
  --thread <substr>     only include threads whose folder name includes <substr>
  --send <endpoint>     POST the batch to <endpoint>/ingest (e.g. http://localhost:8787)
  --out <file>          write posts.json (default: ./posts.json)
  --limit <n>           cap number of posts (for a small test run)
```
Always print: files scanned, per-thread breakdown, total posts, reels vs /p/ counts, dedup
count, and the first few posts as a table. If `--send`, report the HTTP status returned.

## Validation (the agent must actually run these and report real output)

1. `npm install` with pinned latest versions.
2. `npm run typecheck` (tsc --noEmit, strict) — clean.
3. `npm test` (vitest) — parse + encoding tests pass, including: reel + /p/ extraction,
   dedup, mojibake decode (`Ã©`→`é` and an emoji), `--thread` filtering, ISO timestamp,
   plain-text messages ignored.
4. Dry run against the fixture: `npx tsx src/cli.ts test/fixtures/export` prints the expected
   posts. Capture the output.

Report: file tree, exact command outputs, and any assumptions about the export JSON shape that
should be confirmed against the user's real export (field names especially —
`original_content_owner`, `share_text`, the `your_instagram_activity/messages/inbox` path).
Be honest about what's verified against the fixture vs. what awaits the real export.
