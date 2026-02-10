import logging
import os
from filters.base_filter import BaseFilter
from enums.enums import PreviewMode
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)

class SenderFilter(BaseFilter):
    """
    Message sending filter, used to send processed messages
    """

    async def _process(self, context):
        """
        Send processed messages

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        client = context.client
        event = context.event

        if not context.should_forward:
            logger.info('Message does not meet forwarding conditions, skipping send')
            return False

        if rule.enable_only_push:
            logger.info('Only forwarding to push configuration, skipping send')
            return True

        # Get target chat information
        target_chat = rule.target_chat
        target_chat_id = int(target_chat.telegram_chat_id)

        # Pre-fetch target chat entity
        try:
            entity = None
            try:
                # Use ID directly
                entity = await client.get_entity(target_chat_id)
                logger.info(f'Successfully got target chat entity: {target_chat.name} (ID: {target_chat_id})')
            except Exception as e1:
                try:
                    # Try adding -100 prefix
                    if not str(target_chat_id).startswith('-100'):
                        super_group_id = int(f'-100{abs(target_chat_id)}')
                        entity = await client.get_entity(super_group_id)
                        target_chat_id = super_group_id  # Update to use correct ID
                        logger.info(f'Successfully got entity using private group ID format: {target_chat.name} (ID: {target_chat_id})')
                except Exception as e2:
                    try:
                        # Try regular group format
                        if not str(target_chat_id).startswith('-'):
                            group_id = int(f'-{abs(target_chat_id)}')
                            entity = await client.get_entity(group_id)
                            target_chat_id = group_id  # Update to use correct ID
                            logger.info(f'Successfully got entity using regular group ID format: {target_chat.name} (ID: {target_chat_id})')
                    except Exception as e3:
                        logger.warning(f'Unable to get target chat entity, attempting to continue sending: {e1}, {e2}, {e3}')
        except Exception as e:
            logger.warning(f'Error getting target chat entity: {str(e)}')

        # Set message format
        parse_mode = rule.message_mode.value  # Use enum value (string)
        logger.info(f'Using message format: {parse_mode}')

        try:
            # Process media group messages
            if context.is_media_group or (context.media_group_messages and context.skipped_media):
                logger.info(f'Preparing to send media group message')
                await self._send_media_group(context, target_chat_id, parse_mode)
            # Process single media message
            elif context.media_files or context.skipped_media:
                logger.info(f'Preparing to send single media message')
                await self._send_single_media(context, target_chat_id, parse_mode)
            # Process plain text message
            else:
                logger.info(f'Preparing to send plain text message')
                await self._send_text_message(context, target_chat_id, parse_mode)

            logger.info(f'Message sent to: {target_chat.name} ({target_chat_id})')
            return True
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.error(f'Message sending rate limited, need to wait {wait_time} seconds')
            context.errors.append(f"Message sending rate limited, need to wait {wait_time} seconds")
            return False
        except Exception as e:
            logger.error(f'Error sending message: {str(e)}')
            context.errors.append(f"Message sending error: {str(e)}")
            return False

    async def _send_media_group(self, context, target_chat_id, parse_mode):
        """Send media group message"""
        rule = context.rule
        client = context.client
        event = context.event
        # Initialize forwarded messages list
        context.forwarded_messages = []

        # if not context.media_group_messages:
        #     logger.info(f'All media exceeded limit, sending text and prompt')
        #     # Build prompt information
        #     text_to_send = context.message_text or ''

        #     # Set original message link
        #     context.original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"

        #     # Add information for each exceeded file
        #     for message, size, name in context.skipped_media:
        #         text_to_send += f"\n\n⚠️ Media file {name if name else 'unnamed file'} ({size}MB) exceeds size limit"

        #     # Combine complete text
        #     text_to_send = context.sender_info + text_to_send + context.time_info + context.original_link

        #     await client.send_message(
        #         target_chat_id,
        #         text_to_send,
        #         parse_mode=parse_mode,
        #         link_preview=True,
        #         buttons=context.buttons
        #     )
        #     logger.info(f'All media group files exceeded limit, sent text and prompt')
        #     return

        # If there are media that can be sent, send as a group
        files = []
        try:
            for message in context.media_group_messages:
                if message.media:
                    file_path = await message.download_media(os.path.join(os.getcwd(), 'temp'))
                    if file_path:
                        files.append(file_path)

            # Modification: save downloaded file paths to context.media_files
            if files:
                # Initialize media_files if it doesn't exist
                if not hasattr(context, 'media_files') or context.media_files is None:
                    context.media_files = []
                # Add currently downloaded files to the list
                context.media_files.extend(files)
                logger.info(f'Saved {len(files)} downloaded media file paths to context.media_files')

                # Add sender info and message text
                caption_text = context.sender_info + context.message_text

                # If there are exceeded files, add prompt information
                for message, size, name in context.skipped_media:
                    caption_text += f"\n\n⚠️ Media file {name if name else 'unnamed file'} ({size}MB) exceeds size limit"

                if context.skipped_media:
                    context.original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"
                # Add time info and original link
                caption_text += context.time_info + context.original_link

                # Send all files as a group
                sent_messages = await client.send_file(
                    target_chat_id,
                    files,
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

                logger.info(f'Media group message sent, saved {len(context.forwarded_messages)} forwarded messages')
        except Exception as e:
            logger.error(f'Error sending media group message: {str(e)}')
            raise
        finally:
            # Delete temporary files, but keep them if push is enabled
            if not rule.enable_push:
                for file_path in files:
                    try:
                        os.remove(file_path)
                        logger.info(f'Deleted temporary file: {file_path}')
                    except Exception as e:
                        logger.error(f'Failed to delete temporary file: {str(e)}')
            else:
                logger.info(f'Push feature enabled, keeping temporary files')

    async def _send_single_media(self, context, target_chat_id, parse_mode):
        """Send single media message"""
        rule = context.rule
        client = context.client
        event = context.event

        logger.info(f'Sending single media message')

        # Check if all media exceeded limit
        if context.skipped_media and not context.media_files:
            # Build prompt information
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
            logger.info(f'Media file exceeds size limit, only forwarding text')
            return

        # Ensure context.media_files exists
        if not hasattr(context, 'media_files') or context.media_files is None:
            context.media_files = []

        # Send media files
        for file_path in context.media_files:
            try:
                caption = (
                    context.sender_info +
                    context.message_text +
                    context.time_info +
                    context.original_link
                )

                await client.send_file(
                    target_chat_id,
                    file_path,
                    caption=caption,
                    parse_mode=parse_mode,
                    buttons=context.buttons,
                    link_preview={
                        PreviewMode.ON: True,
                        PreviewMode.OFF: False,
                        PreviewMode.FOLLOW: context.event.message.media is not None
                    }[rule.is_preview]
                )
                logger.info(f'Media message sent')
            except Exception as e:
                logger.error(f'Error sending media message: {str(e)}')
                raise
            finally:
                # Delete temporary files, but keep them if push is enabled
                if not rule.enable_push:
                    try:
                        os.remove(file_path)
                        logger.info(f'Deleted temporary file: {file_path}')
                    except Exception as e:
                        logger.error(f'Failed to delete temporary file: {str(e)}')
                else:
                    logger.info(f'Push feature enabled, keeping temporary file: {file_path}')

    async def _send_text_message(self, context, target_chat_id, parse_mode):
        """Send plain text message"""
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
