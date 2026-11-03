"""X/Twitter collector.

twikit's object layer (``User`` / ``Tweet``) no longer matches X's payloads —
``User.__init__`` raises ``KeyError: 'urls'`` because X dropped
``legacy.entities.description.urls``, and its transaction-id bootstrap breaks
on the new bundle manifest. We therefore use twikit only for cookies, proxy and
request signing (``client.gql``), and parse the GraphQL JSON ourselves.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import yaml
from dotenv import load_dotenv
from twikit import Client

from src.collectors.twikit_patch import apply as _apply_twikit_patch

load_dotenv()
_apply_twikit_patch()

TWEET_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


def _env(name: str) -> str:
    """Read an env var, treating empty strings as unset.

    ``python-dotenv`` turns ``PROXY_URL=`` into ``""`` rather than leaving the
    key absent, which previously crashed httpx with
    ``Unknown scheme for proxy URL URL('')``.
    """
    return (os.getenv(name) or "").strip()


def _proxy() -> str | None:
    raw = _env("PROXY_URL")
    if not raw:
        return None
    if "://" not in raw:
        # People write "127.0.0.1:7897"; httpx needs an explicit scheme.
        raw = f"http://{raw}"
    return raw


def _cookies() -> dict:
    auth = _env("X_AUTH_TOKEN")
    ct0 = _env("X_CT0")
    if not auth or not ct0:
        raise RuntimeError(
            "X_AUTH_TOKEN / X_CT0 are empty — copy both cookies from the browser "
            "(DevTools -> Application -> Cookies -> x.com) and fill them in .env"
        )
    return {"auth_token": auth, "ct0": ct0}


def _unwrap_tweet(result: dict) -> dict | None:
    """Skip tombstones / visibility wrappers and unwrap retweets."""
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}
    if result.get("__typename") == "TweetTombstone":
        return None
    if "legacy" not in result:
        return None
    retweet = result["legacy"].get("retweeted_status_result")
    if retweet:
        inner = _unwrap_tweet(retweet.get("result") or {})
        if inner:
            return inner
    return result


def _text_of(result: dict) -> str:
    note = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    if note.get("text"):
        return note["text"]
    return result.get("legacy", {}).get("full_text", "")


def _parse_entries(payload: dict):
    """Yield every tweet object found in a timeline response."""
    user = (payload.get("data") or {}).get("user") or {}
    result = user.get("result") or {}
    timeline = (result.get("timeline_v2") or result.get("timeline") or {})
    instructions = (timeline.get("timeline") or {}).get("instructions") or []

    for instruction in instructions:
        for entry in instruction.get("entries") or []:
            content = entry.get("content") or {}
            item = content.get("itemContent") or {}
            if item.get("promotedMetadata"):
                continue
            raw = (item.get("tweet_results") or {}).get("result")
            tweet = _unwrap_tweet(raw or {})
            if tweet:
                yield tweet


def _to_item(handle, name, bio, tweet, cutoff) -> dict | None:
    legacy = tweet.get("legacy") or {}
    created_raw = legacy.get("created_at")
    if not created_raw:
        return None
    created = datetime.strptime(created_raw, TWEET_DATE_FMT)
    if created < cutoff:
        return None

    text = _text_of(tweet).strip()
    if not text:
        return None

    tweet_id = tweet.get("rest_id") or tweet.get("id_str") or legacy.get("id_str")
    views = (tweet.get("views") or {}).get("count")
    return {
        "title": f"@{handle}: {text[:80]}",
        "url": f"https://x.com/{handle}/status/{tweet_id}",
        "summary": text,
        "source": f"@{handle}",
        "source_name": name,
        "source_bio": bio,
        "source_type": "twitter",
        "published": created.isoformat(),
        "metrics": {
            "likes": legacy.get("favorite_count") or 0,
            "retweets": legacy.get("retweet_count") or 0,
            "replies": legacy.get("reply_count") or 0,
            "views": int(views) if views and str(views).isdigit() else 0,
        },
    }


async def _fetch(client, account, cutoff) -> list[dict]:
    handle = account["handle"]
    name = account.get("name", handle)
    bio = account.get("bio", "")

    resp, _ = await client.gql.user_by_screen_name(handle)
    user = ((resp.get("data") or {}).get("user") or {}).get("result") or {}
    if not user.get("rest_id"):
        raise RuntimeError(f"@{handle} not found or suspended")

    tweets, _ = await client.gql.user_tweets(user["rest_id"], 20, None)

    items = []
    for tweet in _parse_entries(tweets):
        item = _to_item(handle, name, bio, tweet, cutoff)
        if item:
            items.append(item)
    return items


async def _collect(hours=24, handles=None) -> list[dict]:
    client = Client("en-US", proxy=_proxy())
    client.set_cookies(_cookies())

    with open("config/x_accounts.yaml") as f:
        config = yaml.safe_load(f)

    accounts = config.get("accounts", [])
    if handles:
        wanted = {h.lstrip("@").lower() for h in handles}
        accounts = [a for a in accounts if a["handle"].lower() in wanted]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = []

    for account in accounts:
        handle = account["handle"]
        print(f"  Fetching X: @{handle}", flush=True)
        try:
            got = await _fetch(client, account, cutoff)
            items.extend(got)
            print(f"    Got {len(got)} tweets", flush=True)
            await asyncio.sleep(3)  # rate limit
        except Exception as e:
            if "429" in str(e):
                print("    Rate limited, waiting 60s...", flush=True)
                await asyncio.sleep(60)
                try:
                    got = await _fetch(client, account, cutoff)
                    items.extend(got)
                    print(f"    Retry got {len(got)} tweets", flush=True)
                except Exception as e2:
                    print(f"    Retry failed: {e2}", flush=True)
            else:
                print(f"    Error: {e}", flush=True)

    return items


def collect_twitter(hours=24, handles=None) -> list[dict]:
    return asyncio.run(_collect(hours, handles))
