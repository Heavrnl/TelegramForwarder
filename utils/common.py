import importlib
import os
import sys
import logging
from telethon.tl.types import ChannelParticipantsAdmins
from ai import get_ai_provider
from enums.enums import ForwardMode
from models.models import Chat, ForwardRule
import re
import telethon
from utils.auto_delete import respond_and_delete,reply_and_delete,async_delete_user_message
from datetime import datetime, timedelta

from utils.constants import AI_SETTINGS_TEXT,MEDIA_SETTINGS_TEXT

logger = logging.getLogger(__name__)

async def get_main_module():
    """Get the main module"""
    try:
        return sys.modules['__main__']
    except KeyError:
        # If main module not found, try manual import
        spec = importlib.util.spec_from_file_location(
            "main",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
        )
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        return main

async def get_user_client():
    """Get the user client"""
    main = await get_main_module()
    return main.user_client

async def get_bot_client():
    """Get the bot client"""
    main = await get_main_module()
    return main.bot_client

async def get_db_ops():
    """Get the db_ops instance from main.py"""
    main = await get_main_module()
    if main.db_ops is None:
        main.db_ops = await main.init_db_ops()
    return main.db_ops

async def get_user_id():
    """Get the user ID, ensuring environment variables are loaded"""
    user_id_str = os.getenv('USER_ID')
    if not user_id_str:
        logger.error('USER_ID environment variable not set')
        raise ValueError('USER_ID must be set in the .env file')
    return int(user_id_str)


async def get_current_rule(session, event):
    """Get the currently selected rule"""
    try:
        # Get current chat
        current_chat = await event.get_chat()
        logger.info(f'Getting current chat: {current_chat.id}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == str(current_chat.id)
        ).first()

        if not current_chat_db or not current_chat_db.current_add_id:
            logger.info('Current chat not found or no source chat selected')
            await reply_and_delete(event,'Please use /switch to select a source chat first')
            return None

        logger.info(f'Currently selected source chat ID: {current_chat_db.current_add_id}')

        # Find the matching rule
        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_db.current_add_id
        ).first()

        if source_chat:
            logger.info(f'Source chat found: {source_chat.name}')
        else:
            logger.error('Source chat not found')
            return None

        rule = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id,
            ForwardRule.target_chat_id == current_chat_db.id
        ).first()

        if not rule:
            logger.info('No matching forwarding rule found')
            await reply_and_delete(event,'Forwarding rule not found')
            return None

        logger.info(f'Forwarding rule found, ID: {rule.id}')
        return rule, source_chat
    except Exception as e:
        logger.error(f'Error fetching current rule: {str(e)}')
        logger.exception(e)
        await reply_and_delete(event,'Error fetching current rule, please check logs')
        return None


async def get_all_rules(session, event):
    """Get all rules for the current chat"""
    try:
        # Get current chat
        current_chat = await event.get_chat()
        logger.info(f'Getting current chat: {current_chat.id}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == str(current_chat.id)
        ).first()

        if not current_chat_db:
            logger.info('Current chat not found')
            await reply_and_delete(event,'This chat has no forwarding rules')
            return None

        logger.info(f'Current chat DB record found, ID: {current_chat_db.id}')

        # Find all rules targeting the current chat
        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id
        ).all()

        if not rules:
            logger.info('No forwarding rules found')
            await reply_and_delete(event,'This chat has no forwarding rules')
            return None

        logger.info(f'Found {len(rules)} forwarding rule(s)')
        return rules
    except Exception as e:
        logger.error(f'Error fetching all rules: {str(e)}')
        logger.exception(e)
        await reply_and_delete(event,'Error fetching rules, please check logs')
        return None



# Admin cache dictionary
_admin_cache = {}
_CACHE_DURATION = timedelta(minutes=30)  # Cache for 30 minutes



