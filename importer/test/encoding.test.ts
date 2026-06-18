import { describe, it, expect } from "vitest";
import { fixMojibake } from "../src/encoding.js";

describe("fixMojibake", () => {
  it("decodes Ã© to é (accented char)", () => {
    // "Ã©" = bytes [0xC3, 0xA9] interpreted as latin1 => UTF-8 "é"
    const input = "Caf\xc3\xa9"; // CafÃ©
    expect(fixMojibake(input)).toBe("Café");
  });

  it("decodes emoji double-encoding", () => {
    // 😊 UTF-8 bytes: F0 9F 98 8A, treated as latin1 chars
    const input = "Hello \xf0\x9f\x98\x8a";
    expect(fixMojibake(input)).toBe("Hello 😊");
  });

  it("decodes Ã¨ to è", () => {
    const input = "Tr\xc3\xa8s beau";
    expect(fixMojibake(input)).toBe("Très beau");
  });

  it("keeps original if result contains replacement char (not double-encoded)", () => {
    // A string that is already valid UTF-8 and not double-encoded
    // If we try to decode "hello" as latin1->utf8, it's fine (ASCII subset)
    expect(fixMojibake("hello")).toBe("hello");
  });

  it("returns empty string unchanged", () => {
    expect(fixMojibake("")).toBe("");
  });

  it("handles plain ASCII unchanged", () => {
    expect(fixMojibake("plain text 123")).toBe("plain text 123");
  });

  it("keeps valid utf8 string that would produce replacement char if decoded", () => {
    // A string containing an already-correct multi-byte sequence that would
    // corrupt if double-decoded (e.g., a lone surrogate or invalid sequence).
    // Simple case: a string where latin1->utf8 produces replacement char.
    // Example: single byte 0x81 alone in latin1 -> utf8 is invalid -> replacement char
    const withReplacementOnDecode = "\x81";
    const result = fixMojibake(withReplacementOnDecode);
    // Should keep original since decoded contains replacement char
    expect(result).toBe("\x81");
  });
});
