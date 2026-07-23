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
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "/usr/bin/ffmpeg")
DB_PATH = os.environ.get("CAPTURE_DB", os.path.join(BASE, "data", "capture.db"))
MAX_AUDIO_BYTES = 24 * 1024 * 1024
# T06: bounded automatic retry of failed captures. A cookie-walled post that
# keeps failing exhausts its attempts and stays honestly failed (or `partial`
# if some text was salvaged).
MAX_ATTEMPTS = int(os.environ.get("CAPTURE_MAX_ATTEMPTS", "3"))
RETRY_SWEEP_SECONDS = int(os.environ.get("CAPTURE_RETRY_SWEEP_SECONDS", str(24 * 3600)))
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
    # T06 migration: attempt counter, failed stage, salvaged partial content.
    cols = {r[1] for r in con.execute("PRAGMA table_info(posts)")}
    if "attempts" not in cols:
        con.execute("ALTER TABLE posts ADD COLUMN attempts INTEGER DEFAULT 0")
        con.execute("ALTER TABLE posts ADD COLUMN stage TEXT DEFAULT ''")
        con.execute("ALTER TABLE posts ADD COLUMN partial TEXT DEFAULT ''")
        con.commit()
    return con


def normalize(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    if "instagram.com" in p.netloc:
        # IG post identity is the path; query is share-tracking junk (igsh=…)
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), p.query, ""))


def ledger_set(url, status, title="", note=""):
    """Upsert status/title/note. Never clobbers attempts/stage/partial —
    those move only through ledger_fail / ledger_clear_retry_state."""
    con = db()
    con.execute(
        "INSERT INTO posts(url, added_at, status, title, note) VALUES(?,?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET status=excluded.status, "
        "title=excluded.title, note=excluded.note",
        (url, time.strftime("%Y-%m-%dT%H:%M:%S"), status, title, note),
    )
    con.commit()
    con.close()


def ledger_get(url) -> dict:
    con = db()
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM posts WHERE url=?", (url,)).fetchone()
    con.close()
    return dict(row) if row else {}


def ledger_fail(url, stage: str, error: str, fetched: dict = None):
    """Mark a failed attempt: bump the attempt counter, record which stage
    broke, and persist whatever content was already computed so a retry (or
    the terminal partial delivery) never redoes or loses it. Returns the new
    attempt count."""
    partial = ""
    if fetched and (fetched.get("meta") or fetched.get("transcript")
                    or fetched.get("alt_texts") or fetched.get("ocr_text")):
        partial = json.dumps(fetched, ensure_ascii=False)
    con = db()
    con.execute(
        "UPDATE posts SET status='failed', note=?, stage=?, "
        "attempts=attempts+1, partial=CASE WHEN ?='' THEN partial ELSE ? END "
        "WHERE url=?",
        (error, stage, partial, partial, url),
    )
    con.commit()
    row = con.execute("SELECT attempts FROM posts WHERE url=?", (url,)).fetchone()
    con.close()
    return row[0] if row else 1


