"""
Model Rotation Service for handling 429 RESOURCE_EXHAUSTED errors

Automatically rotates through fallback models when rate limits are hit.
"""

import logging
from typing import Any, Callable, TypeVar, cast
from google import genai
from google.genai.errors import ClientError

from src.services.ai.model_config import TaskType, get_model_pool

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ModelRotationService:
    """
    Wraps Gemini API calls with automatic model rotation on 429 errors.
    
    When a model returns RESOURCE_EXHAUSTED (429), automatically retries
    with the next model in the pool for that task type.
    """
    
    @staticmethod
    def call_with_rotation(
        task_type: TaskType,
        is_pro: bool,
        call_fn: Callable[[str], T],
        max_attempts: int | None = None
    ) -> T:
        """
        Execute a Gemini API call with automatic model rotation on 429.
        
        Args:
            task_type: Type of task (determines model pool)
            is_pro: Whether organization has pro plan
            call_fn: Function that takes model name and makes the API call
            max_attempts: Max models to try (None = try all in pool)
            
        Returns:
            Result from successful API call
            
        Raises:
            Exception: If all models in pool fail
            
        Example:
            def make_call(model: str):
                return client.models.generate_content(
                    model=model,
                    contents=[{"role": "user", "parts": [{"text": prompt}]}]
                )
            
            result = ModelRotationService.call_with_rotation(
                task_type="main_assistant",
                is_pro=False,
                call_fn=make_call
            )
        """
        model_pool = get_model_pool(task_type, is_pro=is_pro)
        attempts_limit = max_attempts if max_attempts is not None else len(model_pool)
        
        errors: list[tuple[str, Exception]] = []
        
        for i, model_name in enumerate(model_pool[:attempts_limit]):
            try:
                logger.info(f"Attempting API call with model: {model_name} (attempt {i+1}/{attempts_limit})")
                result = call_fn(model_name)
                
                # Log rotation success if not first model
                if i > 0:
                    logger.warning(
                        f"Model rotation successful: {model_pool[0]} -> {model_name} "
                        f"after {i} failed attempts"
                    )
                
                return result
                
            except ClientError as e:
                # Check if it's a 429 RESOURCE_EXHAUSTED error
                error_str = str(e).lower()
                is_429 = (
                    "429" in error_str or 
                    "resource_exhausted" in error_str or
                    "quota" in error_str or
                    "rate limit" in error_str
                )
                
                if is_429:
                    logger.warning(
                        f"Rate limit hit for {model_name}: {str(e)[:200]}. "
                        f"Rotating to next model..."
                    )
                    errors.append((model_name, e))
                    
                    # If this is the last model, raise with full error context
                    if i >= attempts_limit - 1:
                        error_summary = "\n".join([
                            f"  - {model}: {str(err)[:100]}"
                            for model, err in errors
                        ])
                        raise Exception(
                            f"All {len(errors)} models exhausted for {task_type}:\n{error_summary}"
                        ) from e
                    
                    # Continue to next model
                    continue
                else:
                    # Non-429 error - don't rotate, just raise
                    logger.error(f"Non-rate-limit error for {model_name}: {str(e)[:200]}")
                    raise
                    
            except Exception as e:
                # Non-ClientError exceptions (network, auth, etc.) - don't rotate
                logger.error(f"Unexpected error for {model_name}: {str(e)[:200]}")
                raise
        
        # Should never reach here, but just in case
        raise Exception(f"Model rotation failed for {task_type} with no attempts made")
    
    @staticmethod
    def call_with_rotation_stream(
        task_type: TaskType,
        is_pro: bool,
        call_fn: Callable[[str], Any],
        max_attempts: int | None = None
    ) -> Any:
        """
        Execute a streaming Gemini API call with automatic model rotation on 429.
        
        IMPORTANT: For streaming APIs, errors can occur during iteration, not just during
        the initial call. This method returns an iterator wrapper that handles rotation
        during iteration.
        
        Args:
            task_type: Type of task (determines model pool)
            is_pro: Whether organization has pro plan
            call_fn: Function that takes model name and returns a stream iterator
            max_attempts: Max models to try (None = try all in pool)
            
        Returns:
            Stream iterator wrapper with automatic rotation on 429
            
        Raises:
            Exception: If all models in pool fail
        """
        model_pool = get_model_pool(task_type, is_pro=is_pro)
        attempts_limit = max_attempts if max_attempts is not None else len(model_pool)
        
        def streaming_iterator_with_rotation():
            """Generator that wraps the stream and handles 429 during iteration"""
            errors: list[tuple[str, Exception]] = []
            
            for i, model_name in enumerate(model_pool[:attempts_limit]):
                try:
                    logger.info(f"Attempting streaming API call with model: {model_name} (attempt {i+1}/{attempts_limit})")
                    stream = call_fn(model_name)
                    
                    if i > 0:
                        logger.warning(
                            f"Model rotation successful for streaming: {model_pool[0]} -> {model_name} "
                            f"after {i} failed attempts"
                        )
                    
                    for chunk in stream:
                        yield chunk
                    
                    return
                    
                except ClientError as e:
                    error_str = str(e).lower()
                    is_429 = (
                        "429" in error_str or 
                        "resource_exhausted" in error_str or
                        "quota" in error_str or
                        "rate limit" in error_str
                    )
                    
                    if is_429:
                        logger.warning(
                            f"Rate limit hit for streaming {model_name} during iteration: {str(e)[:200]}. "
                            f"Rotating to next model..."
                        )
                        errors.append((model_name, e))
                        
                        if i >= attempts_limit - 1:
                            error_summary = "\n".join([
                                f"  - {model}: {str(err)[:100]}"
                                for model, err in errors
                            ])
                            raise Exception(
                                f"All {len(errors)} models exhausted for {task_type} streaming:\n{error_summary}"
                            ) from e
                        
                        continue
                    else:
                        logger.error(f"Non-rate-limit error for streaming {model_name}: {str(e)[:200]}")
                        raise
                        
                except Exception as e:
                    logger.error(f"Unexpected error for streaming {model_name}: {str(e)[:200]}")
                    raise
            
            raise Exception(f"Model rotation failed for {task_type} streaming with no attempts made")
        
        return streaming_iterator_with_rotation()
