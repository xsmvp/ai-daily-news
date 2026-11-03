"""
Check that the X/Twitter collector works — no LLM, no publishing.

Start with one account (each account costs ~4s), then run the full list once
that passes.

Usage:
    python scripts/collect_x.py                       # 3 accounts, quick check
    python scripts/collect_x.py --handle karpathy     # single account
    python scripts/collect_x.py --all                 # every account in config
    python scripts/collect_x.py --hours 72
    python scripts/collect_x.py --json
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from src.collectors.twitter import collect_twitter  # noqa: E402

CONFIG = "config/x_accounts.yaml"


def _all_handles():
    with open(CONFIG, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return [a["handle"] for a in config.get("accounts", [])]


def main():
    parser = argparse.ArgumentParser(description="Check X/Twitter collection.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--handle", action="append", help="only these handles")
    parser.add_argument("--all", action="store_true", help="every configured account")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    known = _all_handles()
    if args.handle:
        handles, label = args.handle, f"{len(args.handle)} selected"
    elif args.all:
        handles, label = known, f"all {len(known)}"
    else:
        handles, label = known[:3], f"first 3 of {len(known)}"

    print(f"Fetching {label} account(s), window {args.hours}h\n")
    try:
        items = collect_twitter(hours=args.hours, handles=handles)
    except RuntimeError as e:
        print(f"\nCannot start: {e}")
        return 1

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    print(f"\n=== {len(items)} tweets ===")
    counts = Counter(i["source"] for i in items)
    for source, n in counts.most_common():
        print(f"  {source:<20} {n:>2} tweets")

    if items:
        print("\n--- latest 8 ---")
        for i in items[:8]:
            m = i["metrics"]
            print(
                f"  {i['published'][:16]} | {m['likes']:>5} likes "
                f"{m['retweets']:>4} rt | {i['title'][:52]}"
            )

    silent = [f"@{h}" for h in handles if f"@{h}" not in counts]
    if silent:
        print(f"\nNo tweets from: {', '.join(silent)}")
        print("  (nothing new in window, or the account is gone — not an error)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
