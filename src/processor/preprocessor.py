"""Preprocessing pipeline: score → dedup → classify → sort."""

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher


def _parse_time(published_str):
    """Parse ISO format time string, return datetime or None."""
    if not published_str:
        return None
    try:
        return datetime.fromisoformat(published_str)
    except (ValueError, TypeError):
        return None


def _time_decay(published_str, half_life_hours=24):
    """Exponential decay based on age. Returns 0~1."""
    dt = _parse_time(published_str)
    if not dt:
        return 0.5  # unknown age gets middle value
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = max((now - dt).total_seconds() / 3600, 0)
    return math.pow(0.5, age_hours / half_life_hours)


def _safe_log2(n):
    """log2 that handles 0 and negative values."""
    return math.log2(n + 1) if n and n > 0 else 0


# Ceiling for a single tweet's score. Kept just above tier-1 RSS (25) so a
# strong tweet competes with front-page news instead of dwarfing it.
TWITTER_SCORE_CAP = 30


def _build_weight_map(accounts_config):
    """Build handle -> weight multiplier map from accounts config."""
    weight_map = {}
    for acc in accounts_config.get("accounts", []):
        handle = acc.get("handle", "")
        w = acc.get("weight", "medium")
        weight_map[handle.lower()] = 3 if w == "high" else 1
    return weight_map


def score_items(items, accounts_config):
    """Score each item based on engagement, account weight, and recency."""
    weight_map = _build_weight_map(accounts_config)

    for item in items:
        decay = _time_decay(item.get("published"))

        if item.get("source_type") == "twitter":
            metrics = item.get("metrics", {})
            likes = _safe_log2(metrics.get("likes", 0))
            retweets = _safe_log2(metrics.get("retweets", 0))
            replies = _safe_log2(metrics.get("replies", 0))
            engagement = likes * 3 + retweets * 4 + replies * 2

            handle = item.get("source", "").lstrip("@").lower()
            account_weight = weight_map.get(handle, 1)

            # Uncapped log-engagement lets one viral tweet (50k likes ≈ 117
            # points) bury every RSS item (tier 1 caps at 25). Ceiling keeps
            # tweets competitive with front-page news without letting a
            # birthday greeting outrank the day's actual AI stories.
            score = min(engagement * account_weight, TWITTER_SCORE_CAP)
            item["score"] = round(score * decay, 2)
        else:
            # RSS: per-source base score (tier-weighted for domestic feeds) * decay
            base = item.get("base_score", 15)
            item["score"] = round(base * decay, 2)

    return items


