"""
AI engine — wraps LLM API calls for:
  1. Structured resume parsing
  2. Candidate scoring against a job description
  3. Interview question generation

Provider strategy: Groq and Cerebras are both fast, free (~30 req/min each),
so calls are split between whichever of the two are configured — roughly
doubling effective throughput and combining their daily quotas.
Gemini is the final fallback if both fail or aren't configured.

Multi-key rotation: each provider can have MULTIPLE keys configured. When a
key hits its daily free-tier quota, it's automatically skipped in favor of
the next configured key for that provider — no manual swapping, no waiting
for the quota to reset. Add extra keys either as a comma-separated value on
the base key, or as numbered keys:
  GROQ_API_KEY     = "key1,key2,key3"      (comma-separated), OR
  GROQ_API_KEY     = "key1"
  GROQ_API_KEY_2   = "key2"
  GROQ_API_KEY_3   = "key3"
Same pattern works for CEREBRAS_API_KEY and GEMINI_API_KEY.
Free keys:
  GROQ_API_KEY     — free at https://console.groq.com
  CEREBRAS_API_KEY — free at https://cloud.cerebras.ai
  GEMINI_API_KEY   — free at https://aistudio.google.com
Set them in st.secrets (.streamlit/secrets.toml) or as environment variables.
"""

import os
import json
import time
import re
import random
import threading
import itertools
import logging
from collections import deque
import streamlit as st

# The google.genai SDK logs an informational notice ("Direct use of automatic
# function calling (AFC) in Models.generate_content is not recommended...")
# on every single generate_content call, regardless of whether AFC is
# actually used — this app never passes tools/functions to Gemini, so AFC is
# irrelevant here. Silenced at the source so it doesn't clutter the terminal.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
logging.getLogger("google_genai").setLevel(logging.ERROR)

# ----------------------------- API KEY HELPERS -----------------------------

def _get_secret(name: str) -> str | None:
    # A session-level override set on the Settings page takes priority —
    # lets a person test/swap a key for this session without touching files.
    try:
        override = st.session_state.get(f"override_{name}")
        if override:
            return override
    except Exception:
        pass
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def _collect_keys(base_name: str) -> list[str]:
    """
    Collect every configured key for a provider, not just one.
    Supports two ways of adding extra keys, so a person can add as many as
    they have without touching code:
      1. Numbered secrets/env vars: GROQ_API_KEY_2, GROQ_API_KEY_3, ...
      2. A single comma-separated value in the base key: GROQ_API_KEY = "k1,k2,k3"
    Order is preserved and duplicates are dropped.
    """
    keys: list[str] = []

    primary = _get_secret(base_name)
    if primary:
        keys.extend(k.strip() for k in str(primary).split(",") if k.strip())

    i = 2
    while True:
        extra = _get_secret(f"{base_name}_{i}")
        if not extra:
            break
        keys.extend(k.strip() for k in str(extra).split(",") if k.strip())
        i += 1

    seen = set()
    unique_keys = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique_keys.append(k)
    return unique_keys


def _get_groq_key() -> str | None:
    keys = _collect_keys("GROQ_API_KEY")
    return keys[0] if keys else None


def _get_cerebras_key() -> str | None:
    keys = _collect_keys("CEREBRAS_API_KEY")
    return keys[0] if keys else None


def _get_gemini_key() -> str | None:
    keys = _collect_keys("GEMINI_API_KEY")
    return keys[0] if keys else None


def check_api_key() -> bool:
    """True if at least one provider is configured."""
    return bool(_get_groq_key() or _get_cerebras_key() or _get_gemini_key())


def active_provider() -> str:
    """Which provider(s) will be used, for display in the UI."""
    def _label(name, keys):
        if not keys:
            return None
        return f"{name} ({len(keys)} keys)" if len(keys) > 1 else name

    groq_keys = _collect_keys("GROQ_API_KEY")
    cerebras_keys = _collect_keys("CEREBRAS_API_KEY")
    gemini_keys = _collect_keys("GEMINI_API_KEY")

    fast = [lbl for lbl in (_label("Groq", groq_keys), _label("Cerebras", cerebras_keys)) if lbl]
    if fast:
        label = " + ".join(fast) + (" (split)" if len(fast) > 1 else " (primary)")
        return label + (f" + Gemini fallback ({len(gemini_keys)} keys)" if gemini_keys else "")
    elif gemini_keys:
        return f"Gemini only ({len(gemini_keys)} keys, no Groq/Cerebras key set)"
    return "None configured"


# ----------------------------- MULTI-KEY ROTATION POOL -----------------------------
# Each provider can have multiple keys configured (see _collect_keys above).
# A KeyPool tracks which keys are currently exhausted (hit a DAILY quota, not
# just a per-minute rate limit) and skips them until the quota window resets,
# rotating to the next available key immediately — no waiting, no manual
# swapping. Per-minute 429s are handled separately by the rate limiter /
# retry-sleep logic already in each provider's call function.

