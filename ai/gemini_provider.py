from typing import Optional, List, Dict
import google.generativeai as genai
# Remove import for non-existent module
# from google.genai import types
from .base import BaseAIProvider
from .openai_base_provider import OpenAIBaseProvider
import os
import logging
import base64

logger = logging.getLogger(__name__)

class GeminiOpenAIProvider(OpenAIBaseProvider):
    """Gemini provider using OpenAI-compatible interface"""
    def __init__(self):
        super().__init__(
            env_prefix='GEMINI',
            default_model='gemini-pro',
            default_api_base=''  # API_BASE must be set in environment variables
        )

class GeminiProvider(BaseAIProvider):
    def __init__(self):
        self.model = None
        self.model_name = None  # model_name attribute
        self.provider = None
        
    async def initialize(self, **kwargs):
        """Initialize Gemini client"""
        # Check for GEMINI_API_BASE; if set, use OpenAI-compatible interface
        api_base = os.getenv('GEMINI_API_BASE', '').strip()
        
        if api_base:
            logger.info(f"GEMINI_API_BASE detected: {api_base}, using OpenAI-compatible interface")
            self.provider = GeminiOpenAIProvider()
            await self.provider.initialize(**kwargs)
            return
            
        # Native Gemini API initialization
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        # Use provided model param, fall back to default if not given
        if not self.model_name:  # If model_name not yet set
            self.model_name = kwargs.get('model')

        if not self.model_name:  # If kwargs also has no model
            self.model_name = 'gemini-pro'  # Final fallback default

        logger.info(f"Initialized Gemini model: {self.model_name}")

        # Configure safety settings — basic categories only
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
            
        genai.configure(api_key=api_key)
        # Initialize model using self.model_name
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            safety_settings=safety_settings
        )
        
    async def process_message(self, 
                            message: str, 
                            prompt: Optional[str] = None,
                            images: Optional[List[Dict[str, str]]] = None,
                            **kwargs) -> str:
        """Process a message"""
        try:
            if not self.provider and not self.model:
                await self.initialize(**kwargs)
            
            # If using OpenAI-compatible interface, delegate to that handler
            if self.provider:
                return await self.provider.process_message(message, prompt, images, **kwargs)
                
            # Use Gemini API streaming
            logger.info(f"Using Gemini model: {self.model_name}")

            # Combine prompt and message
            if prompt:
                user_message = f"{prompt}\n\n{message}"
            else:
                user_message = message
            
            # Check for images
            if images and len(images) > 0:
                try:
                    # Add images using MultimodalContent
                    contents = []
                    # Add text
                    contents.append({"role": "user", "parts": [{"text": user_message}]})
                    
                    # Process each image
                    for img in images:
                        try:
                            # Add raw image bytes to model input
                            image_part = {
                                "inline_data": {
                                    "mime_type": img["mime_type"],
                                    "data": img["data"]  # Use raw base64 data
                                }
                            }
                            contents[0]["parts"].append(image_part)
                            logger.info(f"Added image type {img['mime_type']}, ~{len(img['data']) // 1000} KB")
                        except Exception as img_error:
                            logger.error(f"Error processing image: {str(img_error)}")
                    
                    # Use streaming with default parameters
                    response_stream = self.model.generate_content(
                        contents,
                        stream=True
                    )
                except Exception as e:
                    logger.error(f"Gemini error processing message with images: {str(e)}")
                    # If image processing failed, retry with text only
                    response_stream = self.model.generate_content(
                        [{"role": "user", "parts": [{"text": user_message}]}],
                        stream=True
                    )
            else:
                # No images, use streaming
                response_stream = self.model.generate_content(
                    [{"role": "user", "parts": [{"text": user_message}]}],
                    stream=True
                )
            
            # Collect full response
            full_response = ""
            for chunk in response_stream:
                if hasattr(chunk, 'text'):
                    full_response += chunk.text
            
            return full_response
            
        except Exception as e:
            logger.error(f"Gemini error processing message: {str(e)}")
            return f"AI processing failed: {str(e)}" 