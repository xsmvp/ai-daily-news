"""Generate daily digest using LLM."""

import os
import json
import time
import threading
from urllib.parse import urlsplit
from openai import OpenAI


def _load_prompt():
    """Load system prompt based on DIGEST_LANG (default zh)."""
    lang = os.getenv("DIGEST_LANG", "zh")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "prompts", f"digest_{lang}.md")
    if not os.path.isfile(path):
        path = os.path.join(root, "prompts", "digest_zh.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def generate_digest(items: list[dict], date_str: str, output_path=None) -> str:
    model = os.getenv("LLM_MODEL", "moonshot-v1-32k")
    base_url = os.getenv("LLM_BASE_URL", "https://api.moonshot.cn/v1")
    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=base_url,
    )

    items_text = json.dumps(items, ensure_ascii=False, indent=2)
    user_prompt_zh = f"以下是{date_str}采集到的AI相关信息，请整理成日报：\n\n{items_text}"
    user_prompt_en = f"Raw items collected for {date_str}. Build the digest:\n\n{items_text}"
    user_prompt = user_prompt_en if os.getenv("DIGEST_LANG", "zh") == "en" else user_prompt_zh
    system_prompt = _load_prompt()
    max_completion_tokens = int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "16384"))

    parsed_url = urlsplit(base_url)
    is_xfyun = (parsed_url.hostname or "").endswith("xf-yun.com")
    host = parsed_url.hostname or ""
    if parsed_url.port:
        host = f"{host}:{parsed_url.port}"
    safe_endpoint = f"{parsed_url.scheme}://{host}{parsed_url.path}"
    print(
        "  LLM request: "
        f"model={model}, endpoint={safe_endpoint}, items={len(items)}, "
        f"input_chars={len(system_prompt) + len(user_prompt)}, "
        f"max_completion_tokens={max_completion_tokens}, "
        f"thinking={'enabled' if is_xfyun else 'provider default'}, "
        f"temperature={'provider default' if is_xfyun else 0.3}"
    )
    print("  LLM status: sending non-streaming request; waiting for complete response...")

    started_at = time.monotonic()
    stop_progress = threading.Event()
    progress_state = {"status": "waiting for complete response"}

    def show_progress():
        while not stop_progress.wait(5):
            elapsed = time.monotonic() - started_at
            print(
                f"  LLM progress: {progress_state['status']} | elapsed={elapsed:.0f}s",
                flush=True,
            )

    progress_thread = threading.Thread(target=show_progress, daemon=True)
    progress_thread.start()
    finish_reason = None
    usage = None
    request_id = None
    request_args = {
        "model": model,
        "max_completion_tokens": max_completion_tokens,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if is_xfyun:
        request_args["extra_body"] = {"thinking": {"type": "enabled"}}
    else:
        request_args["temperature"] = 0.3

    try:
        if output_path:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            if os.path.exists(output_path):
                os.remove(output_path)
            print(f"  Removed previous digest; will write complete response to: {output_path}")
        response = client.chat.completions.create(**request_args)
        request_id = response.id
        usage = response.usage
        choice = response.choices[0] if response.choices else None
        if choice:
            finish_reason = choice.finish_reason
            content = choice.message.content or ""
        else:
            content = ""
        progress_state["status"] = "response received"
    except Exception as e:
        elapsed = time.monotonic() - started_at
        print(
            f"\n  LLM request failed after {elapsed:.1f}s "
            f"({progress_state['status']}): {e}"
        )
        raise
    finally:
        stop_progress.set()
        progress_thread.join()

    elapsed = time.monotonic() - started_at
    print(
        f"\n  LLM request completed in {elapsed:.1f}s | "
        f"request_id={request_id or 'unavailable'} | "
        f"output_chars={len(content)}"
    )
    print(f"  LLM finish_reason: {finish_reason}")
    if usage:
        print(
            "  LLM token usage: "
            f"prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, "
            f"total={usage.total_tokens}"
        )
        usage_details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(usage_details, "reasoning_tokens", None)
        if reasoning_tokens is not None:
            print(f"  LLM reasoning tokens: {reasoning_tokens}")
    if finish_reason == "length":
        print("  WARNING: LLM output may be truncated because it reached the token limit.")
        raise RuntimeError("LLM output reached its token limit; refusing to publish a truncated digest.")
    if not content.strip():
        raise RuntimeError("LLM returned an empty digest; refusing to publish an empty result.")
    digest_items = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith(("- ", "* ")) and len(line.strip()) > 20
    ]
    if not digest_items:
        raise RuntimeError("LLM returned no complete digest items; refusing to publish incomplete output.")
    if output_path:
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(content)
        print(f"  Digest saved: {output_path}")

    return content