def _seconds_until_next_utc_midnight() -> float:
    now = time.time()
    import datetime
    now_dt = datetime.datetime.utcfromtimestamp(now)
    tomorrow = (now_dt + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now_dt).total_seconds()


def _is_daily_quota_error(msg: str) -> bool:
    lower = msg.lower()
    return (
        "perday" in lower.replace(" ", "")
        or "per_day" in lower
        or "daily" in lower
        or ("quota" in lower and "day" in lower)
    )


class _KeyPool:
    """Thread-safe round-robin pool of API keys for one provider, with
    exhausted-key tracking so a key that hit its daily cap is skipped until
    it resets, instead of being retried and failing over and over."""

    def __init__(self):
        self._lock = threading.Lock()
        self._exhausted_until: dict[str, float] = {}
        self._cycle_index = 0

    def available_keys(self, all_keys: list[str]) -> list[str]:
        now = time.time()
        with self._lock:
            # Clear any keys whose exhaustion window has passed.
            for k in list(self._exhausted_until):
                if self._exhausted_until[k] <= now:
                    del self._exhausted_until[k]
            return [k for k in all_keys if k not in self._exhausted_until]

    def ordered_available_keys(self, all_keys: list[str]) -> list[str]:
        """Available keys, rotated so repeated calls spread evenly across
        all configured keys instead of always starting from the first."""
        avail = self.available_keys(all_keys)
        if not avail:
            return []
        with self._lock:
            start = self._cycle_index % len(avail)
            self._cycle_index += 1
        return avail[start:] + avail[:start]

    def mark_exhausted(self, key: str, msg: str):
        with self._lock:
            if _is_daily_quota_error(msg):
                self._exhausted_until[key] = time.time() + _seconds_until_next_utc_midnight()
            else:
                # Unknown/other hard failure on this key — cool it down for a
                # few minutes rather than hammering it every call.
                self._exhausted_until[key] = time.time() + 300


_GROQ_KEY_POOL = _KeyPool()
_CEREBRAS_KEY_POOL = _KeyPool()
_GEMINI_KEY_POOL = _KeyPool()




# ----------------------------- JSON CLEANUP -----------------------------

