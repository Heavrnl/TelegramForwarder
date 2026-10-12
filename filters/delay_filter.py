import asyncio
import logging
from filters.base_filter import BaseFilter
from utils.common import get_main_module

logger = logging.getLogger(__name__)

class DelayFilter(BaseFilter):
    """
    Delay filter — waits for possible message edits before continuing processing.

    Some channels have their own bots that edit messages after they are sent,
    adding citations, annotations, and similar content. This filter waits for
    a configurable amount of time and then fetches the latest version of the
    message before proceeding.
    """

    async def _process(self, context):
        """
        Based on the rule configuration, decide whether to wait and fetch the
        latest message content.

        Args:
            context: message context

        Returns:
            bool: whether to continue processing
        """
        rule = context.rule
        message = context.event

        # If delay processing is not enabled or delay_seconds is 0, pass through immediately
        if not rule.enable_delay or rule.delay_seconds <= 0:
            logger.debug(f"[Rule ID:{rule.id}] Delay processing not enabled or delay_seconds is 0, skipping")
            return True

        # If the message is incomplete, pass through immediately
        if not message or not hasattr(message, "chat_id") or not hasattr(message, "id"):
            logger.debug(f"[Rule ID:{rule.id}] Message is incomplete, cannot apply delay processing")
            return True

        try:

            original_id = message.id
            chat_id = message.chat_id

            logger.info(f"[Rule ID:{rule.id}] Delaying message {original_id}, waiting {rule.delay_seconds} second(s)...")

            # Wait the specified number of seconds
            await asyncio.sleep(rule.delay_seconds)
            logger.info(f"[Rule ID:{rule.id}] Delay of {rule.delay_seconds} second(s) complete, fetching latest message...")

            # Attempt to get user client
            try:
                main = await get_main_module()
                client = main.user_client if (main and hasattr(main, 'user_client')) else context.client

                # Fetch updated message
                logger.info(f"[Rule ID:{rule.id}] Fetching message {original_id} from chat {chat_id}...")
                updated_message = await client.get_messages(chat_id, ids=original_id)


                if updated_message:
                    updated_text = getattr(updated_message, "text", "")

                    # Regardless of whether the content changed, update all relevant context fields
                    logger.info(f"[Rule ID:{rule.id}] Updating message data in context...")

                    # Update message text fields in context
                    context.message_text = updated_text
                    context.check_message_text = updated_text

                    # Update the message object in the event
                    context.event.message = updated_message

                    # Update other related fields
                    context.original_message_text = updated_text
                    context.buttons = updated_message.buttons if hasattr(updated_message, 'buttons') else None

                    # Update media-related info
                    if hasattr(updated_message, 'media') and updated_message.media:
                        context.is_media_group = updated_message.grouped_id is not None
                        context.media_group_id = updated_message.grouped_id

                    logger.info(f"[Rule ID:{rule.id}] Context message data updated successfully")
                else:
                    logger.warning(f"[Rule ID:{rule.id}] Could not fetch updated message, using original")
            except Exception as e:
                logger.warning(f"[Rule ID:{rule.id}] Error fetching updated message: {str(e)}")
                # Continue with original message

            logger.info(f"[Rule ID:{rule.id}] Delay processing complete, continuing to next filter")
            return True

        except Exception as e:
            logger.error(f"[Rule ID:{rule.id}] Error during delay processing: {str(e)}")
            return True
