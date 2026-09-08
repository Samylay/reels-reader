#!/usr/bin/env python3
"""Offline checks for Instagram alt-text and OCR decision semantics."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402


class OcrPipelineTests(unittest.TestCase):
    def test_alt_parser_preserves_source_order_and_handles_html_attribute_forms(self):
        body = """<img alt='Slide 1: caf&eacute;\nline two'>
        <img ALT=\"Slide 2: text that says &quot;Build small&quot;\">
        <img alt='Slide 1: café\nline two'><div alt='not an image'></div>"""

        self.assertEqual(server.extract_alt_texts(body), [
            "Slide 1: café\nline two",
            'Slide 2: text that says "Build small"',
        ])

    def test_text_bearing_alt_skips_remote_vision_for_an_image_post(self):
        meta = {"description": "Short caption", "duration": None}
        html = '<img alt="May be an image of text that says: first useful slide, with enough detail to exceed the threshold.">'
        with patch("server.ytdlp_json", return_value=meta), \
             patch("server.fetch_embed_page", return_value=html), \
             patch("server.ocr_screen_text") as ocr:
            fetched = server.fetch_content("https://instagram.com/p/fixture")

        ocr.assert_not_called()
        self.assertEqual(fetched["ocr_status"], "not-needed")
        self.assertEqual(len(fetched["alt_texts"]), 1)

    def test_listicle_still_requests_ocr_even_with_a_long_caption(self):
        meta = {"description": "5 tools you need. #ad This long promotional caption hides the actual named items.", "duration": 12}
        with patch("server.ytdlp_json", return_value=meta), \
             patch("server.transcribe", return_value=""), \
             patch("server.ytdlp_audio", return_value=b"audio"), \
             patch("server.ocr_screen_text", return_value=("1. Actual tool", False)) as ocr:
            fetched = server.fetch_content("https://instagram.com/reel/fixture")

        ocr.assert_called_once()
        self.assertEqual(fetched["ocr_status"], "sampled")
        self.assertEqual(fetched["ocr_text"], "1. Actual tool")

    def test_ocr_failure_is_explicit_not_the_same_as_no_ocr(self):
        meta = {"description": "Short", "duration": None}
        with patch("server.ytdlp_json", return_value=meta), \
             patch("server.fetch_embed_page", return_value="<html></html>"), \
             patch("server.ocr_screen_text", side_effect=RuntimeError("vision unavailable")):
            fetched = server.fetch_content("https://instagram.com/p/fixture")

        self.assertEqual(fetched["ocr_status"], "failed")
        self.assertIn("ocr: failed", fetched["fetch_note"])


if __name__ == "__main__":
    unittest.main()