def _sanitize_json_text(text: str) -> str:
    """Clean up common issues in model-returned JSON before parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    # Strip raw control characters (unescaped newlines/tabs inside strings break json.loads)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _extract_retry_seconds(msg: str, attempt: int) -> int:
    match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg) or re.search(r"try again in ([\d.]+)s", msg, re.I)
    if match:
        return int(float(match.group(1))) + 2
    return (attempt + 1) * 15


# ----------------------------- GROQ PROVIDER -----------------------------
# As of Aug 2026, Groq deprecated llama-3.1-8b-instant, llama-3.3-70b-versatile,
# and qwen/qwen3-32b (announced June 17, 2026); mixtral-8x7b-32768 was retired
# even earlier. The old fallback lists here consisted almost entirely of dead
# models, so every call was striking out repeatedly before succeeding — the
# real cause of things feeling "slow" independent of usage volume. Updated to
# Groq's current recommended replacements (openai/gpt-oss-*, qwen3.6-27b).
GROQ_FALLBACK_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
]

# Chat replies prioritize speed over the extra reasoning depth scoring needs.
GROQ_CHAT_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
]


def _call_groq(prompt: str, max_attempts: int = 3) -> dict:
    from groq import Groq

    all_keys = _collect_keys("GROQ_API_KEY")
    if not all_keys:
        raise RuntimeError("Groq API key not configured.")

    last_error = None
    for api_key in _GROQ_KEY_POOL.ordered_available_keys(all_keys):
        client = Groq(api_key=api_key)
        key_exhausted = False
        for model_name in GROQ_FALLBACK_MODELS:
            for attempt in range(max_attempts):
                try:
                    completion = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a precise JSON-generating assistant. Always return only valid JSON, no prose, no markdown fences."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                    raw_text = completion.choices[0].message.content
                    cleaned = _sanitize_json_text(raw_text)
                    return json.loads(cleaned)
                except json.JSONDecodeError as parse_err:
                    last_error = parse_err
                    if attempt < max_attempts - 1:
                        continue
                    break  # try next model
                except Exception as e:
                    msg = str(e)
                    last_error = e
                    if "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
                        if _is_daily_quota_error(msg):
                            # This key is done for the day — mark it and move
                            # straight to the next configured key, no sleeping.
                            _GROQ_KEY_POOL.mark_exhausted(api_key, msg)
                            key_exhausted = True
                            break
                        if attempt < max_attempts - 1:
                            time.sleep(_extract_retry_seconds(msg, attempt))
                            continue
                        break  # exhausted retries on this model, try next model
                    if "404" in msg or "decommissioned" in msg.lower() or "not found" in msg.lower():
                        break  # model retired, try next model in the list
                    raise  # unrelated error (e.g. bad key) — surface immediately
            if key_exhausted:
                break  # stop trying more models on this key; move to next key
        # loop continues to the next available key if this one didn't return
    raise last_error or RuntimeError("Groq: all keys/models failed or exhausted for today.")


# ----------------------------- CEREBRAS PROVIDER -----------------------------
# Cerebras runs open-weight models on its wafer-scale chips — similar speed
# and RPM to Groq (30 req/min free), but a much larger daily token budget.
# Splitting load between the two roughly doubles effective throughput.
# llama-3.3-70b, qwen-3-32b, and llama3.1-8b have all been deprecated on
# Cerebras — gpt-oss-120b and zai-glm-4.7 are the current reliably-live free
# models, so those are listed first/only now instead of models that fail
# immediately on every call.

CEREBRAS_FALLBACK_MODELS = ["gpt-oss-120b", "zai-glm-4.7"]
CEREBRAS_CHAT_MODELS = ["gpt-oss-120b", "zai-glm-4.7"]


def _call_cerebras(prompt: str, max_attempts: int = 3) -> dict:
    from cerebras.cloud.sdk import Cerebras

    all_keys = _collect_keys("CEREBRAS_API_KEY")
    if not all_keys:
        raise RuntimeError("Cerebras API key not configured.")

    last_error = None
    for api_key in _CEREBRAS_KEY_POOL.ordered_available_keys(all_keys):
        client = Cerebras(api_key=api_key)
        key_exhausted = False
        for model_name in CEREBRAS_FALLBACK_MODELS:
            for attempt in range(max_attempts):
                try:
                    completion = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a precise JSON-generating assistant. Always return only valid JSON, no prose, no markdown fences."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                    )
                    raw_text = completion.choices[0].message.content
                    cleaned = _sanitize_json_text(raw_text)
                    return json.loads(cleaned)
                except json.JSONDecodeError as parse_err:
                    last_error = parse_err
                    if attempt < max_attempts - 1:
                        continue
                    break  # try next model
                except Exception as e:
                    msg = str(e)
                    last_error = e
                    if "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
                        if _is_daily_quota_error(msg):
                            _CEREBRAS_KEY_POOL.mark_exhausted(api_key, msg)
                            key_exhausted = True
                            break
                        if attempt < max_attempts - 1:
                            time.sleep(_extract_retry_seconds(msg, attempt))
                            continue
                        break
                    if "404" in msg or "not found" in msg.lower() or "does not exist" in msg.lower():
                        break  # model unavailable, try next model in the list
                    raise
            if key_exhausted:
                break
    raise last_error or RuntimeError("Cerebras: all keys/models failed or exhausted for today.")


def _call_cerebras_text(prompt: str, max_attempts: int = 1) -> str:
    from cerebras.cloud.sdk import Cerebras

    all_keys = _collect_keys("CEREBRAS_API_KEY")
    if not all_keys:
        raise RuntimeError("Cerebras API key not configured.")

    last_error = None
    for api_key in _CEREBRAS_KEY_POOL.ordered_available_keys(all_keys):
        client = Cerebras(api_key=api_key)
        key_exhausted = False
        for model_name in CEREBRAS_CHAT_MODELS:
            for attempt in range(max_attempts):
                try:
                    completion = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a precise, grounded recruiting assistant. Never fabricate information not present in the data you're given. Keep replies concise — a few sentences or short bullet points, not long essays."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.1,
                        max_tokens=500,
                    )
                    return completion.choices[0].message.content.strip()
                except Exception as e:
                    msg = str(e)
                    last_error = e
                    if "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
                        if _is_daily_quota_error(msg):
                            _CEREBRAS_KEY_POOL.mark_exhausted(api_key, msg)
                            key_exhausted = True
                            break
                        # Don't sleep-and-retry the same model — move straight to the next
                        # fallback model/provider instead, so chat replies stay snappy.
                        break
                    if "404" in msg or "not found" in msg.lower() or "does not exist" in msg.lower():
                        break
                    raise
            if key_exhausted:
                break
    raise last_error or RuntimeError("Cerebras: all keys/models failed or exhausted for today.")


# ----------------------------- GEMINI PROVIDER (fallback) -----------------------------

GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash", "gemini-3-flash", "gemini-2.5-flash", "gemini-flash-latest"]


def _call_gemini(prompt: str, max_attempts: int = 3) -> dict:
    from google import genai
    from google.genai import types as genai_types

    all_keys = _collect_keys("GEMINI_API_KEY")
    if not all_keys:
        raise RuntimeError("Gemini API key not configured.")

    last_error = None
    for api_key in _GEMINI_KEY_POOL.ordered_available_keys(all_keys):
        client = genai.Client(api_key=api_key)
        key_exhausted = False
        for model_name in GEMINI_FALLBACK_MODELS:
            for attempt in range(max_attempts):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.2,
                        ),
                    )
                    cleaned = _sanitize_json_text(response.text)
                    return json.loads(cleaned)
                except json.JSONDecodeError as parse_err:
                    last_error = parse_err
                    if attempt < max_attempts - 1:
                        continue
                    break
                except Exception as e:
                    msg = str(e)
                    last_error = e
                    if "429" in msg or "resource_exhausted" in msg.lower() or "quota" in msg.lower():
                        if _is_daily_quota_error(msg):
                            # Daily free-tier cap hit on this key — rotate to
                            # the next configured Gemini key immediately.
                            _GEMINI_KEY_POOL.mark_exhausted(api_key, msg)
                            key_exhausted = True
                            break
                        if attempt < max_attempts - 1:
                            time.sleep(_extract_retry_seconds(msg, attempt))
                            continue
                        break
                    if "404" in msg or "no longer available" in msg.lower() or "not found" in msg.lower():
                        break
                    raise
            if key_exhausted:
                break
    raise last_error or RuntimeError("Gemini: all keys/models failed or exhausted for today.")


# ----------------------------- SHARED RATE LIMITER -----------------------------
# All AI call sites (resume classification, parse+score, chat assistant,
# interview questions) funnel through _call_json / the text callers below.
# When many threads hammer the same provider at once (e.g. a classification
# batch immediately followed by a screening batch), free-tier RPM limits get
# hit and each 429 costs a 15s+ retry sleep on that thread. A shared,
# thread-safe rate limiter smooths request timing across ALL call sites so
# we approach — but don't exceed — each provider's real throughput, avoiding
# 429s (and their retry-sleeps) proactively instead of reacting to them.

class _RateLimiter:
    """Sliding-window limiter: blocks just long enough to keep a provider
    under its per-minute request budget, shared across every thread/caller."""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self._lock = threading.Lock()
        self._timestamps = deque()

    def acquire(self):
        while True:
            with self._lock:
                now = time.time()
                while self._timestamps and now - self._timestamps[0] > 60:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    return
                wait = 60 - (now - self._timestamps[0]) + 0.05
            time.sleep(max(wait, 0.05))


# Kept a couple req/min under the documented free-tier caps (30/min) so we
# stay ahead of the limit rather than bumping into it and paying for 429s.
_GROQ_LIMITER = _RateLimiter(max_per_minute=28)
_CEREBRAS_LIMITER = _RateLimiter(max_per_minute=28)
_GEMINI_LIMITER = _RateLimiter(max_per_minute=14)

# Round-robin (not random) alternation between fast providers — spreads load
# evenly instead of leaving it to chance, which matters once dozens of
# concurrent calls are in flight during a big screening batch.
_provider_cycle_lock = threading.Lock()
_provider_cycle = itertools.cycle([0, 1])


def _next_provider_order(providers: list) -> list:
    if len(providers) < 2:
        return providers
    with _provider_cycle_lock:
        start = next(_provider_cycle)
    return providers[start:] + providers[:start]


class _TokenRateLimiter:
    """Sliding-window limiter for tokens-per-minute (TPM), separate from
    request-count limiting. Some providers (notably Groq's GPT-OSS models,
    capped at 8,000 TPM on the free tier) throttle on token volume, not just
    request count — a handful of large resume-screening prompts can exhaust
    the TPM budget well before the RPM budget is anywhere close. Estimates
    tokens as ~4 characters each, which is close enough for pacing purposes."""

    def __init__(self, max_tokens_per_minute: int):
        self.max_tpm = max_tokens_per_minute
        self._lock = threading.Lock()
        self._entries = deque()  # (timestamp, token_count)

    def acquire(self, estimated_tokens: int):
        while True:
            with self._lock:
                now = time.time()
                while self._entries and now - self._entries[0][0] > 60:
                    self._entries.popleft()
                used = sum(t for _, t in self._entries)
                if used + estimated_tokens <= self.max_tpm:
                    self._entries.append((now, estimated_tokens))
                    return
                # Wait until the oldest entry ages out of the window.
                wait = 60 - (now - self._entries[0][0]) + 0.05 if self._entries else 0.5
            time.sleep(max(wait, 0.05))


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# Groq's GPT-OSS models are capped at 8,000 TPM on the free tier — kept a
# margin under that so screening's large prompts pace themselves instead of
# bursting past the cap and stalling on 429s.
_GROQ_TPM_LIMITER = _TokenRateLimiter(max_tokens_per_minute=7000)


def _limited(fn, limiter: _RateLimiter, prompt: str, tpm_limiter: "_TokenRateLimiter | None" = None):
    if tpm_limiter is not None:
        tpm_limiter.acquire(_estimate_tokens(prompt))
    limiter.acquire()
    return fn(prompt)


# ----------------------------- UNIFIED ENTRY POINT -----------------------------

def _call_json(prompt: str) -> dict:
    """
    Alternate between Groq and Cerebras for each call (whichever are
    configured) — both are fast and free at ~30 req/min, so spreading load
    between them roughly doubles effective throughput and combines their
    daily quotas. A shared rate limiter keeps every concurrent caller
    (classification pass, screening pass, chat assistant, interview-question
    generation) under each provider's real budget so bursts don't trigger
    429s and their costly retry-sleeps. Falls back to Gemini only if the
    fast provider(s) both fail.
    """
    fast_providers = []
    if _get_groq_key():
        fast_providers.append(("Groq", _call_groq, _GROQ_LIMITER, _GROQ_TPM_LIMITER))
    if _get_cerebras_key():
        fast_providers.append(("Cerebras", _call_cerebras, _CEREBRAS_LIMITER, None))
    gemini_key = _get_gemini_key()

    if fast_providers:
        fast_providers = _next_provider_order(fast_providers)
        errors = {}
        for name, fn, limiter, tpm_limiter in fast_providers:
            try:
                return _limited(fn, limiter, prompt, tpm_limiter)
            except Exception as e:
                errors[name] = e
        if gemini_key:
            try:
                return _limited(_call_gemini, _GEMINI_LIMITER, prompt)
            except Exception as gemini_error:
                errors["Gemini"] = gemini_error
        raise RuntimeError(f"All configured providers failed: {errors}")

    if gemini_key:
        return _limited(_call_gemini, _GEMINI_LIMITER, prompt)

    raise RuntimeError("No API key configured. Add GROQ_API_KEY, CEREBRAS_API_KEY, and/or GEMINI_API_KEY.")


# ----------------------------- PROMPTS -----------------------------

def parse_resume_with_ai(raw_text: str) -> dict:
    """
    Extract structured candidate profile fields from raw resume text.
    (Kept standalone for cases where only parsing is needed.)
    """
    prompt = f"""You are a resume parsing engine. Extract structured information from the resume text below.

