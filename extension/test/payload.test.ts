/**
 * payload.test.ts
 * Tests buildIngestPayload produces the correct shape.
 */

import { describe, it, expect } from "vitest";
import { buildIngestPayload } from "../src/payload.js";
import type { Post } from "../src/types.js";

const samplePosts: Post[] = [
  {
    url: "https://www.instagram.com/reel/ABC123/",
    type: "reel",
    author: "@buildingpublic",
    caption: "Building in public for 6 months.",
    timestamp: "2026-05-01T01:00:00.000Z",
    altTexts: ["May be an image of text that says 'BUILD IN PUBLIC'"],
  },
  {
    url: "https://www.instagram.com/p/CAR456/",
    type: "carousel",
    author: "@designthinking",
    caption: "Design thinking in 3 slides.",
    timestamp: "2026-05-02T14:30:00.000Z",
    altTexts: [
      "May be an image of text that says 'SLIDE 1: PROBLEM SPACE'",
      "May be an image of text that says 'SLIDE 2: SOLUTION'",
    ],
  },
];

describe("buildIngestPayload", () => {
  it("returns an object with a posts array", () => {
    const payload = buildIngestPayload(samplePosts);
    expect(payload).toHaveProperty("posts");
    expect(Array.isArray(payload.posts)).toBe(true);
  });

  it("posts array has the same items as input", () => {
    const payload = buildIngestPayload(samplePosts);
    expect(payload.posts).toHaveLength(samplePosts.length);
    expect(payload.posts[0].url).toBe(samplePosts[0].url);
    expect(payload.posts[1].type).toBe("carousel");
  });

  it("includes scrapedAt as an ISO timestamp string", () => {
    const payload = buildIngestPayload(samplePosts);
    expect(typeof payload.scrapedAt).toBe("string");
    expect(() => new Date(payload.scrapedAt)).not.toThrow();
    const parsed = new Date(payload.scrapedAt);
    expect(isNaN(parsed.getTime())).toBe(false);
  });

  it("includes extensionVersion", () => {
    const payload = buildIngestPayload(samplePosts);
    expect(typeof payload.extensionVersion).toBe("string");
    expect(payload.extensionVersion.length).toBeGreaterThan(0);
  });

  it("works with an empty posts array", () => {
    const payload = buildIngestPayload([]);
    expect(payload.posts).toHaveLength(0);
    expect(payload.scrapedAt).toBeTruthy();
  });

  it("posts preserve all required Post fields", () => {
    const payload = buildIngestPayload(samplePosts);
    for (const post of payload.posts) {
      expect(typeof post.url).toBe("string");
      expect(["reel", "carousel", "image"]).toContain(post.type);
      expect(typeof post.author).toBe("string");
      expect(typeof post.caption).toBe("string");
      expect(typeof post.timestamp).toBe("string");
      expect(Array.isArray(post.altTexts)).toBe(true);
    }
  });
});
