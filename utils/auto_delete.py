import asyncio
import os
import logging
from functools import wraps
from utils.constants import BOT_MESSAGE_DELETE_TIMEOUT, USER_MESSAGE_DELETE_ENABLE
logger = logging.getLogger(__name__)

# Get default timeout from environment variable

async def delete_after(message, seconds):
    """Wait the specified number of seconds, then delete the message.

    Args:
        message: the message to delete
        seconds: seconds to wait before deleting; 0 = delete immediately, -1 = do not delete
    """
    if seconds == -1:  # -1 means do not delete
        return

    if seconds > 0:  # positive value means wait before deleting
        await asyncio.sleep(seconds)

    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

async def reply_and_delete(event, text, delete_after_seconds=None, **kwargs):
    """Reply to a message and schedule automatic deletion.

    Args:
        event: Telethon event object
        text: text to send
        delete_after_seconds: seconds before deleting; None uses the default, 0 = immediate, -1 = never
        **kwargs: additional arguments passed to the reply method
    """
    # If no delete time specified, use the value from the environment variable
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds

    # Send reply
    message = await event.reply(text, **kwargs)

    # Schedule deletion task; only schedule if deletion_timeout is not -1
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))

    return message

async def respond_and_delete(event, text, delete_after_seconds=None, **kwargs):
    """Respond to a message and schedule automatic deletion.

    Args:
        event: Telethon event object
        text: text to send
        delete_after_seconds: seconds before deleting; None uses the default, 0 = immediate, -1 = never
        **kwargs: additional arguments passed to the respond method
    """
    # If no delete time specified, use the value from the environment variable
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds

    # Send response
    message = await event.respond(text, **kwargs)

    # Schedule deletion task; only schedule if deletion_timeout is not -1
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))

    return message

async def send_message_and_delete(client, entity, text, delete_after_seconds=None, **kwargs):
    """Send a message and schedule automatic deletion.

    Args:
        client: Telethon client object
        entity: chat object or ID
        text: text to send
        delete_after_seconds: seconds before deleting; None uses the default, 0 = immediate, -1 = never
        **kwargs: additional arguments passed to send_message
    """
    # If no delete time specified, use the value from the environment variable
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds

    # Send message
    message = await client.send_message(entity, text, **kwargs)

    # Schedule deletion task; only schedule if deletion_timeout is not -1
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))

    return message

# Delete a user message
async def async_delete_user_message(client, chat_id, message_id, seconds):
    """Delete a user message.

    Args:
        client: bot client
        chat_id: chat ID
        message_id: message ID
        seconds: seconds to wait before deleting; 0 = immediate, -1 = do not delete
    """
    if USER_MESSAGE_DELETE_ENABLE == "false":
        return

    if seconds == -1:  # -1 means do not delete
        return

    if seconds > 0:  # positive value means wait before deleting
        await asyncio.sleep(seconds)

    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"Failed to delete user message: {e}")