Return ONLY valid JSON with this exact schema:
{{
  "name": "candidate full name",
  "email": "email or empty string",
  "phone": "phone or empty string",
  "years_experience": "e.g. '3 years' or 'Fresher/Entry-level'",
  "education": "highest degree + institution, one line",
  "skills": ["skill1", "skill2", ...],
  "past_roles": ["role at company", ...],
  "summary": "2-sentence neutral summary of the candidate's background"
}}

Resume text:
---
{raw_text[:8000]}
---
"""
    return _call_json(prompt)


def parse_and_score(raw_text: str, job_description: str) -> tuple[dict, dict]:
    """
    Parse the resume AND score it against the job description in a single
    API call — same reasoning depth as calling parse + score separately,
    just done in one pass instead of two, which roughly halves latency
    per candidate.
    """
    prompt = f"""You are an expert technical recruiter and resume parser. Do TWO things in one pass:

STEP 1 — Extract structured information from the resume.
STEP 2 — Evaluate how well this candidate fits the job description below. Be objective and
evidence-based; judge substance over keywords alone; don't penalize non-traditional resume formats.

JOB DESCRIPTION:
---
{job_description[:2500]}
---

RESUME TEXT:
---
{raw_text[:5000]}
---

Return ONLY valid JSON with this exact schema:
{{
  "profile": {{
    "name": "candidate full name",
    "email": "email or empty string",
    "phone": "phone or empty string",
    "years_experience": "e.g. '3 years' or 'Fresher/Entry-level'",
    "education": "highest degree + institution, one line",
    "skills": ["skill1", "skill2", ...],
    "past_roles": ["role at company", ...],
    "summary": "2-sentence neutral summary of the candidate's background"
  }},
  "score": {{
    "overall_score": <integer 0-100>,
    "breakdown": {{
      "skills_match": <integer 0-100>,
      "experience_fit": <integer 0-100>,
      "education_fit": <integer 0-100>
    }},
    "matched_skills": ["skill that matches JD requirements", ...],
    "gaps": ["missing or weak area relative to JD", ...],
    "summary": "2-3 sentence recruiter-style verdict on this candidate's fit"
  }}
}}
"""
    result = _call_json(prompt)
    return result.get("profile", {}), result.get("score", {})


def score_candidate(profile: dict, raw_text: str, job_description: str) -> dict:
    """
    Score a parsed candidate profile against a job description.
    (Kept standalone for re-scoring an already-parsed candidate against a
    different job description, without re-parsing the resume.)
    """
    prompt = f"""You are an expert technical recruiter. Evaluate how well this candidate fits the job description.
