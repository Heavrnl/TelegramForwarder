import logging
from filters.base_filter import BaseFilter
from enums.enums import PreviewMode
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)

class SenderFilter(BaseFilter):
    """
    Message sender filter that sends processed messages.
    """

    async def _process(self, context):
        """
        Send the processed message.

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        client = context.client
        event = context.event

        if not context.should_forward:
            logger.info('Message does not meet forward conditions, skipping send')
            return False

        if rule.enable_only_push:
            logger.info('Forwarding to push config only, skipping send')
            return True

        # Retrieve target chat info
        target_chat = rule.target_chat
        target_chat_id = int(target_chat.telegram_chat_id)

        # Pre-fetch target chat entity
        try:
            entity = None
            try:
                # Use ID directly
                entity = await client.get_entity(target_chat_id)
                logger.info(f'Successfully retrieved target chat entity: {target_chat.name} (ID: {target_chat_id})')
            except Exception as e1:
                try:
                    # Try adding -100 prefix
                    if not str(target_chat_id).startswith('-100'):
                        super_group_id = int(f'-100{abs(target_chat_id)}')
                        entity = await client.get_entity(super_group_id)
                        target_chat_id = super_group_id  # Update to use correct ID
                        logger.info(f'Retrieved entity using supergroup ID format: {target_chat.name} (ID: {target_chat_id})')
                except Exception as e2:
                    try:
                        # Try regular group format
                        if not str(target_chat_id).startswith('-'):
                            group_id = int(f'-{abs(target_chat_id)}')
                            entity = await client.get_entity(group_id)
                            target_chat_id = group_id  # Update to use correct ID
                            logger.info(f'Retrieved entity using regular group ID format: {target_chat.name} (ID: {target_chat_id})')
                    except Exception as e3:
                        logger.warning(f'Unable to retrieve target chat entity, attempting to continue sending: {e1}, {e2}, {e3}')
        except Exception as e:
            logger.warning(f'Error retrieving target chat entity: {str(e)}')

        # Set message parse mode
        parse_mode = rule.message_mode.value  # Use enum value (string)
        logger.info(f'Using message parse mode: {parse_mode}')

        try:
            # Handle media group messages
            if context.is_media_group or (context.media_group_messages and context.skipped_media):
                logger.info(f'Preparing to send media group message')
                await self._send_media_group(context, target_chat_id, parse_mode)
            # Handle single media messages
            elif context.media_messages or context.skipped_media:
                logger.info(f'Preparing to send single media message')
                await self._send_single_media(context, target_chat_id, parse_mode)
            # Handle plain text messages
            else:
                logger.info(f'Preparing to send plain text message')
                await self._send_text_message(context, target_chat_id, parse_mode)

            logger.info(f'Message sent to: {target_chat.name} ({target_chat_id})')
            return True
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.error(f'Message send rate limited, need to wait {wait_time} seconds')
            context.errors.append(f"Message send rate limited, need to wait {wait_time} seconds")
            return False
        except Exception as e:
            logger.error(f'Error sending message: {str(e)}')
            context.errors.append(f"Error sending message: {str(e)}")
            return False

    async def _send_media_group(self, context, target_chat_id, parse_mode):
        """Send a media group message"""
        rule = context.rule
        client = context.client
        event = context.event
        # Initialize forwarded messages list
        context.forwarded_messages = []

        # if not context.media_group_messages:
        #     logger.info(f'All media exceeded size limit, sending text and notification')
        #     # Build notification text
        #     text_to_send = context.message_text or ''

        #     # Set original message link
        #     context.original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"

        #     # Add info for each oversized file
        #     for message, size, name in context.skipped_media:
        #         text_to_send += f"\n\n⚠️ Media file {name if name else 'unnamed file'} ({size}MB) exceeds size limit"

        #     # Combine full text
        #     text_to_send = context.sender_info + text_to_send + context.time_info + context.original_link

        #     await client.send_message(
        #         target_chat_id,
        #         text_to_send,
        #         parse_mode=parse_mode,
        #         link_preview=True,
        #         buttons=context.buttons
        #     )
        #     logger.info(f'All files in media group exceeded size limit, sent text and notification')
        #     return

        # Send available media as a group, by reference (no download/re-upload)
        media = []
        for message in context.media_group_messages:
            if message.media:
                media.append(message.media)

        if media:
            # Add sender info and message text
            caption_text = context.sender_info + context.message_text

            # If there are oversized files, add notification text
            for message, size, name in context.skipped_media:
                caption_text += f"\n\n⚠️ Media file {name if name else 'unnamed file'} ({size}MB) exceeds size limit"

            if context.skipped_media:
                context.original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"
            # Add time info and original link
            caption_text += context.time_info + context.original_link

            # Send all media as a group
            sent_messages = await client.send_file(
                target_chat_id,
                media,
                caption=caption_text,
                parse_mode=parse_mode,
                buttons=context.buttons,
                link_preview={
                    PreviewMode.ON: True,
                    PreviewMode.OFF: False,
                    PreviewMode.FOLLOW: context.event.message.media is not None
                }[rule.is_preview]
            )
            # Save sent messages to context
            if isinstance(sent_messages, list):
                context.forwarded_messages = sent_messages
            else:
                context.forwarded_messages = [sent_messages]

            logger.info(f'Media group message sent, saved {len(context.forwarded_messages)} forwarded message(s)')

    async def _send_single_media(self, context, target_chat_id, parse_mode):
        """Send a single media message"""
        rule = context.rule
        client = context.client
        event = context.event

        logger.info(f'Sending single media message')

        # Check whether all media exceeded size limit
        if context.skipped_media and not context.media_messages:
            # Build notification text
            file_size = context.skipped_media[0][1]
            file_name = context.skipped_media[0][2]
            original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"

            text_to_send = context.message_text or ''
            text_to_send += f"\n\n⚠️ Media file {file_name} ({file_size}MB) exceeds size limit"
            text_to_send = context.sender_info + text_to_send + context.time_info

            text_to_send += original_link

            await client.send_message(
                target_chat_id,
                text_to_send,
                parse_mode=parse_mode,
                link_preview=True,
                buttons=context.buttons
            )
            logger.info(f'Media file exceeded size limit, forwarding text only')
            return

        # Send media by reference (no download/re-upload)
        for message in context.media_messages:
            try:
                caption = (
                    context.sender_info +
                    context.message_text +
                    context.time_info +
                    context.original_link
                )

                await client.send_file(
                    target_chat_id,
                    message.media,
                    caption=caption,
                    parse_mode=parse_mode,
                    buttons=context.buttons,
                    link_preview={
                        PreviewMode.ON: True,
                        PreviewMode.OFF: False,
                        PreviewMode.FOLLOW: context.event.message.media is not None
                    }[rule.is_preview]
                )
                logger.info(f'Media message sent (by reference)')
            except Exception as e:
                logger.error(f'Error sending media message: {str(e)}')
                raise

    async def _send_text_message(self, context, target_chat_id, parse_mode):
        """Send a plain text message"""
        rule = context.rule
        client = context.client

        if not context.message_text:
            logger.info('No text content, not sending message')
            return

        # Set link_preview based on preview mode
        link_preview = {
            PreviewMode.ON: True,
            PreviewMode.OFF: False,
            PreviewMode.FOLLOW: context.event.message.media is not None  # Follow original message
        }[rule.is_preview]

        # Combine message text
        message_text = context.sender_info + context.message_text + context.time_info + context.original_link

        await client.send_message(
            target_chat_id,
            str(message_text),
            parse_mode=parse_mode,
            link_preview=link_preview,
            buttons=context.buttons
        )
        logger.info(f'{"Text message with preview" if link_preview else "Text message without preview"} sent')
