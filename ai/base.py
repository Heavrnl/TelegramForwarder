from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

class BaseAIProvider(ABC):
    """Base class for AI providers"""

    @abstractmethod
    async def process_message(self,
                            message: str,
                            prompt: Optional[str] = None,
                            images: Optional[List[Dict[str, str]]] = None,
                            **kwargs) -> str:
        """
        Abstract method for processing messages

        Args:
            message: The message content to process
            prompt: Optional prompt text
            images: Optional list of images, each image is a dict containing data and mime_type
            **kwargs: Other parameters

        Returns:
            str: The processed message
        """
        pass

    @abstractmethod
    async def initialize(self, **kwargs) -> None:
        """Initialize AI provider"""
        pass