Be objective, evidence-based, and avoid penalizing non-traditional resume formats. Judge substance over keywords alone.

JOB DESCRIPTION:
---
{job_description[:4000]}
---

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

CANDIDATE RESUME (raw, for extra context):
---
{raw_text[:6000]}
---

Return ONLY valid JSON with this exact schema:
{{
  "overall_score": <integer 0-100>,
  "breakdown": {{
    "skills_match": <integer 0-100>,
    "experience_fit": <integer 0-100>,
    "education_fit": <integer 0-100>
  }},
  "matched_skills": ["skill that matches JD requirements", ...],
  "gaps": ["missing or weak area relative to JD", ...],
  "summary": "2-3 sentence recruiter-style verdict on this candidate's fit"
}}
"""
    return _call_json(prompt)


def analyze_ats_ai(raw_text: str, job_description: str) -> dict:
    """
    AI-judged portion of ATS analysis: keyword coverage, grammar quality,
    missing keywords, concrete improvement suggestions, and an overall
    ATS-compatibility verdict. Formatting/Structure/Readability are computed
    separately via free local heuristics (see resume_parser.compute_local_ats_metrics)
    since those are algorithmic, not judgment calls — this call only covers
    the parts that genuinely need language understanding.
    """
    prompt = f"""You are an ATS (Applicant Tracking System) resume analyzer. Evaluate this resume's
