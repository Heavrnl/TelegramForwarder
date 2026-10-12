import logging
import os
from filters.base_filter import BaseFilter
from enums.enums import HandleMode, PreviewMode
from utils.common import get_main_module
from telethon.tl.types import Channel
import traceback

logger = logging.getLogger(__name__)

class EditFilter(BaseFilter):
    """
    Edit filter — modifies the original message when the rule is in edit mode.
    Only takes effect on channel messages.
    """

    async def _process(self, context):
        """
        Handle message editing.

        Args:
            context: message context

        Returns:
            bool: whether to continue processing
        """
        rule = context.rule
        event = context.event



        logger.debug(f"Edit filter starting — message ID: {event.message.id}, chat ID: {event.chat_id}")

        # If not in edit mode, continue to next filter
        if rule.handle_mode != HandleMode.EDIT:
            logger.debug(f"Rule is not in edit mode (current mode: {rule.handle_mode}), skipping edit processing")
            return True

        # Check if this is a channel message
        chat = await event.get_chat()
        logger.debug(f"Chat type: {type(chat).__name__}, chat ID: {chat.id}, chat title: {getattr(chat, 'title', 'unknown')}")

        if not isinstance(chat, Channel):
            logger.info(f"Not a channel message (chat type: {type(chat).__name__}), skipping edit")
            return False

        try:
            # Get user client
            logger.debug("Attempting to get user client")
            main = await get_main_module()
            user_client = main.user_client if (main and hasattr(main, 'user_client')) else None

            if not user_client:
                logger.error("Unable to get user client, cannot perform edit")
                return False

            logger.debug("Successfully obtained user client")

            # Set link_preview based on preview mode
            link_preview = {
                PreviewMode.ON: True,
                PreviewMode.OFF: False,
                PreviewMode.FOLLOW: event.message.media is not None  # Follow the original message
            }[rule.is_preview]

            logger.debug(f"Preview mode: {rule.is_preview}, link_preview value: {link_preview}")

            # Compose message text
            message_text = context.sender_info + context.message_text + context.time_info + context.original_link

            logger.debug(f"Original message text: '{event.message.text}'")
            logger.debug(f"New message text: '{message_text}'")

            # Check if the text has changed
            if message_text == event.message.text:
                logger.info("Message text unchanged, skipping edit")
                return False

            # Handle media group messages
            if context.is_media_group:
                logger.info(f"Processing media group, group ID: {context.media_group_id}, message count: {len(context.media_group_messages) if context.media_group_messages else 'unknown'}")
                # Try to edit each message in the media group
                if not context.media_group_messages:
                    logger.warning("Media group message list is empty, cannot edit")
                    return False

                for message in context.media_group_messages:
                    try:
                        # Only add text to the first message
                        text_to_edit = message_text if message.id == event.message.id else ""
                        logger.debug(f"Attempting to edit media group message {message.id}, media type: {type(message.media).__name__ if message.media else 'no media'}")

                        await user_client.edit_message(
                            event.chat_id,
                            message.id,
                            text=text_to_edit,
                            parse_mode=rule.message_mode.value,
                            link_preview=link_preview
                        )
                        logger.info(f"Successfully edited media group message {message.id}")
                    except Exception as e:
                        error_details = str(e)
                        if "was not modified" not in error_details:
                            logger.error(f"Failed to edit media group message {message.id}: {error_details}")
                            logger.debug(f"Exception details: {traceback.format_exc()}")
                        else:
                            logger.debug(f"Media group message {message.id} content unchanged, no edit needed")
                return False
            # Handle all other messages (single media and plain text)
            else:
                try:
                    logger.debug(f"Attempting to edit single message {event.message.id}, message type: {type(event.message).__name__}, media type: {type(event.message.media).__name__ if event.message.media else 'no media'}")
                    logger.debug(f"Using parse mode: {rule.message_mode.value}")

                    await user_client.edit_message(
                        event.chat_id,
                        event.message.id,
                        text=message_text,
                        parse_mode=rule.message_mode.value,
                        link_preview=link_preview
                    )
                    logger.info(f"Successfully edited message {event.message.id}")
                    return False
                except Exception as e:
                    error_details = str(e)
                    if "was not modified" not in error_details:
                        logger.error(f"Failed to edit message {event.message.id}: {error_details}")
                        logger.debug(f"Message ID attempted: {event.message.id}, chat ID: {event.chat_id}")
                        logger.debug(f"Message text length: {len(message_text)}, parse mode: {rule.message_mode.value}")
                        logger.debug(f"Exception details: {traceback.format_exc()}")
                    else:
                        logger.debug(f"Message {event.message.id} content unchanged, no edit needed")
                    return False

        except Exception as e:
            logger.error(f"Edit filter processing error: {str(e)}")
            logger.debug(f"Exception details: {traceback.format_exc()}")
            logger.debug(f"Context info — message ID: {event.message.id}, chat ID: {event.chat_id}, rule ID: {rule.id if hasattr(rule, 'id') else 'unknown'}")
            return False
