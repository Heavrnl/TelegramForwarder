import logging
from filters.base_filter import BaseFilter
from filters.context import MessageContext

logger = logging.getLogger(__name__)

class FilterChain:
    """
    Filter chain, used to organize and execute multiple filters
    """

    def __init__(self):
        """Initialize filter chain"""
        self.filters = []

    def add_filter(self, filter_obj):
        """
        Add a filter to the chain

        Args:
            filter_obj: Filter object to add, must be a subclass of BaseFilter
        """
        if not isinstance(filter_obj, BaseFilter):
            raise TypeError("Filter must be a subclass of BaseFilter")
        self.filters.append(filter_obj)
        return self

    async def process(self, client, event, chat_id, rule):
        """
        Process message

        Args:
            client: Bot client
            event: Message event
            chat_id: Chat ID
            rule: Forwarding rule

        Returns:
            bool: Indicates whether processing was successful
        """
        # Create message context
        context = MessageContext(client, event, chat_id, rule)

        logger.info(f"Starting filter chain processing, total {len(self.filters)} filters")

        # Execute each filter in sequence
        for filter_obj in self.filters:
            try:
                should_continue = await filter_obj.process(context)
                if not should_continue:
                    logger.info(f"Filter {filter_obj.name} interrupted the processing chain")
                    return False
            except Exception as e:
                logger.error(f"Filter {filter_obj.name} processing error: {str(e)}")
                context.errors.append(f"Filter {filter_obj.name} error: {str(e)}")
                return False

        logger.info("Filter chain processing completed")
        return True
