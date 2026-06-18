import { describe, it, expect } from "vitest";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parseExport, normalizeUrl } from "../src/parse.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE_DIR = join(__dirname, "fixtures/export");

describe("normalizeUrl", () => {
  it("normalizes /reel/ to reel type", () => {
    const result = normalizeUrl("https://www.instagram.com/reel/ABC123def/");
    expect(result).toEqual({
      url: "https://www.instagram.com/reel/ABC123def/",
      type: "reel",
    });
  });

  it("normalizes /reels/ to reel type", () => {
    const result = normalizeUrl("https://www.instagram.com/reels/ABC123def/");
    expect(result).toEqual({
      url: "https://www.instagram.com/reel/ABC123def/",
      type: "reel",
    });
  });

  it("normalizes /tv/ to reel type", () => {
    const result = normalizeUrl("https://www.instagram.com/tv/ABC123def/");
    expect(result).toEqual({
      url: "https://www.instagram.com/reel/ABC123def/",
      type: "reel",
    });
  });

  it("normalizes /p/ to image placeholder type", () => {
    const result = normalizeUrl("https://www.instagram.com/p/XYZ789ghi/");
    expect(result).toEqual({
      url: "https://www.instagram.com/p/XYZ789ghi/",
      type: "image",
    });
  });

  it("returns null for profile URLs", () => {
    expect(normalizeUrl("https://www.instagram.com/somehandle/")).toBeNull();
  });

  it("returns null for non-instagram URLs", () => {
    expect(normalizeUrl("https://twitter.com/status/123")).toBeNull();
  });

  it("returns null for invalid URLs", () => {
    expect(normalizeUrl("not-a-url")).toBeNull();
  });

  it("accepts instagram.com without www", () => {
    const result = normalizeUrl("https://instagram.com/reel/ABC123def/");
    expect(result).toEqual({
      url: "https://www.instagram.com/reel/ABC123def/",
      type: "reel",
    });
  });
});

describe("parseExport", () => {
  it("extracts reel and /p/ posts from fixture", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    const urls = posts.map((p) => p.url);
    expect(urls).toContain("https://www.instagram.com/reel/ABC123def/");
    expect(urls).toContain("https://www.instagram.com/p/XYZ789ghi/");
    expect(urls).toContain("https://www.instagram.com/reel/MOJIBAKE11/");
    expect(urls).toContain("https://www.instagram.com/reel/OTHER999xyz/");
  });

  it("deduplicates posts with the same URL", () => {
    const { posts, stats } = parseExport(FIXTURE_DIR);
    // ABC123def appears twice in self_xxx/message_1.json
    const abc = posts.filter(
      (p) => p.url === "https://www.instagram.com/reel/ABC123def/"
    );
    expect(abc).toHaveLength(1);
    expect(stats.deduped).toBe(1);
  });

  it("ignores plain text messages (no share.link)", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    // The plain text message "Hey check this out!" should not appear
    const plainText = posts.filter((p) => p.caption.includes("plain text"));
    expect(plainText).toHaveLength(0);
  });

  it("counts reels and /p/ posts correctly", () => {
    const { stats } = parseExport(FIXTURE_DIR);
    // reels: ABC123def (via /reel/), MOJIBAKE11 (via /reels/), OTHER999xyz
    expect(stats.reels).toBe(3);
    // /p/: XYZ789ghi
    expect(stats.posts_p).toBe(1);
  });

  it("decodes mojibake in captions (Ã© -> é, emoji)", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    const mojibake = posts.find(
      (p) => p.url === "https://www.instagram.com/reel/MOJIBAKE11/"
    );
    expect(mojibake).toBeDefined();
    // "CafÃ©" should decode to "Café"
    expect(mojibake!.caption).toBe("Café vibes so good!");
  });

  it("decodes emoji mojibake in captions", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    const reel = posts.find(
      (p) => p.url === "https://www.instagram.com/reel/ABC123def/"
    );
    expect(reel).toBeDefined();
    // "Amazing reel ð\x9f\x98\x8a" should decode to "Amazing reel 😊"
    expect(reel!.caption).toBe("Amazing reel 😊");
  });

  it("produces ISO timestamps from timestamp_ms", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    for (const post of posts) {
      if (post.timestamp) {
        // Should be a valid ISO 8601 string
        expect(post.timestamp).toMatch(
          /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/
        );
      }
    }
  });

  it("converts timestamp_ms 1714525200000 to correct ISO date", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    const reel = posts.find(
      (p) => p.url === "https://www.instagram.com/reel/ABC123def/"
    );
    expect(reel?.timestamp).toBe(new Date(1714525200000).toISOString());
  });

  it("includes author with @ prefix when original_content_owner present", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    const reel = posts.find(
      (p) => p.url === "https://www.instagram.com/reel/ABC123def/"
    );
    expect(reel?.author).toBe("@chef_handle");
  });

  it("sets altTexts to empty array for all posts", () => {
    const { posts } = parseExport(FIXTURE_DIR);
    for (const post of posts) {
      expect(post.altTexts).toEqual([]);
    }
  });

  it("tracks per-thread counts", () => {
    const { stats } = parseExport(FIXTURE_DIR);
    expect(stats.threads["self_xxx"]).toBeGreaterThan(0);
    expect(stats.threads["other_yyy"]).toBeGreaterThan(0);
  });

  it("filters by thread name with --thread option", () => {
    const { posts, stats } = parseExport(FIXTURE_DIR, "self_xxx");
    const urls = posts.map((p) => p.url);
    // Should include self_xxx posts
    expect(urls).toContain("https://www.instagram.com/reel/ABC123def/");
    // Should exclude other_yyy posts
    expect(urls).not.toContain(
      "https://www.instagram.com/reel/OTHER999xyz/"
    );
    expect(stats.threads["other_yyy"]).toBeUndefined();
  });

  it("counts filesScanned accurately", () => {
    const { stats } = parseExport(FIXTURE_DIR);
    expect(stats.filesScanned).toBe(2);
  });

  it("--thread filter for other_yyy only returns that thread's posts", () => {
    const { posts } = parseExport(FIXTURE_DIR, "other_yyy");
    expect(posts).toHaveLength(1);
    expect(posts[0].url).toBe(
      "https://www.instagram.com/reel/OTHER999xyz/"
    );
  });
});
