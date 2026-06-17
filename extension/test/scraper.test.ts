/**
 * scraper.test.ts
 * Runs scrapeThread against the dm-thread.html fixture using jsdom.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { scrapeThread } from "../src/scraper.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixturePath = resolve(__dirname, "fixtures/dm-thread.html");

let dom: JSDOM;
let document: Document;

beforeAll(() => {
  const html = readFileSync(fixturePath, "utf-8");
  dom = new JSDOM(html, { url: "https://www.instagram.com/direct/t/12345/" });
  document = dom.window.document;
});

describe("scrapeThread — fixture: dm-thread.html", () => {
  it("extracts 3 unique posts (4 anchors, 1 deduped)", () => {
    const result = scrapeThread(document);
    expect(result.posts).toHaveLength(3);
    expect(result.diagnostics.anchorsSeen).toBe(4);
    expect(result.diagnostics.deduped).toBe(1);
    expect(result.diagnostics.postsExtracted).toBe(3);
  });

  it("classifies the reel correctly", () => {
    const result = scrapeThread(document);
    const reel = result.posts.find((p) => p.url.includes("/reel/ABC123/"));
    expect(reel).toBeDefined();
    expect(reel!.type).toBe("reel");
  });

  it("classifies the carousel correctly", () => {
    const result = scrapeThread(document);
    const carousel = result.posts.find((p) => p.url.includes("/p/CAR456/"));
    expect(carousel).toBeDefined();
    expect(carousel!.type).toBe("carousel");
  });

  it("classifies the single image correctly", () => {
    const result = scrapeThread(document);
    const image = result.posts.find((p) => p.url.includes("/p/IMG789/"));
    expect(image).toBeDefined();
    expect(image!.type).toBe("image");
  });

  it("normalizes all URLs to absolute https://www.instagram.com/... form", () => {
    const result = scrapeThread(document);
    for (const post of result.posts) {
      expect(post.url).toMatch(/^https:\/\/www\.instagram\.com\//);
      expect(post.url.endsWith("/")).toBe(true);
    }
  });

  it("captures altTexts for posts with images", () => {
    const result = scrapeThread(document);

    const reel = result.posts.find((p) => p.url.includes("/reel/ABC123/"));
    expect(reel!.altTexts.length).toBeGreaterThan(0);
    expect(reel!.altTexts[0]).toContain("BUILD IN PUBLIC");

    const carousel = result.posts.find((p) => p.url.includes("/p/CAR456/"));
    expect(carousel!.altTexts.length).toBeGreaterThanOrEqual(2);
    expect(carousel!.altTexts.some((a) => a.includes("text that says"))).toBe(true);
  });

  it("captures ISO timestamp from time[datetime]", () => {
    const result = scrapeThread(document);
    const reel = result.posts.find((p) => p.url.includes("/reel/ABC123/"));
    expect(reel!.timestamp).toBe("2026-05-01T01:00:00.000Z");
  });

  it("diagnostics counters are sane (non-negative integers)", () => {
    const result = scrapeThread(document);
    const d = result.diagnostics;
    expect(d.anchorsSeen).toBeGreaterThanOrEqual(0);
    expect(d.postsExtracted).toBeGreaterThanOrEqual(0);
    expect(d.deduped).toBeGreaterThanOrEqual(0);
    expect(d.missingAuthor).toBeGreaterThanOrEqual(0);
    expect(d.missingCaption).toBeGreaterThanOrEqual(0);
    expect(d.missingTimestamp).toBeGreaterThanOrEqual(0);
    expect(Array.isArray(d.notes)).toBe(true);
  });

  it("never throws — scrapeThread returns a result even on a bad input", () => {
    // Pass an empty div with no content
    const emptyDiv = dom.window.document.createElement("div");
    let result;
    expect(() => {
      result = scrapeThread(emptyDiv);
    }).not.toThrow();
    expect(result!.posts).toHaveLength(0);
    expect(result!.diagnostics.anchorsSeen).toBe(0);
  });
});