async def get_channel_admins(client, chat_id):
    """Get channel admin list with caching"""
    current_time = datetime.now()
    
    # Check if cache exists and has not expired
    if chat_id in _admin_cache:
        cache_data = _admin_cache[chat_id]
        if current_time - cache_data['timestamp'] < _CACHE_DURATION:
            return cache_data['admin_ids']
    
    # Cache missing or expired, re-fetch admin list
    try:
        admins = await client.get_participants(chat_id, filter=ChannelParticipantsAdmins)
        admin_ids = [admin.id for admin in admins]
        
        # Update cache
        _admin_cache[chat_id] = {
            'admin_ids': admin_ids,
            'timestamp': current_time
        }
        return admin_ids
    except Exception as e:
        logger.error(f'Failed to get channel admin list: {str(e)}')
        return None

async def is_admin(event):
    """Check if the user is a channel/group admin
    
    Args:
        event: event object
    Returns:
        bool: whether the user is an admin
    """
    try:
        # Get all bot admin IDs
        bot_admins = get_admin_list()

        # Check if event has message attribute
        if not hasattr(event, 'message'):
            # No message attribute — this is a callback
            if event.sender_id in bot_admins:
                return True
            else:
                logger.info(f'User {event.sender_id} is not an admin, action ignored')
                return False
            
        message = event.message
        main = await get_main_module()
        client = main.user_client
        
        
    
        if message.is_channel and not message.is_group:
            # Get channel admin list (with cache)
            channel_admins = await get_channel_admins(client, event.chat_id)
            if channel_admins is None:
                return False
                
            
            
            # Check if a bot admin is in the channel admin list
            admin_in_channel = any(admin_id in channel_admins for admin_id in bot_admins)
            if not admin_in_channel:
                logger.info(f'No bot admin found in channel admin list, ignored')
                return False
            return True
        else:
            # Check sender ID
            user_id = event.sender_id  # Use sender_id as the primary ID source
            logger.info(f'Sender ID: {user_id}')
            
            bot_admins = get_admin_list()
            # Check if user is a bot admin
            if user_id not in bot_admins:
                logger.info(f'Message from non-admin, ignored')
                return False
            return True
    except Exception as e:
        logger.error(f"Error checking admin permissions: {str(e)}")
        return False

async def get_media_settings_text():
    """Generate media settings page text"""
    return MEDIA_SETTINGS_TEXT

async def get_ai_settings_text(rule):
    """Generate AI settings page text"""
    ai_prompt = rule.ai_prompt or os.getenv('DEFAULT_AI_PROMPT', 'Not set')
    summary_prompt = rule.summary_prompt or os.getenv('DEFAULT_SUMMARY_PROMPT', 'Not set')

    return AI_SETTINGS_TEXT.format(
        ai_prompt=ai_prompt,
        summary_prompt=summary_prompt
    )

async def get_sender_info(event, rule_id):
    """
    Get sender information
    
    Args:
        event: message event
        rule_id: rule ID
        
    Returns:
        str: sender info
    """
    try:
        logger.info("Fetching sender info")
        sender_name = None

        if hasattr(event.message, 'sender_chat') and event.message.sender_chat:
            # User sending as a channel
            sender = event.message.sender_chat
            sender_name = sender.title if hasattr(sender, 'title') else None
            logger.info(f"Using channel info: {sender_name}")

        elif event.sender:
            # User sending as an individual
            sender = event.sender
            sender_name = (
                sender.title if hasattr(sender, 'title')
                else f"{sender.first_name or ''} {sender.last_name or ''}".strip()
            )
            logger.info(f"Using sender info: {sender_name}")

        elif hasattr(event.message, 'peer_id') and event.message.peer_id:
            # Try to get info from peer_id
            peer = event.message.peer_id
            if hasattr(peer, 'channel_id'):
                try:
                    # Try to get channel info
                    channel = await event.client.get_entity(peer)
                    sender_name = channel.title if hasattr(channel, 'title') else None
                    logger.info(f"Using peer_id info: {sender_name}")
                except Exception as ce:
                    logger.error(f'Failed to get channel info: {str(ce)}')

        if sender_name:
            return sender_name
        else:
            logger.warning(f"Rule ID: {rule_id} - Unable to get sender info")
            return None

    except Exception as e:
        logger.error(f'Error getting sender info: {str(e)}')
        return None

