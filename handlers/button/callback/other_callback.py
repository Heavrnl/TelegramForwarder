import traceback
import aiohttp
import os
import asyncio
from telethon.tl import types

from handlers.button.button_helpers import create_media_size_buttons,create_media_settings_buttons,create_media_types_buttons,create_media_extensions_buttons
from models.models import ForwardRule, MediaTypes, MediaExtensions, RuleSync, Keyword, ReplaceRule
from enums.enums import AddMode
import logging
from utils.common import get_media_settings_text, get_db_ops
from models.models import get_session
from models.db_operations import DBOperations
from handlers.button.button_helpers import create_other_settings_buttons
from telethon import Button
from sqlalchemy import inspect
from utils.constants import RSS_HOST, RSS_PORT,RULES_PER_PAGE
from utils.common import check_and_clean_chats, is_admin
from utils.auto_delete import reply_and_delete, send_message_and_delete, respond_and_delete
from managers.state_manager import state_manager

logger = logging.getLogger(__name__)



async def callback_other_settings(event, rule_id, session, message, data):
    await event.edit("Other settings:", buttons=await create_other_settings_buttons(rule_id=rule_id))
    return

async def callback_copy_rule(event, rule_id, session, message, data):
    """Show copy rule selection interface.

    After selection, copies current rule settings to the target rule.
    """
    try:
        # Check for page parameter
        parts = data.split(':')
        page = 0
        if len(parts) > 2:
            page = int(parts[2])

        # Extract source rule ID from rule_id
        source_rule_id = rule_id
        if ':' in str(rule_id):
            source_rule_id = str(rule_id).split(':')[0]

        # Create rule selection buttons
        buttons = await create_copy_rule_buttons(source_rule_id, page)
        await event.edit("Select the target rule to copy the current rule to:", buttons=buttons)
    except Exception as e:
        logger.error(f"Error showing copy rule interface: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer("Failed to show copy rule interface")

    return

async def create_copy_rule_buttons(rule_id, page=0):
    """Create copy rule button list.

    Args:
        rule_id: Current rule ID
        page: Current page

    Returns:
        Button list
    """
    # Set pagination parameters

    buttons = []
    session = get_session()

    try:
        # Get current rule
        if ':' in str(rule_id):
            parts = str(rule_id).split(':')
            source_rule_id = int(parts[0])
        else:
            source_rule_id = int(rule_id)

        current_rule = session.query(ForwardRule).get(source_rule_id)
        if not current_rule:
            buttons.append([Button.inline('❌ Rule not found', 'noop')])
            buttons.append([Button.inline('Close', 'close_settings')])
            return buttons

        # Get all rules (except current rule)
        all_rules = session.query(ForwardRule).filter(
            ForwardRule.id != source_rule_id
        ).all()

        # Calculate pagination
        total_rules = len(all_rules)
        total_pages = (total_rules + RULES_PER_PAGE - 1) // RULES_PER_PAGE

        if total_rules == 0:
            buttons.append([
                Button.inline('👈 Back', f"other_settings:{source_rule_id}"),
                Button.inline('❌ Close', 'close_settings')
            ])
            return buttons

        # Get rules for current page
        start_idx = page * RULES_PER_PAGE
        end_idx = min(start_idx + RULES_PER_PAGE, total_rules)
        current_page_rules = all_rules[start_idx:end_idx]

        # Create rule buttons
        for rule in current_page_rules:
            # Get source and target chat names
            source_chat = rule.source_chat
            target_chat = rule.target_chat

            # Build button text
            button_text = f"{rule.id} {source_chat.name}->{target_chat.name}"

            # Build callback data: perform_copy_rule:source_rule_id:target_rule_id
            callback_data = f"perform_copy_rule:{source_rule_id}:{rule.id}"

            buttons.append([Button.inline(button_text, callback_data)])

        # Add pagination buttons
        page_buttons = []

        if total_pages > 1:
            # Previous page button
            if page > 0:
                page_buttons.append(Button.inline("⬅️", f"copy_rule:{source_rule_id}:{page-1}"))
            else:
                page_buttons.append(Button.inline("⬅️", f"noop"))

            # Page indicator
            page_buttons.append(Button.inline(f"{page+1}/{total_pages}", f"noop"))

            # Next page button
            if page < total_pages - 1:
                page_buttons.append(Button.inline("➡️", f"copy_rule:{source_rule_id}:{page+1}"))
            else:
                page_buttons.append(Button.inline("➡️", f"noop"))

        if page_buttons:
            buttons.append(page_buttons)

        buttons.append([
            Button.inline('👈 Back', f"other_settings:{source_rule_id}"),
            Button.inline('❌ Close', 'close_settings')
        ])

    finally:
        session.close()

    return buttons

async def callback_perform_copy_rule(event, rule_id_data, session, message, data):
    """Execute copy rule operation.

    Args:
        rule_id_data: Format "source_rule_id:target_rule_id"
    """
    try:
        # Parse rule ID
        parts = rule_id_data.split(':')
        if len(parts) != 2:
            await event.answer("Invalid data format")
            return

        source_rule_id = int(parts[0])
        target_rule_id = int(parts[1])

        # Get source and target rules
        source_rule = session.query(ForwardRule).get(source_rule_id)
        target_rule = session.query(ForwardRule).get(target_rule_id)

        if not source_rule or not target_rule:
            await event.answer("Source or target rule not found")
            return

        if source_rule.id == target_rule.id:
            await event.answer('Cannot copy a rule to itself')
            return

        # Track success counts for each section
        keywords_normal_success = 0
        keywords_normal_skip = 0
        keywords_regex_success = 0
        keywords_regex_skip = 0
        replace_rules_success = 0
        replace_rules_skip = 0
        media_extensions_success = 0
        media_extensions_skip = 0
        rule_syncs_success = 0
        rule_syncs_skip = 0

        # Copy plain keywords
        for keyword in source_rule.keywords:
            if not keyword.is_regex:  # plain keyword
                # Check if already exists
                exists = any(not k.is_regex and k.keyword == keyword.keyword and k.is_blacklist == keyword.is_blacklist
                           for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_normal_success += 1
                else:
                    keywords_normal_skip += 1

        # Copy regex keywords
        for keyword in source_rule.keywords:
            if keyword.is_regex:  # regex keyword
                # Check if already exists
                exists = any(k.is_regex and k.keyword == keyword.keyword and k.is_blacklist == keyword.is_blacklist
                           for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_regex_success += 1
                else:
                    keywords_regex_skip += 1

        # Copy replace rules
        for replace_rule in source_rule.replace_rules:
            # Check if already exists
            exists = any(r.pattern == replace_rule.pattern and r.content == replace_rule.content
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                replace_rules_success += 1
            else:
                replace_rules_skip += 1

        # Copy media extensions settings
        if hasattr(source_rule, 'media_extensions') and source_rule.media_extensions:
            for extension in source_rule.media_extensions:
                # Check if already exists
                exists = any(e.extension == extension.extension for e in target_rule.media_extensions)
                if not exists:
                    new_extension = MediaExtensions(
                        rule_id=target_rule.id,
                        extension=extension.extension
                    )
                    session.add(new_extension)
                    media_extensions_success += 1
                else:
                    media_extensions_skip += 1

        # Copy media type settings
        if hasattr(source_rule, 'media_types') and source_rule.media_types:
            target_media_types = session.query(MediaTypes).filter_by(rule_id=target_rule.id).first()

            if not target_media_types:
                # Create new media types entry for target rule if not exists
                target_media_types = MediaTypes(rule_id=target_rule.id)

                # Use inspect to auto-copy all fields (except id and rule_id)
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

                session.add(target_media_types)
            else:
                # If settings already exist, update them
                # Use inspect to auto-copy all fields (except id and rule_id)
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

        # Copy rule sync table data
        # Check if source rule has sync relationships
        if hasattr(source_rule, 'rule_syncs') and source_rule.rule_syncs:
            for sync in source_rule.rule_syncs:
                # Check if already exists
                exists = any(s.sync_rule_id == sync.sync_rule_id for s in target_rule.rule_syncs)
                if not exists:
                    # Ensure no self-referencing sync relationship is created
                    if sync.sync_rule_id != target_rule.id:
                        new_sync = RuleSync(
                            rule_id=target_rule.id,
                            sync_rule_id=sync.sync_rule_id
                        )
                        session.add(new_sync)
                        rule_syncs_success += 1

                        # Enable sync on target rule
                        if rule_syncs_success > 0:
                            target_rule.enable_sync = True
                else:
                    rule_syncs_skip += 1

        # Copy rule settings
        # Save original associations of target rule
        original_source_chat_id = target_rule.source_chat_id
        original_target_chat_id = target_rule.target_chat_id

        # Get all ForwardRule model fields
        inspector = inspect(ForwardRule)
        for column in inspector.columns:
            column_name = column.key
            if column_name not in ['id', 'source_chat_id', 'target_chat_id', 'source_chat', 'target_chat',
                                  'keywords', 'replace_rules', 'media_types']:
                # Copy source rule values to target rule
                value = getattr(source_rule, column_name)
                setattr(target_rule, column_name, value)

        # Restore original associations of target rule
        target_rule.source_chat_id = original_source_chat_id
        target_rule.target_chat_id = original_target_chat_id

        # Save changes
        session.commit()

        # Build message content
        result_message = (
            f"✅ Copied from rule `{source_rule_id}` to rule `{target_rule.id}`\n\n"
            f"Plain keywords: {keywords_normal_success} copied, {keywords_normal_skip} skipped (duplicate)\n"
            f"Regex keywords: {keywords_regex_success} copied, {keywords_regex_skip} skipped (duplicate)\n"
            f"Replace rules: {replace_rules_success} copied, {replace_rules_skip} skipped (duplicate)\n"
            f"Media extensions: {media_extensions_success} copied, {media_extensions_skip} skipped (duplicate)\n"
            f"Sync rules: {rule_syncs_success} copied, {rule_syncs_skip} skipped (duplicate)\n"
            f"Media type settings and other rule settings copied\n"
        )

        # Create back to settings button
        buttons = [[
            Button.inline('👈 Back to settings', f"other_settings:{source_rule.id}"),
            Button.inline('❌ Close', 'close_settings')
        ]]

        # Delete original message
        await message.delete()

        # Send new message
        await send_message_and_delete(
            event.client,
            event.chat_id,
            result_message,
            buttons=buttons,
            parse_mode='markdown'
        )

        await event.answer(f"Copied all settings from rule {source_rule_id} to rule {target_rule_id}")

    except Exception as e:
        logger.error(f"Error copying rule: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer(f"Failed to copy rule: {str(e)}")
    return

async def callback_copy_keyword(event, rule_id, session, message, data):
    """Copy keywords.

    Shows a rule selection list for the user to choose the target rule.
    After selection, copies keywords from current rule to target rule.
    """
    try:
        # Call generic rule selection function
        await show_rule_selection(
            event, rule_id, data, "Select the target rule to copy keywords to:", "perform_copy_keyword"
        )
    except Exception as e:
        logger.error(f"Error showing copy keywords interface: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer("Failed to show copy keywords interface")
    return

async def callback_copy_replace(event, rule_id, session, message, data):
    """Copy replace rules.

    Shows a rule selection list for the user to choose the target rule.
    After selection, copies replace rules from current rule to target rule.
    """
    try:
        # Call generic rule selection function
        await show_rule_selection(
            event, rule_id, data, "Select the target rule to copy replace rules to:", "perform_copy_replace"
        )
    except Exception as e:
        logger.error(f"Error showing copy replace rules interface: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer("Failed to show copy replace rules interface")
    return

async def callback_perform_copy_keyword(event, rule_id_data, session, message, data):
    """Execute copy keywords operation.

    Args:
        rule_id_data: Format "source_rule_id:target_rule_id"
    """
    try:
        # Parse rule ID
        source_rule_id, target_rule_id = await parse_rule_ids(event, rule_id_data)
        if source_rule_id is None or target_rule_id is None:
            return

        # Get source and target rules
        source_rule, target_rule = await get_rules(event, session, source_rule_id, target_rule_id)
        if not source_rule or not target_rule:
            return

        # Track success counts for each section
        keywords_normal_success = 0
        keywords_normal_skip = 0
        keywords_regex_success = 0
        keywords_regex_skip = 0

        # Copy plain keywords
        for keyword in source_rule.keywords:
            if not keyword.is_regex:  # plain keyword
                # Check if already exists
                exists = any(not k.is_regex and k.keyword == keyword.keyword and k.is_blacklist == keyword.is_blacklist
                           for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_normal_success += 1
                else:
                    keywords_normal_skip += 1

        # Copy regex keywords
        for keyword in source_rule.keywords:
            if keyword.is_regex:  # regex keyword
                # Check if already exists
                exists = any(k.is_regex and k.keyword == keyword.keyword and k.is_blacklist == keyword.is_blacklist
                           for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_regex_success += 1
                else:
                    keywords_regex_skip += 1

        # Save changes
        session.commit()

        # Build message content
        result_message = (
            f"✅ Copied keywords from rule `{source_rule_id}` to rule `{target_rule.id}`\n\n"
            f"Plain keywords: {keywords_normal_success} copied, {keywords_normal_skip} skipped (duplicate)\n"
            f"Regex keywords: {keywords_regex_success} copied, {keywords_regex_skip} skipped (duplicate)\n"
        )

        # Send result message
        await send_result_message(event, message, result_message, source_rule.id)

        await event.answer(f"Copied keywords from rule {source_rule_id} to rule {target_rule_id}")

    except Exception as e:
        logger.error(f"Error copying keywords: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer(f"Failed to copy keywords: {str(e)}")
    return

async def callback_perform_copy_replace(event, rule_id_data, session, message, data):
    """Execute copy replace rules operation.

    Args:
        rule_id_data: Format "source_rule_id:target_rule_id"
    """
    try:
        # Parse rule ID
        source_rule_id, target_rule_id = await parse_rule_ids(event, rule_id_data)
        if source_rule_id is None or target_rule_id is None:
            return

        # Get source and target rules
        source_rule, target_rule = await get_rules(event, session, source_rule_id, target_rule_id)
        if not source_rule or not target_rule:
            return

        # Track copy success counts
        replace_rules_success = 0
        replace_rules_skip = 0

        # Copy replace rules
        for replace_rule in source_rule.replace_rules:
            # Check if already exists
            exists = any(r.pattern == replace_rule.pattern and r.content == replace_rule.content
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                replace_rules_success += 1
            else:
                replace_rules_skip += 1

        # Save changes
        session.commit()

        # Build message content
        result_message = (
            f"✅ Copied replace rules from rule `{source_rule_id}` to rule `{target_rule.id}`\n\n"
            f"Replace rules: {replace_rules_success} copied, {replace_rules_skip} skipped (duplicate)\n"
        )

        # Send result message
        await send_result_message(event, message, result_message, source_rule.id)

        await event.answer(f"Copied replace rules from rule {source_rule_id} to rule {target_rule_id}")

    except Exception as e:
        logger.error(f"Error copying replace rules: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer(f"Failed to copy replace rules: {str(e)}")
    return

# Generic helper function
async def show_rule_selection(event, rule_id, data, title, callback_action):
    """Generic function to show rule selection interface

    Args:
        event: Event object
        rule_id: Current rule ID
        data: Callback data
        title: Display title
        callback_action: Callback action to execute after selection
    """
    # Check for page parameter
    parts = data.split(':')
    page = 0
    if len(parts) > 2:
        page = int(parts[2])

    # Extract source rule ID from rule_id
    source_rule_id = rule_id
    if ':' in str(rule_id):
        source_rule_id = str(rule_id).split(':')[0]

    # Create rule selection buttons
    buttons = await create_rule_selection_buttons(source_rule_id, page, callback_action)
    await event.edit(title, buttons=buttons)

async def create_rule_selection_buttons(rule_id, page=0, callback_action="perform_copy_rule"):
    """Generic function to create rule selection buttons

    Args:
        rule_id: Current rule ID
        page: Current page
        callback_action: Callback action on button click

    Returns:
        Button list
    """
    # Set pagination parameters

    buttons = []
    session = get_session()

    try:
        # Get current rule
        if ':' in str(rule_id):
            parts = str(rule_id).split(':')
            source_rule_id = int(parts[0])
        else:
            source_rule_id = int(rule_id)

        current_rule = session.query(ForwardRule).get(source_rule_id)
        if not current_rule:
            buttons.append([Button.inline('❌ Rule not found', 'noop')])
            buttons.append([Button.inline('Close', 'close_settings')])
            return buttons

        # Get all rules (except current rule)
        all_rules = session.query(ForwardRule).filter(
            ForwardRule.id != source_rule_id
        ).all()

        # Calculate pagination
        total_rules = len(all_rules)
        total_pages = (total_rules + RULES_PER_PAGE - 1) // RULES_PER_PAGE

        if total_rules == 0:
            # buttons.append([Button.inline('❌ No rules available', 'noop')])
            buttons.append([
                Button.inline('👈 Back', f"other_settings:{source_rule_id}"),
                Button.inline('❌ Close', 'close_settings')
            ])
            return buttons

        # Get rules for current page
        start_idx = page * RULES_PER_PAGE
        end_idx = min(start_idx + RULES_PER_PAGE, total_rules)
        current_page_rules = all_rules[start_idx:end_idx]

        # Create rule buttons
        for rule in current_page_rules:
            # Get source and target chat names
            source_chat = rule.source_chat
            target_chat = rule.target_chat

            # Build button text
            button_text = f"{rule.id} {source_chat.name}->{target_chat.name}"

            # Build callback data: callback_action:source_rule_id:target_rule_id
            callback_data = f"{callback_action}:{source_rule_id}:{rule.id}"

            buttons.append([Button.inline(button_text, callback_data)])

        # Add pagination buttons
        page_buttons = []
        action_name = callback_action.replace("perform_", "")

        if total_pages > 1:
            # Previous page button
            if page > 0:
                page_buttons.append(Button.inline("⬅️", f"{action_name}:{source_rule_id}:{page-1}"))
            else:
                page_buttons.append(Button.inline("⬅️", f"noop"))

            # Page indicator
            page_buttons.append(Button.inline(f"{page+1}/{total_pages}", f"noop"))

            # Next page button
            if page < total_pages - 1:
                page_buttons.append(Button.inline("➡️", f"{action_name}:{source_rule_id}:{page+1}"))
            else:
                page_buttons.append(Button.inline("➡️", f"noop"))

        if page_buttons:
            buttons.append(page_buttons)

        buttons.append([
            Button.inline('👈 Back', f"other_settings:{source_rule_id}"),
            Button.inline('❌ Close', 'close_settings')
        ])

    finally:
        session.close()

    return buttons

async def parse_rule_ids(event, rule_id_data):
    """Parse rule ID.

    Args:
        event: Event object
        rule_id_data: Format "source_rule_id:target_rule_id"

    Returns:
        (source_rule_id, target_rule_id) or (None, None)
    """
    parts = rule_id_data.split(':')
    if len(parts) != 2:
        await event.answer("Invalid data format")
        return None, None

    source_rule_id = int(parts[0])
    target_rule_id = int(parts[1])

    if source_rule_id == target_rule_id:
        await event.answer('Cannot copy to itself')
        return None, None

    return source_rule_id, target_rule_id

async def get_rules(event, session, source_rule_id, target_rule_id):
    """Get source and target rules.

    Args:
        event: Event object
        session: Database session
        source_rule_id: Source rule ID
        target_rule_id: Target rule ID

    Returns:
        (source_rule, target_rule) or (None, None)
    """
    source_rule = session.query(ForwardRule).get(source_rule_id)
    target_rule = session.query(ForwardRule).get(target_rule_id)

    if not source_rule or not target_rule:
        await event.answer("Source or target rule not found")
        return None, None

    return source_rule, target_rule

async def send_result_message(event, message, result_message, target_rule_id):
    """Send result message.

    Args:
        event: Event object
        message: Original message object
        result_message: Result message content
        target_rule_id: Target rule ID
    """
    # Create back to settings button
    buttons = [[
        Button.inline('👈 Back to settings', f"other_settings:{target_rule_id}"),
        Button.inline('❌ Close', 'close_settings')
    ]]

    # Delete original message
    await message.delete()

    # Send new message
    await send_message_and_delete(
        event.client,
        event.chat_id,
        result_message,
        buttons=buttons,
        parse_mode='markdown'
    )

async def callback_clear_keyword(event, rule_id, session, message, data):
    """Show clear keywords rule selection interface"""
    try:
        # Check for page parameter
        parts = data.split(':')
        page = 0
        if len(parts) > 2:
            page = int(parts[2])

        # Get rule info
        current_rule = session.query(ForwardRule).get(int(rule_id))
        if not current_rule:
            await event.answer("Rule not found")
            return

        # Build button list, starting with current rule
        buttons = []
        source_chat = current_rule.source_chat
        target_chat = current_rule.target_chat

        # Current rule button
        current_button_text = f"🗑️ Clear current rule"
        current_callback_data = f"perform_clear_keyword:{current_rule.id}"
        buttons.append([Button.inline(current_button_text, current_callback_data)])

        # Check if there are other rules
        other_rules = session.query(ForwardRule).filter(
            ForwardRule.id != current_rule.id
        ).count()

        if other_rules > 0:
            # Separator
            buttons.append([Button.inline("---------", "noop")])

            # Add other rule buttons
            other_buttons = await create_rule_selection_buttons(rule_id, page, "perform_clear_keyword")

            # Append all other rule buttons to list
            buttons.extend(other_buttons)
        else:
            # Add back and close buttons
            buttons.append([
                Button.inline('👈 Back', f"other_settings:{current_rule.id}"),
                Button.inline('❌ Close', 'close_settings')
            ])

        await event.edit("Select the rule to clear keywords from:", buttons=buttons)
    except Exception as e:
        logger.error(f"Error showing clear keywords interface: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer("Failed to show clear keywords interface")
    return

async def callback_clear_replace(event, rule_id, session, message, data):
    """Show clear replace rules selection interface"""
    try:
        # Check for page parameter
        parts = data.split(':')
        page = 0
        if len(parts) > 2:
            page = int(parts[2])

        # Get rule info
        current_rule = session.query(ForwardRule).get(int(rule_id))
        if not current_rule:
            await event.answer("Rule not found")
            return

        # Build button list, starting with current rule
        buttons = []
        source_chat = current_rule.source_chat
        target_chat = current_rule.target_chat

        # Current rule button
        current_button_text = f"🗑️ Clear current rule"
        current_callback_data = f"perform_clear_replace:{current_rule.id}"
        buttons.append([Button.inline(current_button_text, current_callback_data)])

        # Check if there are other rules
        other_rules = session.query(ForwardRule).filter(
            ForwardRule.id != current_rule.id
        ).count()

        if other_rules > 0:
            # Separator
            buttons.append([Button.inline("---------", "noop")])

            # Add other rule buttons
            other_buttons = await create_rule_selection_buttons(rule_id, page, "perform_clear_replace")

            # Append all other rule buttons to list
            buttons.extend(other_buttons)
        else:
            # Add back and close buttons
            buttons.append([
                Button.inline('👈 Back', f"other_settings:{current_rule.id}"),
                Button.inline('❌ Close', 'close_settings')
            ])

        await event.edit("Select the rule to clear replace rules from:", buttons=buttons)
    except Exception as e:
        logger.error(f"Error showing clear replace rules interface: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer("Failed to show clear replace rules interface")
    return

async def callback_delete_rule(event, rule_id, session, message, data):
    """Show delete rule selection interface"""
    try:
        # Check for page parameter
        parts = data.split(':')
        page = 0
        if len(parts) > 2:
            page = int(parts[2])

        source_rule_id = rule_id
        if ':' in str(rule_id):
            source_rule_id = str(rule_id).split(':')[0]

        # Get rule info
        current_rule = session.query(ForwardRule).get(int(source_rule_id))
        if not current_rule:
            await event.answer("Rule not found")
            return

        # Build button list, starting with current rule
        buttons = []
        source_chat = current_rule.source_chat
        target_chat = current_rule.target_chat

        # Current rule button
        current_button_text = f"❌ Delete current rule"
        current_callback_data = f"perform_delete_rule:{current_rule.id}"
        buttons.append([Button.inline(current_button_text, current_callback_data)])

        # Check if there are other rules
        other_rules = session.query(ForwardRule).filter(
            ForwardRule.id != current_rule.id
        ).count()

        if other_rules > 0:
            # Separator
            buttons.append([Button.inline("---------", "noop")])

            # Add other rule buttons
            other_buttons = await create_rule_selection_buttons(rule_id, page, "perform_delete_rule")

            # Append all other rule buttons to list
            buttons.extend(other_buttons)
        else:
            # Add back and close buttons
            buttons.append([
                Button.inline('👈 Back', f"other_settings:{current_rule.id}"),
                Button.inline('❌ Close', 'close_settings')
            ])

        await event.edit("Select the rule to delete:", buttons=buttons)
    except Exception as e:
        logger.error(f"Error showing delete rule interface: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer("Failed to show delete rule interface")
    return

# Execute clear keywords callback
async def callback_perform_clear_keyword(event, rule_id_data, session, message, data):
    """Execute clear keywords operation"""
    try:
        # Check for multiple rule IDs (source_id:target_id format)
        if ':' in rule_id_data:
            # Parse rule ID
            source_rule_id, target_rule_id = await parse_rule_ids(event, rule_id_data)
            if source_rule_id is None or target_rule_id is None:
                return

            # Use target rule ID
            rule_id = target_rule_id
        else:
            # Single rule ID case (current rule)
            rule_id = int(rule_id_data)

        # Get rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            await event.answer("Rule not found")
            return

        # Get and delete all keywords
        keyword_count = len(rule.keywords)

        # Delete all keywords
        session.query(Keyword).filter(Keyword.rule_id == rule.id).delete()
        session.commit()

        # Build message content
        result_message = f"✅ Cleared all {keyword_count} keywords from rule `{rule.id}`"

        # Back button points to source rule settings page (if applicable)
        source_id = int(rule_id_data.split(':')[0]) if ':' in rule_id_data else rule.id

        # Send result message
        # Create back to settings button
        buttons = [[
            Button.inline('👈 Back to settings', f"other_settings:{source_id}"),
            Button.inline('❌ Close', 'close_settings')
        ]]

        # Delete original message
        await message.delete()

        # Send new message
        await send_message_and_delete(
            event.client,
            event.chat_id,
            result_message,
            buttons=buttons,
            parse_mode='markdown'
        )

        await event.answer(f"Cleared all keywords from rule {rule.id}")

    except Exception as e:
        logger.error(f"Error clearing keywords: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer(f"Failed to clear keywords: {str(e)}")
    return

# Execute clear replace rules callback
async def callback_perform_clear_replace(event, rule_id_data, session, message, data):
    """Execute clear replace rules operation"""
    try:
        # Check for multiple rule IDs (source_id:target_id format)
        if ':' in rule_id_data:
            # Parse rule ID
            source_rule_id, target_rule_id = await parse_rule_ids(event, rule_id_data)
            if source_rule_id is None or target_rule_id is None:
                return

            # Use target rule ID
            rule_id = target_rule_id
        else:
            # Single rule ID case (current rule)
            rule_id = int(rule_id_data)

        # Get rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            await event.answer("Rule not found")
            return

        # Get and delete all replace rules
        replace_count = len(rule.replace_rules)

        # Delete all replace rules
        session.query(ReplaceRule).filter(ReplaceRule.rule_id == rule.id).delete()
        session.commit()

        # Build message content
        result_message = f"✅ Cleared all {replace_count} replace rules from rule `{rule.id}`"

        # Back button points to source rule settings page (if applicable)
        source_id = int(rule_id_data.split(':')[0]) if ':' in rule_id_data else rule.id

        # Send result message
        # Create back to settings button
        buttons = [[
            Button.inline('👈 Back to settings', f"other_settings:{source_id}"),
            Button.inline('❌ Close', 'close_settings')
        ]]

        # Delete original message
        await message.delete()

        # Send new message
        await send_message_and_delete(
            event.client,
            event.chat_id,
            result_message,
            buttons=buttons,
            parse_mode='markdown'
        )

        await event.answer(f"Cleared all replace rules from rule {rule.id}")

    except Exception as e:
        logger.error(f"Error clearing replace rules: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer(f"Failed to clear replace rules: {str(e)}")
    return

# Execute delete rule callback
async def callback_perform_delete_rule(event, rule_id_data, session, message, data):
    """Execute delete rule operation"""
    try:
        # Check for multiple rule IDs (source_id:target_id format)
        if ':' in rule_id_data:
            # Try parsing with parse_rule_ids function
            parts = rule_id_data.split(':')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                source_rule_id = int(parts[0])
                target_rule_id = int(parts[1])
                # Use target rule ID
                rule_id = target_rule_id
            else:
                # If not source_id:target_id format, may be rule_id:page format
                # Take only the first part as rule ID
                rule_id = int(parts[0])
        else:
            # Single rule ID case (current rule)
            rule_id = int(rule_id_data)

        # Get rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            await event.answer("Rule not found")
            return

        # Save rule object for later chat association check
        rule_obj = rule

        # Delete replace rules first
        session.query(ReplaceRule).filter(
            ReplaceRule.rule_id == rule.id
        ).delete()

        # Then delete keywords
        session.query(Keyword).filter(
            Keyword.rule_id == rule.id
        ).delete()

        # Delete media extensions
        if hasattr(rule, 'media_extensions'):
            session.query(MediaExtensions).filter(MediaExtensions.rule_id == rule.id).delete()

        # Delete media types
        if hasattr(rule, 'media_types'):
            session.query(MediaTypes).filter(MediaTypes.rule_id == rule.id).delete()

        # Delete rule sync relationships
        if hasattr(rule, 'rule_syncs'):
            session.query(RuleSync).filter(RuleSync.rule_id == rule.id).delete()
            session.query(RuleSync).filter(RuleSync.sync_rule_id == rule.id).delete()

        # Delete rule
        session.delete(rule)

        # Commit rule deletion changes
        session.commit()

        # Try to delete related data from RSS service
        try:
            rss_url = f"http://{RSS_HOST}:{RSS_PORT}/api/rule/{rule_id}"
            async with aiohttp.ClientSession() as client_session:
                async with client_session.delete(rss_url) as response:
                    if response.status == 200:
                        logger.info(f"RSS rule data deleted: {rule_id}")
                    else:
                        response_text = await response.text()
                        logger.warning(f"Failed to delete RSS rule data {rule_id}, status: {response.status}, response: {response_text}")
        except Exception as rss_err:
            logger.error(f"Error calling RSS delete API: {str(rss_err)}")
            # Non-fatal, continue

        # Clean up chat records that are no longer in use
        deleted_chats = await check_and_clean_chats(session, rule_obj)
        if deleted_chats > 0:
            logger.info(f"Cleaned up {deleted_chats} unused chat records after rule deletion")

        # Build message content
        result_message = f"✅ Rule `{rule.id}` deleted"

        # Delete original message
        await message.delete()

        # Get source rule ID (if applicable)
        source_id = int(rule_id_data.split(':')[0]) if ':' in rule_id_data else None

        # Prepare buttons
        if source_id and source_id != rule.id:
            # If deleted from another rule, provide back button to source rule
            buttons = [[
                Button.inline('👈 Back to settings', f"other_settings:{source_id}"),
                Button.inline('❌ Close', 'close_settings')
            ]]
        else:
            # If current rule was deleted, only provide close button
            buttons = [[Button.inline('❌ Close', 'close_settings')]]

        # Send result message
        await send_message_and_delete(
            event.client,
            event.chat_id,
            result_message,
            buttons=buttons,
            parse_mode='markdown'
        )

        await event.answer("Rule deleted successfully")

    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting rule: {str(e)}")
        logger.error(f"Details: {traceback.format_exc()}")
        await event.answer(f"Failed to delete rule: {str(e)}")
    return

async def callback_set_userinfo_template(event, rule_id, session, message, data):
    """Set user info template"""
    logger.info(f"Handling set userinfo template callback - event: {event}, rule_id: {rule_id}")

    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('Rule not found')
        return

    # Check if channel message
    if isinstance(event.chat, types.Channel):
        # Check if admin
        if not await is_admin(event):
            await event.answer('Only admins can modify settings')
            return
        user_id = os.getenv('USER_ID')
    else:
        user_id = event.sender_id

    chat_id = abs(event.chat_id)
    state = f"set_userinfo_template:{rule_id}"

    logger.info(f"Setting state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message, state_type="userinfo")
        # Start timeout cancel task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("State set successfully")
    except Exception as e:
        logger.error(f"Error setting state: {str(e)}")
        logger.exception(e)

    try:
        current_template = rule.userinfo_template if hasattr(rule, 'userinfo_template') and rule.userinfo_template else 'Not set'

        help_text = (
            "User info template adds user information to forwarded messages.\n"
            "Available variables:\n"
            "{name} - Username\n"
            "{id} - User ID\n"
        )

        await message.edit(
            f"Please send the new user info template\n"
            f"Current rule ID: `{rule_id}`\n"
            f"Current user info template:\n\n`{current_template}`\n\n"
            f"{help_text}\n"
            f"Will auto-cancel in 5 minutes if not set",
            buttons=[[Button.inline("Cancel", f"cancel_set_userinfo:{rule_id}")]]
        )
        logger.info("Message edited successfully")
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        logger.exception(e)
    return

async def callback_set_time_template(event, rule_id, session, message, data):
    """Set time template"""
    logger.info(f"Handling set time template callback - event: {event}, rule_id: {rule_id}")

    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('Rule not found')
        return

    # Check if channel message
    if isinstance(event.chat, types.Channel):
        # Check if admin
        if not await is_admin(event):
            await event.answer('Only admins can modify settings')
            return
        user_id = os.getenv('USER_ID')
    else:
        user_id = event.sender_id

    chat_id = abs(event.chat_id)
    state = f"set_time_template:{rule_id}"

    logger.info(f"Setting state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message, state_type="time")
        # Start timeout cancel task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("State set successfully")
    except Exception as e:
        logger.error(f"Error setting state: {str(e)}")
        logger.exception(e)

    try:
        current_template = rule.time_template if hasattr(rule, 'time_template') and rule.time_template else 'Not set'

        help_text = (
            "Time template adds time information to forwarded messages.\n"
            "Available variables:\n"
            "{time} - Current time\n"
        )

        await message.edit(
            f"Please send the new time template\n"
            f"Current rule ID: `{rule_id}`\n"
            f"Current time template:\n\n`{current_template}`\n\n"
            f"{help_text}\n"
            f"Will auto-cancel in 5 minutes if not set",
            buttons=[[Button.inline("Cancel", f"cancel_set_time:{rule_id}")]]
        )
        logger.info("Message edited successfully")
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        logger.exception(e)
    return

async def cancel_state_after_timeout(user_id: int, chat_id: int, timeout_minutes: int = 5):
    """Auto-cancel state after the specified timeout"""
    await asyncio.sleep(timeout_minutes * 60)
    current_state, _, _ = state_manager.get_state(user_id, chat_id)
    if current_state:  # Only clear if state still exists
        logger.info(f"State auto-cancelled due to timeout - user_id: {user_id}, chat_id: {chat_id}")
        state_manager.clear_state(user_id, chat_id)

async def callback_cancel_set_userinfo(event, rule_id, session, message, data):
    """Cancel setting user info template"""
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # Clear state
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # Return to other settings page
            await event.edit("Other settings:", buttons=await create_other_settings_buttons(rule_id=rule_id))
            await event.answer("Cancelled")
    finally:
        session.close()
    return

async def callback_cancel_set_time(event, rule_id, session, message, data):
    """Cancel setting time template"""
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # Clear state
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # Return to other settings page
            await event.edit("Other settings:", buttons=await create_other_settings_buttons(rule_id=rule_id))
            await event.answer("Cancelled")
    finally:
        session.close()
    return

async def callback_set_original_link_template(event, rule_id, session, message, data):
    """Set original link template"""
    logger.info(f"Handling set original link template callback - event: {event}, rule_id: {rule_id}")

    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('Rule not found')
        return

    # Check if channel message
    if isinstance(event.chat, types.Channel):
        # Check if admin
        if not await is_admin(event):
            await event.answer('Only admins can modify settings')
            return
        user_id = os.getenv('USER_ID')
    else:
        user_id = event.sender_id

    chat_id = abs(event.chat_id)
    state = f"set_original_link_template:{rule_id}"

    logger.info(f"Setting state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message, state_type="link")
        # Start timeout cancel task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("State set successfully")
    except Exception as e:
        logger.error(f"Error setting state: {str(e)}")
        logger.exception(e)

    try:
        current_template = rule.original_link_template if hasattr(rule, 'original_link_template') and rule.original_link_template else 'Not set'

        help_text = (
            "Original link template adds the original link to forwarded messages.\n"
            "Available variables:\n"
            "{original_link} - Full original link\n"
        )

        await message.edit(
            f"Please send the new original link template\n"
            f"Current rule ID: `{rule_id}`\n"
            f"Current original link template:\n\n`{current_template}`\n\n"
            f"{help_text}\n"
            f"Will auto-cancel in 5 minutes if not set",
            buttons=[[Button.inline("Cancel", f"cancel_set_link:{rule_id}")]]
        )
        logger.info("Message edited successfully")
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        logger.exception(e)
    return

async def callback_cancel_set_original_link(event, rule_id, session, message, data):
    """Cancel setting original link template"""
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # Clear state
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # Return to other settings page
            await event.edit("Other settings:", buttons=await create_other_settings_buttons(rule_id=rule_id))
            await event.answer("Cancelled")
    finally:
        session.close()
    return

async def callback_toggle_reverse_blacklist(event, rule_id, session, message, data):
    """Toggle reverse blacklist setting"""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            rule.enable_reverse_blacklist = not rule.enable_reverse_blacklist
            session.commit()
            await event.answer("Settings updated")

            await event.edit(
                buttons=await create_other_settings_buttons(rule_id=rule_id)
            )
    except Exception as e:
        logger.error(f"Error toggling reverse blacklist setting: {str(e)}")
        await event.answer("Failed to update settings")
    return

async def callback_toggle_reverse_whitelist(event, rule_id, session, message, data):
    """Toggle reverse whitelist setting"""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            rule.enable_reverse_whitelist = not rule.enable_reverse_whitelist
            session.commit()
            await event.answer("Settings updated")

            await event.edit(
                buttons=await create_other_settings_buttons(rule_id=rule_id)
            )
    except Exception as e:
        logger.error(f"Error toggling reverse whitelist setting: {str(e)}")
        await event.answer("Failed to update settings")
    return
