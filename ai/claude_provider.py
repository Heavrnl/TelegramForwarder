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
            raise ValueError("CLAUDE_API_KEY environment variable not set")
            
        # Check for custom API base URL
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
        """Process a message"""
        try:
            if not self.client:
                await self.initialize(**kwargs)
                
            # Build message list
            messages = []
            if prompt:
                messages.append({"role": "system", "content": prompt})
            
            # If images are present, add them to the message
            if images and len(images) > 0:
                # Build content list with images
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
                    logger.info(f"Added image type {img['mime_type']}, ~{len(img['data']) // 1000} KB")
                
                # Add user message
                messages.append({"role": "user", "content": content})
            else:
                # No images, add text only
                messages.append({"role": "user", "content": message})
            
            # Use streaming — per official docs
            with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                messages=messages
            ) as stream:
                # Use text_stream iterator to get text directly
                full_response = ""
                for text in stream.text_stream:
                    full_response += text
        
            return full_response
            
        except Exception as e:
            logger.error(f"Claude API call failed: {str(e)}")
            return f"AI processing failed: {str(e)}" 