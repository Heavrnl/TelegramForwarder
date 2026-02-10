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

# Add a cache to store processed media groups
PROCESSED_GROUPS = set()

BOT_ID = None

async def setup_listeners(user_client, bot_client):
    """
    Set up message listeners

    Args:
        user_client: User client (for listening to messages and forwarding)
        bot_client: Bot client (for handling commands and forwarding)
    """
    global BOT_ID

    # Directly get bot ID
    try:
        me = await bot_client.get_me()
        BOT_ID = me.id
        logger.info(f"Got bot ID: {BOT_ID} (type: {type(BOT_ID)})")
    except Exception as e:
        logger.error(f"Error getting bot ID: {str(e)}")

    # Filter to exclude bot's own messages
    async def not_from_bot(event):
        if BOT_ID is None:
            return True  # If bot ID not obtained, do not filter

        sender = event.sender_id
        try:
            sender_id = int(sender) if sender is not None else None
            is_not_bot = sender_id != BOT_ID
            if not is_not_bot:
                logger.info(f"Filter detected bot message, skipping processing: {sender_id}")
            return is_not_bot
        except (ValueError, TypeError):
            return True  # Do not filter on conversion failure

    # User client listener - use filter to avoid processing bot messages
    @user_client.on(events.NewMessage(func=not_from_bot))
    async def user_message_handler(event):
        await handle_user_message(event, user_client, bot_client)

    # Bot client listener - use filter
    @bot_client.on(events.NewMessage(func=not_from_bot))
    async def bot_message_handler(event):
        # logger.info(f"Bot received non-self message, sender ID: {event.sender_id}")
        await handle_bot_message(event, bot_client)

    # Register bot callback handler
    bot_client.add_event_handler(bot_handler.callback_handler)

async def handle_user_message(event, user_client, bot_client):
    """Handle messages received by user client"""
    # logger.info("handle_user_message: Starting to process user message")

    chat = await event.get_chat()
    chat_id = abs(chat.id)
    # logger.info(f"handle_user_message: Got chat ID: {chat_id}")

    # Check if it's a channel message
    if isinstance(event.chat, types.Channel) and state_manager.check_state():
        # logger.info("handle_user_message: Detected channel message with existing state")
        sender_id = os.getenv('USER_ID')
        # Channel ID needs 100 prefix
        chat_id = int(f"100{chat_id}")
        # logger.info(f"handle_user_message: Channel message processing: sender_id={sender_id}, chat_id={chat_id}")
    else:
        sender_id = event.sender_id
        # logger.info(f"handle_user_message: Non-channel message processing: sender_id={sender_id}")

    # Check user state
    current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
    # logger.info(f'handle_user_message: Current state exists: {state_manager.check_state()}')
    # logger.info(f"handle_user_message: Current user ID and chat ID: {sender_id}, {chat_id}")
    # logger.info(f"handle_user_message: Got current chat window user state: {current_state}")

    if current_state:
        # logger.info(f"Detected user state: {current_state}")
        # Handle prompt setting
        # logger.info("Preparing to handle prompt setting")
        if await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message):
            # logger.info("Prompt setting processing completed, returning")
            return
        # logger.info("Prompt setting processing not completed, continuing execution")

    # Check if it's a media group message
    if event.message.grouped_id:
        # If this media group has already been processed, skip it
        group_key = f"{chat_id}:{event.message.grouped_id}"
        if group_key in PROCESSED_GROUPS:
            return
        # Mark this media group as processed
        PROCESSED_GROUPS.add(group_key)
        asyncio.create_task(clear_group_cache(group_key))

    # First check if there are forwarding rules for this chat in the database
    session = get_session()
    try:
        # Query source chat
        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == str(chat_id)
        ).first()

        if not source_chat:
            return

        # Add log: query forwarding rules
        logger.info(f'Found source chat: {source_chat.name} (ID: {source_chat.id})')

        # Find rules where current chat is the source
        rules = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id
        ).all()

        if not rules:
            logger.info(f'Chat {source_chat.name} has no forwarding rules')
            return

        # Only log message info when there are forwarding rules
        if event.message.grouped_id:
            logger.info(f'[User] Received media group message from chat: {source_chat.name} ({chat_id}) Group ID: {event.message.grouped_id}')
        else:
            logger.info(f'[User] Received new message from chat: {source_chat.name} ({chat_id}) Content: {event.message.text}')

        # Add log: process rules
        logger.info(f'Found {len(rules)} forwarding rules')

        # Process each forwarding rule
        for rule in rules:
            target_chat = rule.target_chat
            if not rule.enable_rule:
                logger.info(f'Rule {rule.id} is not enabled')
                continue
            logger.info(f'Processing forwarding rule ID: {rule.id} (from {source_chat.name} to: {target_chat.name})')
            if rule.use_bot:
                # Directly use process_forward_rule function from filter module
                await process_forward_rule(bot_client, event, str(chat_id), rule)
            else:
                await user_handler.process_forward_rule(user_client, event, str(chat_id), rule)

    except Exception as e:
        logger.error(f'Error processing user message: {str(e)}')
        logger.exception(e)  # Add detailed error stack trace
    finally:
        session.close()

async def handle_bot_message(event, bot_client):
    """Handle messages (commands) received by bot client"""
    try:

        # logger.info("handle_bot_message: Starting to process bot message")

        chat = await event.get_chat()
        chat_id = abs(chat.id)
        # logger.info(f"handle_bot_message: Got chat ID: {chat_id}")

        # Check if it's a channel message
        if isinstance(event.chat, types.Channel) and state_manager.check_state():
            # logger.info("handle_bot_message: Detected channel message with existing state")
            sender_id = os.getenv('USER_ID')
            # Channel ID needs 100 prefix
            chat_id = int(f"100{chat_id}")
            # logger.info(f"handle_bot_message: Channel message processing: sender_id={sender_id}, chat_id={chat_id}")
        else:
            sender_id = event.sender_id
            # logger.info(f"handle_bot_message: Non-channel message processing: sender_id={sender_id}")

        # Check user state
        current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
        # logger.info(f'handle_bot_message: Current state exists: {state_manager.check_state()}')
        # logger.info(f"handle_bot_message: Current user ID and chat ID: {sender_id}, {chat_id}")
        # logger.info(f"handle_bot_message: Got current chat window user state: {current_state}")



        # Handle prompt setting
        if current_state:
            await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message)
            return

        # If no special state, handle regular commands
        await bot_handler.handle_command(bot_client, event)
    except Exception as e:
        logger.error(f'Error processing bot command: {str(e)}')
        logger.exception(e)

async def clear_group_cache(group_key, delay=300):  # Clear cache after 5 minutes
    """Clear processed media group records"""
    await asyncio.sleep(delay)
    PROCESSED_GROUPS.discard(group_key)
