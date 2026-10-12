import logging
from filters.base_filter import BaseFilter
from filters.context import MessageContext

logger = logging.getLogger(__name__)

class FilterChain:
    """
    Filter chain — organizes and executes multiple filters in sequence.
    """

    def __init__(self):
        """Initialize the filter chain."""
        self.filters = []

    def add_filter(self, filter_obj):
        """
        Add a filter to the chain.

        Args:
            filter_obj: the filter object to add; must be a subclass of BaseFilter
        """
        if not isinstance(filter_obj, BaseFilter):
            raise TypeError("Filter must be a subclass of BaseFilter")
        self.filters.append(filter_obj)
        return self

    async def process(self, client, event, chat_id, rule):
        """
        Process a message through the filter chain.

        Args:
            client: bot client
            event: message event
            chat_id: chat ID
            rule: forwarding rule

        Returns:
            bool: whether processing succeeded
        """
        # Create the message context
        context = MessageContext(client, event, chat_id, rule)

        logger.info(f"Starting filter chain with {len(self.filters)} filters")

        # Execute each filter in sequence
        for filter_obj in self.filters:
            try:
                should_continue = await filter_obj.process(context)
                if not should_continue:
                    logger.info(f"Filter {filter_obj.name} interrupted the processing chain")
                    return False
            except Exception as e:
                logger.error(f"Filter {filter_obj.name} error: {str(e)}")
                context.errors.append(f"Filter {filter_obj.name} error: {str(e)}")
                return False

        logger.info("Filter chain processing complete")
        return True
