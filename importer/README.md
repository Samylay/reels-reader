# reels-reader importer

Parses Instagram's official "Download Your Information" **Messages** export (JSON) and
extracts shared posts into the shape the backend expects.

Zero Instagram contact — it only reads a local file you already downloaded.

## 1 · Request your Instagram data export

1. Go to **Instagram Settings → Your activity → Download your information** (or
   <https://www.instagram.com/download/request/>).
2. Select **Messages** (JSON format), date range: **All time**.
3. Request download and wait. Instagram emails a link within minutes to a day.
4. You have a **4-day window** to download the zip before it expires.

## 2 · Unzip the export

```sh
unzip instagram-YYYYMMDD.zip -d ~/ig-export
```

The export folder will have one of two layouts (both supported):

```
~/ig-export/your_instagram_activity/messages/inbox/<thread>/message_*.json   (newer)
~/ig-export/messages/inbox/<thread>/message_*.json                            (older)
```

## 3 · Run the importer

```sh
cd /path/to/reels-reader/importer
npm install       # first time only

# Dry run — print a summary and write posts.json
npx tsx src/cli.ts ~/ig-export

# Filter to a single thread
npx tsx src/cli.ts ~/ig-export --thread "samy.lay"

# Limit to first 10 posts (for a test run)
npx tsx src/cli.ts ~/ig-export --limit 10

# Send to the local backend
npx tsx src/cli.ts ~/ig-export --send http://localhost:8787

# Save output to a specific file
npx tsx src/cli.ts ~/ig-export --out /tmp/my-posts.json
```

## 4 · Send to a mock backend (optional)

You can start a quick mock server to validate the POST payload:

```sh
node -e "
const http = require('http');
http.createServer((req, res) => {
  let body = '';
  req.on('data', d => body += d);
  req.on('end', () => {
    console.log('Received', JSON.parse(body).posts.length, 'posts');
    res.writeHead(200);
    res.end(JSON.stringify({ ok: true }));
  });
}).listen(8787, () => console.log('Mock backend listening on :8787'));
"
```

Then in another terminal:

```sh
npx tsx src/cli.ts ~/ig-export --send http://localhost:8787
```

## Output shape

Each post in `posts.json` (and in the POST body) matches the shape the backend expects:

```json
{
  "url": "https://www.instagram.com/reel/ABC123def/",
  "type": "reel",
  "author": "@creator_handle",
  "caption": "Caption text from the share",
  "timestamp": "2024-05-01T01:00:00.000Z",
  "altTexts": []
}
```

`altTexts` is always `[]` from this source — the export doesn't include per-image alt text.
The backend fetches alt text when it processes each URL.

`type` is `"reel"` for `/reel/`, `/reels/`, and `/tv/` URLs. It is `"image"` (placeholder)
for `/p/` URLs — the backend reclassifies those as `"image"` or `"carousel"` when it fetches
the post.

## Known quirks about the export format

- **Double-encoded text:** Instagram exports text strings as UTF-8 bytes misread as Latin-1.
  The importer fixes these automatically (e.g. `Ã©` → `é`, emoji sequences restored).
- **`original_content_owner`** may be absent; `author` is `""` in that case.
- **`share_text`** may be absent; `caption` is `""` in that case.
- Multiple `message_*.json` files per thread are normal for large threads.
- Only messages with a `share.link` pointing to an Instagram post (`/reel/`, `/p/`, etc.)
  are extracted. Text messages, reactions, calls, and other link types are ignored.

## Dev

```sh
npm run typecheck   # tsc --noEmit (strict)
npm test            # vitest
```
