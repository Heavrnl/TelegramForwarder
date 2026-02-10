import logging
import asyncio
from telethon import Button
from filters.base_filter import BaseFilter
from utils.common import get_main_module
import traceback
logger = logging.getLogger(__name__)

class ReplyFilter(BaseFilter):
    """
    Reply filter, used to handle comment section buttons for media group messages.
    Since media group messages cannot have buttons added directly, this filter uses a bot to reply
    to forwarded messages and add comment section buttons.
    """

    async def _process(self, context):
        """
        Handle comment section buttons for media group messages

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        try:
            # If the rule doesn't exist or comment button feature is not enabled, skip directly
            if not context.rule or not context.rule.enable_comment_button:
                return True

            # Only process media group messages
            if not context.is_media_group:
                return True

            # Check if there is a comment section link and forwarded messages
            if not context.comment_link or not context.forwarded_messages:
                logger.info("No comment section link or forwarded messages, cannot add comment section button reply")
                return True

            # Use bot client (context.client)
            client = context.client

            # Get target chat information
            rule = context.rule
            target_chat = rule.target_chat
            target_chat_id = int(target_chat.telegram_chat_id)

            # Get the first forwarded message ID
            first_forwarded_msg = context.forwarded_messages[0]

            # Create comment section button
            comment_button = Button.url("💬 View comments", context.comment_link)
            buttons = [[comment_button]]

            # Reply to the forwarded media group message
            logger.info(f"Using Bot to send comment section button reply to forwarded media group message {first_forwarded_msg.id}")

            # Send reply message with comment section button
            await client.send_message(
                entity=target_chat_id,
                message="💬 Comments",
                buttons=buttons,
                reply_to=first_forwarded_msg.id,
            )
            logger.info("Successfully sent comment section button reply")

            return True

        except Exception as e:
            logger.error(f"Error in ReplyFilter processing message: {str(e)}")

            logger.error(traceback.format_exc())
            return True
