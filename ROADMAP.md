# Roadmap — reels-reader

> Executor contract: each night an unattended Sonnet agent (`claude -p`, cwd = this repo) picks the FIRST unchecked task, does ONLY that task, verifies it per the task's Verify note, commits with an `autoloop:` prefix (one logical change per commit, never leave the tree dirty), then ticks the checkbox adding the date and a one-line result, and appends details to ## Log. If verification fails: revert, leave unchecked, add a `BLOCKED:` note.

## Context for the executor

Pipeline that drains ~100 Instagram posts (saved in a self-DM thread) into a reviewable
inbox: **importer** (DONE — parses Instagram's official Data Download export, 31 tests
green) → **backend** (NOT BUILT — summarizes each post) → **inbox web app** (NOT BUILT —
review cards). Read `CLAUDE.md` first, then `specs/architecture.md`. **Do not re-open
decisions settled in `specs/decisions.md`.**

- Stack: Node 22, TypeScript strict + NodeNext, vitest — mirror `importer/` conventions
  (`npm run typecheck`, `npm test`, `npm run build`) in every new package.
- Backend lives in a new `backend/` directory. Data store: SQLite (better-sqlite3), file
  `backend/data/posts.db` (gitignore the db file, keep the dir).
- Post shape from the importer: `{ url, type, author, caption, timestamp, altTexts[] }`
  (`altTexts` is always empty from the export — the caption path is the main path).
- LLM: homelab standard is the Claude CLI. Call `/home/quorky/.local/bin/claude -p` (model
  `sonnet`) behind a `GEN_PROVIDER` env seam (`claude-cli` | `ollama`), same pattern as
  `~/apps/flux/lib/ai/client.ts`. Auth env: `/home/quorky/.config/claude-cli.env`.
- Local transcription service exists at `~/services/whisper` (systemd user unit).
- **NEVER touch:** `extension/` (shelved, keep as-is), `specs/decisions.md`, anything that
  contacts Instagram with auth or a headless browser (hard ban-risk constraint), nothing
  destructive to Instagram content.
- Host gap: `yt-dlp` and `ffmpeg` are NOT installed — T05 must gate on installing them
  (user-local: `pipx install yt-dlp` or `python3 -m pip install --user yt-dlp`; ffmpeg via
  static build into `~/.local/bin` — no sudo assumptions).

## Tasks

- [ ] **T01 — Backend scaffold** (S) — Create `backend/` (package.json, strict NodeNext
  tsconfig, vitest) with an Express app exposing `GET /health` → `{ok:true}`, listening on
  `127.0.0.1:8787` (the port the importer already POSTs to). Include `npm run dev|build|
  typecheck|test`. Verify: `cd backend && npm run typecheck && npm test` pass; start server,
  `curl -s 127.0.0.1:8787/health` returns `{"ok":true}`, then stop it.
- [ ] **T02 — SQLite store + `POST /ingest`** (M) — `posts` table matching the per-post data
  model in `specs/architecture.md` (plus `status` default `pending`, timestamps). `/ingest`
  accepts the importer's batch payload (see `importer/src/payload.ts` for the exact shape),
  upserts deduped by `url`, returns counts `{received, inserted, duplicates}`. Verify: unit
  tests incl. re-ingest dedupe; curl a 2-post sample twice → second call reports 2 duplicates.
- [ ] **T03 — Summarization provider seam** (M) — `backend/src/ai/` with `GEN_PROVIDER`
  toggle: `claude-cli` (spawn `/home/quorky/.local/bin/claude -p`, model `sonnet`, timeout,
  JSON-safe output) and an `ollama` fallback stub. Copy the proven pattern from
  `~/apps/flux/lib/ai/client.ts`. Verify: unit tests with the spawn mocked; one live smoke
  call producing a non-empty summary for a hardcoded caption.
- [ ] **T04 — Caption summarize queue** (M) — Sequential worker (1–2s spacing per
  architecture.md Risks): picks `pending` posts, builds a summary from caption + author +
  type (altTexts are empty from the export), stores `summary`, sets `status=processed`;
  errors → `status` stays `pending` with an `error` column note, max 3 attempts. Trigger via
  `POST /process` and on a `--drain` CLI flag. Verify: tests with mocked provider; live: ingest
  2 sample posts, run drain, both rows `processed` with non-empty summaries.
- [ ] **T05 — Reel path: yt-dlp + Whisper transcript** (M) — Install `yt-dlp`+`ffmpeg`
  user-locally (see Context; if that fails, BLOCK — do not sudo). For `type=reel`: download
  audio, transcribe via the local whisper service (`~/services/whisper/server.py` — read it
  for the endpoint contract), feed transcript+caption into the T03 provider. Verify: tests
  with fetch/transcribe mocked; live: process one hardcoded public reel URL end-to-end (if
  Instagram blocks the fetch, BLOCK with the yt-dlp error rather than retrying).
- [ ] **T06 — Inbox app scaffold** (M) — `inbox/` React+Vite app served by the backend (or
  proxied in dev): `GET /posts?status=` API + a card list (summary, caption, author, type,
  source link, status badge). Match repo TS strictness. Verify: `npm run build` clean; with
  backend running and 2 processed rows, `curl /posts` returns them and the built app renders
  (curl the served index.html 200).
- [ ] **T07 — Review actions** (M) — `PATCH /posts/:id` (edit summary, set status
  `reviewed|archived`, add tags TEXT[] json column) + card buttons wired. Non-destructive
  only — no delete of Instagram content, DB delete allowed. Verify: API tests; live: PATCH a
  row and see it reflected in `GET /posts`.
- [ ] **T08 — Containerize + deploy on quorky** (M) — Dockerfile + compose (backend+inbox one
  service, volume for `data/`), bind `127.0.0.1`, document Tailscale Serve exposure in
  README (do NOT change tailnet config yourself). Verify: `docker compose up -d --build`,
  `/health` 200 and `/posts` 200 from host, then leave it running.
- [ ] **T09 — Run guide refresh** (S) — `GETTING-STARTED.md` still documents the shelved
  extension as "what works today". Rewrite it around the importer→backend→inbox flow (keep a
  short "extension (shelved)" appendix). Verify: doc references only commands that exist;
  every command in it copy-paste runs (or is explicitly marked as needing the real export).

## Log
