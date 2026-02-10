from typing import Optional, List, Dict
import google.generativeai as genai
# Remove import of non-existent module
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
            default_api_base=''  # API_BASE must be provided in environment variables
        )

class GeminiProvider(BaseAIProvider):
    def __init__(self):
        self.model = None
        self.model_name = None  # Add model_name attribute
        self.provider = None

    async def initialize(self, **kwargs):
        """Initialize Gemini client"""
        # Check if GEMINI_API_BASE is configured, if so use OpenAI-compatible interface
        api_base = os.getenv('GEMINI_API_BASE', '').strip()

        if api_base:
            logger.info(f"Detected GEMINI_API_BASE environment variable: {api_base}, using OpenAI-compatible interface")
            self.provider = GeminiOpenAIProvider()
            await self.provider.initialize(**kwargs)
            return

        # Original Gemini API initialization code
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")

        # Use the passed model parameter, only use default if not provided
        if not self.model_name:  # If model_name is not set yet
            self.model_name = kwargs.get('model')

        if not self.model_name:  # If model is not in kwargs either
            self.model_name = 'gemini-pro'  # Only then use default value

        logger.info(f"Initializing Gemini model: {self.model_name}")

        # Configure safety settings - only use basic categories
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
        """Process message"""
        try:
            if not self.provider and not self.model:
                await self.initialize(**kwargs)

            # If using OpenAI-compatible interface, call its processing method
            if self.provider:
                return await self.provider.process_message(message, prompt, images, **kwargs)

            # Stream processing using Gemini API
            logger.info(f"Actual Gemini model in use: {self.model_name}")

            # Combine prompt and message
            if prompt:
                user_message = f"{prompt}\n\n{message}"
            else:
                user_message = message

            # Check if there are images
            if images and len(images) > 0:
                try:
                    # Use MultimodalContent to add images
                    contents = []
                    # Add text
                    contents.append({"role": "user", "parts": [{"text": user_message}]})

                    # Process each image
                    for img in images:
                        try:
                            # Directly add image bytes to model input
                            image_part = {
                                "inline_data": {
                                    "mime_type": img["mime_type"],
                                    "data": img["data"]  # Use original base64 data
                                }
                            }
                            contents[0]["parts"].append(image_part)
                            logger.info(f"Added an image of type {img['mime_type']}, size approximately {len(img['data']) // 1000} KB")
                        except Exception as img_error:
                            logger.error(f"Error processing a single image: {str(img_error)}")

                    # Use streaming output - no extra parameters, use defaults
                    response_stream = self.model.generate_content(
                        contents,
                        stream=True
                    )
                except Exception as e:
                    logger.error(f"Error processing message with images in Gemini: {str(e)}")
                    # If image processing fails, try with text only
                    response_stream = self.model.generate_content(
                        [{"role": "user", "parts": [{"text": user_message}]}],
                        stream=True
                    )
            else:
                # No images, use streaming output
                response_stream = self.model.generate_content(
                    [{"role": "user", "parts": [{"text": user_message}]}],
                    stream=True
                )

            # Collect complete response
            full_response = ""
            for chunk in response_stream:
                if hasattr(chunk, 'text'):
                    full_response += chunk.text

            return full_response

        except Exception as e:
            logger.error(f"Error processing message in Gemini: {str(e)}")
            return f"AI processing failed: {str(e)}"
