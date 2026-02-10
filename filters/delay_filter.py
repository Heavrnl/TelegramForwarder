import asyncio
import logging
from filters.base_filter import BaseFilter
from utils.common import get_main_module

logger = logging.getLogger(__name__)

class DelayFilter(BaseFilter):
    """
    Delay filter, waits for possible message edits before processing

    Some channels have their own bots that edit messages after sending,
    adding quotes, annotations, etc. This filter waits for a period of time,
    then re-fetches the latest message content for processing.
    """

    async def _process(self, context):
        """
        Based on rule configuration, decide whether to wait and get the latest message content

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        message = context.event

        # If the rule does not have delay processing enabled or delay seconds is 0, pass directly
        if not rule.enable_delay or rule.delay_seconds <= 0:
            logger.debug(f"[Rule ID:{rule.id}] Delay processing not enabled or delay seconds is 0, skipping delay processing")
            return True

        # If the message is incomplete, pass directly
        if not message or not hasattr(message, "chat_id") or not hasattr(message, "id"):
            logger.debug(f"[Rule ID:{rule.id}] Message is incomplete, cannot apply delay processing")
            return True

        try:

            original_id = message.id
            chat_id = message.chat_id

            logger.info(f"[Rule ID:{rule.id}] Delaying message {original_id}, waiting {rule.delay_seconds} seconds...")

            # Wait for the specified number of seconds
            await asyncio.sleep(rule.delay_seconds)
            logger.info(f"[Rule ID:{rule.id}] Delay of {rule.delay_seconds} seconds ended, fetching latest message...")

            # Try to get user client
            try:
                main = await get_main_module()
                client = main.user_client if (main and hasattr(main, 'user_client')) else context.client

                # Get the updated message
                logger.info(f"[Rule ID:{rule.id}] Fetching message {original_id} from chat {chat_id}...")
                updated_message = await client.get_messages(chat_id, ids=original_id)


                if updated_message:
                    updated_text = getattr(updated_message, "text", "")

                    # Regardless of whether message content has changed, update all related fields in context
                    logger.info(f"[Rule ID:{rule.id}] Updating message data in context...")

                    # Update message text related fields in context
                    context.message_text = updated_text
                    context.check_message_text = updated_text

                    # Update message object in event
                    context.event.message = updated_message

                    # Update other related fields
                    context.original_message_text = updated_text
                    context.buttons = updated_message.buttons if hasattr(updated_message, 'buttons') else None

                    # Update media related information
                    if hasattr(updated_message, 'media') and updated_message.media:
                        context.is_media_group = updated_message.grouped_id is not None
                        context.media_group_id = updated_message.grouped_id

                    logger.info(f"[Rule ID:{rule.id}] Context message data update completed")
                else:
                    logger.warning(f"[Rule ID:{rule.id}] Unable to get updated message, using original message")
            except Exception as e:
                logger.warning(f"[Rule ID:{rule.id}] Error getting updated message: {str(e)}")
                # Continue using original message

            logger.info(f"[Rule ID:{rule.id}] Delay processing completed, continuing with subsequent filters")
            return True

        except Exception as e:
            logger.error(f"[Rule ID:{rule.id}] Error during delay processing of message: {str(e)}")
            return True
