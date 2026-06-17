# Open Questions

Decisions not yet made. Resolve with the user before building the affected piece.

---

## 1. How does the URL list get from extension to backend? — RESOLVED (2026-06-17)

**Resolved:** Auto-POST, hands-off. The extension POSTs the scraped list straight to the
backend, which enqueues and processes it in batches with no manual step. The user's review
checkpoint is the **inbox itself** (validating summaries after processing), not a
pre-processing URL list. See `decisions.md` → "Auto-POST with a server-side batch queue".

---

## 2. Inbox deployment confirmation — RESOLVED (2026-06-17)

**Resolved:** Run **local on the desktop (CachyOS)** during the backlog-draining phase.
Move to a quorky container over Tailscale later, once it works. Keeps early iteration fast
and avoids container/networking setup up front. See `decisions.md` → "Local-first
deployment".

---

## 3. Dedupe (deferred)

The original backlog likely contains duplicate or near-duplicate posts. Dedupe was
explicitly deferred — decide later whether to dedupe by:
- exact post URL (trivial, catches re-sends of the same post)
- author + topic similarity (catches the same creator's reposts)
- semantic similarity of summaries (catches different posts making the same point)

**Not needed for first version.** Revisit once the inbox exists and the real duplication
rate is visible.

---

## 4. Obsidian as an export target (deferred)

The inbox is the primary store. Whether reviewed/archived posts also export to the
Obsidian vault (the user's existing knowledge base) is an open nice-to-have, not a v1
requirement. Revisit after the inbox works.
