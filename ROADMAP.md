# Roadmap — reels-reader

> Executor contract: each night an unattended Sonnet agent (`claude -p`, cwd = this repo) picks the FIRST unchecked task, does ONLY that task, verifies it per the task's Verify note, commits with an `autoloop:` prefix (one logical change per commit, never leave the tree dirty), then ticks the checkbox adding the date and a one-line result, and appends details to ## Log. If verification fails: revert, leave unchecked, add a `BLOCKED:` note.

> **Rewritten 2026-07-07 after the capture-first pivot** (see `specs/decisions.md`).
> The previous T01–T09 (backend scaffold → React inbox → containerized deploy) targeted
> the backlog-draining design and are superseded — the capture service replaced them.

## Context for the executor

Live service: `capture/server.py` runs as system unit `reels-capture.service`
(Telegram long-poll + `POST /ingest` on 127.0.0.1:8093 → yt-dlp → whisper at
`172.17.0.1:8091` → `claude -p` sonnet → vault `01-Inbox/reels/` → Telegram reply).
Read `CLAUDE.md` first. **Do not re-open decisions settled in `specs/decisions.md`.**

- Python 3 stdlib only in `capture/` (house style: see `~/services/whisper/server.py`).
  Verify any change with `python3 -m py_compile capture/server.py` plus the task's
  functional check. You may NOT restart `reels-capture.service` (system unit, needs
  sudo) — code changes take effect on Samy's next restart; say so in the Log entry.
- Secrets: `~/.config/reels-capture.env` (bot token) and `~/.config/claude-cli.env` —
  never read into logs, never commit.
- `importer/` is a retired one-shot tool (31 tests green) — leave it working, don't
  extend it. `extension/` stays shelved as-is.
- **NEVER touch:** anything contacting Instagram with auth, cookies, or a headless
  browser; `capture/data/capture.db` contents; nothing destructive to Instagram content.

## Tasks

- [x] **T01 — Persist the job queue** (S) — `jobs` is an in-memory `queue.Queue`; URLs
  accepted but not yet processed are lost on restart/crash. Persist pending jobs in the
  existing SQLite ledger (`status='queued'` rows re-enqueued on startup) so an accepted
  `202` is a durable promise. Verify: `python3 -m py_compile capture/server.py`; unit
  test or scripted check that a row with `status='queued'`/`'processing'` is re-enqueued
  by the startup path (import `server` with a temp `DB_PATH` and assert). (2026-07-08:
  added `enqueue()`/`reload_pending_jobs()`; py_compile clean, scripted check with a
  temp `DB_PATH` confirms queued/processing rows re-enqueue and done rows don't — takes
  effect on next service restart, not done unattended.)
- [x] **T02 — Image/carousel path via embed alt-text** (M) — image posts have no audio;
  today they only get the caption. In the `/embed/captioned/` fallback (and as an
  enrichment even when yt-dlp succeeds but `duration` is absent), also extract `alt`
  attributes from the embed HTML and pass them to the summarizer as `alt_texts`.
  Per the alt-text-first decision: no vision API call in this task. Verify: py_compile
  plus a unit-style test of the HTML-parsing function on a saved fixture page.
  (2026-07-08: added `extract_alt_texts()`/`embed_caption_from_html()`, wired
  `alt_texts` into `summarize()` for the embed-fallback path and as an enrichment
  when `duration` is absent; py_compile clean, `capture/test_alt_text.py` against
  `capture/fixtures/embed_captioned_sample.html` passes — no vision call added.)
- [x] **T03 — Capture status in ledger CLI** (S) — add `capture/status.py`: prints last
  20 ledger rows (time, status, title, url) and counts by status, so Samy can audit
  captures without sqlite3 syntax. Verify: run it against the real db, exits 0, output
  shows the demo capture row. (2026-07-09: added `capture/status.py`; py_compile clean,
  ran against real `capture/data/capture.db`, exit 0, output lists the 2026-07-07 demo
  row and `done: 1` count.)
- [x] **T06 — Retry failed captures + persist partial results on pipeline failure** (M) —
  from the Hermes loss audit F4 (`~/scratch/hermes-loss-audit-2026-07-13.md`): on any
  pipeline error the ledger row is set `failed` with only the error string
  (`capture/server.py:335-338`) — an already-computed Whisper transcript is discarded if
  `summarize()` then fails — and `failed` rows are never retried
  (`reload_pending_jobs` selects only queued/processing, `server.py:124-133`), so the
  share never reaches the vault unless Samy manually re-shares. Fix: (a) persist partial
  results (caption/transcript, and which stage failed) on the ledger row before marking
  `failed`; (b) on retry, resume from the persisted stage instead of re-fetching (a
  transcript in hand skips yt-dlp + Whisper); (c) bounded automatic retry — re-enqueue
  `failed` rows at startup and once daily, max 3 attempts with the attempt count on the
  row, honoring the existing hard constraints (public/anonymous only — a cookie-walled
  post that keeps failing exhausts its retries and stays honestly failed). Keep the
  Telegram failure reply on the first failure only, and send a success reply if a retry
  later lands it. Verify: `python3 -m py_compile capture/server.py`; unit-style dry run —
  inject a summarize failure after a stubbed transcript, confirm the row holds the
  transcript + stage and that a subsequent retry resumes from summarize and appends to
  the vault (use a temp vault path via env override; do not send real Telegram messages
  while testing — stub/empty the token).
