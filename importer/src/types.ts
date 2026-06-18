// Post type must match extension/src/types.ts and architecture.md data model

export type PostType = "reel" | "carousel" | "image";

export interface Post {
  url: string;       // normalized: https://www.instagram.com/<reel|p>/<code>/
  type: PostType;
  author: string;   // "@handle" or ""
  caption: string;  // decoded share_text, or ""
  timestamp: string; // ISO 8601 from timestamp_ms
  altTexts: string[]; // ALWAYS [] from this source (export has no alt text)
}

export interface IngestPayload {
  posts: Post[];
  importedAt: string; // ISO timestamp
  source: "data-download";
}

// Stats returned by parseExport
export interface ParseStats {
  filesScanned: number;
  threads: Record<string, number>; // slug -> post count
  postsFound: number;
  deduped: number;
  reels: number;
  posts_p: number; // /p/ links (image placeholder — backend reclassifies)
  notes: string[];
}

export interface ParseResult {
  posts: Post[];
  stats: ParseStats;
}

// Raw shape of a message_*.json file from Instagram export
export interface RawMessage {
  sender_name?: string;
  timestamp_ms?: number;
  share?: {
    link?: string;
    share_text?: string;
    original_content_owner?: string;
  };
  content?: string;
  reactions?: unknown[];
}

export interface RawMessageFile {
  participants?: Array<{ name: string }>;
  messages?: RawMessage[];
}
