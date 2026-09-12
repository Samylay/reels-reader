"""Bridge the reels capture worker to triage's immutable evidence contract.

This module owns the integration boundary.  It imports the shared extraction
package from the explicitly configured triage checkout and never imports the
capture server, which keeps the dependency direction one-way.
"""

from __future__ import annotations

from datetime import datetime
import html
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Callable, Mapping


DEFAULT_EXTRACTION_ROOT = "/home/quorky/services/triage"
EXTRACTION_ROOT = os.environ.get("TRIAGE_EXTRACTION_PATH", DEFAULT_EXTRACTION_ROOT)
EXTRACTION_VERSION = os.environ.get("TRIAGE_EXTRACTION_VERSION", "2C.1")
EVIDENCE_DIR = os.environ.get(
    "CAPTURE_EVIDENCE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "evidence"),
)


def _embed_image_url(body: str) -> str:
    """Extract the public embed poster/image URL without treating the page as media."""
    patterns = (
        r'<img(?=[^>]*class=["\'][^"\']*EmbeddedMediaImage)[^>]*src=["\']([^"\']+)',
        r'<img(?=[^>]*src=["\']([^"\']+))(?=[^>]*class=["\'][^"\']*EmbeddedMediaImage)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<img[^>]+src=["\'](https?://[^"\']+)',
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            value = html.unescape(match.group(1))
            if value.startswith(("http://", "https://")):
                return value
    return ""


def _package() -> tuple[Any, Any]:
    """Load the shared package and Instagram adapter from its configured root."""
    root = os.path.abspath(EXTRACTION_ROOT)
    if not os.path.isdir(os.path.join(root, "extraction")):
        raise RuntimeError(f"triage extraction package not found: {root}")
    # The shared package is a configured dependency, not a reason to mutate
    # the capture process import path permanently. This matters when study.py
    # loads server.py by filename from cron.
    original_path = list(sys.path)
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
        package = importlib.import_module("extraction")
        instagram = importlib.import_module("extraction.instagram")
    finally:
        sys.path[:] = original_path
    return package, instagram


class _Downloader:
    """Adapt capture's anonymous media functions to InstagramAdapter."""

    def __init__(
        self,
        metadata: Callable[[str], Mapping[str, Any]],
        *,
        embed_page: Callable[[str], str] | None = None,
        embed_caption: Callable[[str], str] | None = None,
        embed_alts: Callable[[str], list[str]] | None = None,
        download_video: Callable[[str, str], str | bytes] | None = None,
        extract_audio: Callable[[str, str], str | bytes] | None = None,
        download_image: Callable[[str, str], str | bytes] | None = None,
    ) -> None:
        self._metadata = metadata
        self._embed_page = embed_page
        self._embed_caption = embed_caption
        self._embed_alts = embed_alts
        self._download_video = download_video
        self._extract_audio = extract_audio
        self._download_image = download_image
        self._video_urls: dict[str, str] = {}
        self._embed_bodies: dict[str, str] = {}

    def metadata(self, url: str, deadline: float | None = None) -> Mapping[str, Any]:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("extraction deadline exceeded")
        try:
            try:
                value = dict(self._metadata(url, deadline))
            except TypeError:
                value = dict(self._metadata(url))
        except Exception:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("extraction deadline exceeded")
            if not self._embed_page:
                raise
            try:
                body = self._embed_page(url, deadline)
            except TypeError:
                body = self._embed_page(url)
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("extraction deadline exceeded")
            self._embed_bodies[url] = body
            caption = self._embed_caption(body) if self._embed_caption else ""
            alts = self._embed_alts(body) if self._embed_alts else []
            if not caption and not alts:
                raise
            value = {"title": "", "description": caption}

        entries = value.get("entries")
        if isinstance(entries, list):
            normalized_entries = []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                child = dict(entry)
                webpage_url = str(child.get("webpage_url") or "")
                formats = child.get("formats") if isinstance(child.get("formats"), list) else []
                is_video = bool(child.get("duration") or child.get("video_url") or formats)
                direct_url = str(child.get("video_url") or "") if is_video else ""
                if is_video and not direct_url:
                    direct_url = next(
                        (str(fmt.get("url")) for fmt in formats
                         if isinstance(fmt, Mapping) and fmt.get("url")
                         and (fmt.get("vcodec") is None or str(fmt.get("vcodec")) != "none")),
                        "",
                    )
                if not direct_url:
                    candidate = child.get("url")
                    if candidate and str(candidate) != webpage_url:
                        direct_url = str(candidate)
                if not direct_url and not is_video:
                    thumbnails = child.get("thumbnails") if isinstance(child.get("thumbnails"), list) else []
                    direct_url = next(
                        (str(item.get("url")) for item in thumbnails
                         if isinstance(item, Mapping) and item.get("url")),
                        "",
                    )
                    direct_url = direct_url or str(child.get("thumbnail") or "")
                child["url"] = direct_url
                if not child.get("type") and (child.get("duration") or child.get("video_url") or child.get("formats")):
                    child["type"] = "video"
                normalized_entries.append(child)
            value["entries"] = normalized_entries

        # yt-dlp metadata uses duration as the stable video signal. The
        # shared adapter accepts either type/media_type or a video URL.
        if value.get("duration") and not any(
            value.get(key) for key in ("type", "kind", "media_type", "video_url")
        ):
            value["type"] = "reel"

        # The embed page is the anonymous alt-text fallback for image posts.
        # Put those descriptions into a synthetic child so the shared bundle
        # preserves their provenance instead of keeping them bridge-only.
        if not value.get("duration") and self._embed_page:
            try:
                body = self._embed_bodies.pop(url, None)
                if body is None:
                    try:
                        body = self._embed_page(url, deadline)
                    except TypeError:
                        body = self._embed_page(url)
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("extraction deadline exceeded")
                alts = self._embed_alts(body) if self._embed_alts else []
                image_url = _embed_image_url(body)
                if (alts or image_url) and not any(value.get(key) for key in ("children", "carousel", "media", "items", "entries")):
                    value["children"] = [
                        # The embed page is not a child media URL. Preserve
                        # its alt evidence without making the parent webpage
                        # look downloadable.
                        {"id": f"embed-slide-{index}", "type": "image", "url": image_url if index == 1 else "", "alt_text": alt}
                        for index, alt in enumerate(alts or [""], start=1)
                    ]
            except Exception:
                pass
        return value

    def download_video(self, url: str, path: str, deadline: float | None = None) -> str | bytes:
        if not self._download_video:
            raise RuntimeError("video download adapter is not configured")
        self._video_urls[path] = url
        try:
            return self._download_video(url, path, deadline)
        except TypeError:
            return self._download_video(url, path)

    def extract_audio(self, video_path: str, path: str, deadline: float | None = None) -> str | bytes:
        if not self._extract_audio:
            raise RuntimeError("audio extraction adapter is not configured")
        try:
            return self._extract_audio(video_path, path, deadline)
        except TypeError:
            return self._extract_audio(video_path, path)

    def download_image(self, url: str, path: str, deadline: float | None = None) -> str | bytes:
        if not self._download_image:
            raise RuntimeError("image download adapter is not configured")
        try:
            return self._download_image(url, path, deadline)
        except TypeError:
            return self._download_image(url, path)


class _Transcriber:
    def __init__(self, transcribe: Callable[[bytes], Any]) -> None:
        self._transcribe = transcribe

    def transcribe(self, audio: Any, deadline: float | None = None) -> Any:
        if isinstance(audio, str):
            with open(audio, "rb") as stream:
                audio = stream.read()
        try:
            return self._transcribe(audio, deadline)
        except TypeError:
            return self._transcribe(audio)


def extract_evidence(
    url: str,
    *,
    metadata: Callable[[str], Mapping[str, Any]],
    embed_page: Callable[[str], str] | None = None,
    embed_caption: Callable[[str], str] | None = None,
    embed_alts: Callable[[str], list[str]] | None = None,
    download_video: Callable[[str, str], str | bytes] | None = None,
    extract_audio: Callable[[str, str], str | bytes] | None = None,
    download_image: Callable[[str, str], str | bytes] | None = None,
    transcribe: Callable[[bytes], Any] | None = None,
    ocr: Any | None = None,
    vision: Any | None = None,
    frame_extractor: Any | None = None,
    limits: Any | None = None,
    deadline: float | None = None,
    now: datetime | str | None = None,
) -> Any:
    """Run bounded Instagram extraction with capture-owned adapters."""
    package, instagram = _package()
    downloader = _Downloader(
        metadata,
        embed_page=embed_page,
        embed_caption=embed_caption,
        embed_alts=embed_alts,
        download_video=download_video,
        extract_audio=extract_audio,
        download_image=download_image,
    )
    kwargs: dict[str, Any] = {
        "downloader": downloader,
        "ocr": ocr,
        "vision": vision,
        "frame_extractor": frame_extractor,
        "now": now,
    }
    if transcribe:
        kwargs["transcriber"] = _Transcriber(transcribe)
    if limits is not None:
        kwargs["limits"] = limits
    if deadline is not None:
        kwargs["deadline"] = deadline
    return instagram.extract_instagram(url, **kwargs)


def _source_dict(value: Mapping[str, Any], source_type: Any) -> Any:
    return source_type(
        str(value.get("id", "")),
        str(value.get("kind", "page")),
        str(value.get("url", "")),
        resolved_url=value.get("resolvedUrl"),
        platform_id=value.get("platformId"),
        author=value.get("author"),
        published_at=value.get("publishedAt"),
        title=value.get("title"),
        order=value.get("order"),
        media_metadata=value.get("mediaMetadata"),
    )


def bundle_from_dict(data: Mapping[str, Any]) -> Any:
    """Decode and validate one persisted EvidenceBundle."""
    package, _ = _package()
    required = {
        "schemaVersion", "bundleId", "contentHash", "extractionVersion",
        "requestedUrl", "canonicalUrl", "platform", "fetchedAt",
        "rootSourceId", "sources", "relations", "segments", "coverage",
        "quality", "issues",
    }
    if not required.issubset(data) or not isinstance(data.get("sources"), list):
        raise ValueError("evidence bundle has an invalid shape")
    source_type = package.Source
    sources = tuple(_source_dict(value, source_type) for value in data["sources"] if isinstance(value, Mapping))
    relations = tuple(package.Relation(str(value["fromSourceId"]), str(value["toSourceId"]), str(value["kind"])) for value in data["relations"] if isinstance(value, Mapping) and {"fromSourceId", "toSourceId", "kind"}.issubset(value))
    segments = tuple(package.Segment(
        str(value.get("id", "")), str(value.get("sourceId", "")), str(value.get("kind", "")),
        str(value.get("text", "")), str(value.get("method", "")), model=value.get("model"),
        start_ms=value.get("startMs"), end_ms=value.get("endMs"), slide_index=value.get("slideIndex"),
        page_number=value.get("pageNumber"), frame_id=value.get("frameId"),
    ) for value in data["segments"] if isinstance(value, Mapping))
    coverage = tuple(package.Coverage(
        str(value.get("sourceId", "")), str(value.get("aspect", "")), str(value.get("status", "")),
        expected_count=value.get("expectedCount"), observed_count=value.get("observedCount"),
        processed_count=value.get("processedCount"), sampled_timestamps_ms=tuple(value.get("sampledTimestampsMs", ())),
        reason_code=value.get("reasonCode"), detail=value.get("detail"),
    ) for value in data["coverage"] if isinstance(value, Mapping))
    bundle = package.EvidenceBundle(
        str(data["schemaVersion"]), str(data["bundleId"]), str(data["contentHash"]),
        str(data["extractionVersion"]), str(data["requestedUrl"]), str(data["canonicalUrl"]),
        str(data["platform"]), str(data["fetchedAt"]), str(data["rootSourceId"]),
        sources, relations, segments, coverage, str(data["quality"]), tuple(str(item) for item in data["issues"]),
    )
    if not bundle.bundle_id or not bundle.extraction_version or not bundle.root_source_id:
        raise ValueError("evidence bundle identity is empty")
    content_hash = hashlib.sha256(
        "\n".join(segment.text for segment in bundle.segments if segment.text).encode("utf-8")
    ).hexdigest()
    expected_id = f"bundle_{hashlib.sha256((bundle.canonical_url + '\0' + content_hash).encode('utf-8')).hexdigest()[:24]}"
    if bundle.content_hash != content_hash or bundle.bundle_id != expected_id:
        raise ValueError("cached evidence integrity check failed")
    return bundle


def evidence_path(url: str, *, extraction_version: str | None = None) -> str:
    """Return the deterministic cache path for a normalized URL/version."""
    _, instagram = _package()
    version = extraction_version or EXTRACTION_VERSION
    digest = hashlib.sha256(f"{version}\0{url}".encode("utf-8")).hexdigest()[:32]
    return os.path.join(EVIDENCE_DIR, f"{digest}.{version}.json")


def save_evidence(bundle: Any, *, path: str | None = None) -> str:
    """Atomically persist JSON evidence, never media bytes or temporary paths."""
    target = path or evidence_path(bundle.canonical_url, extraction_version=bundle.extraction_version)
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, exist_ok=True)
    payload = bundle.to_json() + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".evidence-", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target


