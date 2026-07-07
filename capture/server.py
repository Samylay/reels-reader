#!/usr/bin/env python3
"""
reels-capture — capture-at-the-moment pipeline for interesting Instagram posts.

Replaces the backlog-draining importer flow (see specs/decisions.md →
"Capture-first pivot"). Two entry points, one pipeline:

  1. Telegram: share a post from Instagram's share sheet to the existing
     homelab bot. This service long-polls getUpdates (the bot's webhook slot
     is unused — n8n only *sends* through it), extracts post URLs from your
     messages, and replies in the same chat with the summary. The reply IS
     the review inbox.
  2. HTTP: POST /ingest {"url": ...} on the tailnet (for an iOS/Android
     share-sheet shortcut, or curl).

Pipeline per URL: dedupe (SQLite) → yt-dlp metadata (public, no auth, no
headless browser — the project's standing constraints) → if video, bestaudio
→ local whisper (172.17.0.1:8091) → `claude -p` summary → append to the
vault inbox (01-Inbox/reels/YYYY-MM-DD.md) → Telegram reply.

If yt-dlp hits Instagram's anonymous-access wall, falls back to parsing the
public /embed/captioned/ page for the caption; if both fail you get an
honest "couldn't fetch" reply and a ledger row, never a silent drop.

Config via environment (see reels-capture.service):
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   ~/.config/reels-capture.env
  CLAUDE_CODE_OAUTH_TOKEN                 ~/.config/claude-cli.env
  CAPTURE_HOST (127.0.0.1) / CAPTURE_PORT (8093)
  WHISPER_URL (http://172.17.0.1:8091/transcribe)
  VAULT_REELS_DIR (~/vault/obsidian/01-Inbox/reels)
"""

import html
import json
import logging
import os
import queue
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

HOME = "/home/quorky"
BASE = os.path.dirname(os.path.abspath(__file__))

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
HOST = os.environ.get("CAPTURE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CAPTURE_PORT", "8093"))
WHISPER_URL = os.environ.get("WHISPER_URL", "http://172.17.0.1:8091/transcribe")
VAULT_DIR = os.environ.get("VAULT_REELS_DIR", f"{HOME}/vault/obsidian/01-Inbox/reels")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", f"{HOME}/.local/bin/claude")
YTDLP_BIN = os.environ.get("YTDLP_BIN", "/usr/bin/yt-dlp")
DB_PATH = os.path.join(BASE, "data", "capture.db")
MAX_AUDIO_BYTES = 24 * 1024 * 1024
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reels-capture")

IG_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/[\w-]+", re.I
)
ANY_URL_RE = re.compile(r"https?://\S+")

jobs: "queue.Queue[str]" = queue.Queue()


# --- ledger -----------------------------------------------------------------

def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA busy_timeout=5000")
    con.execute(
        """CREATE TABLE IF NOT EXISTS posts (
             url TEXT PRIMARY KEY, added_at TEXT, status TEXT,
             title TEXT, note TEXT)"""
    )
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return con


def normalize(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    if "instagram.com" in p.netloc:
        # IG post identity is the path; query is share-tracking junk (igsh=…)
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), p.query, ""))


def ledger_set(url, status, title="", note=""):
    con = db()
    con.execute(
        "INSERT INTO posts(url, added_at, status, title, note) VALUES(?,?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET status=excluded.status, "
        "title=excluded.title, note=excluded.note",
        (url, time.strftime("%Y-%m-%dT%H:%M:%S"), status, title, note),
    )
    con.commit()
    con.close()


def already_done(url) -> bool:
    con = db()
    row = con.execute("SELECT status FROM posts WHERE url=?", (url,)).fetchone()
    con.close()
    return bool(row and row[0] == "done")


# --- fetch ------------------------------------------------------------------

def ytdlp_json(url):
    r = subprocess.run(
        [YTDLP_BIN, "-J", "--no-warnings", "--no-playlist", url],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr else "yt-dlp failed")
    return json.loads(r.stdout)


