from telethon import events
from models.models import get_session, Chat, ForwardRule
import logging
from handlers import user_handler, bot_handler
from handlers.prompt_handlers import handle_prompt_setting
import asyncio
import os
from dotenv import load_dotenv
from telethon.tl.types import ChannelParticipantsAdmins
from managers.state_manager import state_manager
from telethon.tl import types
from filters.process import process_forward_rule
# Load environment variables
load_dotenv()

# Get logger
logger = logging.getLogger(__name__)

# Cache to track already-processed media groups
PROCESSED_GROUPS = set()

BOT_ID = None

async def setup_listeners(user_client, bot_client):
    """
    Set up message listeners.

    Args:
        user_client: User client (for listening to messages and forwarding)
        bot_client: Bot client (for handling commands and forwarding)
    """
    global BOT_ID

    # Fetch the bot's own ID upfront
    try:
        me = await bot_client.get_me()
        BOT_ID = me.id
        logger.info(f"Retrieved bot ID: {BOT_ID} (type: {type(BOT_ID)})")
    except Exception as e:
        logger.error(f"Error retrieving bot ID: {str(e)}")

    # Filter that excludes the bot's own messages
    async def not_from_bot(event):
        if BOT_ID is None:
            return True  # If bot ID is not yet available, do not filter

        sender = event.sender_id
        try:
            sender_id = int(sender) if sender is not None else None
            is_not_bot = sender_id != BOT_ID
            if not is_not_bot:
                logger.info(f"Filter detected bot message; ignoring: {sender_id}")
            return is_not_bot
        except (ValueError, TypeError):
            return True  # Do not filter if conversion fails

    # User client listener — uses the filter to skip bot messages
    @user_client.on(events.NewMessage(func=not_from_bot))
    async def user_message_handler(event):
        await handle_user_message(event, user_client, bot_client)

    # Bot client listener — uses the filter
    @bot_client.on(events.NewMessage(func=not_from_bot))
    async def bot_message_handler(event):
        # logger.info(f"Bot received a non-self message, sender ID: {event.sender_id}")
        await handle_bot_message(event, bot_client)

    # Register the bot callback handler
    bot_client.add_event_handler(bot_handler.callback_handler)

async def handle_user_message(event, user_client, bot_client):
    """Handle messages received by the user client"""
    # logger.info("handle_user_message: starting to process user message")

    chat = await event.get_chat()
    chat_id = abs(chat.id)
    # logger.info(f"handle_user_message: retrieved chat ID: {chat_id}")

    # Check whether this is a channel message
    if isinstance(event.chat, types.Channel) and state_manager.check_state():
        # logger.info("handle_user_message: detected channel message with existing state")
        sender_id = os.getenv('USER_ID')
        # Channel ID requires the 100 prefix
        chat_id = int(f"100{chat_id}")
        # logger.info(f"handle_user_message: channel message handling: sender_id={sender_id}, chat_id={chat_id}")
    else:
        sender_id = event.sender_id
        # logger.info(f"handle_user_message: non-channel message handling: sender_id={sender_id}")

    # Check user state
    current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
    # logger.info(f'handle_user_message: state active: {state_manager.check_state()}')
    # logger.info(f"handle_user_message: current user ID and chat ID: {sender_id}, {chat_id}")
    # logger.info(f"handle_user_message: current user state for this chat window: {current_state}")

    if current_state:
        # logger.info(f"Detected user state: {current_state}")
        # Handle prompt setting
        # logger.info("Preparing to handle prompt setting")
        if await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message):
            # logger.info("Prompt setting handled; returning")
            return
        # logger.info("Prompt setting not fully handled; continuing")

    # Check whether this is a media group message
    if event.message.grouped_id:
        # Skip if this media group has already been processed
        group_key = f"{chat_id}:{event.message.grouped_id}"
        if group_key in PROCESSED_GROUPS:
            return
        # Mark this media group as processed
        PROCESSED_GROUPS.add(group_key)
        asyncio.create_task(clear_group_cache(group_key))

    # Check the database for forwarding rules matching this chat
    session = get_session()
    try:
        # Query the source chat
        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == str(chat_id)
        ).first()

        if not source_chat:
            return

        # Log the found source chat
        logger.info(f'Found source chat: {source_chat.name} (ID: {source_chat.id})')

        # Find rules where this chat is the source
        rules = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id
        ).all()

        if not rules:
            logger.info(f'Chat {source_chat.name} has no forwarding rules')
            return

        # Only log message details when forwarding rules exist
        if event.message.grouped_id:
            logger.info(f'[User] Received media group message from chat: {source_chat.name} ({chat_id}), group ID: {event.message.grouped_id}')
        else:
            logger.info(f'[User] Received new message from chat: {source_chat.name} ({chat_id}), content: {event.message.text}')

        # Log rule processing
        logger.info(f'Found {len(rules)} forwarding rules')

        # Process each forwarding rule
        for rule in rules:
            target_chat = rule.target_chat
            if not rule.enable_rule:
                logger.info(f'Rule {rule.id} is not enabled')
                continue
            logger.info(f'Processing forwarding rule ID: {rule.id} (from {source_chat.name} to: {target_chat.name})')
            # Always run the full filter chain (keyword/media-type/replace/AI/etc.),
            # just choose which account sends the result. use_bot picks the bot
            # account; otherwise the user account sends it (still a fresh
            # send_message/send_file, not a native forward, so no "Forwarded from"
            # tag is added either way).
            send_client = bot_client if rule.use_bot else user_client
            await process_forward_rule(send_client, event, str(chat_id), rule)

    except Exception as e:
        logger.error(f'Error processing user message: {str(e)}')
        logger.exception(e)  # Log full stack trace
    finally:
        session.close()

async def handle_bot_message(event, bot_client):
    """Handle messages (commands) received by the bot client"""
    try:

        # logger.info("handle_bot_message: starting to process bot message")

        chat = await event.get_chat()
        chat_id = abs(chat.id)
        # logger.info(f"handle_bot_message: retrieved chat ID: {chat_id}")

        # Check whether this is a channel message
        if isinstance(event.chat, types.Channel) and state_manager.check_state():
            # logger.info("handle_bot_message: detected channel message with existing state")
            sender_id = os.getenv('USER_ID')
            # Channel ID requires the 100 prefix
            chat_id = int(f"100{chat_id}")
            # logger.info(f"handle_bot_message: channel message handling: sender_id={sender_id}, chat_id={chat_id}")
        else:
            sender_id = event.sender_id
            # logger.info(f"handle_bot_message: non-channel message handling: sender_id={sender_id}")

        # Check user state
        current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
        # logger.info(f'handle_bot_message: state active: {state_manager.check_state()}')
        # logger.info(f"handle_bot_message: current user ID and chat ID: {sender_id}, {chat_id}")
        # logger.info(f"handle_bot_message: current user state for this chat window: {current_state}")



        # Handle prompt setting
        if current_state:
            await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message)
            return

        # No special state; handle regular commands
        await bot_handler.handle_command(bot_client, event)
    except Exception as e:
        logger.error(f'Error processing bot command: {str(e)}')
        logger.exception(e)

async def clear_group_cache(group_key, delay=300):  # Clear cache after 5 minutes
    """Clear the processed media group record"""
    await asyncio.sleep(delay)
    PROCESSED_GROUPS.discard(group_key)
