import logging
import asyncio
from telethon import Button
from filters.base_filter import BaseFilter
from utils.common import get_main_module
import traceback
logger = logging.getLogger(__name__)

class ReplyFilter(BaseFilter):
    """
    Reply filter — handles comment-section buttons for media group messages.
    Because buttons cannot be added directly to media group messages, this filter
    uses the bot to reply to the already-forwarded message with a comment-section button.
    """

    async def _process(self, context):
        """
        Handle comment-section buttons for media group messages.

        Args:
            context: message context

        Returns:
            bool: whether to continue processing
        """
        try:
            # If the rule doesn't exist or the comment button feature isn't enabled, skip
            if not context.rule or not context.rule.enable_comment_button:
                return True

            # Only handle media group messages
            if not context.is_media_group:
                return True

            # Check that a comment link and forwarded messages are available
            if not context.comment_link or not context.forwarded_messages:
                logger.info("No comment link or forwarded messages available; cannot add comment button reply")
                return True

            # Use the bot client (context.client)
            client = context.client

            # Get target chat info
            rule = context.rule
            target_chat = rule.target_chat
            target_chat_id = int(target_chat.telegram_chat_id)

            # Get the first forwarded message ID
            first_forwarded_msg = context.forwarded_messages[0]

            # Create the comment button
            comment_button = Button.url("💬 View Comments", context.comment_link)
            buttons = [[comment_button]]

            # Reply to the forwarded media group message
            logger.info(f"Sending comment button reply to forwarded media group message {first_forwarded_msg.id} via bot")

            # Send the reply message with the comment button
            await client.send_message(
                entity=target_chat_id,
                message="💬 Comments",
                buttons=buttons,
                reply_to=first_forwarded_msg.id,
            )
            logger.info("Comment button reply sent successfully")

            return True

        except Exception as e:
            logger.error(f"ReplyFilter error while processing message: {str(e)}")

            logger.error(traceback.format_exc())
            return True