def ytdlp_audio(url) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "a.%(ext)s")
        r = subprocess.run(
            [YTDLP_BIN, "-f", "bestaudio/best", "-x", "--audio-format", "opus",
             "--audio-quality", "48K", "--no-playlist", "-o", out, url],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            raise RuntimeError("audio download failed")
        files = [os.path.join(td, f) for f in os.listdir(td)]
        if not files:
            raise RuntimeError("no audio file produced")
        data = open(files[0], "rb").read()
        if len(data) > MAX_AUDIO_BYTES:
            raise RuntimeError(f"audio too large ({len(data)} bytes)")
        return data


def embed_caption(url):
    """Fallback: Instagram's public embed page usually carries the caption."""
    embed = normalize(url) + "/embed/captioned/"
    req = urllib.request.Request(embed, headers={"User-Agent": UA})
    body = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    m = re.search(r'class="Caption"[^>]*>(.*?)</div>', body, re.S)
    if not m:
        m = re.search(r'property="og:title" content="([^"]*)"', body)
        return html.unescape(m.group(1)) if m else ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def transcribe(audio: bytes) -> str:
    req = urllib.request.Request(
        WHISPER_URL, data=audio, headers={"Content-Type": "application/octet-stream"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read()).get("transcript", "")


def summarize(meta: dict, transcript: str) -> str:
    material = json.dumps(
        {
            "author": meta.get("uploader") or meta.get("channel") or "",
            "title": meta.get("title") or "",
            "caption": (meta.get("description") or "")[:3000],
            "duration_s": meta.get("duration"),
            "transcript": transcript[:6000],
        },
        ensure_ascii=False,
    )
    prompt = (
        "You summarize a social-media post Samy just saved because it looked "
        "interesting. From the material below, write (in the post's language, "
        "French or English):\n"
        "Line 1: a sharp 6-12 word title.\n"
        "Then 2-4 bullets with the actual substance (techniques, claims, "
        "numbers, steps) — never meta-fluff like 'the video discusses'.\n"
        "Last line: 'Tags:' + 2-4 lowercase topic tags.\n"
        "Plain text only, no markdown headers.\n\nMATERIAL:\n" + material
    )
    r = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--model", "sonnet"],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0 or not r.stdout.strip():
        err = (r.stderr or "")[-300:].strip() or "empty output"
        raise RuntimeError(f"claude summarization failed: {err}")
    return r.stdout.strip()


# --- outputs ----------------------------------------------------------------

def vault_append(url, meta, summary, transcript):
    os.makedirs(VAULT_DIR, exist_ok=True)
    path = os.path.join(VAULT_DIR, time.strftime("%Y-%m-%d") + ".md")
    author = meta.get("uploader") or meta.get("channel") or "unknown"
    block = (
        f"\n### {time.strftime('%H:%M')} — {author}\n"
        f"{url}\n\n{summary}\n"
    )
    if transcript:
        block += f"\n<details><summary>transcript</summary>\n\n{transcript}\n\n</details>\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return path


def tg(method, **params):
    if not BOT_TOKEN:
        return {}
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=65) as resp:
        return json.loads(resp.read())


def reply(text):
    if BOT_TOKEN and CHAT_ID:
        try:
            tg("sendMessage", chat_id=CHAT_ID, text=text[:4000],
               disable_web_page_preview="true")
        except Exception as e:
            log.warning("telegram reply failed: %s", e)


# --- pipeline ---------------------------------------------------------------

def process(url):
    url = normalize(url)
    if already_done(url):
        reply(f"♻️ already captured: {url}")
        return
    ledger_set(url, "processing")
    meta, transcript, fetch_note = {}, "", ""
    try:
        try:
            meta = ytdlp_json(url)
        except Exception as e:
            fetch_note = f"yt-dlp: {e}"
            log.info("yt-dlp failed for %s (%s), trying embed fallback", url, e)
            caption = embed_caption(url)
            if not caption:
                raise RuntimeError(f"unfetchable ({fetch_note}; embed empty)")
            meta = {"title": "", "description": caption}
        if meta.get("duration"):
            try:
                transcript = transcribe(ytdlp_audio(url))
            except Exception as e:
                log.warning("audio/transcribe failed for %s: %s", url, e)
        summary = summarize(meta, transcript)
        path = vault_append(url, meta, summary, transcript)
        ledger_set(url, "done", title=summary.splitlines()[0], note=fetch_note)
        log.info("captured %s -> %s", url, path)
        reply(f"📥 {summary}\n\n{url}")
    except Exception as e:
        ledger_set(url, "failed", note=str(e))
        log.warning("capture failed for %s: %s", url, e)
        reply(f"⚠️ couldn't capture {url}\n{e}")


def worker():
    while True:
        process(jobs.get())


# --- telegram long-poll -----------------------------------------------------

def poll_telegram():
    con = db()
    row = con.execute("SELECT v FROM meta WHERE k='tg_offset'").fetchone()
    con.close()
    offset = int(row[0]) if row else 0
    log.info("telegram long-poll started (offset %d)", offset)
    while True:
        try:
            updates = tg("getUpdates", offset=offset + 1, timeout=50,
                         allowed_updates='["message"]').get("result", [])
            for u in updates:
                offset = max(offset, u["update_id"])
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                    continue
                text = msg.get("text") or msg.get("caption") or ""
                urls = IG_URL_RE.findall(text) or ANY_URL_RE.findall(text)
                for found in urls:
                    log.info("telegram ingest: %s", found)
                    reply("👀 on it…")
                    jobs.put(found)
            if updates:
                con = db()
                con.execute(
                    "INSERT INTO meta(k,v) VALUES('tg_offset',?) "
                    "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(offset),))
                con.commit()
                con.close()
        except Exception as e:
            log.warning("poll error: %s", e)
            time.sleep(10)


# --- http -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "queued": jobs.qsize()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/ingest":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length)) if length else {}
            url = (payload.get("url") or "").strip()
            if not ANY_URL_RE.match(url):
                self._json(400, {"error": "body must be {\"url\": \"https://...\"}"})
                return
            jobs.put(url)
            self._json(202, {"queued": normalize(url)})
        except Exception as e:
            self._json(400, {"error": str(e)})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    if BOT_TOKEN and CHAT_ID:
        threading.Thread(target=poll_telegram, daemon=True).start()
    else:
        log.warning("no TELEGRAM_BOT_TOKEN/CHAT_ID — HTTP ingest only")
    log.info("reels-capture on %s:%d", HOST, PORT)
    HTTPServer((HOST, PORT), Handler).serve_forever()
