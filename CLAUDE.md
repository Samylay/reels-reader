# CLAUDE.md

> Orientation file for Claude Code. Read this first. It points to detailed specs in `/specs`.
> **Do not re-open decisions already settled in `/specs/decisions.md`.** If something seems
> worth changing, check the reasoning there before proposing alternatives.

## What this is

A three-step pipeline that drains a backlog of ~100 Instagram posts (saved to a personal
DM thread sent to self) into a reviewable inbox. Each post gets summarized by Claude; the
user validates summaries in a web app rather than trusting them blindly. Non-destructive —
originals stay in Instagram DMs until the user manually clears them.

## Architecture in three sentences

1. An **importer** does one narrow job: parse Instagram's official "Download Your Information"
   Messages export (JSON) and extract the list of shared post URLs. (It replaced a DM-scraping
   Chrome extension that proved non-viable — see decisions.md "Input via official Data
   Download"; extension code is shelved in `extension/`.) It does NOT summarize or unsend.
2. A **Node backend** takes the URL list and processes each post — reels via yt-dlp +
   Whisper + frames, carousels/images via public fetch + alt-text-or-vision — then calls
   Claude for a summary.
3. A **React inbox web app** presents each processed post as a card the user reviews,
   edits, tags, and archives.

## Hard constraints (these shaped the whole design)

- **All saved posts are public.** This is the load-bearing assumption. It means yt-dlp can
  fetch everything (reels, carousels, images) directly from the backend with no auth.
- **No headless browser.** Driving a headless browser against Instagram is the highest
  ban-risk pattern and is unnecessary given everything is public. See decisions log.
- **Non-destructive.** Nothing the pipeline does touches or deletes Instagram content.

## Current state

Phase 1 pivoted (2026-06-18): live DM scraping (the `extension/`) was built but proven
non-viable; Phase 1 is now an **importer** for Instagram's official data export. Build spec:
`specs/phase-1-importer-plan.md`. Next: build/validate the importer, then Phase 2 (backend).

## Where to look

- `specs/architecture.md` — full spec: steps, content routing, components, phases
- `specs/decisions.md` — why things are the way they are (read before proposing changes)
- `specs/open-questions.md` — the two decisions still open

## Stack context

User runs a homelab machine **quorky** (Beelink SER5 Max, Ubuntu Server, Docker/Portainer,
Tailscale, Ollama/Qwen2.5 7B). The inbox web app is intended to run as a container on
quorky, reachable over Tailscale, sitting alongside an existing "LifeOS v2" dashboard.
User stack: React, Node, TypeScript, Docker, Python, Anthropic SDK.
