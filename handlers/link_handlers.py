import re
import os
import logging
from utils.common import get_main_module, get_user_id
from utils.constants import TEMP_DIR

logger = logging.getLogger(__name__)

async def handle_message_link(client, event):
    """Handle Telegram message links"""
    if not event.message.text:
        return

    # Parse message link
    match = re.match(r'https?://t\.me/(?:c/(\d+)|([^/]+))/(\d+)', event.message.text)
    if not match:
        return

    try:
        chat_id = None
        message_id = int(match.group(3))

        if match.group(1):  # Private channel format
            chat_id = int('-100' + match.group(1))
        else:  # Public channel format
            chat_name = match.group(2)
            try:
                entity = await client.get_entity(chat_name)
                chat_id = entity.id
            except Exception as e:
                logger.error(f'Failed to get channel info: {str(e)}')
                await reply_and_delete(event,'⚠️ Unable to access this channel, please make sure you have followed it.')
                return

        # Get user client
        main = await get_main_module()
        user_client = main.user_client

        # Get original message
        message = await user_client.get_messages(chat_id, ids=message_id)
        if not message:
            await reply_and_delete(event,'⚠️ Unable to get this message, it may have been deleted or access is not permitted.')
            return

        # Check if it is a media group message
        if message.grouped_id:
            await handle_media_group(client, user_client, chat_id, message, event)
        else:
            await handle_single_message(client, message, event)


    except Exception as e:
        logger.error(f'Error processing message link: {str(e)}')
        await reply_and_delete(event,'⚠️ Error processing message, please ensure the link is correct and you have permission to access it.')

async def handle_media_group(client, user_client, chat_id, message, event):
    """Handle media group messages"""
    files = []  # Move files to outer scope
    try:
        # Collect all messages in the media group
        media_group_messages = []
        caption = None
        buttons = None
        
        # Search for messages in the same group within range of message ID
        async for grouped_message in user_client.iter_messages(
            chat_id,
            limit=20,
            min_id=message.id - 10,
            max_id=message.id + 10
        ):
            if grouped_message.grouped_id == message.grouped_id:
                media_group_messages.append(grouped_message)
                # Save text and buttons from the first message
                if not caption:
                    caption = grouped_message.text
                    buttons = grouped_message.buttons if hasattr(grouped_message, 'buttons') else None

        if media_group_messages:
            # Download all media files
            for msg in media_group_messages:
                if msg.media:
                    try:
                        file_path = await msg.download_media(TEMP_DIR)
                        if file_path:
                            files.append(file_path)
                            logger.info(f'Downloaded media file: {file_path}')
                    except Exception as e:
                        logger.error(f'Failed to download media file: {str(e)}')

            if files:
                # Send media group
                await client.send_file(
                    event.chat_id,
                    files,
                    caption=caption,
                    parse_mode='Markdown',
                    buttons=buttons
                )
                logger.info(f'Forwarded media group message, {len(files)} files in total')

    except Exception as e:
        logger.error(f'Error processing media group message: {str(e)}')
        raise
    finally:
        # Ensure all temporary files are cleaned up
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f'Deleted temporary file: {file_path}')
            except Exception as e:
                logger.error(f'Failed to delete temporary file {file_path}: {str(e)}')

async def handle_single_message(client, message, event):
    """Handle single message"""
    parse_mode = 'Markdown'
    buttons = message.buttons if hasattr(message, 'buttons') else None
    file_path = None

    try:
        if message.media:
            # Process media message
            file_path = await message.download_media(TEMP_DIR)
            if file_path:
                logger.info(f'Downloaded media file: {file_path}')
                caption = message.text if message.text else ''
                await client.send_file(
                    event.chat_id,
                    file_path,
                    caption=caption,
                    parse_mode=parse_mode,
                    buttons=buttons
                )
                logger.info('Forwarded single media message')
        else:
            # Process plain text message
            await client.send_message(
                event.chat_id,
                message.text,
                parse_mode=parse_mode,
                link_preview=True,
                buttons=buttons
            )
            logger.info('Forwarded text message')

    except Exception as e:
        logger.error(f'Error processing single message: {str(e)}')
        raise
    finally:
        # Ensure temporary files are cleaned up
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f'Deleted temporary file: {file_path}')
            except Exception as e:
                logger.error(f'Failed to delete temporary file {file_path}: {str(e)}')
