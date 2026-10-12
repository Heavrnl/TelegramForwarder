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
        Abstract method for processing a message
        
        Args:
            message: the message content to process
            prompt: optional prompt
            images: optional list of images, each a dict with data and mime_type
            **kwargs: additional arguments
            
        Returns:
            str: the processed message
        """
        pass
    
    @abstractmethod
    async def initialize(self, **kwargs) -> None:
        """Initialize the AI provider"""
        pass