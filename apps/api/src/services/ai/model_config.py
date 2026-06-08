"""
Gemini Model Configuration and Rotation Pools

Defines model pools for different task types with rotation order based on:
- Rate limits (RPM/TPM/RPD) from Gemini Free tier
- Model capabilities (quality/speed tradeoff)
- Task complexity requirements

Free Model Limits:
- Gemini 3.5 Flash: 5 RPM, 250K TPM, 20 RPD
- Gemini 2.5 Flash: 5 RPM, 250K TPM, 20 RPD
- Gemini 3.1 Flash Lite: 15 RPM, 250K TPM, 500 RPD
- Gemma 4 26B: 15 RPM, unlimited TPM, 1.5K RPD
- Gemma 4 31B: 15 RPM, unlimited TPM, 1.5K RPD
- Gemini 2.5 Flash Lite: 10 RPM, 250K TPM, 20 RPD
- Gemini 3 Flash: 5 RPM, 250K TPM, 20 RPD
"""

from dataclasses import dataclass
from typing import Literal

TaskType = Literal["short_task", "main_assistant", "content_generation"]


@dataclass(frozen=True)
class ModelMetadata:
    """Metadata for a single model"""
    name: str
    rpm: int  # Requests per minute
    tpm: int  # Tokens per minute (0 = unlimited)
    rpd: int  # Requests per day
    description: str


# Model metadata registry
MODEL_REGISTRY: dict[str, ModelMetadata] = {
    "gemini-3.5-flash": ModelMetadata(
        name="gemini-3.5-flash",
        rpm=5,
        tpm=250_000,
        rpd=20,
        description="Latest Flash model - best quality, low limits"
    ),
    "gemini-2.5-flash": ModelMetadata(
        name="gemini-2.5-flash",
        rpm=5,
        tpm=250_000,
        rpd=20,
        description="Stable Flash model - good quality, low limits"
    ),
    "gemini-3-flash": ModelMetadata(
        name="gemini-3-flash",
        rpm=5,
        tpm=250_000,
        rpd=20,
        description="Older Flash model - good quality, low limits"
    ),
    "gemini-3.1-flash-lite": ModelMetadata(
        name="gemini-3.1-flash-lite",
        rpm=15,
        tpm=250_000,
        rpd=500,
        description="Lite model - fast, highest request limits"
    ),
    "gemini-2.5-flash-lite": ModelMetadata(
        name="gemini-2.5-flash-lite",
        rpm=10,
        tpm=250_000,
        rpd=20,
        description="Lite model - fast, medium limits"
    ),
    "gemma-4-26b-a4b-it": ModelMetadata(
        name="gemma-4-26b-a4b-it-a4b-it",
        rpm=15,
        tpm=0,  # unlimited
        rpd=1500,
        description="Open model - good quality, high limits, unlimited tokens"
    ),
    "gemma-4-31b-it": ModelMetadata(
        name="gemma-4-31b-it",
        rpm=15,
        tpm=0,  # unlimited
        rpd=1500,
        description="Open model - best quality, high limits, unlimited tokens"
    ),
}


# Model pools for each task type (ordered by preference for rotation)
# First model = primary, subsequent = fallbacks on 429

# Short tasks: title generation, follow-up suggestions
# Need: high frequency, low latency, cheapest
# Strategy: Use lite models with highest RPM/RPD limits
SHORT_TASK_MODELS = [
    "gemini-3.1-flash-lite",  # 15 RPM, 500 RPD - highest limits
    "gemini-2.5-flash-lite",  # 10 RPM, 20 RPD
    "gemma-4-26b-a4b-it",            # 15 RPM, 1.5K RPD, unlimited tokens
]

# Main assistant: activity chat, editor chat, RAG chat
# Need: good quality, medium frequency
# Strategy: Use Flash models (better quality than lite), rotate through all available
MAIN_ASSISTANT_MODELS = [
    "gemini-3.5-flash",  # Newest, best quality
    "gemini-2.5-flash",  # Stable
    "gemini-3-flash",    # Older but works
    "gemma-4-31b-it",       # Highest quality open model (fallback)
]

# Content generation: course planning, magicblocks, playgrounds
# Need: highest quality, low frequency, can handle long outputs
# Strategy: Use models with unlimited tokens or highest quality, considering plan tier
CONTENT_GEN_MODELS_FREE = [
    "gemini-3.5-flash",  # Best quality for free tier
    "gemini-2.5-flash",  # Stable fallback
    "gemma-4-31b-it",       # Unlimited tokens, high quality
    "gemma-4-26b-a4b-it",       # Unlimited tokens
]

# Pro tier gets access to better models first (currently just reordered)
# Note: The actual "pro" models like gemini-2.5-pro are NOT in free tier
# So we use the best free models for pro users
CONTENT_GEN_MODELS_PRO = [
    "gemini-3.5-flash",  # Latest Flash
    "gemini-2.5-flash",  # Stable
    "gemma-4-31b-it",       # Best free model with unlimited tokens
    "gemma-4-26b-a4b-it",       # Fallback
]


def get_model_pool(task_type: TaskType, is_pro: bool = False) -> list[str]:
    """
    Get ordered model pool for a task type.
    
    Args:
        task_type: Type of task (short_task, main_assistant, content_generation)
        is_pro: Whether organization has pro plan (affects content_generation only)
        
    Returns:
        Ordered list of model names (first = primary, rest = fallbacks)
    """
    if task_type == "short_task":
        return SHORT_TASK_MODELS.copy()
    elif task_type == "main_assistant":
        return MAIN_ASSISTANT_MODELS.copy()
    elif task_type == "content_generation":
        return CONTENT_GEN_MODELS_PRO.copy() if is_pro else CONTENT_GEN_MODELS_FREE.copy()
    else:
        raise ValueError(f"Unknown task type: {task_type}")


def get_model_metadata(model_name: str) -> ModelMetadata:
    """Get metadata for a model by name"""
    if model_name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model: {model_name}")
    return MODEL_REGISTRY[model_name]
