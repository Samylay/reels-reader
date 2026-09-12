#!/usr/bin/env python3
"""Offline checks for the EvidenceBundle capture boundary."""

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/quorky/services/triage")
import server  # noqa: E402
import evidence as evidence_store  # noqa: E402
from evidence import evidence_path, load_evidence  # noqa: E402
from evidence import extract_evidence as bridge_extract  # noqa: E402


class EvidenceCaptureTests(unittest.TestCase):
    def bundle(self, url="https://instagram.com/p/evidence-fixture"):
        from extraction import Coverage, EvidenceBundle, Segment, Source

        source = Source("src_fixture", "post", url, title="Fixture", order=0)
        segment = Segment("seg_fixture", source.id, "caption", "A useful caption", "fixture")
        content_hash = hashlib.sha256(segment.text.encode("utf-8")).hexdigest()
        bundle_id = "bundle_" + hashlib.sha256((url + "\0" + content_hash).encode("utf-8")).hexdigest()[:24]
        return EvidenceBundle(
            "1", bundle_id, content_hash, "2C.1", url, url,
            "instagram", "2026-09-12T00:00:00Z", source.id,
            (source,), (), (segment,),
            (Coverage(source.id, "caption", "complete"),), "usable", (),
        )

    def test_evidence_is_saved_before_summary_and_reused_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "capture.db")
            evidence_dir = os.path.join(directory, "evidence")
            url = "https://instagram.com/p/evidence-fixture"
            bundle = self.bundle(url)
            extraction_calls = []
            summary_calls = []

            def extract(_url):
                extraction_calls.append(_url)
                return bundle

            def summarize(*_args):
                summary_calls.append(True)
                if len(summary_calls) == 1:
                    self.assertIsNotNone(load_evidence(url))
                    raise RuntimeError("model unavailable")
                return "Fixture title\n- substance\nTags: fixture"

            with patch.object(server, "DB_PATH", db_path), \
                 patch.object(server, "EVIDENCE_DIR", evidence_dir), \
                 patch.object(server, "extract_capture_evidence", side_effect=extract), \
                 patch.object(server, "summarize", side_effect=summarize), \
                patch.object(server, "vault_append", return_value="vault.md"), \
                 patch.object(server, "reply"):
                server.process(url)
                self.assertEqual(server.ledger_get(url)["status"], "failed")
                server.process(url)
                self.assertEqual(server.ledger_get(url)["status"], "done")

            self.assertEqual(extraction_calls, [url])
            self.assertTrue(os.path.isfile(evidence_path(url)))

    def test_corrupt_cache_is_replaced_by_a_fresh_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = os.path.join(directory, "evidence")
            url = "https://instagram.com/p/corrupt-fixture"
            os.makedirs(evidence_dir, exist_ok=True)
            # evidence_path uses the module cache directory, so patch it
            # before creating the deliberately malformed cache.
            with patch.object(server, "EVIDENCE_DIR", evidence_dir), \
                 patch.object(evidence_store, "EVIDENCE_DIR", evidence_dir):
                path = evidence_path(url)
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write("not json")
                bundle = self.bundle(url)
                with patch.object(server, "DB_PATH", os.path.join(directory, "capture.db")), \
                     patch.object(server, "extract_capture_evidence", return_value=bundle), \
                     patch.object(server, "summarize", return_value="Title\nTags: fixture"), \
                     patch.object(server, "vault_append", return_value="vault.md"), \
                     patch.object(server, "reply"):
                    server.process(url)
                with open(path, encoding="utf-8") as stream:
                    self.assertEqual(json.load(stream)["bundleId"], bundle.bundle_id)

    def test_importlib_by_path_loads_sibling_without_path_leak(self):
        code = """
import importlib.util, os, sys
path = '/home/quorky/apps/reels-reader/capture/server.py'
spec = importlib.util.spec_from_file_location('reels_capture_cron_check', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.evidence_store is not None
assert os.path.dirname(path) not in sys.path
before = list(sys.path)
module.evidence_store._package()
assert sys.path == before
"""
        result = subprocess.run([sys.executable, "-c", code], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mixed_ytdlp_entries_process_video_and_vague_image(self):
        class Media:
            def metadata(self, _url):
                return {"caption": "mixed", "entries": [
                    {"id": "video", "webpage_url": "https://cdn.test/reel.mp4", "duration": 2, "ext": "mp4"},
                    {"id": "image", "thumbnail": "https://cdn.test/slide.jpg", "alt_text": "A photo"},
                ]}

            def download_video(self, _url, path, *_args):
                with open(path, "wb") as stream:
                    stream.write(b"video")
                return path

            def extract_audio(self, _video, path, *_args):
                with open(path, "wb") as stream:
                    stream.write(b"audio")
                return path

            def download_image(self, _url, path, *_args):
                with open(path, "wb") as stream:
                    stream.write(b"image")
                return path

        class OCR:
            def read(self, _path, *_args):
                return {"text": "overlay"}

        class Frames:
            def extract_frames(self, _video, candidates, directory, *_args):
                return []

            def event_times(self, *_args):
                return [], []

        bundle = bridge_extract(
            "https://instagram.com/p/mixed", metadata=Media().metadata,
            download_video=Media().download_video, extract_audio=Media().extract_audio,
            download_image=Media().download_image,
            transcribe=lambda *_args: {"segments": [{"text": "spoken", "startMs": 0, "endMs": 1000}]},
            ocr=OCR(), frame_extractor=Frames(),
        )
        self.assertEqual([source.order for source in bundle.sources[1:]], [1, 2])
        self.assertTrue(any(source.kind == "video" for source in bundle.sources))
        self.assertTrue(any(segment.kind == "ocr" and segment.text == "overlay" for segment in bundle.segments))
        self.assertTrue(any(item.reason_code == "frame_extractor_partial" for item in bundle.coverage))


if __name__ == "__main__":
    unittest.main()
