from handlers.button.button_helpers import create_delay_time_buttons
from handlers.list_handlers import show_list
from handlers.button.settings_manager import create_settings_text, create_buttons, RULE_SETTINGS, MEDIA_SETTINGS, AI_SETTINGS
from models.models import Chat, ReplaceRule, Keyword,get_session, ForwardRule, RuleSync
from telethon import Button
from handlers.button.callback.ai_callback import *
from handlers.button.callback.media_callback import *
from handlers.button.callback.other_callback import *
from handlers.button.callback.push_callback import *
import logging
import aiohttp
from utils.constants import RSS_HOST, RSS_PORT
from utils.auto_delete import respond_and_delete,reply_and_delete
from utils.common import check_and_clean_chats
from handlers.button.button_helpers import create_sync_rule_buttons,create_other_settings_buttons

logger = logging.getLogger(__name__)


async def callback_switch(event, rule_id, session, message, data):
    """Handle callback for switching source chat"""
    # Get current chat
    current_chat = await event.get_chat()
    current_chat_db = session.query(Chat).filter(
        Chat.telegram_chat_id == str(current_chat.id)
    ).first()

    if not current_chat_db:
        await event.answer('Current chat not found')
        return

    # If this chat is already selected, do nothing
    if current_chat_db.current_add_id == rule_id:
        await event.answer('This chat is already selected')
        return

    # Update the currently selected source chat
    current_chat_db.current_add_id = rule_id  # rule_id here is actually the telegram_chat_id of the source chat
    session.commit()

    # Update button display
    rules = session.query(ForwardRule).filter(
        ForwardRule.target_chat_id == current_chat_db.id
    ).all()

    buttons = []
    for rule in rules:
        source_chat = rule.source_chat
        current = source_chat.telegram_chat_id == rule_id
        button_text = f'{"✓ " if current else ""}From: {source_chat.name}'
        callback_data = f"switch:{source_chat.telegram_chat_id}"
        buttons.append([Button.inline(button_text, callback_data)])

    try:
        await message.edit('Select a forwarding rule to manage:', buttons=buttons)
    except Exception as e:
        if 'message was not modified' not in str(e).lower():
            raise  # Re-raise if it's a different error

    source_chat = session.query(Chat).filter(
        Chat.telegram_chat_id == rule_id
    ).first()
    await event.answer(f'Switched to: {source_chat.name if source_chat else "Unknown chat"}')

async def callback_settings(event, rule_id, session, message, data):
    """Handle callback for displaying settings"""
    # Get current chat
    current_chat = await event.get_chat()
    current_chat_db = session.query(Chat).filter(
        Chat.telegram_chat_id == str(current_chat.id)
    ).first()

    if not current_chat_db:
        await event.answer('Current chat not found')
        return

    rules = session.query(ForwardRule).filter(
        ForwardRule.target_chat_id == current_chat_db.id
    ).all()

    if not rules:
        await event.answer('No forwarding rules found for this chat')
        return

    # Create rule selection buttons
    buttons = []
    for rule in rules:
        source_chat = rule.source_chat
        button_text = f'{source_chat.name}'
        callback_data = f"rule_settings:{rule.id}"
        buttons.append([Button.inline(button_text, callback_data)])

    await message.edit('Select a forwarding rule to manage:', buttons=buttons)

async def callback_delete(event, rule_id, session, message, data):
    """Handle callback for deleting a rule"""
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('Rule not found')
        return

    try:
        # Save rule object for subsequent chat association check
        rule_obj = rule

        # Delete replace rules first
        session.query(ReplaceRule).filter(
            ReplaceRule.rule_id == rule.id
        ).delete()

        # Then delete keywords
        session.query(Keyword).filter(
            Keyword.rule_id == rule.id
        ).delete()

        # Delete the rule
        session.delete(rule)

        # Commit the rule deletion
        session.commit()

        # Try to delete related data from RSS service
        try:
            rss_url = f"http://{RSS_HOST}:{RSS_PORT}/api/rule/{rule_id}"
            async with aiohttp.ClientSession() as client_session:
                async with client_session.delete(rss_url) as response:
                    if response.status == 200:
                        logger.info(f"Successfully deleted RSS rule data: {rule_id}")
                    else:
                        response_text = await response.text()
                        logger.warning(f"Failed to delete RSS rule data {rule_id}, status: {response.status}, response: {response_text}")
        except Exception as rss_err:
            logger.error(f"Error calling RSS delete API: {str(rss_err)}")
            # Does not affect main flow, continue

        # Use common method to check and clean up unused chat records
        deleted_chats = await check_and_clean_chats(session, rule_obj)
        if deleted_chats > 0:
            logger.info(f"Cleaned up {deleted_chats} unused chat records after deleting rule")

        # Delete the bot's message
        await message.delete()
        # Send new notification message
        await respond_and_delete(event,('✅ Rule deleted'))
        await event.answer('Rule deleted')

    except Exception as e:
        session.rollback()
        logger.error(f'Error deleting rule: {str(e)}')
        logger.exception(e)
        await event.answer('Failed to delete rule, check logs')

