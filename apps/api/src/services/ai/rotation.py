"""
Model Rotation Service — Gemini free-tier 429 fallback.

Automatically rotates through fallback Gemini models when the primary model
returns a RESOURCE_EXHAUSTED (429) rate-limit error. Only activates when the
configured AI provider is Google/Gemini; for all other providers this is a
transparent pass-through.

Usage (drop-in replacement for llm.client.generate / generate_stream):

    from src.services.ai.rotation import generate_with_rotation

    output = await generate_with_rotation(
        model_name="gemini-3.5-flash",
        tier="standard",
        user_prompt="Hello",
        ...
    )
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional, Sequence, Type, Union

from src.services.ai.llm.client import generate, generate_stream
from src.services.ai.model_config import get_rotation_pool, is_gemini_provider

logger = logging.getLogger(__name__)

# Re-export the original types for convenience
UserPrompt = Union[str, Sequence[Any]]


def _is_rate_limit_error(error: Exception) -> bool:
    """Detect 429 / RESOURCE_EXHAUSTED errors across different SDKs.

    Covers:
    - google.genai.errors.ClientError (status 429)
    - Pydantic AI wrapped errors (UnexpectedModelBehavior, ModelHTTPError)
    - Any exception whose message contains rate-limit keywords
    """
    # Check the exception class name (works even if google.genai isn't imported)
    for cls in type(error).__mro__:
        name = cls.__name__
        if name in ("ClientError", "APIError", "RateLimitError"):
            # ClientError is google.genai's base API error — check for 429
            msg = str(error).lower()
            if "429" in msg or "resource_exhausted" in msg:
                return True
            # Fall through to string check below

    # String-based detection (catches wrapped/unknown error types)
    msg = str(error).lower()
    rate_limit_markers = (
        "429",
        "resource_exhausted",
        "resource exhausted",
        "rate limit",
        "rate_limit",
        "quota exceeded",
        "too many requests",
    )
    return any(marker in msg for marker in rate_limit_markers)


async def generate_with_rotation(
    *,
    model_name: str,
    user_prompt: UserPrompt,
    tier: str = "standard",
    system_prompt: Optional[str] = None,
    history: Any = None,
    output_type: Type[Any] = str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Single generation with automatic Gemini model rotation on 429.

    When provider is Google: tries ``model_name`` first, then each Gemini
    fallback in ``get_rotation_pool(model_name, tier)`` until one succeeds
    or all are exhausted.

    When provider is NOT Google: passes through to ``generate()`` directly
    (rotation pool is a single-element list in that case).

    All parameters match ``llm.client.generate()`` exactly, with the addition
    of ``tier`` for pool selection.
    """
    pool = get_rotation_pool(model_name, tier)

    # Fast path: non-Gemini provider → no rotation needed
    if len(pool) == 1:
        return await generate(
            model_name=model_name,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            history=history,
            output_type=output_type,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )

    errors: list[tuple[str, str]] = []
    for i, model in enumerate(pool):
        try:
            if i > 0:
                logger.warning(
                    "Model rotation: %s → %s (attempt %d/%d)",
                    pool[0], model, i + 1, len(pool),
                )
            else:
                logger.debug("Primary model: %s", model)

            kwargs: dict[str, Any] = dict(
                model_name=model,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                history=history,
                output_type=output_type,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if timeout is not None:
                kwargs["timeout"] = timeout

            return await generate(**kwargs)

        except Exception as e:
            if _is_rate_limit_error(e):
                logger.warning(
                    "Rate limit for %s (attempt %d/%d): %s",
                    model, i + 1, len(pool), str(e)[:200],
                )
                errors.append((model, str(e)[:200]))
                continue
            # Non-rate-limit error → don't rotate, raise immediately
            logger.error("Non-rate-limit error for %s: %s", model, str(e)[:200])
            raise

    # All models exhausted
    error_summary = "\n".join(f"  - {m}: {e}" for m, e in errors)
    raise Exception(
        f"All {len(errors)} Gemini models exhausted for tier '{tier}':\n{error_summary}"
    )


async def generate_stream_with_rotation(
    *,
    model_name: str,
    user_prompt: UserPrompt,
    tier: str = "standard",
    system_prompt: Optional[str] = None,
    history: Any = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
) -> AsyncGenerator[str, None]:
    """Streaming generation with automatic Gemini model rotation on 429.

    Same rotation logic as ``generate_with_rotation()`` but for streaming.
    Rate-limit errors during chunk iteration are caught and trigger rotation
    to the next model (the stream is restarted with the fallback model).

    When provider is NOT Google: passes through to ``generate_stream()`` directly.
    """
    pool = get_rotation_pool(model_name, tier)

    # Fast path: non-Gemini provider → no rotation needed
    if len(pool) == 1:
        async for chunk in generate_stream(
            model_name=model_name,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            history=history,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        ):
            yield chunk
        return

    errors: list[tuple[str, str]] = []
    for i, model in enumerate(pool):
        try:
            if i > 0:
                logger.warning(
                    "Stream rotation: %s → %s (attempt %d/%d)",
                    pool[0], model, i + 1, len(pool),
                )
            else:
                logger.debug("Primary stream model: %s", model)

            kwargs: dict[str, Any] = dict(
                model_name=model,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                history=history,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if timeout is not None:
                kwargs["timeout"] = timeout

            async for chunk in generate_stream(**kwargs):
                yield chunk
            return  # Stream completed successfully

        except Exception as e:
            if _is_rate_limit_error(e):
                logger.warning(
                    "Stream rate limit for %s (attempt %d/%d): %s",
                    model, i + 1, len(pool), str(e)[:200],
                )
                errors.append((model, str(e)[:200]))
                continue
            logger.error("Non-rate-limit stream error for %s: %s", model, str(e)[:200])
            raise

    # All models exhausted
    error_summary = "\n".join(f"  - {m}: {e}" for m, e in errors)
    raise Exception(
        f"All {len(errors)} Gemini stream models exhausted for tier '{tier}':\n{error_summary}"
    )
