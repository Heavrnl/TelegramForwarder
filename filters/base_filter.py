import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class BaseFilter(ABC):
    """
    Base filter class, defines the filter interface
    """

    def __init__(self, name=None):
        """
        Initialize filter

        Args:
            name: Filter name, uses class name if None
        """
        self.name = name or self.__class__.__name__

    async def process(self, context):
        """
        Process message context

        Args:
            context: Context object containing all information needed for message processing

        Returns:
            bool: Indicates whether the message should continue processing
        """
        logger.debug(f"Starting filter execution: {self.name}")
        result = await self._process(context)
        logger.debug(f"Filter {self.name} processing result: {'passed' if result else 'not passed'}")
        return result

    @abstractmethod
    async def _process(self, context):
        """
        Actual processing logic, must be implemented by subclasses

        Args:
            context: Context object containing all information needed for message processing

        Returns:
            bool: Indicates whether the message should continue processing
        """
        pass