- [ ] **T04 — NEEDS-SAMY: phone share-sheet shortcut for /ingest** (S) — decide the
  phone path for non-Telegram capture: bind CAPTURE_HOST to the tailscale IP or add a
  Tailscale Serve route, then create the iOS/Android shortcut (Share → POST
  `{"url":...}` to quorky:8093/ingest). Doc lives in `capture/README.md`. Samy must do
  the phone-side setup and the bind decision.
- [ ] **T05 — NEEDS-SAMY: retire or run the importer once** (S) — if the old ~100-post
  DM backlog still matters, Samy downloads the Instagram Data Download export and runs
  `importer/` once, feeding the URL list into `POST /ingest` (throttled, e.g. 1/min);
  otherwise mark the importer retired in its README. Needs his export either way.

## Log

- **2026-07-13 (session, not autoloop, T06):** loss-audit F4 fix implemented. Schema
  migration adds `attempts`/`stage`/`partial` to `posts` (auto-applied on next `db()`
  call; existing rows untouched, verified on the live ledger — backup first at
  `~/backups/reels-capture/capture-2026-07-13-pre-T06.db`). `process()` now: persists
  fetched content (meta/transcript/alt-texts) on the row via `ledger_fail()` before
  marking failed; retries resume from the persisted partial (fetch/whisper skipped —
  proven in the dry run by making `fetch_content` raise on the resume pass); Telegram
  warns on the first failure only, replies "recovered on retry" on a later success;
  at 3 exhausted attempts, salvaged caption/transcript is delivered to the vault as an
  explicit `⚠️ partial capture` block and the row goes terminal `status='partial'`
  (nothing salvageable → honest terminal `failed`). Retry feed: `reload_pending_jobs`
  now also re-enqueues budgeted `failed` rows at startup + a daily `retry_sweep`
  thread. New env knobs: `CAPTURE_DB`, `CAPTURE_MAX_ATTEMPTS` (3), 
  `CAPTURE_RETRY_SWEEP_SECONDS`. Verify: `py_compile` clean; 4-step dry run (temp db +
  temp vault + empty bot token) passed — failed row holds transcript+stage / resume
  without re-fetch lands in vault / exhaustion delivers partial with exactly 2 replies
  total / retry selector honors the bound; `test_alt_text.py` still OK. NOT restarted —
  system unit, per the contract above; **the fix is inert until Samy's next
  `sudo systemctl restart reels-capture.service`**.

- **2026-07-07 (session, not autoloop):** capture pivot built and deployed —
  `capture/server.py` + `reels-capture.service` (enabled, active), yt-dlp+ffmpeg
  installed via apt, bot token extracted from n8n credentials into
  `~/.config/reels-capture.env` (webhook slot verified empty → long-poll safe).
  End-to-end verified 13:30 UTC: POST /ingest → yt-dlp → whisper transcript →
  sonnet summary → vault `01-Inbox/reels/2026-07-07.md` (Hermes enriched it) →
  Telegram reply; 17 s. Fixed en route: normalize() stripped load-bearing query
  strings on non-IG URLs; claude errors now carry stderr.

- **2026-07-08 (autoloop, T01):** added `enqueue(url)` (writes `status='queued'` to the
  ledger before `jobs.put`, skipping urls already `done`) and `reload_pending_jobs()`
  (re-enqueues `queued`/`processing` rows on startup), wired into `poll_telegram`,
  `do_POST /ingest`, and `__main__`. Verified with `python3 -m py_compile` and a scripted
  check against a temp `DB_PATH` (2 pending rows re-enqueued, 1 done row skipped; fresh
  `enqueue()` call persists `queued` before reaching the queue). Not restarted — system
  unit, needs Samy's next restart to pick this up.

- **2026-07-08 (autoloop, T02):** split `embed_caption()` into `fetch_embed_page()` +
  `embed_caption_from_html()` so the caption and the new `extract_alt_texts()` parse the
  same fetched HTML without a second request. `extract_alt_texts()` regex-extracts `alt="…"`
  attributes, unescapes, dedups, drops blanks. Wired into `process()`: the embed-fallback
  path passes alt texts from the same fetch; the yt-dlp-success-but-no-`duration` path does
  a second embed fetch just for alt text. `summarize()` now includes `alt_texts` in the
  material JSON handed to `claude -p`. No vision API call (per alt-text-first decision).
  Verified: `python3 -m py_compile capture/server.py` clean; new
  `capture/test_alt_text.py` (unit-style, no network) against
  `capture/fixtures/embed_captioned_sample.html` passes — asserts alt-text dedup/blank-drop
  and caption parsing. Not restarted — system unit, needs Samy's next restart.

- **2026-07-09 (autoloop, T03):** added `capture/status.py` (stdlib, read-only) — prints
  the last 20 `posts` rows (added_at, status, title, url) and counts grouped by status.
  Verified: `python3 -m py_compile capture/status.py` clean; ran it against the real
  `capture/data/capture.db`, exit 0, output lists the 2026-07-07 demo row and `done: 1`.
