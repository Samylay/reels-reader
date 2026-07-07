# CLAUDE.md

> Orientation file for Claude Code. Read this first. It points to detailed specs in `/specs`.
> **Do not re-open decisions already settled in `/specs/decisions.md`.** If something seems
> worth changing, check the reasoning there before proposing alternatives.

## What this is

A capture pipeline for interesting Instagram posts, **at the moment they're found**: Samy
shares a post (Telegram share sheet → the homelab bot, or `POST /ingest`), and gets the
summary back as a Telegram reply seconds later. The summary + transcript are archived in
the Obsidian vault (`01-Inbox/reels/YYYY-MM-DD.md`), where Hermes enriches them like any
other inbox note. The Telegram reply is the review checkpoint; the vault is the store.

(Previous incarnation — draining a ~100-post DM backlog via Instagram's Data Download
export into a React inbox — was dropped 2026-07-07; see decisions.md "Capture-first
pivot". The `importer/` remains as a one-shot tool; `extension/` is shelved.)

## Architecture in two sentences

1. **`capture/server.py`** (systemd `reels-capture.service`, Python stdlib) long-polls the
   existing Telegram bot's getUpdates and serves `POST /ingest` on `127.0.0.1:8093`; both
   feed one worker queue.
2. Per URL: SQLite dedupe → `yt-dlp -J` (public, anonymous) with `/embed/captioned/`
   caption fallback → if video, bestaudio → local Whisper (`172.17.0.1:8091`) → `claude -p`
   (sonnet) summary → vault append → Telegram reply (or an honest failure reply).

## Hard constraints (these shaped the whole design)

- **Public posts only, no Instagram auth, no cookies.** yt-dlp fetches anonymously; if
  Instagram walls it, the pipeline reports failure rather than escalating.
- **No headless browser.** Highest ban-risk pattern; see decisions log.
- **Non-destructive.** Nothing touches or deletes Instagram content.
- The bot token is shared with n8n (which only *sends*); the webhook slot must stay empty
  or long-polling breaks. Config in `~/.config/reels-capture.env` (600).

## Current state

Deployed and verified end-to-end 2026-07-07 (fetch → transcribe → summarize → vault →
Telegram reply, 17 s). Known gaps are queued in `ROADMAP.md` (nightly autoloop executes
one task per night): in-memory job queue loses in-flight URLs on restart; image/carousel
posts only get caption text (no alt-text/vision path yet); phone share-sheet shortcut
for `/ingest` not yet documented.

## Where to look

- `specs/decisions.md` — why things are the way they are (read before proposing changes)
- `capture/server.py` — the whole service; `capture/reels-capture.service` — the unit
- `ROADMAP.md` — executor-contract task queue for the nightly autoloop
- `specs/architecture.md` + `specs/phase-1-importer-plan.md` — the retired backlog design
  (historical context only)

## Stack context

Homelab machine **quorky** (Ubuntu Server, Docker, Tailscale). Whisper runs as a host
service on the docker bridge IP; `claude -p` auth comes from
`~/.config/claude-cli.env` (see the homelab CLAUDE.md constitution for global rules).
