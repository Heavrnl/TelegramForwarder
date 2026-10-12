import logging
from filters.base_filter import BaseFilter
from utils.common import get_main_module

logger = logging.getLogger(__name__)

class DeleteOriginalFilter(BaseFilter):
    """
    Delete-original filter — handles whether to delete the original message after forwarding.
    """

    async def _process(self, context):
        """
        Handle deletion of the original message.

        Args:
            context: message context

        Returns:
            bool: whether to continue processing
        """
        rule = context.rule
        event = context.event

        # If deletion of the original message is not required, return immediately
        if not rule.is_delete_original:
            return True

        try:
            # Get the user client from main.py
            main = await get_main_module()
            user_client = main.user_client  # Get the user client

            # Media group messages
            if event.message.grouped_id:
                # Use the user client to fetch and delete all messages in the media group
                async for message in user_client.iter_messages(
                        event.chat_id,
                        min_id=event.message.id - 10,
                        max_id=event.message.id + 10,
                        reverse=True
                ):
                    if message.grouped_id == event.message.grouped_id:
                        await message.delete()
                        logger.info(f'Deleted media group message ID: {message.id}')
            else:
                # Single message deletion
                message = await user_client.get_messages(event.chat_id, ids=event.message.id)
                await message.delete()
                logger.info(f'Deleted original message ID: {event.message.id}')

            return True
        except Exception as e:
            logger.error(f'Error deleting original message: {str(e)}')
            context.errors.append(f"Delete original message error: {str(e)}")
            return True  # Continue processing even if deletion fails
