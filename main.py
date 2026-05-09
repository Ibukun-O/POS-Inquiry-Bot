#!/usr/bin/env python3
"""
main.py — Run the POS Inquiry scanner once from the command line.

Usage
-----
    python main.py
    OPENAI_MODEL=gpt-4o-mini python main.py
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from scanner import run_scan  # noqa: E402 (import after dotenv)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)


def main() -> None:
    print("=" * 62)
    print("  Gmail POS Inquiry Bot — one-shot scan (OpenAI)")
    print("=" * 62)

    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    print(f"  Model : {model}")
    print()

    results = run_scan(openai_model=model)

    if not results:
        print("No unread 'POS Inquiry' emails found — nothing to do.\n")
        sys.exit(0)

    print(f"Processed {len(results)} email(s):\n")
    for i, r in enumerate(results, 1):
        bar = "▓" * int((r.sentiment_score + 1) / 2 * 20)
        print(f"  [{i}] From      : {r.email.sender}")
        print(f"       Subject   : {r.email.subject}")
        print(f"       Received  : {r.email.received_at.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"       Sentiment : {r.sentiment.upper()}  ({r.sentiment_score:+.2f})  {bar}")
        print(f"       Summary   : {r.sentiment_summary}")
        print(f"       Draft ID  : {r.draft_id}")
        print()

    print("All drafts saved to Gmail → Drafts. Review before sending.")
    print()


if __name__ == "__main__":
    main()