def _similarity(a, b):
    """String similarity ratio using SequenceMatcher."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _title_threshold(a, b):
    """Similarity threshold for the title-dedup layer.

    Chinese headlines are short and information-dense, so a single differing
    character moves SequenceMatcher much more than in English. A strict ratio
    only merges near-identical reposts instead of unrelated stories about the
    same topic. Cross-language pairs are skipped entirely (threshold > 1) —
    a translated headline never scores high enough to be useful, and merging
    them is the LLM's job via ``related_sources``.
    """
    la, lb = a.get("lang", "en"), b.get("lang", "en")
    if la != lb:
        return 1.01
    return 0.80 if la == "zh" else 0.65


def dedup(items):
    """Three-layer dedup: URL → title similarity → summary similarity."""
    kept = []
    seen_urls = set()

    for item in items:
        url = item.get("url", "")
        merged = False

        # Layer 1: exact URL match
        if url and url in seen_urls:
            for k in kept:
                if k.get("url") == url:
                    k.setdefault("related_sources", []).append({
                        "source": item.get("source"),
                        "url": url,
                    })
                    if item.get("score", 0) > k.get("score", 0):
                        k["score"] = item["score"]
                    merged = True
                    break
            if merged:
                continue

        # Layer 2: title similarity (threshold depends on language)
        title = item.get("title", "")
        for k in kept:
            if _similarity(title, k.get("title", "")) >= _title_threshold(item, k):
                k.setdefault("related_sources", []).append({
                    "source": item.get("source"),
                    "url": item.get("url"),
                })
                if item.get("score", 0) > k.get("score", 0):
                    k["score"] = item["score"]
                    k["title"] = title
                    k["summary"] = item.get("summary", k.get("summary", ""))
                    k["url"] = item.get("url", k.get("url", ""))
                merged = True
                break
            if merged:
                break
        if merged:
            continue

        # Layer 3: Twitter summary similarity >= 0.8
        if item.get("source_type") == "twitter":
            summary = item.get("summary", "")
            for k in kept:
                if k.get("source_type") == "twitter" and _similarity(summary, k.get("summary", "")) >= 0.8:
                    k.setdefault("related_sources", []).append({
                        "source": item.get("source"),
                        "url": item.get("url"),
                    })
                    if item.get("score", 0) > k.get("score", 0):
                        k["score"] = item["score"]
                        k["title"] = title
                        k["summary"] = summary
                        k["url"] = item.get("url", k.get("url", ""))
                    merged = True
                    break
        if merged:
            continue

        # No match — keep as new item
        if url:
            seen_urls.add(url)
        kept.append(item)

    return kept


CATEGORY_KEYWORDS = {
    "要闻": [
        "发布", "launch", "release", "announce", "open source", "开源",
        "收购", "acqui", "merger", "融资", "funding", "billion", "million",
        "ban", "regulation", "监管", "政策", "policy",
    ],
    "产品": [
        "update", "更新", "feature", "功能", "app", "tool", "plugin",
        "api", "sdk", "model", "版本", "beta", "alpha", "v1", "v2",
    ],
    "观点": [
        "think", "believe", "opinion", "观点", "看法", "predict", "预测",
        "thread", "take", "hot take", "rant", "essay", "反思",
    ],
}


_CATEGORY_PATTERNS = {
    category: [
        re.compile(rf"(?<![A-Za-z0-9]){re.escape(kw)}(?![A-Za-z0-9])", re.I)
        if kw.isascii() else kw
        for kw in keywords
    ]
    for category, keywords in CATEGORY_KEYWORDS.items()
}


def classify_items(items):
    """Keyword-based pre-classification as suggestion for LLM.

    ASCII keywords match on word boundaries so "app" no longer hits "happen"
    and "api" no longer hits "capital" — noise that got noticeably worse once
    Chinese sources were mixed in.
    """
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        matched = "其他"
        for category, patterns in _CATEGORY_PATTERNS.items():
            hit = False
            for p in patterns:
                if isinstance(p, str):
                    hit = p in text
                else:
                    hit = bool(p.search(text))
                if hit:
                    break
            if hit:
                matched = category
                break
        item["suggested_category"] = matched
    return items


def _apply_lang_quota(items, lang_quota, max_total):
    """Reserve a fixed share of slots per language, then backfill by score.

    Ranking purely by score lets the larger pool crowd the other language out
    of the digest entirely (domestic sources outnumber overseas ones roughly
    2:1). Slots are allocated per language first; anything a language cannot
    fill is handed back to the overall score order, so a thin day for one side
    never wastes capacity.

    ``items`` must already be sorted by score descending.
    """
    if not lang_quota:
        return items, 0

    total = min(len(items), max_total) if max_total else len(items)

    buckets = {}
    for item in items:
        buckets.setdefault(item.get("lang", "en"), []).append(item)

    picked, chosen = [], set()
    for lang, ratio in lang_quota.items():
        quota = int(round(total * float(ratio)))
        for item in buckets.get(lang, [])[:quota]:
            picked.append(item)
            chosen.add(id(item))

    need = total - len(picked)
    if need > 0:
        leftover = [i for i in items if id(i) not in chosen][:need]
        picked.extend(leftover)

    picked.sort(key=lambda x: x.get("score", 0), reverse=True)
    return picked, len(items) - len(picked)


def _cap_by_type(items, ratio_map, max_total):
    """Cap how many items of a given ``source_type`` may enter the digest.

    Each X handle counts as its own source, so ``max_per_source`` cannot stop
    30 accounts from filling the list; a type-level ceiling can.

    ``items`` must already be sorted by score descending.
    """
    if not ratio_map:
        return items, 0

    total = max_total or len(items)
    allowed = {kind: int(total * float(ratio)) for kind, ratio in ratio_map.items()}

    kept, counts, dropped = [], {}, 0
    for item in items:
        kind = item.get("source_type", "rss")
        if kind in allowed and counts.get(kind, 0) >= allowed[kind]:
            dropped += 1
            continue
        counts[kind] = counts.get(kind, 0) + 1
        kept.append(item)
    return kept, dropped


def preprocess(items, accounts_config, max_total=None, max_per_source=None,
               lang_quota=None, max_type_ratio=None):
    """Full preprocessing pipeline: score → dedup → classify → sort.

    ``max_per_source`` enforces a per-source quota after sorting so one
    prolific feed (雷锋网/IT之家 produce 8 relevant items a day) cannot own the
    whole digest. ``max_type_ratio`` caps a whole source type (e.g. twitter),
    ``lang_quota`` reserves slots per language e.g. ``{"zh": 0.6, "en": 0.4}``,
    and ``max_total`` caps the result — all sources together push the LLM
    prompt past its context window otherwise.
    """
    original_count = len(items)

    items = score_items(items, accounts_config)
    items = dedup(items)
    items = classify_items(items)
    items.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Add source_count for multi-source items
    for item in items:
        related = item.get("related_sources", [])
        item["source_count"] = 1 + len(related)

    dedup_count = original_count - len(items)

    # Per-source quota for digest diversity
    source_capped = 0
    if max_per_source:
        limited, per_source = [], {}
        for item in items:
            src = item.get("source", "")
            if per_source.get(src, 0) >= max_per_source:
                source_capped += 1
                continue
            per_source[src] = per_source.get(src, 0) + 1
            limited.append(item)
        items = limited

    # Light filtering: remove very low score items (noise)
    before_filter = len(items)
    items = [i for i in items if i.get("score", 0) >= 5]
    filtered_count = before_filter - len(items)

    items, type_capped = _cap_by_type(items, max_type_ratio, max_total)

    items, lang_dropped = _apply_lang_quota(items, lang_quota, max_total)

    truncated = 0
    if max_total and len(items) > max_total:
        truncated = len(items) - max_total
        items = items[:max_total]

    return items, {
        "original": original_count,
        "after_dedup": original_count - dedup_count,
        "removed": dedup_count,
        "after_filter": len(items) + truncated,
        "filtered": filtered_count,
        "source_capped": source_capped,
        "type_capped": type_capped,
        "lang_dropped": lang_dropped,
        "truncated": truncated,
    }
