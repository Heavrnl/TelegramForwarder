import logging
import re
from utils.common import get_sender_info,check_keywords
from filters.base_filter import BaseFilter
from enums.enums import ForwardMode

logger = logging.getLogger(__name__)

class KeywordFilter(BaseFilter):
    """
    Keyword filter, checks if a message contains specified keywords
    """

    async def _process(self, context):
        """
        Check if the message contains keywords from the rule

        Args:
            context: Message context

        Returns:
            bool: Returns True if the message should continue processing, False otherwise
        """
        rule = context.rule
        message_text = context.message_text
        event = context.event


        should_forward = await check_keywords(rule, message_text, event)

        return should_forward
