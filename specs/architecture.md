# Architecture

Full spec for the Instagram → Inbox pipeline. `CLAUDE.md` is the short orientation;
this is the detail.

## Use case

The user has ~100 Instagram posts saved by sending them to themselves in a DM thread.
They want each post summarized so they can sift the backlog quickly, validating summaries
in a review interface rather than trusting them silently. Originals are never touched by
the pipeline.

## The three steps

### Step 1 — Importer (parse Instagram's official Data Download)

> **Changed 2026-06-18.** The original plan — a Chrome extension scraping the DM thread DOM —
> was built and then proven non-viable against the live site. See decisions.md → "Input via
> official Data Download, not live scraping" for the full evidence. The extension code remains
> in `extension/` (shelved, reusable later); Step 1 is now an importer.

A small Node + TypeScript CLI that reads the **Messages** export from Instagram's official
"Download Your Information" (JSON format) and extracts the list of shared posts.

Single responsibility: walk `inbox/<thread>/message_*.json`, find messages that share a post
(a `share` object with a permalink), and emit the post list.
- Reel links: `https://www.instagram.com/reel/{id}/`
- Post links: `https://www.instagram.com/p/{id}/`
- Also capture what the export provides: author (`share.original_content_owner` when present),
  caption/`share_text`, and the message `timestamp_ms`.

Output: the same list of post objects the backend already expects
`{ url, type, author, caption, timestamp, altTexts[] }`, POSTed to the backend `/ingest`.

It deliberately does NOT summarize, fetch media, or hit Instagram at all — it only parses a
local file the user already downloaded. Zero ban risk, no auth, no DOM.

> **Consequence:** the export contains no per-image `alt` text, so `altTexts[]` is empty from
> this source and the backend's "alt-text-first" cheap path can't key off it. The backend can
> re-derive accessibility/alt text from the public post page when it fetches each URL — the
> heuristic moves server-side rather than disappearing. Caption/author/timestamp still come
> from the export.

### Step 2 — Backend (does the work)

Node + Express. Receives the post list. For each post, routes by type:

| Type | Processing | Cost |
|---|---|---|
| Reel | yt-dlp downloads → **local Whisper** transcript + ffmpeg frames → **Sonnet** summary | API (text) |
| Carousel (text-heavy) | alt text contains "text that says" → **Sonnet** summary from alt only | API (text) |
| Carousel (photo) | alt vague → fetch public image URLs → **local vision** (Ollama) | $0 |
| Single image | same alt-text check → **local vision** fallback | $0 |
| Caption | already extracted in step 1, fed into every summary | Zero |

**Inference (see decisions.md → "Inference split"):** text summarization runs on Anthropic
**Sonnet** (`claude-sonnet-4-6`) behind an env-configurable provider seam; **vision** runs on a
**local Ollama** vision model; **transcription** runs on **local Whisper** inside claude-video.

Reel handling is delegated to the **claude-video** skill
(github.com/bradautomates/claude-video) which already wraps yt-dlp + Whisper + frame
extraction. Don't rebuild it.

Because all content is public, yt-dlp and public endpoints fetch everything. No headless
browser, no session cookies, no screenshots-in-a-browser.

Alt-text richness heuristic: if the alt string contains the phrase **"text that says"**,
Instagram's accessibility pipeline captured readable text — use the cheap text path.
Otherwise send the image to the local Ollama vision model.

### Step 3 — Inbox web app (user reviews)

React + Node, runs as a container on quorky, reachable via Tailscale (alongside LifeOS v2).

Each processed post is a card: summary, original caption, thumbnail, source link, detected
type. The user can validate, edit, tag, archive, or delete. Non-destructive — Instagram
originals remain untouched; the user clears their DMs manually whenever they like.

This replaced the earlier "write to Obsidian + unsend as you go" design. See decisions log.

## Per-post data model

```
{
  url:        "https://instagram.com/reel/{id}/",
  type:       "reel" | "carousel" | "image",
  author:     "@handle",
  caption:    "original caption text",
  timestamp:  "2026-05-01T01:00:00.000Z",
  altTexts:   ["May be an image of text that says '...'", ...],
  // added by backend:
  summary:    "2-3 sentence Claude summary",
  status:     "pending" | "processed" | "reviewed" | "archived",
  thumbnail:  "https://scontent.../...jpg"
}
```

## Dev phases

1. **Extension URL scraper** — Manifest v3, MutationObserver detects posts in DM thread,
   extract `{url, type, author, caption, timestamp, altTexts}`, log to verify reliability.
2. **Backend + routing** — Express endpoint receives list, router sends reels to
   claude-video and carousels/images through alt-or-vision, Claude summarizes.
3. **Inbox web app** — React cards, review/edit/tag/archive, container on quorky via
   Tailscale.
4. **Polish** — sequential processing with delay, error/retry handling, dedupe (deferred —
   see open questions), progress UI.

## Risks

- **Instagram DOM instability** — extension selectors (`._ap3a`, carousel `<ul>`) will
  drift over time and need patching. Mitigated by keeping the extension's job tiny.
- **yt-dlp breakage** — Instagram changes can break yt-dlp; keep it updated.
- **Rate limiting** — ~100 sequential Claude calls; space them 1-2s apart.
