"""Shared LLM access for every generative component (documentation, Q&A,
violation explanations, ADR synthesis).

Two providers, both reached through the OpenAI-compatible `openai` SDK:
- bedrock: Amazon Bedrock's OpenAI-compatible endpoint, one API key, paid
  from AWS credits, high limits.
- groq: Groq's free tier, ~8,000 tokens/min per key; several keys (one per
  account) are rotated, each with its own rate-limit cooldown.

LLM_PROVIDER picks the default (bedrock when BEDROCK_API_KEY is set, else
groq); LLM_PROVIDER_<PURPOSE> overrides it per purpose, e.g.
LLM_PROVIDER_QA=groq. Every call has a hard wall-clock deadline and
classified retries, and usage is counted per purpose for the efficiency
evaluation.
"""
import concurrent.futures
import itertools
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

TIMEOUT_SECONDS = 45
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_FALLBACK_SECONDS = 15
MAX_LENGTH_RETRY_TOKENS = 4000

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_BEDROCK_MODEL = "openai.gpt-oss-120b-1:0"
DEFAULT_BEDROCK_REGION = "us-west-2"
DEFAULT_BEDROCK_CONCURRENCY = 4

# "Request too large" shares Groq's rate_limit_exceeded code with genuine
# throttling, but resending the identical payload fails identically.
_NON_RETRYABLE_MARKERS = ("reduce your message size", "request too large")
_RATE_LIMIT_MARKERS = ("error code: 429", "ratelimiterror", "rate_limit_exceeded", "throttl", "too many requests")
# tool_use_failed: gpt-oss occasionally emits a malformed tool call; a fresh
# sample almost always succeeds.
_RETRYABLE_MARKERS = ("error code: 500", "error code: 502", "error code: 503", "error code: 504",
                      "internal server error", "unavailable", "overloaded", "timed out", "connection error",
                      "tool_use_failed")
