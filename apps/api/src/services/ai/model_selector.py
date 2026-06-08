"""
Centralized Model Selection Service

Replaces the 4 separate get_org_ai_model() functions across routers with a single
unified selection strategy.
"""

from src.services.ai.model_config import TaskType, get_model_pool


def get_model_for_task(
    task_type: TaskType,
    is_pro: bool = False
) -> str:
    """
    Select the primary model for a task type.
    
    This replaces all hardcoded model strings and the 4 separate get_org_ai_model()
    functions in routers (courseplanning, magicblocks, boards_playground, playgrounds).
    
    Args:
        task_type: Type of task - determines which model pool to use
            - "short_task": Title generation, follow-up suggestions
            - "main_assistant": Activity chat, editor chat, RAG chat
            - "content_generation": Course planning, magicblocks, playgrounds
        is_pro: Whether the organization has a pro/enterprise plan
            (only affects content_generation tasks)
    
    Returns:
        Primary model name (first in rotation pool)
        
    Examples:
        >>> get_model_for_task("short_task")
        "gemini-3.1-flash-lite"
        
        >>> get_model_for_task("main_assistant")
        "gemini-3.5-flash"
        
        >>> get_model_for_task("content_generation", is_pro=False)
        "gemini-3.5-flash"
        
        >>> get_model_for_task("content_generation", is_pro=True)
        "gemma-4-31b-it"
    """
    pool = get_model_pool(task_type, is_pro=is_pro)
    return pool[0]  # Primary model is always first in pool
