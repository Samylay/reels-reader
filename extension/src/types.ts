export type PostType = "reel" | "carousel" | "image";

export interface Post {
  url: string;       // absolute, normalized: https://www.instagram.com/<reel|p>/<id>/
  type: PostType;
  author: string;    // "@handle" or "" if not found
  caption: string;   // "" if not found
  timestamp: string; // ISO if derivable, else raw text, else ""
  altTexts: string[]; // every img[alt] inside the post bubble
}

export interface ScrapeResult {
  posts: Post[];
  diagnostics: {
    anchorsSeen: number;
    postsExtracted: number;
    deduped: number;
    missingAuthor: number;
    missingCaption: number;
    missingTimestamp: number;
    notes: string[];
  };
}

export interface IngestPayload {
  posts: Post[];
  scrapedAt: string; // ISO timestamp
  extensionVersion: string;
}

export type PopupCommand =
  | { cmd: "scanNow" }
  | { cmd: "loadAllAndScan" }
  | { cmd: "sendLast" };

export type BackgroundCommand =
  | { cmd: "ingest"; payload: IngestPayload };

export interface ScanResponse {
  ok: true;
  postsExtracted: number;
  deduped: number;
  diagnostics: ScrapeResult["diagnostics"];
}

export interface IngestResponse {
  ok: boolean;
  status?: number;
  error?: string;
}
