from .base import BaseAIProvider
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider
from .deepseek_provider import DeepSeekProvider
from .qwen_provider import QwenProvider
from .grok_provider import GrokProvider
from .claude_provider import ClaudeProvider
import os
import logging
from utils.settings import load_ai_models
from utils.constants import DEFAULT_AI_MODEL

# Get logger
logger = logging.getLogger(__name__)

async def get_ai_provider(model=None):
    """Get an AI provider instance"""
    if not model:
        model = DEFAULT_AI_MODEL
    
    # Load provider config (dict format)
    providers_config = load_ai_models(type="dict")
    
    # Select provider based on model name
    provider = None
    
    # Iterate over all providers in config
    for provider_name, models_list in providers_config.items():
        # Check for exact match
        if model in models_list:
            if provider_name == "openai":
                provider = OpenAIProvider()
            elif provider_name == "gemini":
                provider = GeminiProvider()
            elif provider_name == "deepseek":
                provider = DeepSeekProvider()
            elif provider_name == "qwen":
                provider = QwenProvider()
            elif provider_name == "grok":
                provider = GrokProvider()
            elif provider_name == "claude":
                provider = ClaudeProvider()
            break
    
    if not provider:
        raise ValueError(f"Unsupported model: {model}")

    return provider


__all__ = [
    'BaseAIProvider',
    'OpenAIProvider',
    'GeminiProvider',
    'DeepSeekProvider',
    'QwenProvider',
    'GrokProvider',
    'ClaudeProvider',
    'get_ai_provider'
]