def load_evidence(url: str, *, path: str | None = None) -> Any | None:
    """Load valid cached evidence, returning None for missing/corrupt data."""
    target = path or evidence_path(url)
    try:
        with open(target, encoding="utf-8") as stream:
            data = json.load(stream)
        bundle = bundle_from_dict(data)
        if bundle.extraction_version != EXTRACTION_VERSION:
            raise ValueError("cached evidence extraction version is not current")
        if bundle.canonical_url != url and bundle.requested_url != url:
            raise ValueError("cached evidence URL does not match request")
        return bundle
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def legacy_content(bundle: Any) -> dict[str, Any]:
    """Adapt bundle segments to the pre-EvidenceBundle fetch_content shape."""
    root = next((source for source in bundle.sources if source.id == bundle.root_source_id), None)
    caption = next((segment.text for segment in bundle.segments if segment.kind == "caption"), "")
    transcript = "\n".join(segment.text for segment in bundle.segments if segment.kind == "transcript")
    alt_texts = [segment.text for segment in bundle.segments if segment.kind == "alt-text"]
    ocr = [segment.text for segment in bundle.segments if segment.kind in {"ocr", "vision-observation"}]
    issues = "; ".join(bundle.issues)
    meta = {
            "title": (root.title if root else "") or "",
            "description": caption,
            "uploader": (root.author if root else "") or "",
        } if root else {}
    if bundle.quality == "unavailable" and not any(segment.text for segment in bundle.segments):
        meta = {}
    return {
        "meta": meta,
        "transcript": transcript,
        "alt_texts": alt_texts,
        "ocr_text": "\n".join(ocr),
        "ocr_cover_only": any(item.reason_code == "cover_only" for item in bundle.coverage),
        "ocr_status": "failed" if any("failed" in item for item in bundle.issues) else "sampled" if ocr else "not-needed",
        "fetch_note": issues,
    }


