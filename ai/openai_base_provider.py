from typing import Optional, List, Dict
from openai import AsyncOpenAI
from .base import BaseAIProvider
import os
import logging

logger = logging.getLogger(__name__)

class OpenAIBaseProvider(BaseAIProvider):
    def __init__(self, env_prefix: str = 'OPENAI', default_model: str = 'gpt-4o-mini',
                 default_api_base: str = 'https://api.openai.com/v1'):
        """
        Initialize base OpenAI-format provider

        Args:
            env_prefix: Environment variable prefix, e.g. 'OPENAI', 'GROK', 'DEEPSEEK', 'QWEN'
            default_model: Default model name
            default_api_base: Default API base URL
        """
        super().__init__()
        self.env_prefix = env_prefix
        self.default_model = default_model
        self.default_api_base = default_api_base
        self.client = None
        self.model = None

    async def initialize(self, **kwargs) -> None:
        """Initialize OpenAI client"""
        try:
            api_key = os.getenv(f'{self.env_prefix}_API_KEY')
            if not api_key:
                raise ValueError(f"{self.env_prefix}_API_KEY environment variable is not set")

            api_base = os.getenv(f'{self.env_prefix}_API_BASE', '').strip() or self.default_api_base

            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=api_base
            )

            self.model = kwargs.get('model', self.default_model)
            logger.info(f"Initializing OpenAI model: {self.model}")

        except Exception as e:
            error_msg = f"Error initializing {self.env_prefix} client: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise

    async def process_message(self,
                            message: str,
                            prompt: Optional[str] = None,
                            images: Optional[List[Dict[str, str]]] = None,
                            **kwargs) -> str:
        """Process message"""
        try:
            if not self.client:
                await self.initialize(**kwargs)

            messages = []
            if prompt:
                messages.append({"role": "system", "content": prompt})

            # If there are images, add them to the message
            if images and len(images) > 0:
                # Create content array containing text and images
                content = []

                # Add text
                content.append({
                    "type": "text",
                    "text": message
                })

                # Add each image
                for img in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['mime_type']};base64,{img['data']}"
                        }
                    })
                    logger.info(f"Added an image of type {img['mime_type']}, size approximately {len(img['data']) // 1000} KB")

                messages.append({"role": "user", "content": content})
            else:
                # No images, only add text
                messages.append({"role": "user", "content": message})

            logger.info(f"Actual OpenAI model in use: {self.model}")

            # All models use streaming calls uniformly
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True
            )

            # Collect all content
            collected_content = ""
            collected_reasoning = ""

            async for chunk in completion:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # Process thinking content (if present)
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content is not None:
                    collected_reasoning += delta.reasoning_content

                # Process response content
                if hasattr(delta, 'content') and delta.content is not None:
                    collected_content += delta.content

            # If no content but has thinking process, the thinking model may have only returned the thinking process
            if not collected_content and collected_reasoning:
                logger.warning("Model only returned thinking process, no final answer")
                return "Model failed to generate a valid answer"

            return collected_content

        except Exception as e:
            logger.error(f"{self.env_prefix} API call failed: {str(e)}", exc_info=True)
            return f"AI processing failed: {str(e)}"
