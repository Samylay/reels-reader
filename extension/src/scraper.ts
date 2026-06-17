/**
 * scraper.ts — PURE module, no chrome.* APIs.
 * Safely testable under jsdom/node.
 *
 * NOTE: Per-field selectors (author/caption/timestamp) are best-effort guesses
 * against Instagram's current DM markup. URL+type extraction is robust.
 * The diagnostics block is designed to make selector tuning fast after the
 * first real run.
 */

import type { Post, PostType, ScrapeResult } from "./types.js";

const IG_ORIGIN = "https://www.instagram.com";

// ── URL helpers ──────────────────────────────────────────────────────────────

function normalizeHref(href: string): string | null {
  try {
    const url = href.startsWith("http")
      ? new URL(href)
      : new URL(href, IG_ORIGIN);
    if (url.hostname !== "www.instagram.com" && url.hostname !== "instagram.com") {
      return null;
    }
    // Ensure trailing slash
    const path = url.pathname.endsWith("/") ? url.pathname : url.pathname + "/";
    return `${IG_ORIGIN}${path}`;
  } catch {
    return null;
  }
}

function classifyUrl(normalizedUrl: string): PostType | null {
  const path = new URL(normalizedUrl).pathname;
  if (/^\/reels?\//.test(path)) return "reel";
  if (/^\/p\//.test(path)) return null; // need bubble inspection to decide image vs carousel
  return null;
}

// ── Bubble traversal ─────────────────────────────────────────────────────────

/**
 * Walk up from el up to maxLevels. Stop at a likely message-row boundary
 * (role=listitem, role=row, or a data- attribute common on IG DM rows).
 */
function findBubble(el: Element, maxLevels = 8): Element {
  let current: Element | null = el;
  for (let i = 0; i < maxLevels; i++) {
    const parent: Element | null = current?.parentElement ?? null;
    if (!parent) break;
    const role = parent.getAttribute("role");
    if (role === "listitem" || role === "row" || role === "gridcell") break;
    // IG-specific: message row containers sometimes use these tag names at root
    const tag = parent.tagName.toLowerCase();
    if (tag === "li" || tag === "article") break;
    current = parent;
  }
  return current ?? el;
}

// ── Field extractors (best-effort) ────────────────────────────────────────────

/**
 * Extract author handle. Looks for text that looks like @handle or a username.
 * Searches headers, spans, divs near the top of the bubble.
 *
 * BEST-EFFORT: Instagram's DM markup is volatile. Will need tuning on real DOM.
 */
function extractAuthor(bubble: Element): string {
  // Try elements that commonly hold usernames in IG preview cards
  const candidates = bubble.querySelectorAll(
    "header span, [class*='Username'] span, [class*='username'] span, " +
    "[class*='author'] span, [class*='Author'] span, " +
    "a[href*='/'][class], span[dir='auto']"
  );

  for (const el of candidates) {
    const text = (el.textContent ?? "").trim();
    // Match @handle or plain handle (alphanumeric + _ + .)
    if (/^@?[\w.]{1,30}$/.test(text) && text.length > 1) {
      return text.startsWith("@") ? text : `@${text}`;
    }
  }

  // Fallback: any link to a profile (/<handle>/) near the top
  const links = bubble.querySelectorAll("a[href]");
  for (const link of links) {
    const href = link.getAttribute("href") ?? "";
    const m = href.match(/^\/([A-Za-z0-9_.]{1,30})\/?$/);
    if (m && !["reel", "reels", "p", "direct", "stories", "explore"].includes(m[1])) {
      return `@${m[1]}`;
    }
  }

  return "";
}

/**
 * Extract caption text — the longest visible text block that isn't the author/timestamp.
 * BEST-EFFORT.
 */
function extractCaption(bubble: Element): string {
  // Common IG caption containers
  const candidates = bubble.querySelectorAll(
    "[class*='caption'] span, [class*='Caption'] span, " +
    "span[dir='auto'], div[dir='auto']"
  );

  let longest = "";
  for (const el of candidates) {
    const text = (el.textContent ?? "").trim();
    // Skip short texts (likely labels/handles) and texts that look like timestamps
    if (text.length <= 2) continue;
    if (/^\d{1,2}[: h]\d{0,2}/.test(text)) continue; // timestamp-like
    if (/^@?[\w.]{1,30}$/.test(text)) continue; // handle-like
    if (text.length > longest.length) longest = text;
  }

  return longest;
}

/**
 * Extract timestamp. Prefers time[datetime], then aria-label dates, then raw text.
 * BEST-EFFORT.
 */
function extractTimestamp(bubble: Element): string {
  // Most reliable: time element with datetime attribute
  const timeEl = bubble.querySelector("time[datetime], [datetime]");
  if (timeEl) {
    const dt = timeEl.getAttribute("datetime");
    if (dt) {
      try {
        return new Date(dt).toISOString();
      } catch {
        return dt;
      }
    }
  }

  // Aria-label on elements that describe a time
  const ariaEls = bubble.querySelectorAll("[aria-label]");
  for (const el of ariaEls) {
    const label = el.getAttribute("aria-label") ?? "";
    // Looks like a date/time description
    if (/\d{4}|\d{1,2}[\/\-]\d{1,2}|ago|yesterday|today/i.test(label)) {
      return label.trim();
    }
  }

  // Fallback: span/div text that looks like a relative time
  const allSpans = bubble.querySelectorAll("span, div");
  for (const el of allSpans) {
    const text = (el.textContent ?? "").trim();
    if (/^\d{1,2}[hm]$/.test(text) || /^(just now|yesterday|today)/i.test(text)) {
      return text;
    }
  }

  return "";
}

/** Extract alt text from all images in the bubble */
function extractAltTexts(bubble: Element): string[] {
  const alts: string[] = [];
  for (const img of bubble.querySelectorAll("img[alt]")) {
    const alt = img.getAttribute("alt")?.trim();
    if (alt) alts.push(alt);
  }
  return alts;
}

/**
 * Decide whether a /p/ post is a carousel or single image.
 * Look for carousel signals: multiple imgs, "1 of N", Carousel aria, <ul> with multiple <li>.
 */
function classifyPPost(bubble: Element, notes: string[]): PostType {
  const imgs = bubble.querySelectorAll("img");
  if (imgs.length > 1) return "carousel";

  const text = bubble.textContent ?? "";
  if (/1\s+of\s+\d+/i.test(text) || /carousel/i.test(text)) return "carousel";

  const listItems = bubble.querySelectorAll("ul > li");
  if (listItems.length > 1) return "carousel";

  // Check aria roles
  const roleList = bubble.querySelector('[role="listbox"], [aria-label*="Carousel"]');
  if (roleList) return "carousel";

  notes.push("Classified /p/ post as image (no carousel signals found); may need tuning");
  return "image";
}

// ── Main export ──────────────────────────────────────────────────────────────

export function scrapeThread(root: ParentNode): ScrapeResult {
  const diagnostics: ScrapeResult["diagnostics"] = {
    anchorsSeen: 0,
    postsExtracted: 0,
    deduped: 0,
    missingAuthor: 0,
    missingCaption: 0,
    missingTimestamp: 0,
    notes: [],
  };

  const seenUrls = new Set<string>();
  const posts: Post[] = [];

  // Find all post anchors — the most stable signal
  const anchors = Array.from(
    root.querySelectorAll<HTMLAnchorElement>(
      'a[href^="/reel/"], a[href^="/reels/"], a[href^="/p/"], ' +
      `a[href^="${IG_ORIGIN}/reel/"], a[href^="${IG_ORIGIN}/reels/"], a[href^="${IG_ORIGIN}/p/"]`
    )
  );

  diagnostics.anchorsSeen = anchors.length;

  for (const anchor of anchors) {
    try {
      const href = anchor.getAttribute("href") ?? "";
      const normalized = normalizeHref(href);
      if (!normalized) {
        diagnostics.notes.push(`Could not normalize href: ${href}`);
        continue;
      }

      // Dedup
      if (seenUrls.has(normalized)) {
        diagnostics.deduped++;
        continue;
      }
      seenUrls.add(normalized);

      // Classify URL
      const urlType = classifyUrl(normalized);

      // Find bubble container
      const bubble = findBubble(anchor);

      // Determine type
      let type: PostType;
      if (urlType === "reel") {
        type = "reel";
      } else {
        // /p/ path — inspect bubble
        type = classifyPPost(bubble, diagnostics.notes);
      }

      // Extract fields
      const author = extractAuthor(bubble);
      const caption = extractCaption(bubble);
      const timestamp = extractTimestamp(bubble);
      const altTexts = extractAltTexts(bubble);

      if (!author) diagnostics.missingAuthor++;
      if (!caption) diagnostics.missingCaption++;
      if (!timestamp) diagnostics.missingTimestamp++;

      posts.push({ url: normalized, type, author, caption, timestamp, altTexts });
      diagnostics.postsExtracted++;
    } catch (err) {
      diagnostics.notes.push(`Error processing anchor: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return { posts, diagnostics };
}
