from pathlib import Path

path = Path("ai_engine.py")
text = path.read_text(encoding="utf-8")

replacements = {
    "def _call_groq(prompt: str, max_attempts: int = 3) -> dict:":
        "def _call_groq(prompt: str, max_attempts: int = 1) -> dict:",
    "def _call_cerebras(prompt: str, max_attempts: int = 3) -> dict:":
        "def _call_cerebras(prompt: str, max_attempts: int = 1) -> dict:",
    "def _call_gemini(prompt: str, max_attempts: int = 3) -> dict:":
        "def _call_gemini(prompt: str, max_attempts: int = 1) -> dict:",
    'GROQ_FALLBACK_MODELS = [\n    "openai/gpt-oss-120b",\n    "openai/gpt-oss-20b",':
        'GROQ_FALLBACK_MODELS = [\n    "openai/gpt-oss-20b",\n    "openai/gpt-oss-120b",',
}

for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"Expected pattern not found: {old[:80]}")
    text = text.replace(old, new, 1)

# On a per-minute rate limit, do not sleep inside the same provider/model.
# The shared provider dispatcher can immediately try the next configured
# provider, which keeps one blocked key from freezing an entire batch.
old_sleep = """                        if attempt < max_attempts - 1:\n                            time.sleep(_extract_retry_seconds(msg, attempt))\n                            continue\n                        break"""
new_fail_fast = """                        # Fail fast: let _call_json switch provider immediately.\n                        break"""
count = text.count(old_sleep)
if count < 3:
    raise SystemExit(f"Expected at least 3 retry-sleep blocks, found {count}")
text = text.replace(old_sleep, new_fail_fast)

path.write_text(text, encoding="utf-8")
print(f"Applied latency patch; replaced {count} retry-sleep blocks.")
