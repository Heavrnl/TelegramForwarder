import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class BaseFilter(ABC):
    """
    Base filter class — defines the filter interface.
    """

    def __init__(self, name=None):
        """
        Initialize the filter.

        Args:
            name: filter name; defaults to the class name if None
        """
        self.name = name or self.__class__.__name__

    async def process(self, context):
        """
        Process the message context.

        Args:
            context: context object containing all information needed to process the message

        Returns:
            bool: whether processing should continue
        """
        logger.debug(f"Starting filter: {self.name}")
        result = await self._process(context)
        logger.debug(f"Filter {self.name} result: {'pass' if result else 'reject'}")
        return result

    @abstractmethod
    async def _process(self, context):
        """
        Concrete processing logic — must be implemented by subclasses.

        Args:
            context: context object containing all information needed to process the message

        Returns:
            bool: whether processing should continue
        """
        pass