# Groq phrases the wait as "6.07s", "532.5ms" or "1m30.5s".
_RETRY_AFTER_PATTERN = re.compile(r"try again in (?:(\d+)m(?!s))?([\d.]+)(ms|s)", re.IGNORECASE)
_REASONING_BLOCK = re.compile(r"<reasoning>.*?</reasoning>\s*", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LLMConfigError(RuntimeError):
    """No provider is configured for the requested purpose."""


@dataclass
class ChatResult:
    content: str
    tool_calls: list
    finish_reason: str
    provider: str


@dataclass
class _Provider:
    name: str
    model: str
    clients: list
    parallelism: int
    cooldown_until: list = field(default_factory=list)
    round_robin: itertools.count = field(default_factory=itertools.count)

    def __post_init__(self):
        self.cooldown_until = [0.0] * len(self.clients)


_lock = threading.Lock()
_providers = {}
_no_tools = set()
_notices = []
_usage = {}


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def _groq_keys() -> list:
    raw = os.environ.get("GROQ_API_KEYS", "").strip()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys and os.environ.get("GROQ_API_KEY", "").strip():
        keys = [os.environ["GROQ_API_KEY"].strip()]
    return keys


def _build_provider(name: str):
    if name == "groq":
        keys = _groq_keys()
        if not keys:
            return None
        clients = [OpenAI(base_url=GROQ_BASE_URL, api_key=k, max_retries=0) for k in keys]
        return _Provider("groq", os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL), clients, parallelism=len(clients))
    if name == "bedrock":
        key = os.environ.get("BEDROCK_API_KEY", "").strip()
        if not key:
            return None
        region = os.environ.get("BEDROCK_REGION", DEFAULT_BEDROCK_REGION).strip()
        base_url = f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1"
        client = OpenAI(base_url=base_url, api_key=key, max_retries=0)
        parallelism = int(os.environ.get("BEDROCK_MAX_CONCURRENCY", DEFAULT_BEDROCK_CONCURRENCY))
        return _Provider("bedrock", os.environ.get("BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL), [client],
                         parallelism=max(1, parallelism))
    raise LLMConfigError(f"Unknown LLM provider '{name}' (expected 'bedrock' or 'groq')")


def _get(name: str) -> _Provider:
    with _lock:
        if name not in _providers:
            _providers[name] = _build_provider(name)
        provider = _providers[name]
    if provider is None:
        raise LLMConfigError(f"LLM provider '{name}' is not configured (set its API key in .env)")
    return provider


def provider_name(purpose: str, needs_tools: bool = False) -> str:
    name = (os.environ.get(f"LLM_PROVIDER_{purpose.upper()}")
            or os.environ.get("LLM_PROVIDER")
            or ("bedrock" if os.environ.get("BEDROCK_API_KEY", "").strip() else "groq")).strip().lower()
    if needs_tools and name in _no_tools:
        return "groq"
    return name


def parallelism(purpose: str) -> int:
    """How many calls for this purpose may run at once without colliding on
    a rate limit: one per Groq key, or BEDROCK_MAX_CONCURRENCY on Bedrock."""
    return _get(provider_name(purpose)).parallelism


def describe(purpose: str) -> dict:
    p = _get(provider_name(purpose))
    return {"provider": p.name, "model": p.model, "keys": len(p.clients), "parallelism": p.parallelism}


def reset_for_tests() -> None:
    with _lock:
        _providers.clear()
        _no_tools.clear()
        _notices.clear()
        _usage.clear()


# --------------------------------------------------------------------------
# Usage accounting and notices
# --------------------------------------------------------------------------

def _record(purpose, response=None, failed=False):
    with _lock:
        u = _usage.setdefault(purpose, {"calls": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0})
        if failed:
            u["failures"] += 1
            return
        u["calls"] += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            u["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            u["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0


def usage_snapshot() -> dict:
    with _lock:
        return json.loads(json.dumps(_usage))


def notices() -> list:
    with _lock:
        return list(_notices)


def _notice(text):
    print(f"[llm] {text}", flush=True)
    with _lock:
        if text not in _notices:
            _notices.append(text)


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------

def extract_retry_after(text: str) -> float:
    match = _RETRY_AFTER_PATTERN.search(text)
    if not match:
        return RATE_LIMIT_FALLBACK_SECONDS
    minutes, amount, unit = match.groups()
    seconds = float(amount) / 1000 if unit.lower() == "ms" else float(amount)
    return seconds + 60 * int(minutes or 0)


def strip_reasoning(text: str) -> str:
    return _REASONING_BLOCK.sub("", text or "").strip()


def parse_json(text: str) -> dict:
    """Parses a JSON object from model output, tolerating surrounding prose or
    code fences."""
    text = strip_reasoning(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(text)
        if not match:
            raise ValueError("model output contained no JSON object")
        return json.loads(match.group(0))


def _classify(exc_text: str):
    text = exc_text.lower()
    non_retryable = any(m in text for m in _NON_RETRYABLE_MARKERS)
    rate_limited = not non_retryable and any(m in text for m in _RATE_LIMIT_MARKERS)
    retryable = not non_retryable and (rate_limited or any(m in text for m in _RETRYABLE_MARKERS))
    return rate_limited, retryable


def _pick_slot(provider: _Provider, pinned):
    now = time.time()
    with _lock:
        if pinned is not None:
            slot = pinned % len(provider.clients)
        else:
            # Round-robin, skipping ahead to whichever key's cooldown ends soonest.
            start = next(provider.round_robin) % len(provider.clients)
            order = [(start + i) % len(provider.clients) for i in range(len(provider.clients))]
            slot = min(order, key=lambda i: max(0.0, provider.cooldown_until[i] - now))
        return slot, max(0.0, provider.cooldown_until[slot] - now)


def _call_with_deadline(client, params):
    # Manually managed executor: `with ThreadPoolExecutor()` blocks on exit
    # until a slow call finishes, which would defeat the deadline.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(client.chat.completions.create, **params).result(timeout=TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        # concurrent.futures.TimeoutError stringifies to "", which would
        # surface as a blank error.
        raise TimeoutError(f"LLM call timed out after {TIMEOUT_SECONDS}s")
    finally:
        pool.shutdown(wait=False)


def chat(messages, *, purpose, max_tokens, tools=None, tool_choice=None, json_mode=False,
         temperature=0.2, key_slot=None) -> ChatResult:
    """One chat completion with retries.

    key_slot pins the call (and its retries) to one key: the documentation
    map phase runs one batch per key concurrently and must never collide.
    Without it, each attempt rotates to the key whose cooldown ends soonest.
    """
    needs_tools = bool(tools)
    provider = _get(provider_name(purpose, needs_tools))
    params = {"model": provider.model, "messages": messages, "temperature": temperature,
              "max_tokens": max_tokens, "timeout": TIMEOUT_SECONDS}
    if tools:
        params["tools"] = tools
        params["tool_choice"] = tool_choice or "auto"
    if json_mode:
        params["response_format"] = {"type": "json_object"}

    length_retried = False
    attempt = 0
    while True:
        slot, wait = _pick_slot(provider, key_slot)
        if wait > 0:
            print(f"[llm] {provider.name}[{slot}] {purpose}: waiting out cooldown {wait:.1f}s", flush=True)
            time.sleep(wait)
        t0 = time.time()
        try:
            response = _call_with_deadline(provider.clients[slot], params)
        except Exception as exc:
            _record(purpose, failed=True)
            exc_text = f"{type(exc).__name__}: {exc}"
            print(f"[llm] {provider.name}[{slot}] {purpose}: FAILED in {time.time() - t0:.1f}s "
                  f"(attempt {attempt}): {exc_text}", flush=True)
            lowered = exc_text.lower()

            if json_mode and "response_format" in lowered and "response_format" in params:
                params.pop("response_format")
                _notice(f"{provider.name} rejected JSON mode; falling back to prompt-only JSON.")
                continue
            if (needs_tools and provider.name == "bedrock" and "tool" in lowered
                    and ("400" in lowered or "not support" in lowered) and "tool_use_failed" not in lowered):
                with _lock:
                    _no_tools.add("bedrock")
                _notice("Bedrock rejected tool calling; tool-using features now run on Groq.")
                return chat(messages, purpose=purpose, max_tokens=max_tokens, tools=tools,
                            tool_choice=tool_choice, json_mode=json_mode, temperature=temperature)

            rate_limited, retryable = _classify(exc_text)
            if rate_limited:
                wait_s = extract_retry_after(exc_text) + 1.0
                with _lock:
                    provider.cooldown_until[slot] = max(provider.cooldown_until[slot], time.time() + wait_s)
            if not retryable or attempt >= MAX_RETRIES:
                raise
            attempt += 1
            if not rate_limited:
                time.sleep(RETRY_DELAY_SECONDS)
            continue

        _record(purpose, response)
        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise ValueError(f"{provider.name} returned no choices")
        message = choice.message
        content = strip_reasoning(message.content or "")
        tool_calls = list(message.tool_calls or [])
        finish_reason = choice.finish_reason or ""
        print(f"[llm] {provider.name}[{slot}] {purpose}: ok in {time.time() - t0:.1f}s (attempt {attempt})",
              flush=True)

        # gpt-oss can spend the whole budget reasoning and return nothing.
        if finish_reason == "length" and not content and not tool_calls and not length_retried:
            length_retried = True
            params["max_tokens"] = min(MAX_LENGTH_RETRY_TOKENS, params["max_tokens"] * 2)
            continue
        return ChatResult(content=content, tool_calls=tool_calls, finish_reason=finish_reason,
                          provider=provider.name)
