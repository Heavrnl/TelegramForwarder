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
    Media filter that handles media content in messages.
    """

    async def _process(self, context):
        """
        Process media content.

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        # Ensure the temp directory exists
        os.makedirs(TEMP_DIR, exist_ok=True)

        rule = context.rule
        event = context.event
        client = context.client


        # If this is a media group message
        if event.message.grouped_id:
            await self._process_media_group(context)
        else:
            await self._process_single_media(context)

        return True

    async def _process_media_group(self, context):
        """Process a media group message"""
        event = context.event
        rule = context.rule
        client = context.client

        logger.info(f'Processing media group message, group ID: {event.message.grouped_id}')

        # Wait longer to allow all media messages to arrive
        await asyncio.sleep(1)

        # Retrieve media type settings
        media_types = None
        if rule.enable_media_type_filter:
            session = get_session()
            try:
                media_types = session.query(MediaTypes).filter_by(rule_id=rule.id).first()
            finally:
                session.close()

        # Collect all messages in the media group
        total_media_count = 0  # Total number of media items
        blocked_media_count = 0  # Number of blocked media items
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
                                logger.info(f'Media type blocked, skipping message ID={message.id}')
                                blocked_media_count += 1
                                continue

                        # Check media extension
                        if rule.enable_extension_filter and message.media:
                            if not await self._is_media_extension_allowed(rule, message.media):
                                logger.info(f'Media extension blocked, skipping message ID={message.id}')
                                blocked_media_count += 1
                                continue

                    # Check media size
                    if message.media:
                        file_size = await get_media_size(message.media)
                        file_size = round(file_size/1024/1024, 2)  # Convert to MB
                        logger.info(f'Media file size: {file_size}MB')
                        logger.info(f'Rule max media size: {rule.max_media_size}MB')
                        logger.info(f'Media size filter enabled: {rule.enable_media_size_filter}')
                        logger.info(f'Send over-size media notification: {rule.is_send_over_media_size_message}')

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

        logger.info(f'Found {len(context.media_group_messages)} media group message(s), {len(context.skipped_media)} over-size')

        # If all media is blocked, set should_forward to False
        if total_media_count > 0 and total_media_count == blocked_media_count:
            logger.info('All media in group is blocked, setting no-forward')
            # Check whether text is allowed through
            if rule.media_allow_text:
                logger.info('Media blocked but text is allowed through')
                context.media_blocked = True  # Mark media as blocked
            else:
                context.should_forward = False
            return True

        # If all media exceeds size limit and no over-size notification is to be sent, set no-forward
        if len(context.skipped_media) > 0 and len(context.media_group_messages) == 0 and not rule.is_send_over_media_size_message:
            # Check whether text is allowed through
            if rule.media_allow_text:
                logger.info('Media over size limit but text is allowed through')
                context.media_blocked = True  # Mark media as blocked
            else:
                context.should_forward = False
                logger.info('All media exceeds size limit and no notification will be sent, setting no-forward')

    async def _process_single_media(self, context):
        """Process a single media message"""
        event = context.event
        rule = context.rule
        # logger.info(f'context attributes: {context.rule.__dict__}')
        # Check whether this is a pure link preview message
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

        # Check whether there is actual media
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
            # Check whether the media type is blocked
            if rule.enable_media_type_filter:
                session = get_session()
                try:
                    media_types = session.query(MediaTypes).filter_by(rule_id=rule.id).first()
                    if media_types and await self._is_media_type_blocked(event.message.media, media_types):
                        logger.info(f'Media type blocked, skipping message ID={event.message.id}')
                        # Check whether text is allowed through
                        if rule.media_allow_text:
                            logger.info('Media blocked but text is allowed through')
                            context.media_blocked = True  # Mark media as blocked
                        else:
                            context.should_forward = False
                        return True
                finally:
                    session.close()

            # Check media extension
            if rule.enable_extension_filter and event.message.media:
                if not await self._is_media_extension_allowed(rule, event.message.media):
                    logger.info(f'Media extension blocked, skipping message ID={event.message.id}')
                    # Check whether text is allowed through
                    if rule.media_allow_text:
                        logger.info('Media blocked but text is allowed through')
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
                    # Correctly retrieve the filename from document attributes
                    for attr in event.message.document.attributes:
                        if hasattr(attr, 'file_name'):
                            file_name = attr.file_name
                            break

                logger.info(f'Media file exceeds size limit ({rule.max_media_size}MB)')
                if rule.is_send_over_media_size_message:
                    logger.info(f'Send over-size media notification: {rule.is_send_over_media_size_message}')
                    context.should_forward = True
                else:
                    # Check whether text is allowed through
                    if rule.media_allow_text:
                        logger.info('Media over size limit but text is allowed through')
                        context.media_blocked = True  # Mark media as blocked
                        context.skipped_media.append((event.message, file_size, file_name))
                        return True  # Skip subsequent media download
                    else:
                        context.should_forward = False
                context.skipped_media.append((event.message, file_size, file_name))
                return True  # Skip subsequent media download regardless
            else:
                # If forwarding to RSS only, skip storing media — let RSS handle it
                if rule.only_rss:
                    return True
                # Store the source message so the sender can forward the media by
                # reference (a server-side copy) instead of downloading and re-uploading.
                context.media_messages.append(event.message)
                logger.info(f'Media queued for by-reference forward: message ID={event.message.id}')
        else:
            if is_pure_link_preview:
                # Record that this is a pure link preview message
                context.is_pure_link_preview = True
                logger.info('This is a pure link preview message')

            # No recognized media on this message (plain text, or a bare
            # link preview with no photo/document/video/audio/voice).
            # If the rule restricts forwarding to specific media types,
            # a message with none of those types should not go through either.
            if rule.enable_media_type_filter:
                logger.info('Message has no media and media type filter is enabled, blocking')
                if rule.media_allow_text:
                    logger.info('No media, but text is allowed through')
                    context.media_blocked = True
                else:
                    context.should_forward = False

    async def _is_media_type_blocked(self, media, media_types):
        """
        Check whether a media type is blocked.

        Args:
            media: Media object
            media_types: MediaTypes object

        Returns:
            bool: True if the media type is blocked, False otherwise
        """
        # Check each media type
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
        Check whether a media file extension is allowed.

        Args:
            rule: Forward rule
            media: Media object

        Returns:
            bool: True if the extension is allowed, False otherwise
        """
        # If extension filter is not enabled, allow by default
        if not rule.enable_extension_filter:
            return True

        # Get file name
        file_name = None

        for attr in media.document.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break


        # If no file name, cannot determine extension — allow by default
        if not file_name:
            logger.info("Cannot retrieve file name, cannot determine extension")
            return True

        # Extract extension
        _, extension = os.path.splitext(file_name)
        extension = extension.lstrip('.').lower()  # Remove leading dot and convert to lowercase

        # Special case: if file has no extension, set a placeholder value
        if not extension:
            logger.info(f"File {file_name} has no extension")
            extension = "no-extension"
        else:
            logger.info(f"File {file_name} extension: {extension}")

        # Retrieve the saved extension list for this rule
        db_ops = await get_db_ops()
        session = get_session()
        allowed = True
        try:
            # Use the db_operations function to get the extension list
            extensions = await db_ops.get_media_extensions(session, rule.id)
            extension_list = [ext["extension"].lower() for ext in extensions]

            # Determine whether this extension is allowed
            if rule.extension_filter_mode == AddMode.BLACKLIST:
                # Blacklist mode: block if extension is in the list
                if extension in extension_list:
                    logger.info(f"Extension {extension} is in blacklist, not allowed")
                    allowed = False
                else:
                    logger.info(f"Extension {extension} is not in blacklist, allowed")
                    allowed = True
            else:
                # Whitelist mode: block if extension is not in the list
                if extension in extension_list:
                    logger.info(f"Extension {extension} is in whitelist, allowed")
                    allowed = True
                else:
                    logger.info(f"Extension {extension} is not in whitelist, not allowed")
                    allowed = False
        except Exception as e:
            logger.error(f"Error checking media extension: {str(e)}")
            allowed = True  # Allow by default on error
        finally:
            session.close()

        return allowed