async def callback_page(event, rule_id, session, message, data):
    """Handle pagination callback"""
    logger.info(f'Pagination callback data: action=page, rule_id={rule_id}')

    try:
        # Parse page number and command
        page_number, command = rule_id.split(':')
        page = int(page_number)

        # Get current chat and rule
        current_chat = await event.get_chat()
        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == str(current_chat.id)
        ).first()

        if not current_chat_db or not current_chat_db.current_add_id:
            await event.answer('Please select a source chat first')
            return

        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_db.current_add_id
        ).first()

        rule = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id,
            ForwardRule.target_chat_id == current_chat_db.id
        ).first()

        if command == 'keyword':
            # Get keyword list
            keywords = session.query(Keyword).filter(
                Keyword.rule_id == rule.id
            ).all()

            await show_list(
                event,
                'keyword',
                keywords,
                lambda i, kw: f'{i}. {kw.keyword}{" (regex)" if kw.is_regex else ""}',
                f'Keyword list\nRule: from {source_chat.name}',
                page
            )

        elif command == 'replace':
            # Get replace rule list
            replace_rules = session.query(ReplaceRule).filter(
                ReplaceRule.rule_id == rule.id
            ).all()

            await show_list(
                event,
                'replace',
                replace_rules,
                lambda i, rr: f'{i}. Match: {rr.pattern} -> {"delete" if not rr.content else f"replace with: {rr.content}"}',
                f'Replace rule list\nRule: from {source_chat.name}',
                page
            )

        # Mark callback as handled
        await event.answer()

    except Exception as e:
        logger.error(f'Error handling pagination: {str(e)}')
        await event.answer('Error handling pagination, check logs')



async def callback_rule_settings(event, rule_id, session, message, data):
    """Handle callback for rule settings"""
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('Rule not found')
        return

    await message.edit(
        await create_settings_text(rule),
        buttons=await create_buttons(rule)
    )

async def callback_toggle_current(event, rule_id, session, message, data):
    """Handle callback for toggling the current rule"""
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('Rule not found')
        return

    target_chat = rule.target_chat
    source_chat = rule.source_chat

    # Check if this is already the currently selected rule
    if target_chat.current_add_id == source_chat.telegram_chat_id:
        await event.answer('This rule is already selected')
        return

    # Update the currently selected source chat
    target_chat.current_add_id = source_chat.telegram_chat_id
    session.commit()

    # Update button display
    try:
        await message.edit(
            await create_settings_text(rule),
            buttons=await create_buttons(rule)
        )
    except Exception as e:
        if 'message was not modified' not in str(e).lower():
            raise

    await event.answer(f'Switched to: {source_chat.name}')



async def callback_set_delay_time(event, rule_id, session, message, data):
    await event.edit("Select delay time:", buttons=await create_delay_time_buttons(rule_id, page=0))
    return



async def callback_delay_time_page(event, rule_id, session, message, data):
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("Select delay time:", buttons=await create_delay_time_buttons(rule_id, page=page))
    return

            


async def callback_select_delay_time(event, rule_id, session, message, data):
    parts = data.split(':', 2)  # Split at most 2 times
    if len(parts) == 3:
        _, rule_id, time = parts
        logger.info(f"Setting delay time for rule {rule_id} to: {time}")
        try:
            rule = session.query(ForwardRule).get(int(rule_id))
            if rule:
                # Record old time
                old_time = rule.delay_seconds

                # Update time
                rule.delay_seconds = int(time)
                session.commit()
                logger.info(f"Database updated successfully: {old_time} -> {time}")

                # Get message object
                message = await event.get_message()

                await message.edit(
                    await create_settings_text(rule),
                    buttons=await create_buttons(rule)
                )
                logger.info("UI update complete")
        except Exception as e:
            logger.error(f"Error setting delay time: {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")
        finally:
            session.close()
    return

