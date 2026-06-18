# Phase 1 Plan — Extension (URL scraper)  ⚠️ SUPERSEDED (2026-06-18)

> **This plan is superseded.** The extension was built per this spec, then proven non-viable
> against the live Instagram site (no URLs in DOM, REST API 500s, DMs over MQTT WebSocket,
> nothing in React/Relay). See `decisions.md` → "Input via official Data Download" and the
> live spec `specs/phase-1-importer-plan.md`. The extension code in `extension/` is kept but
> shelved. This file is retained for historical context only.

Authored as the build spec for the implementation agent. Read `CLAUDE.md`,
`specs/architecture.md`, and `specs/decisions.md` first — this plan refines Phase 1 of the
dev phases into concrete files, behavior, and acceptance criteria.

## Goal

A **cross-browser MV3 extension** that, on an Instagram DM thread, scrapes each shared post
into a `Post` object, logs the result to the console, and (when enabled) auto-POSTs the batch
to the backend `/ingest` endpoint.

**Phase 1 is done when:** the scraper reliably extracts posts from the real DM thread
(verified by the user via console), the auto-POST path works against a local mock backend, and
the automated checks (typecheck + unit tests + `web-ext lint`) pass.

Scope boundary (from decisions.md — do NOT exceed): the extension scrapes and sends URLs +
metadata only. No summarizing, screenshotting, downloading, or unsending.

## Environment (verified)

- Node v22.22.2, npm 10.9.8. Box: quorky (Ryzen 7 7735HS, no GPU).
- Chromium 149 installed here (snap) — usable for a load smoke-test. No Firefox/Chrome here.
- User mentioned XPI → may test in Firefox. Build must target **both** Chrome and Firefox.

## Dependencies — pin these LATEST versions (all devDependencies; zero runtime deps)

| package | version |
|---|---|
| typescript | ^6.0.3 |
| esbuild | ^0.28.1 |
| @types/chrome | ^0.1.43 |
| vitest | ^4.1.9 |
| jsdom | ^29.1.1 |
| web-ext | ^10.4.0 |
| rimraf | ^6.1.3 |

If any install fails or a peer conflict appears, re-check the latest with `npm view <pkg> version`
and adjust — do not silently downgrade to an old major.

## File layout

```
extension/
  package.json
  tsconfig.json            # TS6, strict, moduleResolution bundler, no emit (esbuild emits)
  build.mjs                # esbuild bundle + static copy; supports --target=chrome|firefox|all, --watch
  manifest.base.json       # shared manifest fields
  src/
    types.ts               # Post interface + ScrapeResult diagnostics
    scraper.ts             # PURE: scrapeThread(root: ParentNode): ScrapeResult  (no chrome/* APIs)
    autoscroll.ts          # PURE-ish: loadAllMessages(container, opts) scrolls to force lazy-load
    payload.ts             # PURE: buildIngestPayload(posts) -> request body  (unit-testable)
    content.ts             # injects floating button, runs autoscroll+scraper, logs, msgs background
    background.ts          # service worker: receives posts, POSTs to configured endpoint
    popup.html / popup.ts  # buttons: "Load all & scan", "Scan now", "Send last batch"; shows counts
    options.html / options.ts # set + persist backend endpoint (default http://localhost:8787)
  icons/                   # 16/48/128 png (simple generated placeholder is fine)
  test/
    scraper.test.ts        # vitest + jsdom, runs scraper against fixture
    payload.test.ts        # asserts payload shape
    fixtures/dm-thread.html # representative IG DM DOM snapshot (see "Fixture" below)
  tools/
    mock-backend.mjs       # tiny Node http server logging POSTed batches (no deps)
  README.md                # build / load (Chrome + Firefox) / test / mock-backend
  .gitignore               # node_modules, dist*, *.log
```

Build outputs: `dist-chrome/` and `dist-firefox/` (gitignored). These are what get loaded.

## Data shape (must match architecture.md data model)

```ts
// src/types.ts
export type PostType = "reel" | "carousel" | "image";

export interface Post {
  url: string;          // absolute, normalized: https://www.instagram.com/<reel|p>/<id>/
  type: PostType;
  author: string;       // "@handle" or "" if not found
  caption: string;      // "" if not found
  timestamp: string;    // ISO if derivable, else raw text, else ""
  altTexts: string[];   // every img[alt] inside the post bubble
}

export interface ScrapeResult {
  posts: Post[];
  diagnostics: {
    anchorsSeen: number;
    postsExtracted: number;
    deduped: number;
    missingAuthor: number;
    missingCaption: number;
    missingTimestamp: number;
    notes: string[];    // human-readable warnings to aid selector tuning
  };
}
```

