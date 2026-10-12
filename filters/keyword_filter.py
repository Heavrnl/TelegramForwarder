import logging
import re
from utils.common import get_sender_info,check_keywords
from filters.base_filter import BaseFilter
from enums.enums import ForwardMode

logger = logging.getLogger(__name__)

class KeywordFilter(BaseFilter):
    """
    Keyword filter — checks whether a message contains specified keywords.
    """

    async def _process(self, context):
        """
        Check whether the message contains the keywords defined in the rule.

        Args:
            context: message context

        Returns:
            bool: True if the message should continue to be processed, False otherwise
        """
        rule = context.rule
        message_text = context.message_text
        event = context.event


        should_forward = await check_keywords(rule, message_text, event)

        return should_forward