async def check_and_clean_chats(session, rule=None):
    """
    Check and clean up chat records no longer associated with any rule
    
    Args:
        session: database session
        rule: deleted rule object (optional), used to get chat IDs if provided
        
    Returns:
        int: number of deleted chat records
    """
    deleted_count = 0
    
    try:
        # Get all chat IDs
        chat_ids_to_check = set()
        
        # If a rule is provided, check the affected chats first
        if rule:
            if rule.source_chat_id:
                chat_ids_to_check.add(rule.source_chat_id)
            if rule.target_chat_id:
                chat_ids_to_check.add(rule.target_chat_id)
        else:
            # If no rule provided, check all chats
            all_chats = session.query(Chat.id).all()
            chat_ids_to_check = set(chat[0] for chat in all_chats)
        
        # Check each chat ID
        for chat_id in chat_ids_to_check:
            # Check if this chat is still referenced by any rule
            as_source = session.query(ForwardRule).filter(
                ForwardRule.source_chat_id == chat_id
            ).count()
            
            as_target = session.query(ForwardRule).filter(
                ForwardRule.target_chat_id == chat_id
            ).count()
            
            # If the chat is no longer referenced by any rule
            if as_source == 0 and as_target == 0:
                chat = session.query(Chat).get(chat_id)
                if chat:
                    # Get telegram_chat_id for logging
                    telegram_chat_id = chat.telegram_chat_id
                    name = chat.name or "Unnamed Chat"
                    
                    # Clear all records referencing this chat as current_add_id
                    chats_using_this = session.query(Chat).filter(
                        Chat.current_add_id == telegram_chat_id
                    ).all()
                    
                    for other_chat in chats_using_this:
                        other_chat.current_add_id = None
                        logger.info(f'Cleared current_add_id for chat {other_chat.name}')
                    
                    # Delete chat record
                    session.delete(chat)
                    logger.info(f'Deleted unused chat: {name} (ID: {telegram_chat_id})')
                    deleted_count += 1
        
        # If any deletions occurred, commit changes
        if deleted_count > 0:
            session.commit()
            logger.info(f'Cleaned up {deleted_count} unused chat record(s)')
        
        return deleted_count
        
    except Exception as e:
        logger.error(f'Error checking and cleaning chat records: {str(e)}')
        session.rollback()
        return 0

def get_admin_list():
    """Get the admin ID list, defaulting to USER_ID if ADMINS is empty"""
    admin_str = os.getenv('ADMINS', '')
    if not admin_str:
        user_id = os.getenv('USER_ID')
        if not user_id:
            logger.error('USER_ID environment variable not set')
            raise ValueError('USER_ID must be set in the .env file')
        return [int(user_id)]
    return [int(admin.strip()) for admin in admin_str.split(',') if admin.strip()]




async def check_keywords(rule, message_text, event = None):
    """
    Check if a message matches keyword rules

    Args:
        rule: forwarding rule object with forward_mode and keywords attributes
        message_text: the message text to check
        event: optional message event object

    Returns:
        bool: whether the message should be forwarded
    """
    reverse_blacklist = rule.enable_reverse_blacklist
    reverse_whitelist = rule.enable_reverse_whitelist
    logger.info(f"Reverse blacklist: {reverse_blacklist}, Reverse whitelist: {reverse_whitelist}")

    # Process user info filtering
    if rule.is_filter_user_info and event:
        message_text = await process_user_info(event, rule.id, message_text)

    logger.info("Starting keyword rule check")
    logger.info(f"Current forward mode: {rule.forward_mode}")
    forward_mode = rule.forward_mode

    # Whitelist-only mode
    if forward_mode == ForwardMode.WHITELIST:
        return await process_whitelist_mode(rule, message_text, reverse_blacklist)

    # Blacklist-only mode
    elif forward_mode == ForwardMode.BLACKLIST:
        return await process_blacklist_mode(rule, message_text, reverse_whitelist)

    # Whitelist-then-blacklist mode
    elif forward_mode == ForwardMode.WHITELIST_THEN_BLACKLIST:
        return await process_whitelist_then_blacklist_mode(rule, message_text, reverse_blacklist)

    # Blacklist-then-whitelist mode
    elif forward_mode == ForwardMode.BLACKLIST_THEN_WHITELIST:
        return await process_blacklist_then_whitelist_mode(rule, message_text, reverse_whitelist)

    logger.error(f"Unknown forward mode: {forward_mode}")
    return False

