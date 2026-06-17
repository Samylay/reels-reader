# Decisions

Why things are the way they are. Read this before proposing changes to the architecture —
most "why didn't we just..." questions are answered here. Each entry is a decision, the
reasoning, and what was rejected.

---

## No headless browser

**Decision:** The backend uses yt-dlp and public HTTP fetches. It does NOT drive a headless
browser against Instagram.

**Why:** Every saved post is public. yt-dlp pulls public reels, carousels, and images
directly — no login, no session, no screenshots needed. A headless browser would add
nothing the public endpoints don't already give us.

**What it avoids:** Driving a headless/automated browser against Instagram is the single
highest ban-risk pattern — Meta detects automation signatures aggressively. Avoiding it
keeps the user's account safe.

**Rejected:** "Open each post in a headless browser and screenshot the content." Considered
during the relaunch discussion. Only necessary for auth-gated content, which doesn't exist
in this backlog. Dropped.

---

## Inbox, not Obsidian-write-then-unsend

**Decision:** Processed posts land in a reviewable inbox web app. The user validates each
summary, then archives. Instagram originals are never touched by the pipeline.

**Why:** A 100-post backlog needs batch review and the ability to correct bad summaries.
An inbox gives a checkpoint; silent filing does not.

**Rejected:** The earlier locked spec wrote summaries straight to an Obsidian vault and then
**unsent** each DM message to clear the queue. Two problems: (1) unsend is permanent and
destructive — a silent write failure followed by an unsend loses the post forever; (2) no
chance to review or fix a summary before it's filed. The inbox is non-destructive and
reviewable. Obsidian export can still happen later as an *output* of the inbox if wanted,
but it is not the primary store and nothing auto-unsends.

---

## Decoupled three-step pipeline, not a monolithic extension

**Decision:** Extension scrapes URLs only. Backend does all processing. Web app handles
review. Three separable pieces.

**Why:** The original monolithic extension (scrape + screenshot + summarize + unsend, all
in-browser) was fragile — every stage depended on Instagram's DOM holding still and on the
user being present for the entire run. Splitting it means the extension is tiny and rarely
breaks, while the expensive/fragile processing happens server-side where it can be retried,
cached, and debugged without touching Instagram.

**Rejected:** Single extension doing everything. Dropped for fragility and the
all-or-nothing run problem.

---

## Reel processing delegated to claude-video

**Decision:** Use the existing `claude-video` skill (github.com/bradautomates/claude-video)
for reels instead of building the download/transcribe/frame pipeline from scratch.

**Why:** It already wraps yt-dlp + Whisper (Groq/OpenAI backends) + ffmpeg frame extraction,
with flags for resolution (reading on-screen text) and fps control. Reinventing it would be
wasted effort.

**Check early:** Confirm it handles the public reel URLs in the backlog cleanly before
building around it.

---

## Alt-text-first for carousels and images

**Decision:** Before any vision API call, check the image's `alt` text. If it contains the
phrase "text that says", summarize from the alt text alone. Only call Claude vision when
alt text is vague.

**Why:** Instagram auto-generates alt text via its own accessibility OCR. For the
text-heavy informational carousels the user tends to save (slides, quote cards,
infographics), the alt text already contains the content — making summarization nearly free.
Vision is reserved for photos where alt text is uninformative.

**Why this heuristic specifically:** Instagram only emits "text that says" when its pipeline
actually detected readable text, so it's a reliable cheap/rich signal. Minimizing token
consumption was an explicit user goal.

---

## Auto-POST with a server-side batch queue

**Decision (2026-06-17):** The extension POSTs the scraped URL list directly to the backend.
The backend enqueues the posts and processes them in batches sequentially, fully hands-off.
There is no manual paste step.

**Why:** The user's explicit goal is "ideally i don't have to do anything." A pre-processing
URL-review checkpoint adds a manual step for little gain, because the design is already
non-destructive — the real review happens in the inbox, where the user validates summaries
before archiving. So the checkpoint moves *after* processing rather than before.

**Implication:** The backend needs a persistent job queue and sequential processing with a
1–2s delay between Claude calls (rate-limit safety, see architecture risks). The inbox shows
processing status (`pending` → `processed`) so the user can watch progress without acting.

**Rejected:** Manual paste (the earlier lean). Safer for token spend but requires the user to
move data by hand, which contradicts the hands-off goal.

---

## Local-first deployment

**Decision (2026-06-17):** During the backlog-draining phase the backend + inbox run locally
on the desktop (CachyOS). Migration to a quorky Docker container over Tailscale is deferred
until the pipeline works end-to-end.

**Why:** Fastest iteration loop; no container build, Tailscale routing, or cross-host config
to debug while the core logic is still in flux. The quorky container is the end state, not
the starting point.

**Implication:** Keep deployment-specific assumptions out of the code — backend URL via env
var/config, SQLite file store rather than anything host-specific — so the later move to
quorky is a packaging step, not a rewrite.

---

## Inference split: Sonnet for text, local for vision and transcription

**Decision (2026-06-17):** 
- **Text summarization** (the main, frequent path) → **Anthropic Sonnet** (`claude-sonnet-4-6`)
  via the Anthropic SDK. Good quality/cost balance for backlog-triage summaries.
- **Vision** (the rare photo path that survives the alt-text-first filter) → **local** Ollama
  vision model (e.g. `qwen2.5-vl`) on quorky. Avoids per-image API cost.
- **Transcription** (reels) → **local Whisper** (`faster-whisper`), wired into claude-video
  in place of its Groq/OpenAI backends. Anthropic has no audio API and there's no reason to
  pay for transcription.

**Why this split:** The user wants to minimize API usage. Vision is the easiest thing to keep
local because the alt-text-first heuristic means it rarely fires, so a weaker local vision
model is low-stakes. Summarization is the quality-sensitive, high-frequency path, so it's
worth Sonnet-grade output there. Transcription is free locally at equal quality.

**Hardware note:** quorky is a Ryzen 7 7735HS / Radeon 680M iGPU / ~19 GB RAM box with **no
discrete GPU** — local inference is CPU-bound. Fine for Whisper and for the occasional vision
call; this is why the frequent summarization path went to the API rather than a local LLM.

**Implication:** Keep the summarizer call behind a thin provider seam anyway (env-configurable
model id), so swapping Sonnet ↔ Opus ↔ local is a config change, not a rewrite. Requires
`ANTHROPIC_API_KEY` in `.env`; vision and Whisper require a running local Ollama + Whisper.

**Supersedes:** the architecture spec's original "claude-opus-4-8 for everything" assumption.
