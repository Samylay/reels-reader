import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, basename, sep } from "node:path";
import { fixMojibake } from "./encoding.js";
import type {
  Post,
  PostType,
  ParseResult,
  ParseStats,
  RawMessage,
  RawMessageFile,
} from "./types.js";

/** Normalize an Instagram share link to a canonical URL + classify its type.
 *  Returns null for non-post links (profiles, external URLs, etc.).
 */
export function normalizeUrl(
  link: string
): { url: string; type: PostType } | null {
  let parsed: URL;
  try {
    parsed = new URL(link);
  } catch {
    return null;
  }

  if (
    parsed.hostname !== "www.instagram.com" &&
    parsed.hostname !== "instagram.com"
  ) {
    return null;
  }

  // pathname examples:
  //   /reel/ABC123/   /reels/ABC123/   /p/ABC123/   /tv/ABC123/
  const match = parsed.pathname.match(
    /^\/(reel|reels|p|tv)\/([A-Za-z0-9_-]+)\/?/
  );
  if (!match) return null;

  const [, segment, code] = match;

  let type: PostType;
  let normalizedSegment: string;

  if (segment === "reel" || segment === "reels" || segment === "tv") {
    type = "reel";
    normalizedSegment = "reel";
  } else {
    // /p/  — placeholder; backend reclassifies carousel vs single image
    type = "image";
    normalizedSegment = "p";
  }

  const url = `https://www.instagram.com/${normalizedSegment}/${code}/`;
  return { url, type };
}

/** Recursively collect all files under dir whose path contains "inbox/" and
 *  whose basename matches message_*.json.
 */
function findMessageFiles(dir: string): string[] {
  const results: string[] = [];
  function walk(current: string): void {
    let entries: string[];
    try {
      entries = readdirSync(current);
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = join(current, entry);
      let stat;
      try {
        stat = statSync(full);
      } catch {
        continue;
      }
      if (stat.isDirectory()) {
        walk(full);
      } else if (
        stat.isFile() &&
        /^message_\d+\.json$/.test(entry) &&
        full.includes(`${sep}inbox${sep}`)
      ) {
        results.push(full);
      }
    }
  }
  walk(dir);
  return results;
}

/** Extract the thread slug (the folder directly under inbox/) from an absolute path. */
function threadSlug(filePath: string): string {
  // The path looks like: ...inbox/<slug>/message_*.json
  const parts = filePath.split(sep);
  const inboxIdx = parts.lastIndexOf("inbox");
  if (inboxIdx !== -1 && inboxIdx + 1 < parts.length) {
    return parts[inboxIdx + 1];
  }
  // Fallback: parent directory name
  const parentParts = filePath.split(sep);
  return parentParts[parentParts.length - 2] ?? "unknown";
}

/** Parse all message_*.json files under rootDir that live inside an inbox/ path.
 *  Returns deduplicated posts and per-run stats.
 */
export function parseExport(
  rootDir: string,
  threadFilter?: string
): ParseResult {
  const stats: ParseStats = {
    filesScanned: 0,
    threads: {},
    postsFound: 0,
    deduped: 0,
    reels: 0,
    posts_p: 0,
    notes: [],
  };

  const seen = new Set<string>(); // normalized URLs for dedup
  const posts: Post[] = [];

  const files = findMessageFiles(rootDir);

  for (const filePath of files) {
    const slug = threadSlug(filePath);

    // Apply --thread filter if provided
    if (threadFilter && !slug.includes(threadFilter)) {
      continue;
    }

    stats.filesScanned++;

    let raw: RawMessageFile;
    try {
      const text = readFileSync(filePath, "utf8");
      raw = JSON.parse(text) as RawMessageFile;
    } catch (err) {
      stats.notes.push(
        `Skipped malformed file ${filePath}: ${String(err)}`
      );
      continue;
    }

    const messages: RawMessage[] = raw.messages ?? [];

    for (const msg of messages) {
      const share = msg.share;
      if (!share?.link) continue; // not a shared post

      const normalized = normalizeUrl(share.link);
      if (!normalized) continue; // non-post link

      stats.postsFound++;

      if (seen.has(normalized.url)) {
        stats.deduped++;
        continue;
      }
      seen.add(normalized.url);

      if (normalized.type === "reel") {
        stats.reels++;
      } else {
        stats.posts_p++;
        if (stats.notes.every((n) => !n.includes("image placeholder"))) {
          stats.notes.push(
            "/p/ links are typed as 'image' (placeholder) — backend will reclassify carousel vs single image when fetching."
          );
        }
      }

      const rawAuthor = share.original_content_owner ?? "";
      const author = rawAuthor ? "@" + fixMojibake(rawAuthor) : "";
      const caption = share.share_text ? fixMojibake(share.share_text) : "";
      const timestamp = msg.timestamp_ms
        ? new Date(msg.timestamp_ms).toISOString()
        : "";

      const post: Post = {
        url: normalized.url,
        type: normalized.type,
        author,
        caption,
        timestamp,
        altTexts: [],
      };

      posts.push(post);

      // Count per thread
      stats.threads[slug] = (stats.threads[slug] ?? 0) + 1;
    }
  }

  // Ensure threads that were seen but had 0 posts still don't appear (only those
  // that contributed posts get a count). This is fine by spec.
  return { posts, stats };
}
