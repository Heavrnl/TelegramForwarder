from telethon import events
from handlers.button.callback.callback_handlers import handle_callback
from handlers.command_handlers import *
from handlers.link_handlers import handle_message_link
from telethon.tl.types import ChannelParticipantsAdmins
from dotenv import load_dotenv
from utils.common import *
from utils.media import *
from datetime import datetime, timedelta
from version import WELCOME_TEXT

logger = logging.getLogger(__name__)

# Ensure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)

load_dotenv()


async def handle_command(client, event):
    """Handle bot commands"""

    # Check if user is admin
    if not await is_admin(event):
        return
    
    # Handle command logic
    message = event.message
    if not message.text:
        return
    
    chat = await event.get_chat()
    user_id = await get_user_id()
    chat_id = abs(chat.id)
    user_id = int(user_id)
    

    # Link forwarding feature
    if not message.text.startswith('/') and chat_id == user_id:
        # Check if this is a Telegram message link from the user
        logger.info(f'Entering link forwarding: {message.text}')
        if 't.me/' in message.text:
            await handle_message_link(client, event)
        return
    if not message.text.startswith('/'):
        return
    
    logger.info(f'Received admin command: {event.message.text}')
    # Split command, handling possible @botusername suffix
    parts = message.text.split()
    command = parts[0].split('@')[0][1:]  # Strip leading '/' and handle @username

    # Command handler dict
    command_handlers = {
        'bind': lambda: handle_bind_command(event, client, parts),
        'b': lambda: handle_bind_command(event, client, parts),
        'settings': lambda: handle_settings_command(event, command, parts),
        's': lambda: handle_settings_command(event, command, parts),
        'switch': lambda: handle_switch_command(event),
        'sw': lambda: handle_switch_command(event),
        'add': lambda: handle_add_command(event, command, parts),
        'a': lambda: handle_add_command(event, command, parts),
        'add_regex': lambda: handle_add_command(event, command, parts),
        'ar': lambda: handle_add_command(event, 'add_regex', parts),
        'replace': lambda: handle_replace_command(event, parts),
        'r': lambda: handle_replace_command(event, parts),
        'list_keyword': lambda: handle_list_keyword_command(event),
        'lk': lambda: handle_list_keyword_command(event),
        'list_replace': lambda: handle_list_replace_command(event),
        'lrp': lambda: handle_list_replace_command(event),
        'remove_keyword': lambda: handle_remove_command(event, command, parts),
        'rk': lambda: handle_remove_command(event, 'remove_keyword', parts),
        'remove_keyword_by_id': lambda: handle_remove_command(event, command, parts),
        'rkbi': lambda: handle_remove_command(event, 'remove_keyword_by_id', parts),
        'remove_replace': lambda: handle_remove_command(event, command, parts),
        'rr': lambda: handle_remove_command(event, 'remove_replace', parts),
        'remove_all_keyword': lambda: handle_remove_all_keyword_command(event, command, parts),
        'rak': lambda: handle_remove_all_keyword_command(event, 'remove_all_keyword', parts),
        'clear_all': lambda: handle_clear_all_command(event),
        'ca': lambda: handle_clear_all_command(event),
        'start': lambda: handle_start_command(event),
        'help': lambda: handle_help_command(event,'help'),
        'h': lambda: handle_help_command(event,'help'),
        'export_keyword': lambda: handle_export_keyword_command(event, command),
        'ek': lambda: handle_export_keyword_command(event, command),
        'export_replace': lambda: handle_export_replace_command(event, client),
        'er': lambda: handle_export_replace_command(event, client),
        'add_all': lambda: handle_add_all_command(event, command, parts),
        'aa': lambda: handle_add_all_command(event, 'add_all', parts),
        'add_regex_all': lambda: handle_add_all_command(event, command, parts),
        'ara': lambda: handle_add_all_command(event, 'add_regex_all', parts),
        'replace_all': lambda: handle_replace_all_command(event, parts),
        'ra': lambda: handle_replace_all_command(event, parts),
        'import_keyword': lambda: handle_import_command(event, command),
        'ik': lambda: handle_import_command(event, 'import_keyword'),
        'import_regex_keyword': lambda: handle_import_command(event, command),
        'irk': lambda: handle_import_command(event, 'import_regex_keyword'),
        'import_replace': lambda: handle_import_command(event, command),
        'ir': lambda: handle_import_command(event, 'import_replace'),
        'ufb_bind': lambda: handle_ufb_bind_command(event, command),
        'ub': lambda: handle_ufb_bind_command(event, 'ufb_bind'),
        'ufb_unbind': lambda: handle_ufb_unbind_command(event, command),
        'uu': lambda: handle_ufb_unbind_command(event, 'ufb_unbind'),
        'ufb_item_change': lambda: handle_ufb_item_change_command(event, command),
        'uic': lambda: handle_ufb_item_change_command(event, 'ufb_item_change'),
        'clear_all_keywords': lambda: handle_clear_all_keywords_command(event, command),
        'cak': lambda: handle_clear_all_keywords_command(event, 'clear_all_keywords'),
        'clear_all_keywords_regex': lambda: handle_clear_all_keywords_regex_command(event, command),
        'cakr': lambda: handle_clear_all_keywords_regex_command(event, 'clear_all_keywords_regex'),
        'clear_all_replace': lambda: handle_clear_all_replace_command(event, command),
        'car': lambda: handle_clear_all_replace_command(event, 'clear_all_replace'),
        'copy_keywords': lambda: handle_copy_keywords_command(event, command),
        'ck': lambda: handle_copy_keywords_command(event, 'copy_keywords'),
        'copy_keywords_regex': lambda: handle_copy_keywords_regex_command(event, command),
        'ckr': lambda: handle_copy_keywords_regex_command(event, 'copy_keywords_regex'),
        'copy_replace': lambda: handle_copy_replace_command(event, command),
        'crp': lambda: handle_copy_replace_command(event, 'copy_replace'),
        'copy_rule': lambda: handle_copy_rule_command(event, command),
        'cr': lambda: handle_copy_rule_command(event, 'copy_rule'),
        'changelog': lambda: handle_changelog_command(event),
        'cl': lambda: handle_changelog_command(event),
        'list_rule': lambda: handle_list_rule_command(event, command, parts),
        'lr': lambda: handle_list_rule_command(event, command, parts),
        'delete_rule': lambda: handle_delete_rule_command(event, command, parts),
        'dr': lambda: handle_delete_rule_command(event, command, parts),
        'delete_rss_user': lambda: handle_delete_rss_user_command(event, command, parts),
        'dru': lambda: handle_delete_rss_user_command(event, command, parts),
        'rss': lambda: handle_rss_dashboard_command(event, command),
    }

    # Execute matching command handler
    handler = command_handlers.get(command)
    if handler:
        await handler()



# Register callback handlers
@events.register(events.CallbackQuery)
async def callback_handler(event):
    """Callback handler entry point"""
    # Check if this callback is from an admin
    if not await is_admin(event):
        return
    await handle_callback(event)


async def send_welcome_message(client):
    """Send welcome message"""
    main = await get_main_module()
    user_id = await get_user_id()

    try:
        await client.send_message(
            user_id,
            WELCOME_TEXT,
            parse_mode='html',
            link_preview=True
        )
        logger.info("Welcome message sent")
    except Exception as e:
        logger.warning(f"Could not send welcome message (user may not have started the bot yet): {e}")