async def callback_set_sync_rule(event, rule_id, session, message, data):
    """Handle callback for setting sync rule"""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer('Rule not found')
            return

        await message.edit("Select a rule to sync to:", buttons=await create_sync_rule_buttons(rule_id, page=0))
    except Exception as e:
        logger.error(f"Error setting sync rule: {str(e)}")
        await event.answer('Error processing request, check logs')
    return

async def callback_toggle_rule_sync(event, rule_id_data, session, message, data):
    """Handle callback for toggling rule sync status"""
    try:
        # Parse callback data - format is source_rule_id:target_rule_id:page
        parts = rule_id_data.split(":")
        if len(parts) != 3:
            await event.answer('Invalid callback data format')
            return

        source_rule_id = int(parts[0])
        target_rule_id = int(parts[1])
        page = int(parts[2])

        # Get database operations object
        db_ops = await get_db_ops()

        # Check if sync relationship already exists
        syncs = await db_ops.get_rule_syncs(session, source_rule_id)
        sync_target_ids = [sync.sync_rule_id for sync in syncs]

        # Toggle sync status
        if target_rule_id in sync_target_ids:
            # If already synced, remove the sync relationship
            success, message_text = await db_ops.delete_rule_sync(session, source_rule_id, target_rule_id)
            if success:
                await event.answer(f'Sync with rule {target_rule_id} cancelled')
            else:
                await event.answer(f'Failed to cancel sync: {message_text}')
        else:
            # If not synced, add the sync relationship
            success, message_text = await db_ops.add_rule_sync(session, source_rule_id, target_rule_id)
            if success:
                await event.answer(f'Sync to rule {target_rule_id} enabled')
            else:
                await event.answer(f'Failed to set sync: {message_text}')

        # Update button display
        await message.edit("Select a rule to sync to:", buttons=await create_sync_rule_buttons(source_rule_id, page))

    except Exception as e:
        logger.error(f"Error toggling rule sync status: {str(e)}")
        await event.answer('Error processing request, check logs')
    return

async def callback_sync_rule_page(event, rule_id_data, session, message, data):
    """Handle pagination for the sync rule page"""
    try:
        # Parse callback data - format is rule_id:page
        parts = rule_id_data.split(":")
        if len(parts) != 2:
            await event.answer('Invalid callback data format')
            return

        rule_id = int(parts[0])
        page = int(parts[1])

        # Check if rule exists
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            await event.answer('Rule not found')
            return

        # Update button display
        await message.edit("Select a rule to sync to:", buttons=await create_sync_rule_buttons(rule_id, page))

    except Exception as e:
        logger.error(f"Error handling sync rule page pagination: {str(e)}")
        await event.answer('Error processing request, check logs')
    return


async def callback_close_settings(event, rule_id, session, message, data):
    """Handle callback for close settings button, deletes current message"""
    try:
        logger.info("Executing close settings, preparing to delete message")
        await message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {str(e)}")
        await event.answer("Failed to close settings, check logs")

async def callback_noop(event, rule_id, session, message, data):
    # Used for page number buttons, does nothing
    await event.answer("Current page")
    return


async def callback_page_rule(event, page_str, session, message, data):
    """Handle callback for rule list pagination"""
    try:
        page = int(page_str)
        if page < 1:
            await event.answer('Already on the first page')
            return

        per_page = 30
        offset = (page - 1) * per_page

        # Get total rule count
        total_rules = session.query(ForwardRule).count()

        if total_rules == 0:
            await event.answer('No rules found')
            return

        # Calculate total pages
        total_pages = (total_rules + per_page - 1) // per_page

        if page > total_pages:
            await event.answer('Already on the last page')
            return

        # Get rules for current page
        rules = session.query(ForwardRule).order_by(ForwardRule.id).offset(offset).limit(per_page).all()

        # Build rule list message
        message_parts = [f'📋 Forwarding rule list (page {page}/{total_pages}):\n']

        for rule in rules:
            source_chat = rule.source_chat
            target_chat = rule.target_chat

            rule_desc = (
                f'<b>ID: {rule.id}</b>\n'
                f'<blockquote>Source: {source_chat.name} ({source_chat.telegram_chat_id})\n'
                f'Target: {target_chat.name} ({target_chat.telegram_chat_id})\n'
                '</blockquote>'
            )
            message_parts.append(rule_desc)

        # Create pagination buttons
        buttons = []
        nav_row = []

        if page > 1:
            nav_row.append(Button.inline('⬅️ Previous', f'page_rule:{page-1}'))
        else:
            nav_row.append(Button.inline('⬅️', 'noop'))

        nav_row.append(Button.inline(f'{page}/{total_pages}', 'noop'))

        if page < total_pages:
            nav_row.append(Button.inline('Next ➡️', f'page_rule:{page+1}'))
        else:
            nav_row.append(Button.inline('➡️', 'noop'))

        buttons.append(nav_row)

        await message.edit('\n'.join(message_parts), buttons=buttons, parse_mode='html')
        await event.answer()

    except Exception as e:
        logger.error(f'Error handling rule list pagination: {str(e)}')
        await event.answer('Error processing pagination request, check logs')

