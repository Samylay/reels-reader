# Architecture

Full spec for the Instagram → Inbox pipeline. `CLAUDE.md` is the short orientation;
this is the detail.

## Use case

The user has ~100 Instagram posts saved by sending them to themselves in a DM thread.
They want each post summarized so they can sift the backlog quickly, validating summaries
in a review interface rather than trusting them silently. Originals are never touched by
the pipeline.

## The three steps

### Step 1 — Extension (dumb URL scraper)

A Chrome extension, Manifest v3, content script on `instagram.com/direct/*`.

Single responsibility: read the DM thread DOM and extract the list of post URLs.
- Reel links: `<a href="/reels/{id}/">` or `/p/{id}/`
- Carousel/image posts: `<a href="/p/{id}/">`
- Also capture, cheaply from the DOM, what's already there: author handle, caption,
  timestamp, and per-image `alt` text (Instagram auto-generates OCR-ish alt text).

Output: a list of post objects `{ url, type, author, caption, timestamp, altTexts[] }`.

It deliberately does NOT summarize, screenshot, download, or unsend. Keeping it tiny is
what keeps it reliable when Instagram's DOM shifts.

How the list reaches the backend: see `open-questions.md` (auto-POST vs manual paste).

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
