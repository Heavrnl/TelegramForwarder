import logging
import os
import pytz
import asyncio
import apprise
from datetime import datetime
import traceback

from filters.base_filter import BaseFilter
from models.models import get_session, PushConfig
from enums.enums import PreviewMode

logger = logging.getLogger(__name__)

class PushFilter(BaseFilter):
    """
    Push filter, uses the apprise library to push messages
    """

    async def _process(self, context):
        """
        Push messages

        Args:
            context: Message context

        Returns:
            bool: Returns True if the message should continue processing, False otherwise
        """
        rule = context.rule
        client = context.client
        event = context.event

        # If the rule does not have push enabled, return directly
        if not rule.enable_push:
            logger.info('Push not enabled, skipping push')
            return True

        # Get rule ID and all enabled push configurations
        rule_id = rule.id
        session = get_session()


        logger.info(f"Push filter starting processing - Rule ID: {rule_id}")
        logger.info(f"Is media group: {context.is_media_group}")
        logger.info(f"Media group message count: {len(context.media_group_messages) if context.media_group_messages else 0}")
        logger.info(f"Existing media file count: {len(context.media_files) if context.media_files else 0}")
        logger.info(f"Push only without forwarding: {rule.enable_only_push}")

        # Track processed files
        processed_files = []

        try:
            # Get all enabled push configurations
            push_configs = session.query(PushConfig).filter(
                PushConfig.rule_id == rule_id,
                PushConfig.enable_push_channel == True
            ).all()

            if not push_configs:
                logger.info(f'Rule {rule_id} has no enabled push configurations, skipping push')
                return True

            # Push media group messages
            if context.is_media_group or (context.media_group_messages and context.skipped_media):
                processed_files = await self._push_media_group(context, push_configs)
            # Push single media message
            elif context.media_files or context.skipped_media:
                processed_files = await self._push_single_media(context, push_configs)
            # Push plain text message
            else:
                processed_files = await self._push_text_message(context, push_configs)

            logger.info(f'Push sent to {len(push_configs)} configurations')
            return True

        except Exception as e:
            logger.error(f'Push filter processing error: {str(e)}')
            logger.error(traceback.format_exc())
            context.errors.append(f"Push error: {str(e)}")
            return False
        finally:
            session.close()

            # Only clean up processed media files
            if processed_files:
                logger.info(f'Cleaning up processed media files, total {len(processed_files)}')
                for file_path in processed_files:
                    try:
                        if os.path.exists(str(file_path)):
                            os.remove(file_path)
                            logger.info(f'Deleted processed media file: {file_path}')
                    except Exception as e:
                        logger.error(f'Failed to delete media file: {str(e)}')

    async def _push_media_group(self, context, push_configs):
        """Push media group messages"""
        rule = context.rule
        client = context.client
        event = context.event

        # Initialize file list
        files = []
        need_cleanup = False

        try:
            # If there are no media group messages (all exceeded limit), send text and prompt
            if not context.media_group_messages and context.skipped_media:
                logger.info(f'All media exceeded limit, sending text and prompt')
                # Build prompt information
                text_to_send = context.message_text or ''

                # Set original message link
                if rule.is_original_link:
                    context.original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"

                # Add information for each exceeded file
                for message, size, name in context.skipped_media:
                    text_to_send += f"\n\n⚠️ Media file {name if name else 'unnamed file'} ({size}MB) exceeds size limit"

                # Combine complete text
                if rule.is_original_sender:
                    text_to_send = context.sender_info + text_to_send
                if rule.is_original_time:
                    text_to_send += context.time_info
                if rule.is_original_link:
                    text_to_send += context.original_link

                # Send text push
                await self._send_push_notification(push_configs, text_to_send)
                return

            # Check if there are media group messages but no media files (this is the key fix)
            if context.media_group_messages and not context.media_files:
                logger.info(f'Detected media group messages but no media files, starting download...')
                need_cleanup = True
                for message in context.media_group_messages:
                    if message.media:
                        file_path = await message.download_media(os.path.join(os.getcwd(), 'temp'))
                        if file_path:
                            files.append(file_path)
                            logger.info(f'Downloaded media group file: {file_path}')
            # If SenderFilter already downloaded files, use them
            elif context.media_files:
                logger.info(f'Using files already downloaded by SenderFilter: {len(context.media_files)}')
                files = context.media_files
            # Otherwise, need to download files ourselves
            elif rule.enable_only_push:
                logger.info(f'Need to download files ourselves, starting media group message download...')
                need_cleanup = True
                for message in context.media_group_messages:
                    if message.media:
                        file_path = await message.download_media(os.path.join(os.getcwd(), 'temp'))
                        if file_path:
                            files.append(file_path)
                            logger.info(f'Downloaded media file: {file_path}')

            # If there are available media files, build push content
            if files:
                # Add sender info and message text
                caption_text = ""
                if rule.is_original_sender and context.sender_info:
                    caption_text += context.sender_info
                caption_text += context.message_text or ""

                # If there are exceeded files, add prompt information
                for message, size, name in context.skipped_media:
                    caption_text += f"\n\n⚠️ Media file {name if name else 'unnamed file'} ({size}MB) exceeds size limit"

                # Add original link
                if rule.is_original_link and context.skipped_media:
                    original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"
                    caption_text += original_link

                # Add time info
                if rule.is_original_time and context.time_info:
                    caption_text += context.time_info

                # Set default description (if no text content)
                default_caption = f"Received a group of media files (total {len(files)})"

                # Handle each push configuration separately based on configured media send mode
                processed_files = []

                for config in push_configs:
                    # Get the media send mode for this configuration
                    send_mode = config.media_send_mode  # "Single" or "Multiple"

                    # Check if all files exist
                    valid_files = [f for f in files if os.path.exists(str(f))]
                    if not valid_files:
                        continue

                    # Decide send method based on media send mode
                    if send_mode == "Multiple":
                        try:
                            logger.info(f'Trying to send {len(valid_files)} files at once to {config.push_channel}, mode: {send_mode}')
                            await self._send_push_notification(
                                [config],
                                caption_text or f"Received a group of media files (total {len(valid_files)})",
                                None,  # Don't use single attachment parameter
                                valid_files  # Use multiple attachments parameter
                            )
                            processed_files.extend(valid_files)
                        except Exception as e:
                            logger.error(f'Failed to send multiple files at once, error: {str(e)}')
                            # If sending at once fails, try sending one by one
                            for i, file_path in enumerate(valid_files):
                                # First file uses full text, subsequent files use short description
                                file_caption = caption_text if i == 0 else f"File {i+1} of the media group"
                                await self._send_push_notification([config], file_caption, file_path)
                                processed_files.append(file_path)
                    # Send files one by one
                    else:
                        for i, file_path in enumerate(valid_files):
                            # First file uses full text, subsequent files use short description
                            if i == 0:
                                file_caption = caption_text or f"Received a group of media files (total {len(valid_files)})"
                            else:
                                file_caption = f"File {i+1} of the media group" if len(valid_files) > 1 else ""

                            await self._send_push_notification([config], file_caption, file_path)
                            processed_files.append(file_path)

        except Exception as e:
            logger.error(f'Error pushing media group message: {str(e)}')
            logger.error(traceback.format_exc())
            raise
        finally:
            # If files were downloaded by us, clean up immediately
            if need_cleanup:
                for file_path in files:
                    try:
                        if os.path.exists(str(file_path)):
                            os.remove(file_path)
                            logger.info(f'Deleted temporary file: {file_path}')
                            # Remove already deleted files to avoid duplicate deletion
                            if file_path in processed_files:
                                processed_files.remove(file_path)
                    except Exception as e:
                        logger.error(f'Failed to delete temporary file: {str(e)}')

            # Return processed but not yet deleted files
            return processed_files

    async def _push_single_media(self, context, push_configs):
        """Push single media message"""
        rule = context.rule
        client = context.client
        event = context.event

        logger.info(f'Pushing single media message')

        # Initialize processed file list
        processed_files = []

        # Check if all media exceeded limit
        if context.skipped_media and not context.media_files:
            # Build prompt information
            file_size = context.skipped_media[0][1]
            file_name = context.skipped_media[0][2]

            text_to_send = context.message_text or ''
            text_to_send += f"\n\n⚠️ Media file {file_name} ({file_size}MB) exceeds size limit"

            # Add sender info
            if rule.is_original_sender:
                text_to_send = context.sender_info + text_to_send

            # Add time info
            if rule.is_original_time:
                text_to_send += context.time_info

            # Add original link
            if rule.is_original_link:
                original_link = f"\nOriginal message: https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"
                text_to_send += original_link

            # Send text push
            await self._send_push_notification(push_configs, text_to_send)
            return processed_files

        # Process media files
        files = []
        need_cleanup = False

        try:
            # If SenderFilter already downloaded files, use them
            if context.media_files:
                logger.info(f'Using files already downloaded by SenderFilter: {len(context.media_files)}')
                files = context.media_files
            # Otherwise, need to download files ourselves
            elif rule.enable_only_push and event.message and event.message.media:
                logger.info(f'Need to download files ourselves, starting single media message download...')
                need_cleanup = True
                file_path = await event.message.download_media(os.path.join(os.getcwd(), 'temp'))
                if file_path:
                    files.append(file_path)
                    logger.info(f'Downloaded media file: {file_path}')

            # Send media files
            for file_path in files:
                try:
                    # Build push content
                    caption = ""
                    if rule.is_original_sender and context.sender_info:
                        caption += context.sender_info
                    caption += context.message_text or ""

                    # Add time info
                    if rule.is_original_time and context.time_info:
                        caption += context.time_info

                    # Add original link
                    if rule.is_original_link and context.original_link:
                        caption += context.original_link

                    # If no text content, add default description
                    if not caption:
                        # Set description based on file type
                        caption = " "
                        # ext = os.path.splitext(str(file_path))[1].lower()
                        # if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                        #     caption = "Received a photo"
                        # elif ext in ['.mp4', '.avi', '.mkv', '.mov', '.webm']:
                        #     caption = "Received a video"
                        # elif ext in ['.mp3', '.wav', '.ogg', '.flac']:
                        #     caption = "Received an audio file"
                        # else:
                        #     caption = f"Received a file ({ext})"

                    # Send push
                    await self._send_push_notification(push_configs, caption, file_path)
                    # Add to processed file list
                    processed_files.append(file_path)

                except Exception as e:
                    logger.error(f'Error pushing single media file: {str(e)}')
                    logger.error(traceback.format_exc())
                    raise

        except Exception as e:
            logger.error(f'Error pushing single media message: {str(e)}')
            logger.error(traceback.format_exc())
            raise
        finally:
            # If files were downloaded by us, need to clean up
            if need_cleanup:
                for file_path in files:
                    try:
                        if os.path.exists(str(file_path)):
                            os.remove(file_path)
                            logger.info(f'Deleted temporary file: {file_path}')
                            # Remove from processed list
                            if file_path in processed_files:
                                processed_files.remove(file_path)
                    except Exception as e:
                        logger.error(f'Failed to delete temporary file: {str(e)}')

            # Return processed but not yet deleted files
            return processed_files

    async def _push_text_message(self, context, push_configs):
        """Push plain text message"""
        rule = context.rule

        if not context.message_text:
            logger.info('No text content, not sending push')
            return []

        # Combine message text
        message_text = ""
        if rule.is_original_sender and context.sender_info:
            message_text += context.sender_info
        message_text += context.message_text
        if rule.is_original_time and context.time_info:
            message_text += context.time_info
        if rule.is_original_link and context.original_link:
            message_text += context.original_link

        # Send push
        await self._send_push_notification(push_configs, message_text)
        logger.info(f'Text message push sent')

        # Return empty list, indicating no files were processed
        return []

    async def _send_push_notification(self, push_configs, body, attachment=None, all_attachments=None):
        """Send push notification"""
        if not body and not attachment and not all_attachments:
            logger.warning('No content to push')
            return

        for config in push_configs:
            try:
                # Create Apprise object
                apobj = apprise.Apprise()

                # Add push service
                service_url = config.push_channel
                if apobj.add(service_url):
                    logger.info(f'Successfully added push service: {service_url}')
                else:
                    logger.error(f'Failed to add push service: {service_url}')
                    continue

                # Send push
                if all_attachments and len(all_attachments) > 0 and config.media_send_mode == "Multiple":
                    # Try to send all attachments at once
                    logger.info(f'Sending push with {len(all_attachments)} attachments, mode: {config.media_send_mode}')
                    send_result = await asyncio.to_thread(
                        apobj.notify,
                        body=body or f"Received {len(all_attachments)} media files",
                        attach=all_attachments
                    )
                elif attachment and os.path.exists(str(attachment)):
                    # Single attachment push
                    logger.info(f'Sending push with single attachment: {os.path.basename(str(attachment))}')
                    send_result = await asyncio.to_thread(
                        apobj.notify,
                        body=body or " ",
                        attach=attachment
                    )
                else:
                    # Plain text push
                    logger.info('Sending plain text push')
                    send_result = await asyncio.to_thread(
                        apobj.notify,
                        body=body
                    )

                if send_result:
                    logger.info(f'Push sent successfully: {service_url}')
                else:
                    logger.error(f'Push sending failed: {service_url}')

            except Exception as e:
                logger.error(f'Error sending push: {str(e)}')
                logger.error(traceback.format_exc())
