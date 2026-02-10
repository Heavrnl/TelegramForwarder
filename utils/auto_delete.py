import asyncio
import os
import logging
from functools import wraps
from utils.constants import BOT_MESSAGE_DELETE_TIMEOUT, USER_MESSAGE_DELETE_ENABLE
logger = logging.getLogger(__name__)

# Get default timeout from environment variable

async def delete_after(message, seconds):
    """Wait for the specified number of seconds then delete the message

    Args:
        message: The message to delete
        seconds: Number of seconds to wait before deleting, 0 means delete immediately, -1 means do not delete
    """
    if seconds == -1:  # -1 means do not delete
        return

    if seconds > 0:  # Positive number means wait the specified seconds before deleting
        await asyncio.sleep(seconds)

    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

async def reply_and_delete(event, text, delete_after_seconds=None, **kwargs):
    """Reply to a message and schedule auto-deletion

    Args:
        event: Telethon event object
        text: Text to send
        delete_after_seconds: Number of seconds before deleting the message, None uses default, 0 means delete immediately, -1 means do not delete
        **kwargs: Other parameters passed to the reply method
    """
    # If no deletion time is specified, use the default from environment variable
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds

    # Send reply
    message = await event.reply(text, **kwargs)

    # Schedule deletion task, only delete when deletion_timeout is not -1
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))

    return message

async def respond_and_delete(event, text, delete_after_seconds=None, **kwargs):
    """Use respond to reply to a message and schedule auto-deletion

    Args:
        event: Telethon event object
        text: Text to send
        delete_after_seconds: Number of seconds before deleting the message, None uses default, 0 means delete immediately, -1 means do not delete
        **kwargs: Other parameters passed to the respond method
    """
    # If no deletion time is specified, use the default from environment variable
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds

    # Send reply
    message = await event.respond(text, **kwargs)

    # Schedule deletion task, only delete when deletion_timeout is not -1
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))

    return message

async def send_message_and_delete(client, entity, text, delete_after_seconds=None, **kwargs):
    """Send a message and schedule auto-deletion

    Args:
        client: Telethon client object
        entity: Chat object or ID
        text: Text to send
        delete_after_seconds: Number of seconds before deleting the message, None uses default, 0 means delete immediately, -1 means do not delete
        **kwargs: Other parameters passed to the send_message method
    """
    # If no deletion time is specified, use the default from environment variable
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds

    # Send message
    message = await client.send_message(entity, text, **kwargs)

    # Schedule deletion task, only delete when deletion_timeout is not -1
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))

    return message

# Delete user message
async def async_delete_user_message(client, chat_id, message_id, seconds):
    """Delete a user message

    Args:
        client: Bot client
        chat_id: Chat ID
        message_id: Message ID
        seconds: Number of seconds to wait before deleting, 0 means delete immediately, -1 means do not delete
    """
    if USER_MESSAGE_DELETE_ENABLE == "false":
        return

    if seconds == -1:  # -1 means do not delete
        return

    if seconds > 0:  # Positive number means wait the specified seconds before deleting
        await asyncio.sleep(seconds)

    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"Failed to delete user message: {e}")