async def update_rule_setting(event, rule_id, session, message, field_name, config, setting_type):
    """Generic rule setting update function

    Args:
        event: Callback event
        rule_id: Rule ID
        session: Database session
        message: Message object
        field_name: Field name
        config: Setting configuration
        setting_type: Setting type ('rule', 'media', 'ai')
    """
    logger.info(f'Found matching setting: {field_name}')
    rule = session.query(ForwardRule).get(int(rule_id))
    if not rule:
        logger.warning(f'Rule not found: {rule_id}')
        await event.answer('Rule not found')
        return False

    current_value = getattr(rule, field_name)
    new_value = config['toggle_func'](current_value)
    setattr(rule, field_name, new_value)

    try:
        # Update current rule first
        session.commit()
        logger.info(f'Updated rule {rule.id} field {field_name} from {current_value} to {new_value}')

        # Check if sync is enabled, and not the "enable_rule" or "enable_sync" fields
        if rule.enable_sync and field_name != 'enable_rule' and field_name != 'enable_sync':
            logger.info(f"Rule {rule.id} has sync enabled, syncing setting change to associated rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

            # Apply same setting to each sync rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing setting {field_name} to rule {sync_rule_id}")

                # Get sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                    continue

                # Update sync target rule's setting
                try:
                    # Record old value
                    old_value = getattr(target_rule, field_name)

                    # Set new value
                    setattr(target_rule, field_name, new_value)
                    session.flush()

                    logger.info(f"Synced rule {sync_rule_id} field {field_name} from {old_value} to {new_value}")
                except Exception as e:
                    logger.error(f"Error syncing setting to rule {sync_rule_id}: {str(e)}")
                    continue

            # Commit all sync changes
            session.commit()
            logger.info("All sync changes committed")

        # Update UI based on setting type
        if setting_type == 'rule':
            await message.edit(
                await create_settings_text(rule),
                buttons=await create_buttons(rule)
            )
        elif setting_type == 'media':
            await event.edit("Media settings:", buttons=await create_media_settings_buttons(rule))
        elif setting_type == 'ai':
            await message.edit(
                await get_ai_settings_text(rule),
                buttons=await create_ai_settings_buttons(rule)
            )
        elif setting_type == 'other':
            await event.edit("Other settings:", buttons=await create_other_settings_buttons(rule))
        elif setting_type == 'push':
            await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule), link_preview=False)
        display_name = config.get('display_name', field_name)
        if field_name == 'use_bot':
            await event.answer(f'Switched to {"bot" if new_value else "user account"} mode')
        else:
            await event.answer(f'Updated {display_name}')
        return True
    except Exception as e:
        session.rollback()
        logger.error(f'Error updating rule setting: {str(e)}')
        await event.answer('Failed to update setting, check logs')
        return False


async def handle_callback(event):
    """Handle button callbacks"""
    try:
        data = event.data.decode()
        logger.info(f'Received callback data: {data}')

        # Parse callback data
        parts = data.split(':')
        action = parts[0]
        rule_id = ':'.join(parts[1:]) if len(parts) > 1 else None
        logger.info(f'Parsed callback data: action={action}, rule_id={rule_id}')

        # Get message object
        message = await event.get_message()

        # Use session
        session = get_session()
        try:
            # Get the corresponding handler
            handler = CALLBACK_HANDLERS.get(action)
            if handler:
                logger.info(f'Found handler: {handler}')
                await handler(event, rule_id, session, message, data)
            else:
                logger.info(f'No handler found, trying rule setting toggle: {action}')

                # Try to find in RULE_SETTINGS
                for field_name, config in RULE_SETTINGS.items():
                    if action == config['toggle_action']:
                        success = await update_rule_setting(event, rule_id, session, message, field_name, config, 'rule')
                        if success:
                            return

                # Try to find in MEDIA_SETTINGS
                for field_name, config in MEDIA_SETTINGS.items():
                    if action == config['toggle_action']:
                        success = await update_rule_setting(event, rule_id, session, message, field_name, config, 'media')
                        if success:
                            return

                # Try to find in AI_SETTINGS
                for field_name, config in AI_SETTINGS.items():
                    if action == config['toggle_action']:
                        success = await update_rule_setting(event, rule_id, session, message, field_name, config, 'ai')
                        if success:
                            return
        finally:
            session.close()

    except Exception as e:
        logger.error(f'Error handling button callback: {str(e)}')
        logger.error(f'Error stack: {traceback.format_exc()}')
        await event.answer('Error processing request, check logs')



