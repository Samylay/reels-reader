#!/usr/bin/env python3
"""
capture/status.py — print recent capture ledger rows and status counts.

Read-only audit tool for capture/data/capture.db, so Samy doesn't need to
write sqlite3 by hand. Usage: python3 capture/status.py
"""

import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "capture.db")


def main():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT added_at, status, title, url FROM posts ORDER BY added_at DESC LIMIT 20"
    ).fetchall()

    print("Last 20 captures:")
    for added_at, status, title, url in rows:
        print(f"{added_at}  {status:<10}  {title[:50]:<50}  {url}")

    counts = con.execute(
        "SELECT status, COUNT(*) FROM posts GROUP BY status ORDER BY status"
    ).fetchall()
    print("\nCounts by status:")
    for status, count in counts:
        print(f"  {status}: {count}")

    con.close()


if __name__ == "__main__":
    main()
