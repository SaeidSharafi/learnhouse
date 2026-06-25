"""
Gemini Free-Tier Model Configuration and Rotation Pools

Defines model rotation pools for Google Gemini's free tier, where multiple models
are available with independent rate limits (RPM/TPM/RPD). When one model exhausts
its quota, rotation switches to the next.

Rotation is Gemini-only — other providers (DeepSeek, Moonshot, OpenRouter, Bedrock)
don't offer free resetable quotas, so rotation is a no-op for them.

Free Model Limits (June 2026):
- Gemini 3.5 Flash:       5 RPM, 250K TPM, 20 RPD
- Gemini 2.5 Flash:       5 RPM, 250K TPM, 20 RPD
- Gemini 3.1 Flash Lite:  15 RPM, 250K TPM, 500 RPD
- Gemma 4 26B:            15 RPM, unlimited TPM, 1.5K RPD
- Gemma 4 31B:            15 RPM, unlimited TPM, 1.5K RPD
- Gemini 2.5 Flash Lite:  10 RPM, 250K TPM, 20 RPD
- Gemini 3 Flash:         5 RPM, 250K TPM, 20 RPD
"""

from dataclasses import dataclass
from typing import Optional

from config.config import get_learnhouse_config


@dataclass(frozen=True)
class ModelMetadata:
    """Metadata for a single model (informational, not used at runtime)."""
    name: str
    rpm: int       # Requests per minute
    tpm: int       # Tokens per minute (0 = unlimited)
    rpd: int       # Requests per day
    description: str


MODEL_REGISTRY: dict[str, ModelMetadata] = {
    "gemini-3.5-flash": ModelMetadata(
        name="gemini-3.5-flash", rpm=5, tpm=250_000, rpd=20,
        description="Latest Flash model — best quality, low limits",
    ),
    "gemini-2.5-flash": ModelMetadata(
        name="gemini-2.5-flash", rpm=5, tpm=250_000, rpd=20,
        description="Stable Flash model — good quality, low limits",
    ),
    "gemini-3-flash": ModelMetadata(
        name="gemini-3-flash", rpm=5, tpm=250_000, rpd=20,
        description="Older Flash model — good quality, low limits",
    ),
    "gemini-3.1-flash-lite": ModelMetadata(
        name="gemini-3.1-flash-lite", rpm=15, tpm=250_000, rpd=500,
        description="Lite model — fast, highest request limits",
    ),
    "gemini-2.5-flash-lite": ModelMetadata(
        name="gemini-2.5-flash-lite", rpm=10, tpm=250_000, rpd=20,
        description="Lite model — fast, medium limits",
    ),
    "gemma-4-26b-a4b-it": ModelMetadata(
        name="gemma-4-26b-a4b-it", rpm=15, tpm=0, rpd=1500,
        description="Open model — good quality, high limits, unlimited tokens",
    ),
    "gemma-4-31b-it": ModelMetadata(
        name="gemma-4-31b-it", rpm=15, tpm=0, rpd=1500,
        description="Open model — best quality, high limits, unlimited tokens",
    ),
}

# ── Rotation pools per tier ──────────────────────────────────────────────
# Ordered by preference: best-quality-first, then fall back to higher-limit
# models. The primary model (from llm/tiers.py) is prepended by the rotation
# wrapper, so these lists are fallback-only.
#
# Tier mapping from upstream llm/tiers.py:
#   fast     → quick tasks (titles, follow-ups, migration)
#   standard → chat, RAG, planning, content generation
#   pro      → advanced planning (Pro+ plans)

GEMINI_FALLBACK_POOLS: dict[str, list[str]] = {
    "fast": [
        "gemini-2.5-flash-lite",
        "gemma-4-26b-a4b-it",
    ],
    "standard": [
        "gemini-2.5-flash",
        "gemma-4-31b-it",
        "gemma-4-26b-a4b-it",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-3-flash",
    ],
    "pro": [
        "gemini-3.5-flash",
        "gemma-4-31b-it",
        "gemini-2.5-flash",
    ],
}

# Provider IDs that identify Google/Gemini as the active AI provider.
# Must match the aliases in llm/provider.py.
_GEMINI_PROVIDER_IDS = frozenset({"google", "google-gla", "gemini"})


def is_gemini_provider() -> bool:
    """Return True if the currently configured AI provider is Google/Gemini."""
    try:
        cfg = get_learnhouse_config().ai_config
        provider = (getattr(cfg, "provider", None) or "").strip().lower()
        return provider in _GEMINI_PROVIDER_IDS or not provider  # unset → Google default
    except Exception:
        return False


def get_rotation_pool(model_name: str, tier: str = "standard") -> list[str]:
    """Build the full rotation pool: primary model + Gemini fallbacks (deduped).

    When the provider is NOT Gemini this returns a single-element list, so
    rotation is effectively a no-op.
    """
    if not is_gemini_provider():
        return [model_name]

    fallbacks = GEMINI_FALLBACK_POOLS.get(tier, [])
    seen = {model_name}
    pool = [model_name]
    for m in fallbacks:
        if m not in seen:
            seen.add(m)
            pool.append(m)
    return pool