# Callback handler dictionary
CALLBACK_HANDLERS = {
    'toggle_current': callback_toggle_current,
    'switch': callback_switch,
    'settings': callback_settings,
    'delete': callback_delete,
    'page': callback_page,
    'rule_settings': callback_rule_settings,
    'set_summary_time': callback_set_summary_time,
    'set_delay_time': callback_set_delay_time,
    'select_delay_time': callback_select_delay_time,
    'delay_time_page': callback_delay_time_page,
    'page_rule': callback_page_rule,
    'close_settings': callback_close_settings,
    'set_sync_rule': callback_set_sync_rule,
    'toggle_rule_sync': callback_toggle_rule_sync,
    'sync_rule_page': callback_sync_rule_page,
    # AI settings
    'set_summary_prompt': callback_set_summary_prompt,
    'set_ai_prompt': callback_set_ai_prompt,
    'ai_settings': callback_ai_settings,
    'time_page': callback_time_page,
    'select_time': callback_select_time,
    'select_model': callback_select_model,
    'model_page': callback_model_page,
    'change_model': callback_change_model,
    'cancel_set_prompt': callback_cancel_set_prompt,
    'cancel_set_summary': callback_cancel_set_summary,
    'summary_now':callback_summary_now,
    # Media settings
    'select_max_media_size': callback_select_max_media_size,
    'set_max_media_size': callback_set_max_media_size,
    'media_settings': callback_media_settings,
    'set_media_types': callback_set_media_types,
    'toggle_media_type': callback_toggle_media_type,
    'set_media_extensions': callback_set_media_extensions,
    'media_extensions_page': callback_media_extensions_page,
    'toggle_media_extension': callback_toggle_media_extension,
    'toggle_media_allow_text': callback_toggle_media_allow_text,
    'noop': callback_noop,
    # Other settings
    'other_settings': callback_other_settings,
    'copy_rule': callback_copy_rule,
    'copy_keyword': callback_copy_keyword,
    'copy_replace': callback_copy_replace,
    'clear_keyword': callback_clear_keyword,
    'clear_replace': callback_clear_replace,
    'delete_rule': callback_delete_rule,
    'perform_copy_rule': callback_perform_copy_rule,
    'perform_copy_keyword': callback_perform_copy_keyword,
    'perform_copy_replace': callback_perform_copy_replace,
    'perform_clear_keyword': callback_perform_clear_keyword,
    'perform_clear_replace': callback_perform_clear_replace,
    'perform_delete_rule': callback_perform_delete_rule,
    'set_userinfo_template': callback_set_userinfo_template,
    'set_time_template': callback_set_time_template,
    'set_original_link_template': callback_set_original_link_template,
    'cancel_set_userinfo': callback_cancel_set_userinfo,
    'cancel_set_time': callback_cancel_set_time,
    'cancel_set_original_link': callback_cancel_set_original_link,
    'toggle_reverse_blacklist': callback_toggle_reverse_blacklist,
    'toggle_reverse_whitelist': callback_toggle_reverse_whitelist,
    # Push settings
    'push_settings': callback_push_settings,
    'toggle_enable_push': callback_toggle_enable_push,
    'toggle_enable_only_push': callback_toggle_enable_only_push,
    'add_push_channel': callback_add_push_channel,
    'cancel_add_push_channel': callback_cancel_add_push_channel,
    'toggle_push_config': callback_toggle_push_config,
    'toggle_push_config_status': callback_toggle_push_config_status,
    'toggle_media_send_mode': callback_toggle_media_send_mode,
    'delete_push_config': callback_delete_push_config,
    'push_page': callback_push_page,
}