## Scraper design (the crux — be defensive, Instagram DOM drifts)

`scrapeThread(root: ParentNode): ScrapeResult`

- Find post anchors: `a[href^="/reel/"], a[href^="/reels/"], a[href^="/p/"]` (also handle
  absolute `https://www.instagram.com/...` hrefs). These shortcode links are the most stable
  signal — anchor the whole extraction on them, NOT on volatile class names like `._ap3a`.
- Normalize each href → absolute `https://www.instagram.com/<reel|p>/<shortcode>/`; extract the
  shortcode; classify:
  - `/reel/` or `/reels/` → `"reel"`
  - `/p/` → `"carousel"` if the bubble shows carousel signals (multiple `<img>` in the preview,
    carousel dots/aria like "Carousel" / "1 of N", or `<ul>` with multiple `<li>` media), else
    `"image"`. When unsure default to `"image"` and add a diagnostics note.
- For each anchor, climb to the nearest enclosing "message bubble" container (a bounded ancestor
  walk, e.g. up to ~8 levels, stopping at a row/listitem boundary). From that bubble extract:
  - `author`: handle text in the shared-post preview header; prefer text matching `/^@?[\w.]+$/`
    near the top of the card. Store as `@handle`.
  - `caption`: the caption/description text node in the preview card (longest visible text block
    that isn't the handle/timestamp), trimmed.
  - `timestamp`: look for `time[datetime]`, `[datetime]`, or aria-labels with a date; fall back to
    visible time text; ISO-normalize when possible else keep raw.
  - `altTexts`: all `img[alt]` within the bubble, alt non-empty.
- **Dedup by normalized URL**, keep first occurrence; count dropped in `diagnostics.deduped`.
- **Never throw.** Wrap per-anchor extraction in try/catch; on failure push a note and continue.
- Populate all diagnostics counters. The point: when run on the real DOM, the console output
  tells us exactly which fields the selectors are missing so they can be tuned.

> Honesty note for the implementer and the user: the per-field selectors (author/caption/
> timestamp) are best-effort guesses against IG's current DM markup. The URL+type extraction is
> robust; the metadata fields will likely need one tuning pass after the first real run. The
> diagnostics block is what makes that tuning fast. Build for that, don't pretend it's final.

## Auto-scroll (handles the ~100-post lazy-loaded backlog)

`loadAllMessages(container, { maxRounds, idleRounds, delayMs })` — IG lazy-loads DM history as
you scroll up. Repeatedly scroll the message container toward the top, wait `delayMs`, and stop
when the post-anchor count stops growing for `idleRounds` consecutive rounds or `maxRounds` is
hit. Defaults: maxRounds 60, idleRounds 3, delayMs 700. Return how many rounds ran and final
anchor count. Triggered by the popup's "Load all & scan" button.

## content.ts behavior

- Runs on `https://www.instagram.com/direct/*`.
- Inject a small fixed-position floating button (bottom-right, high z-index) labeled
  "📥 Scan thread"; clicking it = "Scan now".
- Listen for popup messages: `{cmd:"scanNow"|"loadAllAndScan"|"sendLast"}`.
- On scan: (optionally loadAllMessages first) → `scrapeThread(document)` →
  `console.log` a summary + `console.table(posts)` + the raw JSON (so the user can copy it) →
  save `{posts, ts}` to `chrome.storage.local` → reply to popup with counts + diagnostics.
- On send: read last batch from storage, send `{cmd:"ingest", payload}` to background; relay
  the background's success/failure (status code or error) back to the popup.
- Use a cross-browser API handle: `const api = (globalThis as any).browser ?? chrome;`

## background.ts (service worker) — why it exists

Instagram's page CSP can block a cross-origin `fetch` made from the content script. The POST to
the local backend must therefore run in the **extension/background context**, which is governed
by `host_permissions`, not the page CSP. Flow: content script → `runtime.sendMessage({cmd:
"ingest", payload})` → background `fetch(endpoint + "/ingest", {method:"POST", headers:{"content-
type":"application/json"}, body: JSON.stringify(payload)})` → reply `{ok, status, error?}`.
Endpoint read from `chrome.storage.local` (default `http://localhost:8787`).

## Manifest (MV3, cross-browser via build targets)

`manifest.base.json` shared fields:
- `manifest_version: 3`, `name: "Reel Inbox Scraper"`, `version: "0.1.0"`,
  `description`, `permissions: ["storage","activeTab","scripting"]`,
  `host_permissions: ["https://www.instagram.com/*","http://localhost/*","http://127.0.0.1/*"]`,
  `content_scripts: [{matches:["https://www.instagram.com/direct/*"], js:["content.js"], run_at:"document_idle"}]`,
  `action: {default_popup:"popup.html"}`, `options_ui: {page:"options.html", open_in_tab:true}`,
  `icons: {16,48,128}`.

`build.mjs` merges base + per-target background key:
- **chrome target** → `background: { service_worker: "background.js", type: "module" }`
- **firefox target** → `background: { scripts: ["background.js"], type: "module" }` plus
  `browser_specific_settings: { gecko: { id: "reel-inbox@local", strict_min_version: "121.0" } }`

Write the merged `manifest.json` into each `dist-*` folder.

## build.mjs

Plain Node ESM using the esbuild JS API. Responsibilities:
1. Parse flags: `--target=chrome|firefox|all` (default all), `--watch`.
2. Clean target dir(s) with rimraf.
3. esbuild bundle each TS entry (`content`, `background`, `popup`, `options`) → IIFE/ESM JS in
   the target dir, `bundle:true`, `format:"esm"`, `target:"es2022"`, `sourcemap:true` (dev).
4. Copy static: `popup.html`, `options.html`, `icons/` → target dir.
5. Generate `manifest.json` per target (base + background merge above).
6. `--watch`: rebuild on src/static changes.

## tools/mock-backend.mjs

Dependency-free Node `http` server on port 8787. `POST /ingest` → read JSON body → log a table
of received posts + total count → respond `200 {ok:true, received:N}`. Enables full end-to-end
auto-POST testing before Phase 2's real backend exists. `GET /` → simple "mock backend up".

## Tests (vitest + jsdom)

- `scraper.test.ts`: load `fixtures/dm-thread.html` into jsdom, run `scrapeThread`, assert:
  reel + carousel + image all detected with correct `type`; URLs normalized + absolute;
  duplicate URL deduped; altTexts captured; diagnostics counts sane. Use jsdom via vitest
  `environment: "jsdom"` or construct a JSDOM instance directly.
- `payload.test.ts`: `buildIngestPayload` produces `{posts:[...]}` with the right shape.

### Fixture (`test/fixtures/dm-thread.html`)

Hand-write a small but representative IG-DM-like structure: a scrollable container with several
message bubbles, each containing a shared-post preview anchor. Include:
- one reel (`/reel/ABC123/`), one carousel (`/p/CAR456/` with multiple imgs + "1 of 3" text),
  one single image (`/p/IMG789/`), and one DUPLICATE of the reel.
- realistic `img alt` like `May be an image of text that says 'BUILD IN PUBLIC'` and a vague one.
- author handles, captions, and a `time[datetime]`.
This fixture encodes our current assumptions; it is the contract the scraper is tested against.
It is NOT a guarantee the real IG DOM matches — that's what the user's first real run verifies.

## package.json scripts

```
"build":        "node build.mjs --target=all"
"build:chrome": "node build.mjs --target=chrome"
"build:firefox":"node build.mjs --target=firefox"
"dev":          "node build.mjs --target=chrome --watch"
"typecheck":    "tsc --noEmit"
"test":         "vitest run"
"lint:ext":     "web-ext lint --source-dir=dist-firefox"
"mock":         "node tools/mock-backend.mjs"
"verify":       "npm run typecheck && npm run test && npm run build && npm run lint:ext"
```

## Acceptance criteria (the implementation agent must self-verify all of these)

1. `npm install` completes with the pinned latest versions.
2. `npm run typecheck` passes (strict).
3. `npm run test` passes (scraper + payload).
4. `npm run build` produces `dist-chrome/` and `dist-firefox/`, each with a valid `manifest.json`,
   all referenced JS/HTML/icons present.
5. `npm run lint:ext` (`web-ext lint`) reports no errors (warnings acceptable; list them).
6. README documents: install, build, load-unpacked in Chrome/Chromium, load temporary add-on in
   Firefox, run the mock backend, and the real-IG verification steps.

Report the exact command outputs back. Do not claim success for any step you did not run.
