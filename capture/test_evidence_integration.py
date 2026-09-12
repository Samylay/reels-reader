#!/usr/bin/env python3
"""Offline checks for the EvidenceBundle capture boundary."""

import json
import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/quorky/services/triage")
import server  # noqa: E402
import evidence as evidence_store  # noqa: E402
from evidence import evidence_path, load_evidence  # noqa: E402


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

            self.assertEqual(extraction_calls, [url])
            self.assertEqual(server.ledger_get(url), {})
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


if __name__ == "__main__":
    unittest.main()
