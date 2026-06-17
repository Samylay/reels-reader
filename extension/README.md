# Reel Inbox Scraper — Browser Extension

Phase 1 of the Reels Reader pipeline. A cross-browser MV3 extension that scrapes
Instagram DM-thread shared posts into `Post` objects, logs them to the console,
and auto-POSTs them to a backend `/ingest` endpoint.

**Scope boundary:** scrapes URLs + metadata only. No summarizing, screenshotting,
downloading, or unsending. (See `specs/decisions.md`.)

---

## Prerequisites

- Node v18+ (v22 recommended)
- npm 10+
- Chrome/Chromium or Firefox (119+) for manual testing

---

## Install

```bash
cd extension/
npm install
```

---

## Build

```bash
# Build both Chrome and Firefox targets (default)
npm run build

# Build one target only
npm run build:chrome
npm run build:firefox

# Watch mode (Chrome, for active development)
npm run dev
```

Outputs: `dist-chrome/` and `dist-firefox/` (gitignored).

---

## Typecheck

```bash
npm run typecheck
# Runs tsc --noEmit with strict settings (no emit — esbuild does that)
```

---

## Tests

```bash
npm test
# Runs vitest against test/scraper.test.ts and test/payload.test.ts
# Uses jsdom; no browser required
```

---

## Load in Chrome / Chromium

1. Build: `npm run build:chrome`
2. Open Chrome and navigate to `chrome://extensions/`
3. Enable **Developer mode** (top-right toggle)
4. Click **Load unpacked**
5. Select the `dist-chrome/` folder
6. Navigate to `https://www.instagram.com/direct/t/<thread_id>/`
7. The "📥 Scan thread" floating button appears bottom-right
8. Click the extension icon in the toolbar to open the popup

---

## Load in Firefox (Temporary Add-on)

1. Build: `npm run build:firefox`
2. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`
3. Click **Load Temporary Add-on…**
4. Select `dist-firefox/manifest.json`
5. Navigate to `https://www.instagram.com/direct/t/<thread_id>/`
6. The floating button and popup work the same as Chrome

> **Note:** Firefox temporary add-ons are removed on browser restart. For a persistent
> install you would need to sign the extension via `web-ext sign` (requires AMO API keys)
> or use Developer Edition / Nightly with `xpinstall.signatures.required = false`.

---

## Mock Backend

The mock backend is a dependency-free Node HTTP server that logs POSTed batches
to the console. Use it to test the auto-POST path before Phase 2's real backend exists.

```bash
# In one terminal:
npm run mock
# Listening on http://127.0.0.1:8787

# In the extension popup, the default endpoint is http://localhost:8787
# After scanning, click "Send last batch" to POST to the mock server
```

The mock server logs a table of received posts and responds `200 {ok:true, received:N}`.

---

## Options Page (Backend URL)

The extension defaults to `http://localhost:8787`. To change it:

1. Click the extension icon → click **⚙️ Options** link at the bottom of the popup
2. Enter your backend URL (e.g. `http://192.168.1.100:8787` for a remote machine)
3. Click **Save**

The background service worker reads this URL each time it POSTs.

---

## Real-Instagram Verification Steps

After loading the extension in Chrome/Chromium:

1. Log in to Instagram and open a DM thread that contains shared posts
   (e.g. `https://www.instagram.com/direct/t/<thread_id>/`)
2. Open DevTools (`F12`) → Console tab
3. **Scan now:** Click the "📥 Scan thread" floating button (or use popup → "Scan now")
4. In the console, verify:
   - `[ReelInbox] Scan complete` log group appears
   - `console.table` shows the scraped posts
   - The diagnostics block shows `anchorsSeen`, `postsExtracted`, `deduped` counts
5. **Load all:** For a large backlog (~100 posts), use popup → "Load all & scan" to
   autoscroll the thread and force Instagram to lazy-load all messages before scraping
6. **Inspect fields:** Check `missingAuthor`, `missingCaption`, `missingTimestamp` counts.
   These will likely be non-zero on the first run — see "Selector Tuning" below.
7. **Send to mock backend:**
   - Start mock backend: `npm run mock`
   - Popup → "Send last batch"
   - Verify the mock backend console shows the received posts table

---

## Selector Tuning (Expected After First Real Run)

The URL and type extraction (reel vs carousel vs image) is robust and anchored
to `<a href>` patterns that are stable Instagram signals.

The per-field extractors — **author**, **caption**, **timestamp** — are best-effort
guesses against the current DM markup and **will likely need one tuning pass** after
the first real run. The diagnostics block (`missingAuthor`, `missingCaption`,
`missingTimestamp`, `notes[]`) is designed to make this fast:

1. Run the extension on the real thread
2. Read the diagnostics in the console
3. Use DevTools to inspect the actual DOM around a shared post bubble
4. Update the selectors in `src/scraper.ts` → `extractAuthor`, `extractCaption`,
   `extractTimestamp`
5. Rebuild and reload

The fixture `test/fixtures/dm-thread.html` encodes the assumed structure; update
it to match any real-DOM discoveries and re-run `npm test`.

---

## web-ext Lint

```bash
npm run lint:ext
# Runs web-ext lint against dist-firefox/
# No errors expected; warnings about MV3 features are ok
```

---

## All Checks At Once

```bash
npm run verify
# Runs: typecheck → test → build → lint:ext
```

---

## File Layout

```
extension/
  package.json
  tsconfig.json          # TS strict, moduleResolution bundler, no emit
  build.mjs              # esbuild bundler; --target=chrome|firefox|all, --watch
  manifest.base.json     # shared manifest fields
  src/
    types.ts             # Post, ScrapeResult, IngestPayload interfaces
    scraper.ts           # PURE: scrapeThread(root) → ScrapeResult
    autoscroll.ts        # PURE-ish: loadAllMessages() + findMessageContainer()
    payload.ts           # PURE: buildIngestPayload(posts) → IngestPayload
    content.ts           # Injects floating button, talks to popup & background
    background.ts        # Service worker: POSTs to backend (bypasses page CSP)
    popup.html / popup.ts
    options.html / options.ts
  icons/                 # 16/48/128 png
  test/
    scraper.test.ts
    payload.test.ts
    fixtures/dm-thread.html
  tools/
    mock-backend.mjs     # Dependency-free mock /ingest server on port 8787
  .gitignore
  README.md
```