def failed_retryable_urls() -> list:
    con = db()
    rows = con.execute(
        "SELECT url FROM posts WHERE status='failed' AND attempts < ?",
        (MAX_ATTEMPTS,),
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def already_done(url) -> bool:
    con = db()
    row = con.execute("SELECT status FROM posts WHERE url=?", (url,)).fetchone()
    con.close()
    return bool(row and row[0] == "done")


def enqueue(url):
    """Record a durable 'queued' promise before handing off to the in-memory queue."""
    nurl = normalize(url)
    if not already_done(nurl):
        ledger_set(nurl, "queued")
    jobs.put(url)


def reload_pending_jobs():
    """Startup recovery: re-enqueue rows left 'queued'/'processing' by a prior
    crash/restart, plus 'failed' rows that still have retry budget (T06)."""
    con = db()
    rows = con.execute(
        "SELECT url FROM posts WHERE status IN ('queued','processing')"
    ).fetchall()
    con.close()
    for (url,) in rows:
        log.info("re-enqueuing pending job from ledger: %s", url)
        jobs.put(url)
    for url in failed_retryable_urls():
        log.info("re-enqueuing failed job for retry: %s", url)
        jobs.put(url)


def retry_sweep():
    """Once-daily second chance for failed captures with budget left —
    walled-then-unwalled posts get retried without Samy re-sharing."""
    while True:
        time.sleep(RETRY_SWEEP_SECONDS)
        urls = failed_retryable_urls()
        if urls:
            log.info("retry sweep: re-enqueuing %d failed job(s)", len(urls))
        for url in urls:
            jobs.put(url)


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


def fetch_embed_page(url):
    """Fetch Instagram's public /embed/captioned/ page (no auth, no headless browser)."""
    embed = normalize(url) + "/embed/captioned/"
    req = urllib.request.Request(embed, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")


def embed_caption_from_html(body: str) -> str:
    m = re.search(r'class="Caption"[^>]*>(.*?)</div>', body, re.S)
    if not m:
        m = re.search(r'property="og:title" content="([^"]*)"', body)
        return html.unescape(m.group(1)) if m else ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def embed_caption(url):
    """Fallback: Instagram's public embed page usually carries the caption."""
    return embed_caption_from_html(fetch_embed_page(url))


def extract_alt_texts(body: str) -> list:
    """Image alt text is IG's own accessibility OCR — cheap/rich signal (see
    decisions.md "Alt-text-first"). Pull it straight from the embed HTML, dedup,
    drop blanks."""
    seen = []
    for raw in re.findall(r'alt="([^"]*)"', body):
        text = html.unescape(raw).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def poster_url_from_embed(body: str) -> str:
    """The embed page's EmbeddedMediaImage is the reel's cover frame — for a
    cookie-walled video it's the one frame we can still reach anonymously."""
    m = re.search(r'class="EmbeddedMediaImage"[^>]*?src="([^"]+)"', body)
    return html.unescape(m.group(1)) if m else ""


def sample_video_frames(url: str, td: str) -> list:
    """Download the video (yt-dlp, anonymous) and sample up to 8 frames at
    3 s intervals for OCR. Raises if the video is unreachable."""
    out = os.path.join(td, "v.%(ext)s")
    r = subprocess.run(
        [YTDLP_BIN, "-f", "best[height<=720]/best", "--no-playlist",
         "--no-warnings", "-o", out, url],
        capture_output=True, text=True, timeout=300,
    )
    vids = [os.path.join(td, f) for f in os.listdir(td) if f.startswith("v.")]
    if r.returncode != 0 or not vids:
        raise RuntimeError("video download failed")
    subprocess.run(
        [FFMPEG_BIN, "-loglevel", "error", "-i", vids[0],
         "-vf", "fps=1/3", "-frames:v", "8", os.path.join(td, "frame%02d.jpg")],
        capture_output=True, timeout=120,
    )
    return sorted(
        os.path.join(td, f) for f in os.listdir(td) if f.startswith("frame")
    )


def ocr_images(paths: list) -> str:
    """Burned-in text via `claude -p` vision (the homelab's LLM backend — no
    tesseract dep). Merged + deduped across frames by the model itself."""
    prompt = (
        "Read each of these image files (frames sampled in order from one "
        "short social-media video):\n" + "\n".join(paths) + "\n\n"
        "Transcribe ALL burned-in on-screen text (captions, overlays, titles) "
        "merged across frames, deduplicated, in order of first appearance. "
        "Output the transcribed text only, no commentary, no markdown. "
        "If there is no on-screen text, output exactly: NOTEXT"
    )
    r = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--model", "sonnet", "--allowedTools", "Read"],
        capture_output=True, text=True, timeout=240,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ocr claude call failed: {(r.stderr or '')[-200:]}")
    text = r.stdout.strip()
    return "" if text == "NOTEXT" else text


def ocr_screen_text(url: str) -> str:
    """Frame-based OCR fallback for posts whose caption/transcript came up
    empty but whose video carries burned-in text. Frames from yt-dlp when the
    video is reachable; otherwise the embed page's cover frame alone."""
    with tempfile.TemporaryDirectory() as td:
        frames = []
        try:
            frames = sample_video_frames(url, td)
        except Exception as e:
            log.info("frame sampling failed for %s (%s), trying cover frame", url, e)
        if not frames:
            purl = poster_url_from_embed(fetch_embed_page(url))
            if not purl:
                return ""
            path = os.path.join(td, "poster.jpg")
            req = urllib.request.Request(purl, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp, \
                    open(path, "wb") as f:
                f.write(resp.read())
            frames = [path]
        return ocr_images(frames)


def transcribe(audio: bytes) -> str:
    req = urllib.request.Request(
        WHISPER_URL, data=audio, headers={"Content-Type": "application/octet-stream"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read()).get("transcript", "")


def summarize(meta: dict, transcript: str, alt_texts: list = None,
              ocr_text: str = "") -> str:
    material = json.dumps(
        {
            "author": meta.get("uploader") or meta.get("channel") or "",
            "title": meta.get("title") or "",
            "caption": (meta.get("description") or "")[:3000],
            "duration_s": meta.get("duration"),
            "transcript": transcript[:6000],
            "alt_texts": alt_texts or [],
            "on_screen_text_ocr": ocr_text[:3000],
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

def fetch_content(url: str) -> dict:
    """Side-effect-free content fetch for one IG URL — no ledger, no vault, no
    Telegram, safe to import from other services (the triage study step reuses
    it). yt-dlp metadata with /embed/captioned/ caption fallback, alt-texts,
    and a Whisper transcript when the post is a video yt-dlp can reach
    anonymously. Best-effort: returns whatever partial text exists.

    Returns {"meta": dict, "transcript": str, "alt_texts": list,
    "fetch_note": str}; meta is {} only when every fetch path came up empty.
    """
    url = normalize(url)
    meta, transcript, alt_texts, fetch_note = {}, "", [], ""
    try:
        meta = ytdlp_json(url)
    except Exception as e:
        fetch_note = f"yt-dlp: {e}"
        log.info("yt-dlp failed for %s (%s), trying embed fallback", url, e)
        try:
            body = fetch_embed_page(url)
            caption = embed_caption_from_html(body)
            alt_texts = extract_alt_texts(body)
            if caption:
                meta = {"title": "", "description": caption}
            else:
                fetch_note += "; embed empty"
        except Exception as e2:
            fetch_note += f"; embed: {e2}"
    if meta.get("duration"):
        try:
            transcript = transcribe(ytdlp_audio(url))
        except Exception as e:
            log.warning("audio/transcribe failed for %s: %s", url, e)
    elif not alt_texts:
        try:
            alt_texts = extract_alt_texts(fetch_embed_page(url))
        except Exception as e:
            log.info("alt-text enrichment failed for %s: %s", url, e)
    # Burned-in-text OCR: when everything text-shaped came up thin (a follow-me
    # caption, a music-only video), the substance is usually baked into the
    # frames. Fallback/supplement, never a replacement for a real transcript.
    ocr_text = ""
    caption = (meta.get("description") or meta.get("title") or "").strip()
    substance = re.sub(r"#\w+", "", f"{caption} {transcript}").strip()
    if len(substance) < 80:
        try:
            ocr_text = ocr_screen_text(url)
        except Exception as e:
            log.info("ocr failed for %s: %s", url, e)
        if ocr_text:
            fetch_note = (fetch_note + "; " if fetch_note else "") + "ocr salvaged on-screen text"
            if not meta:
                meta = {"title": "", "description": ""}
    return {"meta": meta, "transcript": transcript,
            "alt_texts": alt_texts, "ocr_text": ocr_text,
            "fetch_note": fetch_note}


def vault_append_partial(url, fetched, error):
    """Terminal delivery of salvaged content when retries are exhausted:
    better a caption/transcript marked partial in the vault than nothing."""
    meta = fetched.get("meta") or {}
    caption = (meta.get("description") or meta.get("title") or "").strip()
    transcript = fetched.get("transcript") or ""
    alt_texts = fetched.get("alt_texts") or []
    ocr_text = fetched.get("ocr_text") or ""
    body = "\n".join(
        s for s in (
            f"**Caption:** {caption}" if caption else "",
            f"**Alt text:** {' · '.join(alt_texts)}" if alt_texts else "",
            f"**On-screen text (OCR):** {ocr_text}" if ocr_text else "",
        ) if s
    )
    summary = (
        f"⚠️ partial capture (summarization failed after {MAX_ATTEMPTS} "
        f"attempts: {error})\n{body}" if body else
        f"⚠️ partial capture ({error})"
    )
    return vault_append(url, meta, summary, transcript)


def process(url):
    url = normalize(url)
    if already_done(url):
        reply(f"♻️ already captured: {url}")
        return
    prior = ledger_get(url)
    is_retry = prior.get("status") == "failed"
    resumed = {}
    if is_retry and prior.get("partial"):
        try:
            resumed = json.loads(prior["partial"])
        except ValueError:
            resumed = {}
    ledger_set(url, "processing", title=prior.get("title") or "",
               note=prior.get("note") or "")
    stage, fetched = "fetch", None
    try:
        if resumed.get("meta"):
            # Resume: content already fetched on a prior attempt — skip
            # yt-dlp/Whisper entirely and go straight to the failed stage.
            fetched = resumed
            log.info("retrying %s from stage '%s' with persisted partial",
                     url, prior.get("stage") or "summarize")
        else:
            fetched = fetch_content(url)
        meta, transcript = fetched["meta"], fetched["transcript"]
        alt_texts = fetched.get("alt_texts") or []
        fetch_note = fetched.get("fetch_note") or ""
        if not meta:
            raise RuntimeError(f"unfetchable ({fetch_note})")
        stage = "summarize"
        summary = summarize(meta, transcript, alt_texts,
                            fetched.get("ocr_text") or "")
        stage = "vault"
        path = vault_append(url, meta, summary, transcript)
        ledger_set(url, "done", title=summary.splitlines()[0], note=fetch_note)
        log.info("captured %s -> %s", url, path)
        reply(f"📥{' (recovered on retry)' if is_retry else ''} {summary}\n\n{url}")
    except Exception as e:
        attempts = ledger_fail(url, stage, str(e), fetched)
        log.warning("capture failed for %s at %s (attempt %d/%d): %s",
                    url, stage, attempts, MAX_ATTEMPTS, e)
        if attempts >= MAX_ATTEMPTS:
            row = ledger_get(url)
            salvaged = {}
            if row.get("partial"):
                try:
                    salvaged = json.loads(row["partial"])
                except ValueError:
                    salvaged = {}
            if salvaged.get("meta") or salvaged.get("transcript") \
                    or salvaged.get("alt_texts") or salvaged.get("ocr_text"):
                path = vault_append_partial(url, salvaged, e)
                ledger_set(url, "partial",
                           title=(salvaged.get("meta") or {}).get("title") or "",
                           note=f"partial after {attempts} attempts: {e}")
                log.info("delivered partial for %s -> %s", url, path)
                reply(f"⚠️ gave up on {url} after {attempts} attempts, but "
                      f"salvaged the caption/transcript into the vault.\n{e}")
            else:
                reply(f"⚠️ gave up on {url} after {attempts} attempts "
                      f"(nothing salvageable).\n{e}")
        elif attempts == 1:
            # First failure only — retries are silent unless they succeed
            # or exhaust the budget.
            reply(f"⚠️ couldn't capture {url} (will retry, "
                  f"{MAX_ATTEMPTS - attempts} attempts left)\n{e}")


def worker():
    while True:
        process(jobs.get())


# --- telegram voice notes ----------------------------------------------------
# A voice/audio message to the bot = a talk-session entry in the vault voice
# inbox (same format LifeOS's /api/voice/save writes), so the objectives
# classifier sweeps and routes it exactly like a brief-page recording. This is
# the phone half of "one list of things to talk about, one voice input".

VOICE_INBOX_DIR = os.environ.get(
    "VOICE_INBOX_DIR", f"{HOME}/vault/obsidian/01-Inbox/voice"
)


def tg_download(file_id: str) -> bytes:
    info = tg("getFile", file_id=file_id)
    fp = info.get("result", {}).get("file_path")
    if not fp:
        raise RuntimeError("getFile returned no file_path")
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise RuntimeError(f"voice note too large ({len(data)} bytes)")
    return data


def voice_inbox_append(transcript: str) -> str:
    os.makedirs(VOICE_INBOX_DIR, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    path = os.path.join(VOICE_INBOX_DIR, f"{date}.md")
    header = "" if os.path.exists(path) else f"# Voice inbox — {date}\n"
    entry = (
        f"{header}\n## {time.strftime('%H:%M')} · talk-session\n"
        f"> (voice note via Telegram — today's talking points are in the morning brief)\n\n"
        f"{transcript}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
    return path


def process_voice(file_id: str):
    try:
        transcript = transcribe(tg_download(file_id))
        if not transcript.strip():
            reply("⚠️ voice note came back empty from whisper")
            return
        voice_inbox_append(transcript)
        preview = transcript[:400] + ("…" if len(transcript) > 400 else "")
        reply(f"🎙 in the inbox (routes on the next objectives sweep):\n{preview}")
        log.info("voice note captured (%d chars)", len(transcript))
    except Exception as e:
        log.warning("voice capture failed: %s", e)
        reply(f"⚠️ couldn't process the voice note: {e}")


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
                media = msg.get("voice") or msg.get("audio") or msg.get("video_note")
                if media and media.get("file_id"):
                    threading.Thread(
                        target=process_voice, args=(media["file_id"],), daemon=True
                    ).start()
                    continue
                text = msg.get("text") or msg.get("caption") or ""
                urls = IG_URL_RE.findall(text) or ANY_URL_RE.findall(text)
                for found in urls:
                    log.info("telegram ingest: %s", found)
                    reply("👀 on it…")
                    enqueue(found)
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
            enqueue(url)
            self._json(202, {"queued": normalize(url)})
        except Exception as e:
            self._json(400, {"error": str(e)})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    reload_pending_jobs()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=retry_sweep, daemon=True).start()
    if BOT_TOKEN and CHAT_ID:
        threading.Thread(target=poll_telegram, daemon=True).start()
    else:
        log.warning("no TELEGRAM_BOT_TOKEN/CHAT_ID — HTTP ingest only")
    log.info("reels-capture on %s:%d", HOST, PORT)
    HTTPServer((HOST, PORT), Handler).serve_forever()