def add_ocr(bundle: Any, text: str, *, cover_only: bool = False) -> Any:
    """Attach legacy OCR output while preserving frame/coverage provenance."""
    if not text:
        return bundle
    package, _ = _package()
    source_id = next((source.id for source in bundle.sources if source.kind == "video"), bundle.root_source_id)
    frame_id = f"frame_{hashlib.sha256((source_id + ':legacy-ocr').encode()).hexdigest()[:24]}"
    segment_id = f"seg_{hashlib.sha256((frame_id + ':' + text).encode()).hexdigest()[:24]}"
    frame = package.Segment(frame_id, source_id, "frame", "", "legacy-ocr-cover" if cover_only else "legacy-ocr", frame_id=frame_id)
    ocr = package.Segment(segment_id, source_id, "ocr", text, "vision-ocr", frame_id=frame_id)
    coverage = package.Coverage(source_id, "ocr", "partial" if cover_only else "complete", reason_code="cover_only" if cover_only else None)
    issues = tuple(dict.fromkeys((*bundle.issues, "cover_only" if cover_only else "")))
    issues = tuple(item for item in issues if item)
    # Frame identity is provenance on the non-empty OCR segment. A synthetic
    # empty ``frame`` segment would violate the shared segment contract.
    segments = (*bundle.segments, ocr)
    content_hash = hashlib.sha256("\n".join(segment.text for segment in segments if segment.text).encode("utf-8")).hexdigest()
    bundle_id = f"bundle_{hashlib.sha256((bundle.canonical_url + '\0' + content_hash).encode('utf-8')).hexdigest()[:24]}"
    return package.EvidenceBundle(
        bundle.schema_version, bundle_id, content_hash, bundle.extraction_version,
        bundle.requested_url, bundle.canonical_url, bundle.platform, bundle.fetched_at,
        bundle.root_source_id, bundle.sources, bundle.relations, segments,
        (*bundle.coverage, coverage), "limited" if cover_only else bundle.quality, issues,
    )


__all__ = [
    "EVIDENCE_DIR", "EXTRACTION_ROOT", "add_ocr", "bundle_from_dict", "evidence_path",
    "extract_evidence", "legacy_content", "load_evidence", "save_evidence",
]
