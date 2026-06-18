/**
 * Fix Instagram's double-encoded text.
 *
 * Instagram exports JSON strings as UTF-8 bytes re-escaped through Latin-1.
 * e.g. "é" appears as "Ã©", emoji appear as multi-byte sequences like "ð\x9f\x98\x8a".
 *
 * Fix: reinterpret each string's bytes as latin1, then decode as utf8.
 * Guard: if the result contains the Unicode replacement char (U+FFFD), the string
 * was NOT double-encoded — keep the original.
 */
export function fixMojibake(s: string): string {
  if (!s) return s;
  try {
    const decoded = Buffer.from(s, "latin1").toString("utf8");
    if (decoded.includes("�")) {
      // Decoding produced replacement chars — original was already valid UTF-8
      return s;
    }
    return decoded;
  } catch {
    return s;
  }
}
