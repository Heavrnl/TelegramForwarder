from typing import Optional, List, Dict
import anthropic
from .base import BaseAIProvider
import os
import logging

logger = logging.getLogger(__name__)

class ClaudeProvider(BaseAIProvider):
    def __init__(self):
        self.client = None
        self.model = None
        self.default_model = 'claude-3-5-sonnet-latest'

    async def initialize(self, **kwargs):
        """Initialize Claude client"""
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError("CLAUDE_API_KEY environment variable is not set")

        # Check if a custom API base URL is configured
        api_base = os.getenv('CLAUDE_API_BASE', '').strip()
        if api_base:
            logger.info(f"Using custom Claude API base URL: {api_base}")
            self.client = anthropic.Anthropic(
                api_key=api_key,
                base_url=api_base
            )
        else:
            # Use default URL
            self.client = anthropic.Anthropic(api_key=api_key)

        self.model = kwargs.get('model', self.default_model)

    async def process_message(self,
                            message: str,
                            prompt: Optional[str] = None,
                            images: Optional[List[Dict[str, str]]] = None,
                            **kwargs) -> str:
        """Process message"""
        try:
            if not self.client:
                await self.initialize(**kwargs)

            # Build message list
            messages = []
            if prompt:
                messages.append({"role": "system", "content": prompt})

            # If there are images, add them to the message
            if images and len(images) > 0:
                # Build content list containing images
                content = []

                # Add text
                content.append({
                    "type": "text",
                    "text": message
                })

                # Add each image
                for img in images:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img["mime_type"],
                            "data": img["data"]
                        }
                    })
                    logger.info(f"Added an image of type {img['mime_type']}, size approximately {len(img['data']) // 1000} KB")

                # Add user message
                messages.append({"role": "user", "content": content})
            else:
                # No images, only add text
                messages.append({"role": "user", "content": message})

            # Use streaming output - correctly implemented per official documentation
            with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                messages=messages
            ) as stream:
                # Use dedicated text_stream iterator to directly get text
                full_response = ""
                for text in stream.text_stream:
                    full_response += text

            return full_response

        except Exception as e:
            logger.error(f"Claude API call failed: {str(e)}")
            return f"AI processing failed: {str(e)}"
