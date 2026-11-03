"""RSS feed collector.

Supports multiple feed configs: the default ``config/feeds.yaml`` (overseas
feeds) and ``config/feeds_zh.yaml`` (domestic sources). The Chinese config adds
optional per-feed fields that are ignored when absent, so the original config
keeps working unchanged:

    tier          -> base score bucket (see ``tier_base_score``)
    lang          -> "zh" / "en", used for language-aware dedup downstream
    filter_mode   -> "strict" requires an ai_keywords hit, "loose" keeps all
    max_items     -> per-source cap
    enabled       -> false to skip a broken source
"""

import re
import feedparser
import requests
import yaml
from datetime import datetime, timedelta, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

_ASCII_ONLY = re.compile(r"^[\x20-\x7e]+$")


def _keyword_matchers(keywords):
    """Precompile keyword matchers.

    ASCII keywords must match on word boundaries, otherwise "AI" hits "email"
    and "said" — the exact false positive that makes naive substring checks
    useless on Chinese feeds. CJK keywords fall back to plain substring.
    """
    matchers = []
    for kw in keywords:
        kw = str(kw).strip()
        if not kw:
            continue
        if _ASCII_ONLY.match(kw):
            matchers.append(
                re.compile(rf"(?<![A-Za-z0-9]){re.escape(kw)}(?![A-Za-z0-9])", re.I)
            )
        else:
            matchers.append(kw)
    return matchers


def _matches(text, matchers):
    for m in matchers:
        if isinstance(m, str):
            if m in text:
                return True
        elif m.search(text):
            return True
    return False


def _load_config(config_path):
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def collect_rss(hours=24, config_path="config/feeds.yaml") -> list[dict]:
    """Fetch articles from RSS feeds published in the last N hours."""
    config = _load_config(config_path)
    defaults = config.get("defaults") or {}
    matchers = _keyword_matchers(config.get("ai_keywords") or [])
    tier_scores = config.get("tier_base_score") or {}
    default_filter = defaults.get("filter_mode", "loose")
    default_scope = defaults.get("filter_scope", "title")
    default_summary_chars = defaults.get("summary_chars", 1500)
    default_max = defaults.get("max_items_per_source")
    default_base = defaults.get("base_score", 15)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = []

    for feed_cfg in config.get("rss_feeds", []):
        name = feed_cfg["name"]
        url = feed_cfg["rss"]

        if not feed_cfg.get("enabled", True):
            print(f"  Skipping RSS (disabled): {name}")
            continue

        tier = feed_cfg.get("tier", 2)
        lang = feed_cfg.get("lang", "en")
        filter_mode = feed_cfg.get("filter_mode", default_filter)
        filter_scope = feed_cfg.get("filter_scope", default_scope)
        summary_chars = feed_cfg.get("summary_chars", default_summary_chars)
        max_items = feed_cfg.get("max_items", default_max)
        base_score = feed_cfg.get("base_score") or tier_scores.get(tier) or default_base
        use_filter = filter_mode == "strict" and bool(matchers)

        print(f"  Fetching RSS: {name}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            feed = feedparser.parse(resp.text)
            kept = stale = off_topic = 0

            for entry in feed.entries:
                if max_items and kept >= max_items:
                    break

                published = None
                if getattr(entry, "published_parsed", None):
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif getattr(entry, "updated_parsed", None):
                    published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                if published and published < cutoff:
                    stale += 1
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")[:summary_chars]

                # Match on the headline by default: long summaries mention AI
                # in passing (funding rounds, biotech pieces), which let
                # off-topic articles through the strict filter.
                if use_filter:
                    probe = title if filter_scope == "title" else f"{title} {summary}"
                    if not _matches(probe, matchers):
                        off_topic += 1
                        continue

                items.append({
                    "title": title,
                    "url": entry.get("link", ""),
                    "summary": summary,
                    "source": name,
                    "source_type": "rss",
                    "lang": lang,
                    "tier": tier,
                    "base_score": base_score,
                    "published": published.isoformat() if published else None,
                })
                kept += 1

            detail = f"    Got {kept} items"
            if stale or off_topic:
                detail += f" (skipped {stale} stale, {off_topic} off-topic)"
            print(detail)
        except Exception as e:
            print(f"    Error: {e}")

    return items
