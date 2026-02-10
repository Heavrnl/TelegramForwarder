import logging
import os
import pytz
import asyncio
from utils.constants import TEMP_DIR
from utils.media import get_max_media_size

from filters.base_filter import BaseFilter

logger = logging.getLogger(__name__)

class InitFilter(BaseFilter):
    """
    Initialization filter, adds basic information to context
    """

    async def _process(self, context):
        """
        Add original link and sender information

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        event = context.event

        # logger.info(f"Before InitFilter processing, context: {context.__dict__}")
        try:
            # Process media group messages
            if event.message.grouped_id:
                # Wait longer for all media messages to arrive
                # await asyncio.sleep(1)

                # Collect all messages in the media group
                try:
                    async for message in event.client.iter_messages(
                        event.chat_id,
                        limit=20,
                        min_id=event.message.id - 10,
                        max_id=event.message.id + 10
                    ):
                        if message.grouped_id == event.message.grouped_id:
                            if message.text:
                                # Save the first message's text and buttons
                                context.message_text = message.text or ''
                                context.original_message_text = message.text or ''
                                context.check_message_text = message.text or ''
                                context.buttons = message.buttons if hasattr(message, 'buttons') else None
                            logger.info(f'Got media group text and added to context: {message.text}')

                except Exception as e:
                    logger.error(f'Error collecting media group messages: {str(e)}')
                    context.errors.append(f"Error collecting media group messages: {str(e)}")

        finally:
            # logger.info(f"After InitFilter processing, context: {context.__dict__}")
            return True
