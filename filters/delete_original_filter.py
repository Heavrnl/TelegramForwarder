import logging
from filters.base_filter import BaseFilter
from utils.common import get_main_module

logger = logging.getLogger(__name__)

class DeleteOriginalFilter(BaseFilter):
    """
    Delete original message filter, handles whether to delete the original message after forwarding
    """

    async def _process(self, context):
        """
        Handle whether to delete the original message

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        event = context.event

        # If deletion of original message is not needed, return directly
        if not rule.is_delete_original:
            return True

        try:
            # Get user client from main.py
            main = await get_main_module()
            user_client = main.user_client  # Get user client

            # Media group messages
            if event.message.grouped_id:
                # Use user client to get and delete media group messages
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
                # Single message deletion logic
                message = await user_client.get_messages(event.chat_id, ids=event.message.id)
                await message.delete()
                logger.info(f'Deleted original message ID: {event.message.id}')

            return True
        except Exception as e:
            logger.error(f'Error deleting original message: {str(e)}')
            context.errors.append(f"Error deleting original message: {str(e)}")
            return True  # Even if deletion fails, continue processing
