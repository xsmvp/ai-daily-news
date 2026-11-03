"""
Inspect domestic sources defined in config/feeds_zh.yaml — no LLM, no publishing.

Use this to answer "did source X actually return anything today?" before
trusting it in the daily digest.

Usage:
    python scripts/collect_zh.py                  # 24h window, summary table
    python scripts/collect_zh.py --hours 48
    python scripts/collect_zh.py --source 量子位   # one source, full output
    python scripts/collect_zh.py --json           # machine-readable dump
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.collectors.rss import collect_rss  # noqa: E402

CONFIG = "config/feeds_zh.yaml"


def main():
    parser = argparse.ArgumentParser(description="Inspect domestic feed collection.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--source", help="only show items from this source name")
    parser.add_argument("--json", action="store_true", help="dump raw items as JSON")
    args = parser.parse_args()

    items = collect_rss(hours=args.hours, config_path=CONFIG)

    if args.source:
        items = [i for i in items if i["source"] == args.source]
        if not items:
            print(f"\nNo items from '{args.source}'. Check the name against {CONFIG}.")
            return 1

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    print(f"\n=== {len(items)} items in the last {args.hours}h ===")
    counts = Counter(i["source"] for i in items)
    for source, n in counts.most_common():
        tiers = {i["tier"] for i in items if i["source"] == source}
        print(f"  {source:<14} {n:>2} items  tier={','.join(map(str, sorted(tiers)))}")

    print("\n--- latest 10 ---")
    for i in items[:10]:
        print(f"  [{i['tier']}] {i['source']:<12} {i['title'][:56]}")

    empty = [s for s in _configured_sources() if s not in counts]
    if empty:
        print(f"\nNo items from: {', '.join(empty)}")
        print("  (out of window, or the source is broken — see docs/zh-sources.md)")
    return 0


def _configured_sources():
    import yaml

    with open(CONFIG, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return [
        feed["name"]
        for feed in config.get("rss_feeds", [])
        if feed.get("enabled", True)
    ]


if __name__ == "__main__":
    sys.exit(main())
