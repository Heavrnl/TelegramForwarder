import logging
import os
import asyncio
from utils.media import get_media_size
from utils.constants import TEMP_DIR
from filters.base_filter import BaseFilter
from utils.media import get_max_media_size
from enums.enums import PreviewMode
from models.models import MediaTypes
from models.models import get_session
from sqlalchemy import text
from utils.common import get_db_ops
from enums.enums import AddMode
logger = logging.getLogger(__name__)

class MediaFilter(BaseFilter):
    """
    Media filter, processes media content in messages
    """

    async def _process(self, context):
        """
        Process media content

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        # Ensure temporary directory exists
        os.makedirs(TEMP_DIR, exist_ok=True)

        rule = context.rule
        event = context.event
        client = context.client



        # If it's a media group message
        if event.message.grouped_id:
            await self._process_media_group(context)
        else:
            await self._process_single_media(context)

        return True

    async def _process_media_group(self, context):
        """Process media group messages"""
        event = context.event
        rule = context.rule
        client = context.client

        logger.info(f'Processing media group message, group ID: {event.message.grouped_id}')

        # Wait longer for all media messages to arrive
        await asyncio.sleep(1)

        # Get media type settings
        media_types = None
        if rule.enable_media_type_filter:
            session = get_session()
            try:
                media_types = session.query(MediaTypes).filter_by(rule_id=rule.id).first()
            finally:
                session.close()

        # Collect all messages in the media group
        total_media_count = 0  # Total media count
        blocked_media_count = 0  # Blocked media count
        try:
            async for message in event.client.iter_messages(
                event.chat_id,
                limit=20,
                min_id=event.message.id - 10,
                max_id=event.message.id + 10
            ):
                if message.grouped_id == event.message.grouped_id:
                    if message.media:
                        total_media_count += 1
                        # Check media type
                        if rule.enable_media_type_filter and media_types and message.media:
                            if await self._is_media_type_blocked(message.media, media_types):
                                logger.info(f'Media type is blocked, skipping message ID={message.id}')
                                blocked_media_count += 1
                                continue

                        # Check media extension
                        if rule.enable_extension_filter and message.media:
                            if not await self._is_media_extension_allowed(rule, message.media):
                                logger.info(f'Media extension is blocked, skipping message ID={message.id}')
                                blocked_media_count += 1
                                continue

                    # Check media size
                    if message.media:
                        file_size = await get_media_size(message.media)
                        file_size = round(file_size/1024/1024, 2)  # Convert to MB
                        logger.info(f'Media file size: {file_size}MB')
                        logger.info(f'Rule max media size: {rule.max_media_size}MB')
                        logger.info(f'Media size filter enabled: {rule.enable_media_size_filter}')
                        logger.info(f'Send oversized media notification: {rule.is_send_over_media_size_message}')

                        if rule.max_media_size and (file_size > rule.max_media_size) and rule.enable_media_size_filter:
                            file_name = ''
                            if hasattr(message.media, 'document') and message.media.document:
                                for attr in message.media.document.attributes:
                                    if hasattr(attr, 'file_name'):
                                        file_name = attr.file_name
                                        break
                            logger.info(f'Media file {file_name} exceeds size limit ({rule.max_media_size}MB)')
                            context.skipped_media.append((message, file_size, file_name))
                            continue

                    context.media_group_messages.append(message)
                    logger.info(f'Found media group message: ID={message.id}, type={type(message.media).__name__ if message.media else "no media"}')
        except Exception as e:
            logger.error(f'Error collecting media group messages: {str(e)}')
            context.errors.append(f"Error collecting media group messages: {str(e)}")

        logger.info(f'Found {len(context.media_group_messages)} media group messages, {len(context.skipped_media)} exceeded limit')

        # If all media are blocked, set not to forward
        if total_media_count > 0 and total_media_count == blocked_media_count:
            logger.info('All media in the media group are blocked, setting not to forward')
            # Check if text is allowed to pass through
            if rule.media_allow_text:
                logger.info('Media blocked but text allowed to pass through')
                context.media_blocked = True  # Mark media as blocked
            else:
                context.should_forward = False
            return True

        # If all media exceeded limit and oversized notification is not enabled, set not to forward
        if len(context.skipped_media) > 0 and len(context.media_group_messages) == 0 and not rule.is_send_over_media_size_message:
            # Check if text is allowed to pass through
            if rule.media_allow_text:
                logger.info('Media exceeded limit but text allowed to pass through')
                context.media_blocked = True  # Mark media as blocked
            else:
                context.should_forward = False
                logger.info('All media exceeded limit and oversized notification not enabled, setting not to forward')

    async def _process_single_media(self, context):
        """Process single media message"""
        event = context.event
        rule = context.rule
        # logger.info(f'context attributes: {context.rule.__dict__}')
        # Check if it's a pure link preview message
        is_pure_link_preview = (
            event.message.media and
            hasattr(event.message.media, 'webpage') and
            not any([
                getattr(event.message.media, 'photo', None),
                getattr(event.message.media, 'document', None),
                getattr(event.message.media, 'video', None),
                getattr(event.message.media, 'audio', None),
                getattr(event.message.media, 'voice', None)
            ])
        )

        # Check if there is actual media
        has_media = (
            event.message.media and
            any([
                getattr(event.message.media, 'photo', None),
                getattr(event.message.media, 'document', None),
                getattr(event.message.media, 'video', None),
                getattr(event.message.media, 'audio', None),
                getattr(event.message.media, 'voice', None)
            ])
        )

        # Process actual media
        if has_media:
            # Check if media type is blocked
            if rule.enable_media_type_filter:
                session = get_session()
                try:
                    media_types = session.query(MediaTypes).filter_by(rule_id=rule.id).first()
                    if media_types and await self._is_media_type_blocked(event.message.media, media_types):
                        logger.info(f'Media type is blocked, skipping message ID={event.message.id}')
                        # Check if text is allowed to pass through
                        if rule.media_allow_text:
                            logger.info('Media blocked but text allowed to pass through')
                            context.media_blocked = True  # Mark media as blocked
                        else:
                            context.should_forward = False
                        return True
                finally:
                    session.close()

            # Check media extension
            if rule.enable_extension_filter and event.message.media:
                if not await self._is_media_extension_allowed(rule, event.message.media):
                    logger.info(f'Media extension is blocked, skipping message ID={event.message.id}')
                    # Check if text is allowed to pass through
                    if rule.media_allow_text:
                        logger.info('Media blocked but text allowed to pass through')
                        context.media_blocked = True  # Mark media as blocked
                    else:
                        context.should_forward = False
                    return True

            # Check media size
            file_size = await get_media_size(event.message.media)
            file_size = round(file_size/1024/1024, 2)
            logger.info(f'event.message.document: {event.message.document}')

            logger.info(f'Media file size: {file_size}MB')
            logger.info(f'Rule max media size: {rule.max_media_size}MB')

            logger.info(f'Media size filter enabled: {rule.enable_media_size_filter}')
            if rule.max_media_size and (file_size > rule.max_media_size) and rule.enable_media_size_filter:
                file_name = ''
                if event.message.document:
                    # Correctly get filename from document attributes
                    for attr in event.message.document.attributes:
                        if hasattr(attr, 'file_name'):
                            file_name = attr.file_name
                            break

                logger.info(f'Media file exceeds size limit ({rule.max_media_size}MB)')
                if rule.is_send_over_media_size_message:
                    logger.info(f'Send oversized media notification: {rule.is_send_over_media_size_message}')
                    context.should_forward = True
                else:
                    # Check if text is allowed to pass through
                    if rule.media_allow_text:
                        logger.info('Media exceeded limit but text allowed to pass through')
                        context.media_blocked = True  # Mark media as blocked
                        context.skipped_media.append((event.message, file_size, file_name))
                        return True  # Skip subsequent media download
                    else:
                        context.should_forward = False
                context.skipped_media.append((event.message, file_size, file_name))
                return True  # Skip subsequent media download regardless
            else:
                # If only forwarding to RSS, skip downloading media files, let RSS handle the download
                if rule.only_rss:
                    return True
                try:
                    # Download media file
                    file_path = await event.message.download_media(TEMP_DIR)
                    if file_path:
                        context.media_files.append(file_path)
                        logger.info(f'Media file downloaded to: {file_path}')
                except Exception as e:
                    logger.error(f'Error downloading media file: {str(e)}')
                    context.errors.append(f"Error downloading media file: {str(e)}")
        elif is_pure_link_preview:
            # Record that this is a pure link preview message
            context.is_pure_link_preview = True
            logger.info('This is a pure link preview message')

    async def _is_media_type_blocked(self, media, media_types):
        """
        Check if media type is blocked

        Args:
            media: Media object
            media_types: MediaTypes object

        Returns:
            bool: Returns True if media type is blocked, False otherwise
        """
        # Check various media types
        if getattr(media, 'photo', None) and media_types.photo:
            logger.info('Media type is photo, blocked')
            return True

        if getattr(media, 'document', None) and media_types.document:
            logger.info('Media type is document, blocked')
            return True

        if getattr(media, 'video', None) and media_types.video:
            logger.info('Media type is video, blocked')
            return True

        if getattr(media, 'audio', None) and media_types.audio:
            logger.info('Media type is audio, blocked')
            return True

        if getattr(media, 'voice', None) and media_types.voice:
            logger.info('Media type is voice, blocked')
            return True

        return False

    async def _is_media_extension_allowed(self, rule, media):
        """
        Check if media extension is allowed

        Args:
            rule: Forwarding rule
            media: Media object

        Returns:
            bool: Returns True if extension is allowed, False otherwise
        """
        # If extension filter is not enabled, allow by default
        if not rule.enable_extension_filter:
            return True

        # Get filename
        file_name = None

        for attr in media.document.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break


        # If filename cannot be obtained, extension cannot be determined, allow by default
        if not file_name:
            logger.info("Cannot get filename, unable to determine extension")
            return True

        # Extract extension
        _, extension = os.path.splitext(file_name)
        extension = extension.lstrip('.').lower()  # Remove dot and convert to lowercase

        # Special handling: if the file has no extension, set extension to a special value "no_extension"
        if not extension:
            logger.info(f"File {file_name} has no extension")
            extension = "no_extension"
        else:
            logger.info(f"File {file_name} extension: {extension}")

        # Get the extension list saved in the rule
        db_ops = await get_db_ops()
        session = get_session()
        allowed = True
        try:
            # Use the function from db_operations to get the extension list
            extensions = await db_ops.get_media_extensions(session, rule.id)
            extension_list = [ext["extension"].lower() for ext in extensions]

            # Determine if the extension is allowed
            if rule.extension_filter_mode == AddMode.BLACKLIST:
                # Blacklist mode: if extension is in the list, not allowed
                if extension in extension_list:
                    logger.info(f"Extension {extension} is in the blacklist, not allowed")
                    allowed = False
                else:
                    logger.info(f"Extension {extension} is not in the blacklist, allowed")
                    allowed = True
            else:
                # Whitelist mode: if extension is not in the list, not allowed
                if extension in extension_list:
                    logger.info(f"Extension {extension} is in the whitelist, allowed")
                    allowed = True
                else:
                    logger.info(f"Extension {extension} is not in the whitelist, not allowed")
                    allowed = False
        except Exception as e:
            logger.error(f"Error checking media extension: {str(e)}")
            allowed = True  # Allow by default on error
        finally:
            session.close()

        return allowed
