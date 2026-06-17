# Getting Started — running this on your main PC

This is the human run-guide. It gets the **Phase 1 extension** working from a fresh clone on
your main machine (the one logged into Instagram). For the *why* behind the design see
[`CLAUDE.md`](CLAUDE.md) and [`specs/`](specs/) — those are the project/agent docs, this is the
"just get it running" doc.

> **Why your main PC, not quorky:** the extension has to run in the browser that's signed into
> your Instagram account. It was built/validated on quorky (headless Chromium), but you'll
> actually *use* it wherever your Instagram session lives — your desktop.

## What works today (Phase 1)

A cross-browser MV3 extension that, on your Instagram **self-DM thread**, scrolls the whole
backlog, scrapes every shared post into `{url, type, author, caption, timestamp, altTexts}`,
logs it to the console, and POSTs the batch to a local backend. The "backend" for now is a tiny
**mock server** that just logs what it receives — the real one is Phase 2.

---

## 1. Prerequisites

- **git**
- **Node.js ≥ 22** and npm (built/tested on Node 22.22, npm 10.9)
- A browser logged into your Instagram: **Chrome / Chromium / Edge / Brave**, or **Firefox**

On CachyOS / Arch:
```bash
sudo pacman -S --needed git nodejs npm
node -v   # expect v22+ ; if your distro ships older, use fnm/nvm instead
```

## 2. Clone

```bash
git clone git@github.com:Samylay/reels-reader.git
cd reels-reader
```

## 3. Build the extension

```bash
cd extension
npm install
npm run build      # outputs dist-chrome/ and dist-firefox/
```

Optional sanity check (same checks CI-style):
```bash
npm run verify     # typecheck + tests + build + web-ext lint
```

## 4. Start the mock backend

In a **separate terminal**, from `extension/`:
```bash
npm run mock       # http://localhost:8787 — logs every batch it receives
```
Leave it running. This is where "Send" lands until the Phase 2 backend exists.

## 5. Load the extension

### Chrome / Chromium / Edge / Brave (no packaging needed)
1. Open `chrome://extensions`
2. Turn on **Developer mode** (top-right)
3. **Load unpacked** → pick the `extension/dist-chrome` folder
4. Pin it: puzzle-piece icon → pin **Reel Inbox Scraper**

### Firefox (no XPI needed for testing)
1. Open `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on** → pick `extension/dist-firefox/manifest.json`
   - (Temporary add-ons unload when Firefox restarts — fine for testing. A permanent install
     needs a *signed* XPI via `npx web-ext sign`; skip that for now.)

## 6. Configure the backend URL (optional)

Default is already `http://localhost:8787`, matching the mock server. To change it: click the
extension icon → **Options** (gear link in the popup).

## 7. Use it

1. Open your self-DM thread: `https://www.instagram.com/direct/...`
2. Open the browser console (**F12** → Console) so you can watch output
3. Click the extension icon. Buttons:
   - **Load all & scan** — scrolls up to force-load the whole ~100-post backlog, then scrapes
   - **Scan now** — scrapes only what's currently on screen (quick test)
   - **Send last batch** — POSTs the scraped batch to the backend (watch your mock terminal)
4. Read the console: a `console.table` of all posts plus a diagnostics line like
   `missing author=2 caption=0 timestamp=5`.

---

## Expect one tuning pass

URL + post-type detection is robust. The **author / caption / timestamp** selectors are
best-effort guesses against Instagram's current DM markup and will likely need a small fix after
the first real run — that's expected, not a bug. If those fields come back empty:

1. Note the `missing …` counts in the console.
2. Copy the raw JSON of 2–3 posts.
3. Hand that back to the project (or Claude) — it's a quick selector patch, then
   `npm run build` and reload the extension.

## Updating after a code change

```bash
cd extension && npm run build
```
Then in `chrome://extensions` (or `about:debugging`) click the **reload** icon on the extension.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Popup says "Navigate to an Instagram DM thread first" | You must be on a `instagram.com/direct/...` page |
| "Send" fails / nothing in mock terminal | Is `npm run mock` running? Does the Options endpoint match (`http://localhost:8787`)? |
| Nothing scraped | Use **Load all & scan** (lazy-loaded history must be scrolled in first); check console for errors |
| Extension won't load | Rebuild (`npm run build`) and load the `dist-chrome` / `dist-firefox` folder, not `src/` |

## What's next

**Phase 2** — the real Node backend: `/ingest` endpoint, SQLite store, a hands-off batch queue,
reels via local Whisper + Sonnet summaries, images via local vision. See
[`specs/architecture.md`](specs/architecture.md) and [`specs/phase-1-plan.md`](specs/phase-1-plan.md).
