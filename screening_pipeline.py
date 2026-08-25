"""Pure helpers for fast, deterministic resume-screening orchestration."""

from __future__ import annotations

import copy
import hashlib
import os


def content_hash(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def job_description_hash(job_description: str) -> str:
    normalized = "\n".join(line.rstrip() for line in job_description.strip().splitlines())
    return content_hash(normalized)


def cache_key(resume_hash: str, jd_hash: str) -> str:
    return f"{resume_hash}:{jd_hash}"


def worker_count(item_count: int) -> int:
    """Default to three workers and never exceed five, even if misconfigured."""
    try:
        configured = int(os.environ.get("SCREENING_MAX_WORKERS", "3"))
    except (TypeError, ValueError):
        configured = 3
    return min(max(1, item_count), max(1, min(configured, 5)))


def cached_ai_result(candidate: dict) -> tuple[dict, dict] | None:
    """Return a copy of the reusable, pre-weighting AI result."""
    profile = candidate.get("profile") or {}
    score = candidate.get("score") or {}
    if not profile or not score or score.get("error"):
        return None
    reusable_score = copy.deepcopy(score)
    reusable_score["overall_score"] = reusable_score.get(
        "ai_overall_score", reusable_score.get("overall_score", 0)
    )
    return copy.deepcopy(profile), reusable_score