text against the job description for keyword coverage and writing quality — the kind of
analysis a tool like Jobscan or an ATS parser would surface to a candidate.

JOB DESCRIPTION:
---
{job_description[:3000]}
---

RESUME TEXT:
---
{raw_text[:6000]}
---

Return ONLY valid JSON with this exact schema:
{{
  "keyword_score": <integer 0-100, how well the resume's terminology covers the JD's key terms>,
  "grammar_score": <integer 0-100, writing quality: clarity, tense consistency, no typos>,
  "missing_keywords": ["important JD term/skill absent from the resume", ...],
  "suggestions": ["concrete, specific improvement suggestion", ...],
  "ats_compatibility": "High" or "Medium" or "Low",
  "compatibility_reason": "one sentence explaining the compatibility verdict"
}}
"""
    return _call_json(prompt)


def is_resume_ai_check(text: str) -> dict:
    """
    Second-pass, AI-based check for whether a document is actually a resume/CV.
    Only called for files that failed the fast local heuristic check — this
    is the "check twice before excluding" safety net, so an unusually
    formatted real resume doesn't get silently dropped.
    """
    prompt = f"""Determine whether the text below is a resume/CV (a document describing a
person's work experience, education, and skills for a job application) or something else
entirely (e.g. a cover letter, certificate, random document, ID card, receipt, unrelated image).

Return ONLY valid JSON with this schema:
{{
  "is_resume": true or false,
  "reason": "one short sentence explaining why"
}}

TEXT (may be partial or OCR'd, so tolerate minor noise):
---
{text[:3000]}
---
"""
    return _call_json(prompt)


def generate_interview_questions(profile: dict, score_data: dict, job_description: str) -> dict:
    """
    Generate role- and candidate-specific interview questions, grouped by
    section, each paired with concrete guidance on what a strong answer
    should cover — so the recruiter has a concrete rubric to evaluate
    against rather than just a bare question.
    """
    prompt = f"""You are preparing an interview guide for a recruiter. Based on the candidate's profile,
their identified gaps, and the job description, generate targeted interview questions.

For EACH question, also provide "what_good_looks_like": concrete, specific points a strong
answer should cover, grounded in the job description and this candidate's actual background
(not generic advice). This is what the recruiter will use to judge the candidate's real answer,
so be specific and evidence-based rather than vague.

JOB DESCRIPTION:
---
{job_description[:3000]}
---

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

IDENTIFIED GAPS:
{json.dumps(score_data.get('gaps', []))}

Return ONLY valid JSON with this exact schema (3-4 items per section):
{{
  "Technical Validation": [
    {{"question": "...", "what_good_looks_like": "specific points a strong answer covers"}}
  ],
  "Experience Deep-Dive": [
    {{"question": "...", "what_good_looks_like": "..."}}
  ],
  "Gap Probing": [
    {{"question": "question targeting an identified gap", "what_good_looks_like": "..."}}
  ],
  "Culture & Motivation": [
    {{"question": "...", "what_good_looks_like": "..."}}
  ]
}}
"""
    return _call_json(prompt)


APP_KNOWLEDGE = """
This is the Intelligent Candidate Discovery Platform — an AI-powered resume screening and
candidate ranking app. Its features:

- Resume Screening: enter a job title + key requirements, set priority weighting (how much
  Skills/Experience/Education matter for ranking), set "Top N" (how many candidates to shortlist),
  then upload resumes as individual files (PDF/DOCX/JPG/PNG, image resumes are read via OCR) or as
  a ZIP folder. Non-resume files (invoices, certificates, random documents) are auto-detected and
  excluded via a two-pass check (a fast local keyword/contact-info check, then an AI confirmation
  before final exclusion) — nothing gets dropped on a single weak signal.
- Home: the command center and landing page. Shows live recruitment stats (resumes uploaded/analyzed,
  shortlisted/selected/rejected counts, interviews pending/completed, candidates awaiting an interview
  decision, active job openings, completed recruitments, average ATS score, hiring success rate), a
  recent activity timeline, and recruitment charts (hiring funnel, score distribution, top skills,
  education mix).
- Resume Screening: also shows a "Top Candidates" section (ranked by priority-weighted score) with
  Select/Reject actions, once resumes have been screened.
- Shortlisted: lists candidates with an ATS score ≥ 70 — and, once they've been interviewed, their
  interview score must also be ≥ 70 to remain on this list.
- Interview: combines interview prep and tracking in one page. The "Prep & Schedule" tab generates
  candidate- and role-specific interview questions in four categories (Technical Validation, Experience
  Deep-Dive, Gap Probing, Culture & Motivation), each with "what a strong answer covers" guidance, and
  lets the recruiter schedule an interview. The candidate picker shows each candidate's ATS score next
  to their name. The "Track Interviews" tab shows scheduled/completed/cancelled interviews; once an
  interview is completed, the recruiter enters an interview score out of 100, which saves immediately
  and also feeds the Shortlisted page's pass/fail check.
- Reports: export candidate, shortlist, and interview data as PDF, Excel, or CSV.
- AI Insights (this chat): answers questions about screened candidates (grounded strictly in
  their actual screening data), explains how to use the app, and can suggest ideas — e.g. how to
  word a job description, what priority weighting suits a given role, what to watch for when
  screening a particular type of role.
"""


def ask_assistant(question: str, candidates: list, job_role: str, job_details: str, chat_history: list) -> str:
    """
    General-purpose assistant for this app. Works in two modes depending on
    whether candidates have been screened yet:

    - With screened candidates: answers are grounded strictly in the actual
      structured data already computed (scores, matched skills, gaps,
      summaries) — never invents facts about a candidate.
    - Without any screened candidates yet (or for questions unrelated to any
      specific candidate): still fully functional — explains how the app
      works, and gives practical recruiting/job-description/weighting ideas.
      It's honest about which mode it's answering in, rather than pretending
      to know things about candidates that don't exist yet.
    """
    candidate_summaries = []
    for c in candidates:
        if c["score"].get("error"):
            continue
        p, s = c["profile"], c["score"]
        candidate_summaries.append({
            "name": c["name"],
            "years_experience": p.get("years_experience"),
            "education": p.get("education"),
            "skills": p.get("skills", []),
            "past_roles": p.get("past_roles", []),
            "overall_score": s.get("overall_score"),
            "breakdown": s.get("breakdown", {}),
            "matched_skills": s.get("matched_skills", []),
            "gaps": s.get("gaps", []),
            "recruiter_summary": s.get("summary"),
        })

    history_text = ""
    for turn in chat_history[-6:]:  # last few turns for context, keep prompt small
        history_text += f"{turn['role'].upper()}: {turn['content']}\n"

    if candidate_summaries:
        data_block = f"""CANDIDATE DATA (the only source of truth for candidate-specific questions — {len(candidate_summaries)} candidate(s) screened this session):
{json.dumps(candidate_summaries, separators=(',', ':'))[:4500]}

JOB ROLE BEING SCREENED FOR: {job_role or '(not set)'}
JOB REQUIREMENTS: {job_details or '(not set)'}"""
    else:
        data_block = (
            "No candidates have been screened yet this session (the CANDIDATE DATA is empty). "
            "If the recruiter asks about a specific candidate, say clearly that nothing has been "
            "screened yet and suggest they use the Resume Screening page first. You can still fully "
            "answer questions about how the app works, or give general recruiting/job-description/"
            "interview ideas."
        )

    prompt = f"""You are the built-in AI Insights assistant for the Intelligent Candidate Discovery Platform.
You help the recruiter in two ways: (1) answering questions about candidates they've screened,
strictly grounded in real data, and (2) answering questions about the app itself, plus offering
practical, concrete ideas (job description wording, priority-weighting suggestions, interview
strategy, what to watch for in a given role) — this second mode does not require any screened data.

APP KNOWLEDGE (use this to answer "how does this work" / "what can this app do" questions):
{APP_KNOWLEDGE}

Rules:
- For candidate-specific questions: answer ONLY using the CANDIDATE DATA below. Never invent
  facts, scores, or skills that aren't present in it. If something isn't covered by the data
  (a skill never mentioned, salary expectations, availability, a candidate not in the list),
  say clearly that this wasn't captured during screening — do not guess or fabricate.
- For app-usage questions: answer from the APP KNOWLEDGE above.
- For open-ended requests ("give me ideas for...", "how should I word...", "what should I ask
  a candidate for X role"): give practical, specific, well-reasoned suggestions — this is
  general recruiting expertise, not something that needs to be "looked up," so answer confidently.
- Keep answers concise, concrete, and recruiter-friendly. Use bullet points for comparisons or lists.

{data_block}

RECENT CONVERSATION:
{history_text}

RECRUITER'S QUESTION:
{question}

Answer now."""

    # This is a free-text answer, not JSON — use a lighter-weight direct call.
    # Shares the same rate limiters as _call_json so the chat assistant
    # doesn't get starved (or itself cause 429s) when a screening batch is
    # in flight on the same provider keys.
    fast_providers = []
    if _get_groq_key():
        fast_providers.append(("Groq", _call_groq_text, _GROQ_LIMITER, _GROQ_TPM_LIMITER))
    if _get_cerebras_key():
        fast_providers.append(("Cerebras", _call_cerebras_text, _CEREBRAS_LIMITER, None))
    gemini_key = _get_gemini_key()

    if fast_providers:
        fast_providers = _next_provider_order(fast_providers)
        last_error = None
        for name, fn, limiter, tpm_limiter in fast_providers:
            try:
                return _limited(fn, limiter, prompt, tpm_limiter)
            except Exception as e:
                last_error = e
        if gemini_key:
            return _limited(_call_gemini_text, _GEMINI_LIMITER, prompt)
        raise last_error
    elif gemini_key:
        return _limited(_call_gemini_text, _GEMINI_LIMITER, prompt)
    raise RuntimeError("No API key configured.")


def _call_groq_text(prompt: str, max_attempts: int = 1) -> str:
    from groq import Groq

    all_keys = _collect_keys("GROQ_API_KEY")
    if not all_keys:
        raise RuntimeError("Groq API key not configured.")

    last_error = None
    for api_key in _GROQ_KEY_POOL.ordered_available_keys(all_keys):
        client = Groq(api_key=api_key)
        key_exhausted = False
        for model_name in GROQ_CHAT_MODELS:
            for attempt in range(max_attempts):
                try:
                    completion = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a precise, grounded recruiting assistant. Never fabricate information not present in the data you're given. Keep replies concise — a few sentences or short bullet points, not long essays."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.1,
                        max_tokens=500,  # keeps replies snappy; concise answers don't need more
                    )
                    return completion.choices[0].message.content.strip()
                except Exception as e:
                    msg = str(e)
                    last_error = e
                    if "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
                        if _is_daily_quota_error(msg):
                            _GROQ_KEY_POOL.mark_exhausted(api_key, msg)
                            key_exhausted = True
                            break
                        # Don't sleep-and-retry the same model — move straight to the next
                        # fallback model/provider instead, so chat replies stay snappy.
                        break
                    if "404" in msg or "decommissioned" in msg.lower() or "not found" in msg.lower():
                        break
                    raise
            if key_exhausted:
                break
    raise last_error or RuntimeError("Groq: all keys/models failed or exhausted for today.")


def _call_gemini_text(prompt: str, max_attempts: int = 1) -> str:
    from google import genai
    from google.genai import types as genai_types

    all_keys = _collect_keys("GEMINI_API_KEY")
    if not all_keys:
        raise RuntimeError("Gemini API key not configured.")

    last_error = None
    for api_key in _GEMINI_KEY_POOL.ordered_available_keys(all_keys):
        client = genai.Client(api_key=api_key)
        key_exhausted = False
        for model_name in GEMINI_FALLBACK_MODELS:
            for attempt in range(max_attempts):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(temperature=0.1),
                    )
                    return response.text.strip()
                except Exception as e:
                    msg = str(e)
                    last_error = e
                    if "429" in msg or "resource_exhausted" in msg.lower() or "quota" in msg.lower():
                        if _is_daily_quota_error(msg):
                            _GEMINI_KEY_POOL.mark_exhausted(api_key, msg)
                            key_exhausted = True
                            break
                        # Don't sleep-and-retry the same model — move straight to the next
                        # fallback model instead, so chat replies stay snappy.
                        break
                    if "404" in msg or "no longer available" in msg.lower() or "not found" in msg.lower():
                        break
                    raise
            if key_exhausted:
                break
    raise last_error or RuntimeError("Gemini: all keys/models failed or exhausted for today.")
