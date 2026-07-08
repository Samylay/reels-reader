#!/usr/bin/env python3
"""Unit-style check for extract_alt_texts()/embed_caption_from_html() (T02).

Run directly: python3 capture/test_alt_text.py
Uses the saved fixture page rather than hitting Instagram.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "embed_captioned_sample.html")


def main():
    with open(FIXTURE, encoding="utf-8") as f:
        body = f.read()

    alt_texts = server.extract_alt_texts(body)
    assert alt_texts == [
        "Photo by Jane Doe on July 08, 2026. May be an image of text that says "
        "'Ship small, ship often.'",
        "No text detected, just a photo of a laptop on a desk",
    ], alt_texts
    assert "" not in alt_texts, "blank alt attributes must be dropped"

    caption = server.embed_caption_from_html(body)
    assert caption == "Some caption & text with markup", caption

    print("OK:", len(alt_texts), "alt texts,", "caption:", repr(caption))


if __name__ == "__main__":
    main()