async def process_whitelist_mode(rule, message_text, reverse_blacklist):
    """Handle whitelist-only mode"""
    logger.info("Entering whitelist-only mode")
    should_forward = False

    # Check regular whitelist keywords
    whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
    logger.info(f"Whitelist keywords: {[k.keyword for k in whitelist_keywords]}")
    
    for keyword in whitelist_keywords:
        if await check_keyword_match(keyword, message_text):
            should_forward = True
            break
    
    if not should_forward:
        logger.info("No whitelist keyword matched, not forwarding")
        return False

    # If blacklist reversal is enabled, also require a match against the reversed blacklist (as a second whitelist)
    if reverse_blacklist:
        logger.info("Checking reversed blacklist keywords (as whitelist)")
        reversed_blacklist = [k for k in rule.keywords if k.is_blacklist]
        logger.info(f"Reversed blacklist keywords: {[k.keyword for k in reversed_blacklist]}")
        
        reversed_match = False
        for keyword in reversed_blacklist:
            if await check_keyword_match(keyword, message_text):
                reversed_match = True
                break
        
        if not reversed_match:
            logger.info("No reversed blacklist keyword matched, not forwarding")
            return False

    logger.info("All whitelist conditions met, forwarding allowed")
    return True

async def process_blacklist_mode(rule, message_text, reverse_whitelist):
    """Handle blacklist-only mode"""
    logger.info("Entering blacklist-only mode")

    # Check regular blacklist keywords
    blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
    logger.info(f"Blacklist keywords: {[k.keyword for k in blacklist_keywords]}")
    
    for keyword in blacklist_keywords:
        if await check_keyword_match(keyword, message_text):
            logger.info(f"Blacklist keyword matched: '{keyword.keyword}', not forwarding")
            return False

    # If whitelist reversal is enabled, check the reversed whitelist (as blacklist)
    if reverse_whitelist:
        logger.info("Checking reversed whitelist keywords (as blacklist)")
        reversed_whitelist = [k for k in rule.keywords if not k.is_blacklist]
        logger.info(f"Reversed whitelist keywords: {[k.keyword for k in reversed_whitelist]}")
        
        for keyword in reversed_whitelist:
            if await check_keyword_match(keyword, message_text):
                logger.info(f"Reversed whitelist keyword matched: '{keyword.keyword}', not forwarding")
                return False

    logger.info("No blacklist keyword matched, forwarding allowed")
    return True

async def check_keyword_match(keyword, message_text):
    """Check if a single keyword matches"""
    logger.info(f"Checking keyword: {keyword.keyword} (regex: {keyword.is_regex})")
    if keyword.is_regex:
        try:
            if re.search(keyword.keyword, message_text):
                logger.info(f"Regex match found: {keyword.keyword}")
                return True
        except re.error:
            logger.error(f"Regex error: {keyword.keyword}")
    else:
        if keyword.keyword.lower() in message_text.lower():
            logger.info(f"Keyword matched: {keyword.keyword}")
            return True
    return False

async def process_user_info(event, rule_id, message_text):
    """Process user info filtering"""
    username = await get_sender_info(event, rule_id)
    name = None
    
    if hasattr(event.message, 'sender_chat') and event.message.sender_chat:
        sender = event.message.sender_chat
        name = sender.title if hasattr(sender, 'title') else None
    elif event.sender:
        sender = event.sender
        name = (
            sender.title if hasattr(sender, 'title')
            else f"{sender.first_name or ''} {sender.last_name or ''}".strip()
        )
        
    if username and name:
        logger.info(f"Successfully retrieved sender info: {username} {name}")
        return f"{username} {name}:\n{message_text}"
    elif username:
        logger.info(f"Successfully retrieved sender info: {username}")
        return f"{username}:\n{message_text}"
    elif name:
        logger.info(f"Successfully retrieved sender info: {name}")
        return f"{name}:\n{message_text}"
    else:
        logger.warning(f"Rule ID: {rule_id} - Unable to get sender info")
        return message_text


async def process_whitelist_then_blacklist_mode(rule, message_text, reverse_blacklist):
    """Handle whitelist-then-blacklist mode
    
    First check whitelist (must match), then check blacklist (must not match)
    If blacklist reversal is enabled, blacklist becomes a second whitelist (must match)
    """
    logger.info("Entering whitelist-then-blacklist mode")

    # Check regular whitelist (must match)
    whitelist_match = False
    whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
    logger.info(f"Checking whitelist keywords: {[k.keyword for k in whitelist_keywords]}")
    
    for keyword in whitelist_keywords:
        if await check_keyword_match(keyword, message_text):
            whitelist_match = True
            break
    
    if not whitelist_match:
        logger.info("No whitelist keyword matched, not forwarding")
        return False

    # Handle blacklist based on reversal setting
    blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
    
    if reverse_blacklist:
        # Blacklist reversed to whitelist — must match to forward
        logger.info("Blacklist reversed, checking as second whitelist")
        logger.info(f"Reversed blacklist keywords: {[k.keyword for k in blacklist_keywords]}")
        
        blacklist_match = False
        for keyword in blacklist_keywords:
            if await check_keyword_match(keyword, message_text):
                blacklist_match = True
                break
        
        if not blacklist_match:
            logger.info("No reversed blacklist keyword matched, not forwarding")
            return False
    else:
        # Normal blacklist — match means do not forward
        logger.info(f"Checking blacklist keywords: {[k.keyword for k in blacklist_keywords]}")
        for keyword in blacklist_keywords:
            if await check_keyword_match(keyword, message_text):
                logger.info(f"Blacklist keyword matched: '{keyword.keyword}', not forwarding")
                return False

    logger.info("All conditions met, forwarding allowed")
    return True

async def process_blacklist_then_whitelist_mode(rule, message_text, reverse_whitelist):
    """Handle blacklist-then-whitelist mode
    
    First check blacklist (must not match), then check whitelist (must match)
    If whitelist reversal is enabled, whitelist becomes a second blacklist (must not match)
    """
    logger.info("Entering blacklist-then-whitelist mode")

    # Check regular blacklist (match = reject)
    blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
    logger.info(f"Checking blacklist keywords: {[k.keyword for k in blacklist_keywords]}")
    
    for keyword in blacklist_keywords:
        if await check_keyword_match(keyword, message_text):
            logger.info(f"Blacklist keyword matched: '{keyword.keyword}', not forwarding")
            return False

    # Process whitelist
    whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
    
    if reverse_whitelist:
        # Whitelist reversed to blacklist — match means do not forward
        logger.info("Whitelist reversed, checking as second blacklist")
        logger.info(f"Reversed whitelist keywords: {[k.keyword for k in whitelist_keywords]}")
        
        for keyword in whitelist_keywords:
            if await check_keyword_match(keyword, message_text):
                logger.info(f"Reversed whitelist keyword matched: '{keyword.keyword}', not forwarding")
                return False
    else:
        # Normal whitelist — must match to forward
        logger.info(f"Checking whitelist keywords: {[k.keyword for k in whitelist_keywords]}")
        whitelist_match = False
        for keyword in whitelist_keywords:
            if await check_keyword_match(keyword, message_text):
                whitelist_match = True
                break
        
        if not whitelist_match:
            logger.info("No whitelist keyword matched, not forwarding")
            return False

    logger.info("All conditions met, forwarding allowed")
    return True
