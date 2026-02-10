from sqlalchemy.exc import IntegrityError
from telethon import Button
from models.models import MediaTypes, MediaExtensions
from enums.enums import AddMode, ForwardMode
from models.models import get_session, Keyword, ReplaceRule, User, RuleSync
from utils.common import *
from utils.media import *
from handlers.list_handlers import *
from utils.constants import TEMP_DIR
import traceback
from sqlalchemy import inspect
from version import VERSION, UPDATE_INFO
import shlex
import logging
import os
import aiohttp
from utils.constants import RSS_HOST, RSS_PORT
import models.models as models
from utils.auto_delete import respond_and_delete,reply_and_delete,async_delete_user_message
from utils.common import get_bot_client
from handlers.button.settings_manager import create_settings_text, create_buttons

logger = logging.getLogger(__name__)

async def handle_bind_command(event, client, parts):
    """Handle bind command"""
    # Use shlex to parse command
    message_text = event.message.text
    try:
        # Remove command prefix, get raw argument string
        if ' ' in message_text:
            command, args_str = message_text.split(' ', 1)
            args = shlex.split(args_str)
            if len(args) >= 1:
                source_target = args[0]
                # Check if there is a second argument (target chat)
                target_chat_input = args[1] if len(args) >= 2 else None
            else:
                raise ValueError("Insufficient arguments")
        else:
            raise ValueError("Insufficient arguments")
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /bind <source chat link or name> [target chat link or name]\nExamples:\n/bind https://t.me/channel_name\n/bind "channel name"\n/bind https://t.me/source_channel https://t.me/target_channel\n/bind "source channel name" "target channel name"')
        return

    # Check if it is a link
    is_source_link = source_target.startswith(('https://', 't.me/'))

    # Default to using current chat as target chat
    current_chat = await event.get_chat()
    
    try:
        # Get user client from main module
        main = await get_main_module()
        user_client = main.user_client

        # Use user client to get source chat entity info
        try:
            if is_source_link:
                # If it is a link, get entity directly
                source_chat_entity = await user_client.get_entity(source_target)
            else:
                # If it is a name, get dialog list and find the first match
                async for dialog in user_client.iter_dialogs():
                    if dialog.name and source_target.lower() in dialog.name.lower():
                        source_chat_entity = dialog.entity
                        break
                else:
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,'No matching source group/channel found, please ensure the name is correct and the account has joined the group/channel')
                    return
            
            # Get target chat entity
            if target_chat_input:
                is_target_link = target_chat_input.startswith(('https://', 't.me/'))
                if is_target_link:
                    # If it is a link, get entity directly
                    target_chat_entity = await user_client.get_entity(target_chat_input)
                else:
                    # If it is a name, get dialog list and find the first match
                    async for dialog in user_client.iter_dialogs():
                        if dialog.name and target_chat_input.lower() in dialog.name.lower():
                            target_chat_entity = dialog.entity
                            break
                    else:
                        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                        await reply_and_delete(event,'No matching target group/channel found, please ensure the name is correct and the account has joined the group/channel')
                        return
            else:
                # Use current chat as target
                target_chat_entity = current_chat

            # # Check if binding to self
            # if str(source_chat_entity.id) == str(target_chat_entity.id):
            #     await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            #     await reply_and_delete(event,'⚠️ Cannot bind channel/group to itself')
            #     return

        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Unable to get chat info, please ensure the link/name is correct and the account has joined the group/channel')
            return
        except Exception as e:
            logger.error(f'Error getting chat info: {str(e)}')
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Error getting chat info, please check logs')
            return

        # Save to database
        session = get_session()
        try:
            # Save source chat
            source_chat_db = session.query(Chat).filter(
                Chat.telegram_chat_id == str(source_chat_entity.id)
            ).first()

            if not source_chat_db:
                source_chat_db = Chat(
                    telegram_chat_id=str(source_chat_entity.id),
                    name=source_chat_entity.title if hasattr(source_chat_entity, 'title') else 'Private Chat'
                )
                session.add(source_chat_db)
                session.flush()

            # Save target chat
            target_chat_db = session.query(Chat).filter(
                Chat.telegram_chat_id == str(target_chat_entity.id)
            ).first()

            if not target_chat_db:
                target_chat_db = Chat(
                    telegram_chat_id=str(target_chat_entity.id),
                    name=target_chat_entity.title if hasattr(target_chat_entity, 'title') else 'Private Chat'
                )
                session.add(target_chat_db)
                session.flush()

            # If no source chat is currently selected, set it to the newly bound chat
            if not target_chat_db.current_add_id:
                target_chat_db.current_add_id = str(source_chat_entity.id)

            # Create forwarding rule
            rule = ForwardRule(
                source_chat_id=source_chat_db.id,
                target_chat_id=target_chat_db.id
            )
            
            # If binding to self, default to whitelist mode
            if str(source_chat_entity.id) == str(target_chat_entity.id):
                rule.forward_mode = ForwardMode.WHITELIST
                rule.add_mode = AddMode.WHITELIST
                
            session.add(rule)
            session.commit()

            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,
                f'Forwarding rule set:\n'
                f'Source chat: {source_chat_db.name} ({source_chat_db.telegram_chat_id})\n'
                f'Target chat: {target_chat_db.name} ({target_chat_db.telegram_chat_id})\n'
                f'Please use /add or /add_regex to add keywords',
                buttons=[Button.inline("⚙️ Open Settings", f"rule_settings:{rule.id}")]
            )

        except IntegrityError:
            session.rollback()
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,
                f'Identical forwarding rule already exists:\n'
                f'Source chat: {source_chat_db.name}\n'
                f'Target chat: {target_chat_db.name}\n'
                f'Use /settings command to modify'
            )
            return
        finally:
            session.close()

    except Exception as e:
        logger.error(f'Error setting forwarding rule: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error setting forwarding rule, please check logs')
        return

async def handle_settings_command(event, command, parts):
    """Handle settings command"""
    # Add logs
    logger.info(f'Processing settings command - parts: {parts}')
    
    # Get arguments
    args = parts[1:] if len(parts) > 1 else []
    
    # Check if rule ID is provided
    if len(args) >= 1 and args[0].isdigit():
        rule_id = int(args[0])
        
        # Open the specified rule settings page directly
        session = get_session()
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                await reply_and_delete(event, f'Cannot find rule with ID {rule_id}')
                return
                
            # Same processing as callback_rule_settings function
            settings_message = await event.respond(
                await create_settings_text(rule),
                buttons=await create_buttons(rule)
            )
            
        except Exception as e:
            logger.error(f'Error opening rule settings: {str(e)}')
            await reply_and_delete(event, 'Error opening rule settings, please check logs')
        finally:
            session.close()
        return
    
    current_chat = await event.get_chat()
    current_chat_id = str(current_chat.id)
    # Add logs
    logger.info(f'Looking for forwarding rules for chat ID: {current_chat_id} ')

    session = get_session()
    try:
        # Add logs, show all chats in database
        all_chats = session.query(Chat).all()
        logger.info('All chats in database:')
        for chat in all_chats:
            logger.info(f'ID: {chat.id}, telegram_chat_id: {chat.telegram_chat_id}, name: {chat.name}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_id
        ).first()

        if not current_chat_db:
            logger.info(f'Cannot find chat ID in database: {current_chat_id}')
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Current chat has no forwarding rules')
            return

        # Add logs
        logger.info(f'Found chat: {current_chat_db.name} (ID: {current_chat_db.id})')

        # Find rules with current chat as target
        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id  # Changed to target_chat_id
        ).all()

        # Add logs
        logger.info(f'Found {len(rules)} forwarding rules')
        for rule in rules:
            logger.info(f'Rule ID: {rule.id}, source chat: {rule.source_chat.name}, target chat: {rule.target_chat.name}')

        if not rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Current chat has no forwarding rules')
            return

        # Create rule selection buttons
        buttons = []
        for rule in rules:
            source_chat = rule.source_chat  # Display source chat
            button_text = f'{source_chat.name}'
            callback_data = f"rule_settings:{rule.id}"
            buttons.append([Button.inline(button_text, callback_data)])
        
        # Delete user message
        client = await get_bot_client()
        await async_delete_user_message(client, event.message.chat_id, event.message.id, 0)

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Please select a forwarding rule to manage:', buttons=buttons)

    except Exception as e:
        logger.info(f'Error getting forwarding rules: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error getting forwarding rules, please check logs')
    finally:
        session.close()

async def handle_switch_command(event):
    """Handle switch command"""
    # Show list of rules that can be switched
    current_chat = await event.get_chat()
    current_chat_id = str(current_chat.id)

    session = get_session()
    try:
        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_id
        ).first()

        if not current_chat_db:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Current chat has no forwarding rules')
            return

        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id
        ).all()

        if not rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Current chat has no forwarding rules')
            return

        # Create rule selection buttons
        buttons = []
        for rule in rules:
            source_chat = rule.source_chat
            # Mark the currently selected rule
            current = current_chat_db.current_add_id == source_chat.telegram_chat_id
            button_text = f'{"✓ " if current else ""}From: {source_chat.name}'
            callback_data = f"switch:{source_chat.telegram_chat_id}"
            buttons.append([Button.inline(button_text, callback_data)])
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Please select a forwarding rule to manage:', buttons=buttons)
    finally:
        session.close()

async def handle_add_command(event, command, parts):
    """Handle add and add_regex commands"""
    message_text = event.message.text
    logger.info(f"Received raw message: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'Usage: /{command} <keyword1> [keyword2] ...\nExamples:\n/{command} keyword1 "key word 2" \'key word 3\'')
        return

    # Separate command and argument parts
    _, args_text = message_text.split(None, 1)
    logger.info(f"Separated argument part: {args_text}")

    keywords = []
    if command in ['add', 'a']:
        try:
            # Use shlex to properly handle quoted arguments
            logger.info("Starting to parse arguments with shlex")
            keywords = shlex.split(args_text)
            logger.info(f"shlex parse result: {keywords}")
        except ValueError as e:
            logger.error(f"shlex parse error: {str(e)}")
            # Handle errors like unclosed quotes
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Argument format error: please ensure quotes are properly paired')
            return
    else:
        # add_regex command keeps as is
        keywords = parts[1:]
        logger.info(f"add_regex command, using raw arguments: {keywords}")

    if not keywords:
        logger.warning("No keywords provided")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Please provide at least one keyword')
        return

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info
        logger.info(f"Current rule ID: {rule.id}, source chat: {source_chat.name}")

        # Use db_operations to add keywords
        db_ops = await get_db_ops()
        logger.info(f"Preparing to add keywords: {keywords}, is_regex={command == 'add_regex'}, is_blacklist={rule.add_mode == AddMode.BLACKLIST}")
        success_count, duplicate_count = await db_ops.add_keywords(
            session,
            rule.id,
            keywords,
            is_regex=(command == 'add_regex'),
            is_blacklist=(rule.add_mode == AddMode.BLACKLIST)
        )
        logger.info(f"Add result: success={success_count}, duplicates={duplicate_count}")

        session.commit()

        # Build reply message
        keyword_type = "regex" if command == "add_regex" else "keyword"
        keywords_text = '\n'.join(f'- {k}' for k in keywords)
        result_text = f'Added {success_count} {keyword_type}(s)'
        if duplicate_count > 0:
            result_text += f'\nSkipped duplicates: {duplicate_count}'
        result_text += f'\nKeyword list:\n{keywords_text}\n'
        result_text += f'Current rule: from {source_chat.name}\n'
        mode_text = 'whitelist' if rule.add_mode == AddMode.WHITELIST else 'blacklist'
        result_text += f'Current keyword add mode: {mode_text}'

        logger.info(f"Sending reply message: {result_text}")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'Error adding keywords: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error adding keywords, please check logs')
    finally:
        session.close()

async def handle_replace_command(event, parts):
    """Handle replace command"""
    message_text = event.message.text
    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /replace <match pattern> [replacement content]\nExamples:\n/replace ad  # Delete matched content\n/replace ad [replaced]\n/replace "ad text" [replaced]\n/replace \'ad text\' [replaced]')
        return

    # Split arguments directly, keeping regex in original form
    try:
        # Remove command prefix, get raw argument string
        _, args_text = message_text.split(None, 1)
        
        # Split by first space, keeping remaining content unchanged
        parts = args_text.split(None, 1)
        if not parts:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Please provide a valid match pattern')
            return
            
        pattern = parts[0]
        content = parts[1] if len(parts) > 1 else ''
        
        logger.info(f"Parsed replace command arguments: pattern='{pattern}', content='{content}'")
        
    except ValueError as e:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'Argument parsing error: {str(e)}\nPlease ensure quotes are properly paired')
        return
        
    if not pattern:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Please provide a valid match pattern')
        return

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Use add_replace_rules to add replace rule
        db_ops = await get_db_ops()
        # Pass patterns and contents arguments separately
        success_count, duplicate_count = await db_ops.add_replace_rules(
            session,
            rule.id,
            [pattern],  # patterns argument
            [content]   # contents argument
        )

        # Ensure replace mode is enabled
        if success_count > 0 and not rule.is_replace:
            rule.is_replace = True

        session.commit()

        # Check if it is full text replacement
        rule_type = "full text replacement" if pattern == ".*" else "regex replacement"
        action_type = "delete" if not content else "replace"

        # Build reply message
        result_text = f'Added {rule_type} rule:\n'
        if success_count > 0:
            result_text += f'Match: {pattern}\n'
            result_text += f'Action: {action_type}\n'
            result_text += f'{"Replace with: " + content if content else "Delete matched content"}\n'
        if duplicate_count > 0:
            result_text += f'Skipped duplicate rules: {duplicate_count}\n'
        result_text += f'Current rule: from {source_chat.name}'

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'Error adding replace rule: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error adding replace rule, please check logs')
    finally:
        session.close()

async def handle_list_keyword_command(event):
    """Handle list_keyword command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Use get_keywords to get all keywords
        db_ops = await get_db_ops()
        rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
        keywords = await db_ops.get_keywords(session, rule.id, rule_mode)

        await show_list(
            event,
            'keyword',
            keywords,
            lambda i, kw: f'{i}. {kw.keyword}{" (regex)" if kw.is_regex else ""}',
            f'Keyword List\nCurrent mode: {"blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"}\nRule: from {source_chat.name}'
        )

    finally:
        session.close()

async def handle_list_replace_command(event):
    """Handle list_replace command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Use get_replace_rules to get all replace rules
        db_ops = await get_db_ops()
        replace_rules = await db_ops.get_replace_rules(session, rule.id)

        await show_list(
            event,
            'replace',
            replace_rules,
            lambda i, rr: f'{i}. Match: {rr.pattern} -> {"delete" if not rr.content else f"replace with: {rr.content}"}',
            f'Replace Rule List\nRule: from {source_chat.name}'
        )

    finally:
        session.close()

async def handle_remove_command(event, command, parts):
    """Handle remove_keyword and remove_replace commands"""
    message_text = event.message.text
    logger.info(f"Received raw message: {message_text}")

    # If it is a replace rule, keep the original ID deletion method
    if command == 'remove_replace':
        if len(parts) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Usage: /{command} <ID1> [ID2] [ID3] ...\nExample: /{command} 1 2 3')
            return

        try:
            ids_to_remove = [int(x) for x in parts[1:]]
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'ID must be a number')
            return
    elif command in ['remove_keyword_by_id', 'rkbi']:  # Add handling for deleting keywords by ID
        if len(parts) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Usage: /{command} <ID1> [ID2] [ID3] ...\nExample: /{command} 1 2 3')
            return

        try:
            ids_to_remove = [int(x) for x in parts[1:]]
            logger.info(f"Preparing to delete keywords by ID: {ids_to_remove}")
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'ID must be a number')
            return
    else:  # remove_keyword
        if len(message_text.split(None, 1)) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Usage: /{command} <keyword1> [keyword2] ...\nExamples:\n/{command} keyword1 "key word 2" \'key word 3\'')
            return

        # Separate command and argument parts
        _, args_text = message_text.split(None, 1)
        logger.info(f"Separated argument part: {args_text}")

        try:
            # Use shlex to properly handle quoted arguments
            logger.info("Starting to parse arguments with shlex")
            keywords_to_remove = shlex.split(args_text)
            logger.info(f"shlex parse result: {keywords_to_remove}")
        except ValueError as e:
            logger.error(f"shlex parse error: {str(e)}")
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Argument format error: please ensure quotes are properly paired')
            return

        if not keywords_to_remove:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Please provide at least one keyword')
            return

    # Define item_type outside try block
    item_type = 'keyword' if command in ['remove_keyword', 'remove_keyword_by_id', 'rkbi'] else 'replace rule'

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info
        rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
        mode_name = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"

        db_ops = await get_db_ops()
        if command == 'remove_keyword':
            # Get keywords under current mode
            items = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'Current rule has no keywords in {mode_name} mode')
                return

            # Modified: delete matching keywords
            removed_count = 0
            removed_indices = [] # Store keyword indices to delete
            
            for keyword in keywords_to_remove:
                logger.info(f"Attempting to delete keyword: {keyword}")
                for i, item in enumerate(items):
                    if item.keyword == keyword:
                        logger.info(f"Found matching keyword: {item.keyword}")
                        removed_indices.append(i + 1) # Convert to 1-based index
                        removed_count += 1
                        break
            
            if removed_indices:
                # Use db_ops to delete keywords (supports sync feature)
                await db_ops.delete_keywords(session, rule.id, removed_indices)
                session.commit()
                logger.info(f"Successfully deleted {removed_count} keywords")
            
            # Re-fetch the updated list
            remaining_items = await db_ops.get_keywords(session, rule.id, rule_mode)

            # Show deletion results
            if removed_count > 0:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"Deleted {removed_count} keywords from {mode_name}")
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"No matching keywords found in {mode_name}")

        elif command in ['remove_keyword_by_id', 'rkbi']:
            # Get keywords under current mode
            items = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'Current rule has no keywords in {mode_name} mode')
                return

            # Check if IDs are valid
            max_id = len(items)
            invalid_ids = [id for id in ids_to_remove if id < 1 or id > max_id]
            if invalid_ids:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'Invalid ID(s): {", ".join(map(str, invalid_ids))}')
                return

            # Modified: record keywords to delete
            removed_count = 0
            removed_keywords = []
            valid_ids = [id for id in ids_to_remove if 1 <= id <= max_id]
            
            for id in valid_ids:
                removed_keywords.append(items[id - 1].keyword)
                
            # Use db_ops to delete keywords (supports sync feature)
            removed_count, _ = await db_ops.delete_keywords(session, rule.id, valid_ids)
            session.commit()
            logger.info(f"Successfully deleted {removed_count} keywords")

            # Build reply message
            if removed_count > 0:
                keywords_text = '\n'.join(f'- {k}' for k in removed_keywords)
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,
                    f"Deleted {removed_count} keywords from {mode_name}:\n"
                    f"{keywords_text}"
                )
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"No matching keywords found in {mode_name}")

        else:  # remove_replace
            # Handle replace rule deletion (keep original logic)
            items = await db_ops.get_replace_rules(session, rule.id)
            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'Current rule has no {item_type}')
                return

            max_id = len(items)
            invalid_ids = [id for id in ids_to_remove if id < 1 or id > max_id]
            if invalid_ids:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'Invalid ID(s): {", ".join(map(str, invalid_ids))}')
                return

            await db_ops.delete_replace_rules(session, rule.id, ids_to_remove)
            session.commit()

            remaining_items = await db_ops.get_replace_rules(session, rule.id)
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Deleted {len(ids_to_remove)} replace rules')

    except Exception as e:
        session.rollback()
        logger.error(f'Error deleting {item_type}: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'Error deleting {item_type}, please check logs')
    finally:
        session.close()

async def handle_clear_all_command(event):
    """Handle clear_all command"""
    session = get_session()
    try:
        # Delete all replace rules
        replace_count = session.query(ReplaceRule).delete(synchronize_session=False)

        # Delete all keywords
        keyword_count = session.query(Keyword).delete(synchronize_session=False)

        # Delete all forwarding rules
        rule_count = session.query(ForwardRule).delete(synchronize_session=False)

        # Delete all chats
        chat_count = session.query(Chat).delete(synchronize_session=False)

        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            'All data cleared:\n'
            f'- {chat_count} chats\n'
            f'- {rule_count} forwarding rules\n'
            f'- {keyword_count} keywords\n'
            f'- {replace_count} replace rules'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error clearing data: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error clearing data, please check logs')
    finally:
        session.close()


async def handle_changelog_command(event):
    """Handle changelog command"""
    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,UPDATE_INFO, parse_mode='html')


async def handle_start_command(event):
    """Handle start command"""

    welcome_text = f"""
    👋 Welcome to the Telegram Message Forwarding Bot!
    
    📱 Current version: v{VERSION}

    📖 Use /help to view the full command list

    """
    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,welcome_text)

async def handle_help_command(event, command):
    """Handle help command"""
    help_text = (
        f"🤖 **Telegram Message Forwarding Bot v{VERSION}**\n\n"

        "**Basic Commands**\n"
        "/start - Get started\n"
        "/help(/h) - Show this help message\n\n"

        "**Binding and Settings**\n"
        "/bind(/b) <source chat link or name> [target chat link or name] - Bind source chat\n"
        "/settings(/s) [rule ID] - Manage forwarding rules\n"
        "/changelog(/cl) - View changelog\n\n"

        "**Forwarding Rule Management**\n"
        "/copy_rule(/cr)  <source rule ID> [target rule ID] - Copy all settings from specified rule to current rule or target rule ID\n"
        "/list_rule(/lr) - List all forwarding rules\n"
        "/delete_rule(/dr) <rule ID> [rule ID] [rule ID] ... - Delete specified rules\n\n"

        "**Keyword Management**\n"
        "/add(/a) <keyword> [keyword] [\"key word\"] [\'key word\'] ... - Add plain keywords\n"
        "/add_regex(/ar) <regex> [regex] [regex] ... - Add regular expressions\n"
        "/add_all(/aa) <keyword> [keyword] [keyword] ... - Add plain keywords to all rules bound to current channel\n"
        "/add_regex_all(/ara) <regex> [regex] [regex] ... - Add regular expressions to all rules\n"
        "/list_keyword(/lk) - List all keywords\n"
        "/remove_keyword(/rk) <keyword1> [\"key word\"] [\'key word\'] ... - Remove keywords\n"
        "/remove_keyword_by_id(/rkbi) <ID> [ID] [ID] ... - Remove keywords by ID\n"
        "/remove_all_keyword(/rak) [keyword] [\"key word\"] [\'key word\'] ... - Remove specified keywords from all rules bound to current channel\n"
        "/clear_all_keywords(/cak) - Clear all keywords of current rule\n"
        "/clear_all_keywords_regex(/cakr) - Clear all regex keywords of current rule\n"
        "/copy_keywords(/ck) <rule ID> - Copy keywords from specified rule to current rule\n"
        "/copy_keywords_regex(/ckr) <rule ID> - Copy regex keywords from specified rule to current rule\n\n"

        "**Replace Rule Management**\n"
        "/replace(/r) <regex> [replacement content] - Add replace rule\n"
        "/replace_all(/ra) <regex> [replacement content] - Add replace rule to all rules\n"
        "/list_replace(/lrp) - List all replace rules\n"
        "/remove_replace(/rr) <index> - Remove replace rule\n"
        "/clear_all_replace(/car) - Clear all replace rules of current rule\n"
        "/copy_replace(/crp) <rule ID> - Copy replace rules from specified rule to current rule\n\n"

        "**Import/Export**\n"
        "/export_keyword(/ek) - Export keywords of current rule\n"
        "/export_replace(/er) - Export replace rules of current rule\n"
        "/import_keyword(/ik) <send file simultaneously> - Import plain keywords\n"
        "/import_regex_keyword(/irk) <send file simultaneously> - Import regex keywords\n"
        "/import_replace(/ir) <send file simultaneously> - Import replace rules\n\n"

        "**RSS Related**\n"
        "/delete_rss_user(/dru) [username] - Delete RSS user\n"

        "**UFB Related**\n"
        "/ufb_bind(/ub) <domain> - Bind UFB domain\n"
        "/ufb_unbind(/uu) - Unbind UFB domain\n"
        "/ufb_item_change(/uic) - Switch UFB sync configuration type\n\n"

        "💡 **Tips**\n"
        "• Content in parentheses is the shorthand form of the command\n"
        "• Angle brackets <> indicate required parameters\n"
        "• Square brackets [] indicate optional parameters\n"
        "• Import commands require sending the file simultaneously"
    )

    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)

    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,help_text, parse_mode='markdown')

async def handle_export_keyword_command(event, command):
    """Handle export_keyword command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Get all keywords
        normal_keywords = []
        regex_keywords = []

        # Get keywords directly from rule object
        for keyword in rule.keywords:
            if keyword.is_regex:
                regex_keywords.append(f"{keyword.keyword} {1 if keyword.is_blacklist else 0}")
            else:
                normal_keywords.append(f"{keyword.keyword} {1 if keyword.is_blacklist else 0}")

        # Create temporary files
        normal_file = os.path.join(TEMP_DIR, 'keywords.txt')
        regex_file = os.path.join(TEMP_DIR, 'regex_keywords.txt')

        # Write plain keywords, one per line
        with open(normal_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(normal_keywords))

        # Write regex keywords, one per line
        with open(regex_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(regex_keywords))

        # If both files are empty
        if not normal_keywords and not regex_keywords:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "Current rule has no keywords")
            return

        try:
            # Send files first
            files = []
            if normal_keywords:
                files.append(normal_file)
            if regex_keywords:
                files.append(regex_file)

            await event.client.send_file(
                event.chat_id,
                files
            )

            # Then send description text separately
            await respond_and_delete(event,(f"Rule: {source_chat.name}"))

        finally:
            # Delete temporary files
            if os.path.exists(normal_file):
                os.remove(normal_file)
            if os.path.exists(regex_file):
                os.remove(regex_file)

    except Exception as e:
        logger.error(f'Error exporting keywords: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error exporting keywords, please check logs')
    finally:
        session.close()

async def handle_import_command(event, command):
    """Handle import command"""
    try:
        # Check if there is an attachment
        if not event.message.file:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Please send the file together with the /{command} command')
            return

        # Get current rule
        session = get_session()
        try:
            rule_info = await get_current_rule(session, event)
            if not rule_info:
                return

            rule, source_chat = rule_info

            # Download file
            file_path = await event.message.download_media(TEMP_DIR)

            try:
                # Read file content
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]

                # Process according to command type
                if command == 'import_replace':
                    success_count = 0
                    logger.info(f'Starting to import replace rules, {len(lines)} lines total')
                    for i, line in enumerate(lines, 1):
                        try:
                            # Split by first tab
                            parts = line.split('\t', 1)
                            pattern = parts[0].strip()
                            content = parts[1].strip() if len(parts) > 1 else ''

                            logger.info(f'Processing line {i}: pattern="{pattern}", content="{content}"')

                            # Create replace rule
                            replace_rule = ReplaceRule(
                                rule_id=rule.id,
                                pattern=pattern,
                                content=content
                            )
                            session.add(replace_rule)
                            success_count += 1
                            logger.info(f'Successfully added replace rule: pattern="{pattern}", content="{content}"')

                            # Ensure replace mode is enabled
                            if not rule.is_replace:
                                rule.is_replace = True
                                logger.info('Replace mode enabled')

                        except Exception as e:
                            logger.error(f'Error processing replace rule on line {i}: {str(e)}\n{traceback.format_exc()}')
                            continue

                    session.commit()
                    logger.info(f'Import complete, successfully imported {success_count} replace rules')
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,f'Successfully imported {success_count} replace rules\nRule: from {source_chat.name}')


                else:
                    # Process keyword import
                    success_count = 0
                    duplicate_count = 0
                    is_regex = (command == 'import_regex_keyword')
                    for i, line in enumerate(lines, 1):
                        try:
                            # Split by space, extract keyword and flag
                            parts = line.split()
                            if len(parts) < 2:
                                raise ValueError("Invalid line format, at least keyword and flag required")
                            flag_str = parts[-1]  # Last part is the flag
                            if flag_str not in ('0', '1'):
                                raise ValueError("Flag value must be 0 or 1")
                            is_blacklist = (flag_str == '1')  # Convert to boolean
                            keyword = ' '.join(parts[:-1])  # Combine preceding parts as keyword
                            if not keyword:
                                raise ValueError("Keyword is empty")
                            # Check if the same keyword already exists
                            existing = session.query(Keyword).filter_by(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=is_regex
                            ).first()

                            if existing:
                                duplicate_count += 1
                                continue

                            # Create new Keyword object
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=is_regex,
                                is_blacklist=is_blacklist
                            )
                            session.add(new_keyword)
                            success_count += 1

                        except Exception as e:
                            logger.error(f'Error processing line {i}: {line}\n{str(e)}')
                            continue

                    session.commit()
                    keyword_type = "regex" if is_regex else "keyword"
                    result_text = f'Successfully imported {success_count} {keyword_type}(s)'
                    if duplicate_count > 0:
                        result_text += f'\nSkipped duplicates: {duplicate_count}'
                    result_text += f'\nRule: from {source_chat.name}'
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,result_text)
            finally:
                # Delete temporary file
                if os.path.exists(file_path):
                    os.remove(file_path)

        finally:
            session.close()

    except Exception as e:
        logger.error(f'Error during import: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error during import, please check logs')

async def handle_ufb_item_change_command(event, command):
    """Handle ufb_item_change command"""

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Create 4 buttons
        buttons = [
            [
                Button.inline("Homepage Keywords", "ufb_item:main"),
                Button.inline("Content Page Keywords", "ufb_item:content")
            ],
            [
                Button.inline("Homepage Username", "ufb_item:main_username"),
                Button.inline("Content Page Username", "ufb_item:content_username")
            ]
        ]

        # Send message with buttons
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event, "Please select the UFB sync configuration type to switch:", buttons=buttons)

    except Exception as e:
        session.rollback()
        logger.error(f'Error switching UFB configuration type: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error switching UFB configuration type, please check logs')
    finally:
        session.close()

async def handle_ufb_bind_command(event, command):
    """Handle ufb_bind command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Get domain and type from message
        parts = event.message.text.split()
        if len(parts) < 2 or len(parts) > 3:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Usage: /ufb_bind <domain> [type]\nType options: main, content, main_username, content_username\nExample: /ufb_bind example.com main')
            return

        domain = parts[1].strip().lower()
        item = 'main'  # Default value

        if len(parts) == 3:
            item = parts[2].strip().lower()
            if item not in ['main', 'content', 'main_username', 'content_username']:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,'Type must be one of: main, content, main_username, content_username')
                return

        # Update rule ufb_domain and ufb_item
        rule.ufb_domain = domain
        rule.ufb_item = item
        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'UFB domain bound: {domain}\nType: {item}\nRule: from {source_chat.name}')

    except Exception as e:
        session.rollback()
        logger.error(f'Error binding UFB domain: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error binding UFB domain, please check logs')
    finally:
        session.close()

async def handle_ufb_unbind_command(event, command):
    """Handle ufb_unbind command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Clear rule ufb_domain
        old_domain = rule.ufb_domain
        rule.ufb_domain = None
        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'UFB domain unbound: {old_domain or "none"}\nRule: from {source_chat.name}')

    except Exception as e:
        session.rollback()
        logger.error(f'Error unbinding UFB domain: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error unbinding UFB domain, please check logs')
    finally:
        session.close()

async def handle_clear_all_keywords_command(event, command):
    """Handle clear all keywords command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Get keyword count for current rule
        keyword_count = len(rule.keywords)

        if keyword_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "Current rule has no keywords")
            return

        # Delete all keywords
        for keyword in rule.keywords:
            session.delete(keyword)

        session.commit()

        # Send success message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Cleared all keywords for rule `{rule.id}`\n"
            f"Source chat: {source_chat.name}\n"
            f"Total deleted: {keyword_count} keywords",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error clearing keywords: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error clearing keywords, please check logs')
    finally:
        session.close()

async def handle_clear_all_keywords_regex_command(event, command):
    """Handle clear all regex keywords command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Get regex keyword count for current rule
        regex_keywords = [kw for kw in rule.keywords if kw.is_regex]
        keyword_count = len(regex_keywords)

        if keyword_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "Current rule has no regex keywords")
            return

        # Delete all regex keywords
        for keyword in regex_keywords:
            session.delete(keyword)

        session.commit()

        # Send success message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Cleared all regex keywords for rule `{rule.id}`\n"
            f"Source chat: {source_chat.name}\n"
            f"Total deleted: {keyword_count} regex keywords",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error clearing regex keywords: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error clearing regex keywords, please check logs')
    finally:
        session.close()

async def handle_clear_all_replace_command(event, command):
    """Handle clear all replace rules command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Get replace rule count for current rule
        replace_count = len(rule.replace_rules)

        if replace_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "Current rule has no replace rules")
            return

        # Delete all replace rules
        for replace_rule in rule.replace_rules:
            session.delete(replace_rule)

        # If there are no more replace rules, disable replace mode
        rule.is_replace = False

        session.commit()

        # Send success message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Cleared all replace rules for rule `{rule.id}`\n"
            f"Source chat: {source_chat.name}\n"
            f"Total deleted: {replace_count} replace rules\n"
            "Replace mode has been automatically disabled",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error clearing replace rules: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error clearing replace rules, please check logs')
    finally:
        session.close()

async def handle_copy_keywords_command(event, command):
    """Handle copy keywords command"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /copy_keywords <rule ID>')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Rule ID must be a number')
        return

    session = get_session()
    try:
        # Get current rule
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # Get source rule
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Cannot find rule ID: {source_rule_id}')
            return

        # Copy keywords
        success_count = 0
        skip_count = 0

        for keyword in source_rule.keywords:
            if not keyword.is_regex:  # Only copy plain keywords
                # Check if already exists
                exists = any(k.keyword == keyword.keyword and not k.is_regex
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    success_count += 1
                else:
                    skip_count += 1

        session.commit()

        # Send result message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Copied keywords from rule `{source_rule_id}` to rule `{target_rule.id}`\n"
            f"Successfully copied: {success_count}\n"
            f"Skipped duplicates: {skip_count}",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error copying keywords: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error copying keywords, please check logs')
    finally:
        session.close()

async def handle_copy_keywords_regex_command(event, command):
    """Handle copy regex keywords command"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /copy_keywords_regex <rule ID>')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Rule ID must be a number')
        return

    session = get_session()
    try:
        # Get current rule
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # Get source rule
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Cannot find rule ID: {source_rule_id}')
            return

        # Copy regex keywords
        success_count = 0
        skip_count = 0

        for keyword in source_rule.keywords:
            if keyword.is_regex:  # Only copy regex keywords
                # Check if already exists
                exists = any(k.keyword == keyword.keyword and k.is_regex
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    success_count += 1
                else:
                    skip_count += 1

        session.commit()

        # Send result message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Copied regex keywords from rule `{source_rule_id}` to rule `{target_rule.id}`\n"
            f"Successfully copied: {success_count}\n"
            f"Skipped duplicates: {skip_count}",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error copying regex keywords: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error copying regex keywords, please check logs')
    finally:
        session.close()

async def handle_copy_replace_command(event, command):
    """Handle copy replace rules command"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /copy_replace <rule ID>')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Rule ID must be a number')
        return

    session = get_session()
    try:
        # Get current rule
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # Get source rule
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Cannot find rule ID: {source_rule_id}')
            return

        # Copy replace rules
        success_count = 0
        skip_count = 0

        for replace_rule in source_rule.replace_rules:
            # Check if already exists
            exists = any(r.pattern == replace_rule.pattern
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                success_count += 1
            else:
                skip_count += 1

        session.commit()

        # Send result message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Copied replace rules from rule `{source_rule_id}` to rule `{target_rule.id}`\n"
            f"Successfully copied: {success_count}\n"
            f"Skipped duplicates: {skip_count}\n",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error copying replace rules: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error copying replace rules, please check logs')
    finally:
        session.close()

async def handle_copy_rule_command(event, command):
    """Handle copy rule command - Copy all settings from one rule to current rule or specified rule"""
    parts = event.message.text.split()
    
    # Check argument count
    if len(parts) not in [2, 3]:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /copy_rule <source rule ID> [target rule ID]')
        return

    try:
        source_rule_id = int(parts[1])
        
        # Determine target rule ID
        if len(parts) == 3:
            # If two arguments provided, use the second as target rule ID
            target_rule_id = int(parts[2])
            use_current_rule = False
        else:
            # If only one argument provided, use current rule as target
            target_rule_id = None
            use_current_rule = True
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Rule ID must be a number')
        return

    session = get_session()
    try:
        # Get source rule
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'Cannot find source rule ID: {source_rule_id}')
            return

        # Get target rule
        if use_current_rule:
            # Get current rule
            rule_info = await get_current_rule(session, event)
            if not rule_info:
                return
            target_rule, source_chat = rule_info
        else:
            # Use specified target rule ID
            target_rule = session.query(ForwardRule).get(target_rule_id)
            if not target_rule:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'Cannot find target rule ID: {target_rule_id}')
                return

        if source_rule.id == target_rule.id:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Cannot copy rule to itself')
            return

        # Record success count for each copied part
        keywords_normal_success = 0
        keywords_normal_skip = 0
        keywords_regex_success = 0
        keywords_regex_skip = 0
        replace_rules_success = 0
        replace_rules_skip = 0
        media_extensions_success = 0
        media_extensions_skip = 0


        # Copy plain keywords
        for keyword in source_rule.keywords:
            if not keyword.is_regex:
                # Check if already exists
                exists = any(k.keyword == keyword.keyword and not k.is_regex and k.is_blacklist == keyword.is_blacklist
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
            if keyword.is_regex:
                # Check if already exists
                exists = any(k.keyword == keyword.keyword and k.is_regex and k.is_blacklist == keyword.is_blacklist
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

        # Copy media extension settings
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
                # If target rule has no media type settings, create new one
                target_media_types = MediaTypes(rule_id=target_rule.id)

                # Use inspect to automatically copy all fields (except id and rule_id)
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

                session.add(target_media_types)
            else:
                # If settings already exist, update existing settings
                # Use inspect to automatically copy all fields (except id and rule_id)
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

        # Copy rule sync table data
        rule_syncs_success = 0
        rule_syncs_skip = 0
        
        # Check if source rule has sync relationships
        if hasattr(source_rule, 'rule_syncs') and source_rule.rule_syncs:
            for sync in source_rule.rule_syncs:
                # Check if already exists
                exists = any(s.sync_rule_id == sync.sync_rule_id for s in target_rule.rule_syncs)
                if not exists:
                    # Ensure self-referencing sync relationships are not created
                    if sync.sync_rule_id != target_rule.id:
                        new_sync = RuleSync(
                            rule_id=target_rule.id,
                            sync_rule_id=sync.sync_rule_id
                        )
                        session.add(new_sync)
                        rule_syncs_success += 1
                        
                        # Enable sync feature for target rule
                        if rule_syncs_success > 0:
                            target_rule.enable_sync = True
                else:
                    rule_syncs_skip += 1

        # Copy rule settings
        # Get all fields of ForwardRule model
        inspector = inspect(ForwardRule)
        for column in inspector.columns:
            column_name = column.key
            if column_name not in ['id', 'source_chat_id', 'target_chat_id', 'source_chat', 'target_chat',
                                      'keywords', 'replace_rules', 'media_types']:
                # Get value from source rule and set to target rule
                value = getattr(source_rule, column_name)
                setattr(target_rule, column_name, value)

        session.commit()


        # Send result message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ Copied from rule `{source_rule_id}` to rule `{target_rule.id}`\n\n"
            f"Plain keywords: successfully copied {keywords_normal_success}, skipped duplicates {keywords_normal_skip}\n"
            f"Regex keywords: successfully copied {keywords_regex_success}, skipped duplicates {keywords_regex_skip}\n"
            f"Replace rules: successfully copied {replace_rules_success}, skipped duplicates {replace_rules_skip}\n"
            f"Media extensions: successfully copied {media_extensions_success}, skipped duplicates {media_extensions_skip}\n"
            f"Sync rules: successfully copied {rule_syncs_success}, skipped duplicates {rule_syncs_skip}\n"
            f"Media type settings and other rule settings have been copied\n",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'Error copying rule: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error copying rule, please check logs')
    finally:
        session.close()

async def handle_export_replace_command(event, client):
    """Handle export_replace command"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # Get all replace rules
        replace_rules = []
        for rule in rule.replace_rules:
            replace_rules.append((rule.pattern, rule.content))

        # If there are no replace rules
        if not replace_rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "Current rule has no replace rules")
            return

        # Create and write to file
        replace_file = os.path.join(TEMP_DIR, 'replace_rules.txt')

        # Write replace rules, one rule per line, tab separated
        with open(replace_file, 'w', encoding='utf-8') as f:
            for pattern, content in replace_rules:
                line = f"{pattern}\t{content if content else ''}"
                f.write(line + '\n')

        try:
            # Send file first
            await event.client.send_file(
                event.chat_id,
                replace_file
            )

            # Then send description text separately
            await respond_and_delete(event,(f"Rule: {source_chat.name}"))

        finally:
            # Delete temporary file
            if os.path.exists(replace_file):
                os.remove(replace_file)

    except Exception as e:
        logger.error(f'Error exporting replace rules: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error exporting replace rules, please check logs')
    finally:
        session.close()


async def handle_remove_all_keyword_command(event, command, parts):
    """Handle remove_all_keyword command"""
    message_text = event.message.text
    logger.info(f"Received raw message: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'Usage: /{command} <keyword1> [keyword2] ...\nExamples:\n/{command} keyword1 "key word 2" \'key word 3\'')
        return

    # Separate command and argument parts
    _, args_text = message_text.split(None, 1)
    logger.info(f"Separated argument part: {args_text}")

    try:
        # Use shlex to properly handle quoted arguments
        logger.info("Starting to parse arguments with shlex")
        keywords_to_remove = shlex.split(args_text)
        logger.info(f"shlex parse result: {keywords_to_remove}")
    except ValueError as e:
        logger.error(f"shlex parse error: {str(e)}")
        # Handle errors like unclosed quotes
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Argument format error: please ensure quotes are properly paired')
        return

    if not keywords_to_remove:
        logger.warning("No keywords provided")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Please provide at least one keyword')
        return

    session = get_session()
    try:
        # Get current rule to determine blacklist/whitelist mode
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        current_rule, source_chat = rule_info
        mode_name = "blacklist" if current_rule.add_mode == AddMode.BLACKLIST else "whitelist"

        # Get all related rules
        rules = await get_all_rules(session, event)
        if not rules:
            return

        db_ops = await get_db_ops()
        total_removed = 0
        total_not_found = 0
        removed_details = {}  # Used to record deleted keywords for each rule

        # Delete keywords from each rule
        for rule in rules:
            # Get keywords for current rule
            rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
            keywords = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not keywords:
                continue

            rule_removed = 0
            rule_removed_keywords = []

            # Delete matching keywords
            for keyword in keywords:
                if keyword.keyword in keywords_to_remove:
                    logger.info(f"Deleting keyword in rule {rule.id}: {keyword.keyword}")
                    session.delete(keyword)
                    rule_removed += 1
                    rule_removed_keywords.append(keyword.keyword)

            if rule_removed > 0:
                removed_details[rule.id] = rule_removed_keywords
                total_removed += rule_removed
            else:
                total_not_found += 1

        session.commit()

        # Build reply message
        if total_removed > 0:
            result_text = f"Deleted keywords from {mode_name}:\n\n"
            for rule_id, keywords in removed_details.items():
                rule = next((r for r in rules if r.id == rule_id), None)
                if rule:
                    result_text += f"Rule {rule_id} (from: {rule.source_chat.name}):\n"
                    result_text += "\n".join(f"- {k}" for k in keywords)
                    result_text += "\n\n"
            result_text += f"Total deleted: {total_removed} keywords"

            logger.info(f"Sending reply message: {result_text}")
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,result_text)
        else:
            msg = f"No matching keywords found in {mode_name}"
            logger.info(msg)
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,msg)

    except Exception as e:
        session.rollback()
        logger.error(f'Error batch deleting keywords: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error deleting keywords, please check logs')
    finally:
        session.close()

async def handle_add_all_command(event, command, parts):
    """Handle add_all and add_regex_all commands"""
    message_text = event.message.text
    logger.info(f"Received raw message: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'Usage: /{command} <keyword1> [keyword2] ...\nExamples:\n/{command} keyword1 "key word 2" \'key word 3\'')
        return

    # Separate command and argument parts
    _, args_text = message_text.split(None, 1)
    logger.info(f"Separated argument part: {args_text}")

    keywords = []
    if command == 'add_all':
        try:
            # Use shlex to properly handle quoted arguments
            logger.info("Starting to parse arguments with shlex")
            keywords = shlex.split(args_text)
            logger.info(f"shlex parse result: {keywords}")
        except ValueError as e:
            logger.error(f"shlex parse error: {str(e)}")
            # Handle errors like unclosed quotes
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Argument format error: please ensure quotes are properly paired')
            return
    else:
        # add_regex_all command uses simple split, keeping regex in original form
        if len(args_text.split()) > 0:
            keywords = args_text.split()
        else:
            keywords = [args_text]
        logger.info(f"add_regex_all command, using raw arguments: {keywords}")

    if not keywords:
        logger.warning("No keywords provided")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Please provide at least one keyword')
        return

    session = get_session()
    try:
        rules = await get_all_rules(session, event)
        if not rules:
            return

        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        current_rule, source_chat = rule_info

        db_ops = await get_db_ops()
        # Add keywords for each rule
        success_count = 0
        duplicate_count = 0
        for rule in rules:
            # Use add_keywords to add keywords
            s_count, d_count = await db_ops.add_keywords(
                session,
                rule.id,
                keywords,
                is_regex=(command == 'add_regex_all'),
                is_blacklist=(current_rule.add_mode == AddMode.BLACKLIST)
            )
            success_count += s_count
            duplicate_count += d_count

        session.commit()

        # Build reply message
        keyword_type = "regex" if command == "add_regex_all" else "keyword"
        keywords_text = '\n'.join(f'- {k}' for k in keywords)
        result_text = f'Added {success_count} {keyword_type}(s)\n'
        if duplicate_count > 0:
            result_text += f'Skipped duplicates: {duplicate_count}\n'
        result_text += f'Keyword list:\n{keywords_text}'

        logger.info(f"Sending reply message: {result_text}")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'Error batch adding keywords: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error adding keywords, please check logs')
    finally:
        session.close()

async def handle_replace_all_command(event, parts):
    """Handle replace_all command"""
    message_text = event.message.text
    
    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Usage: /replace_all <match pattern> [replacement content]\nExamples:\n/replace_all ad  # Delete matched content\n/replace_all ad [replaced]')
        return

    # Split arguments directly, keeping regex in original form
    _, args_text = message_text.split(None, 1)
    
    # Split by first space, keeping remaining content unchanged
    parts = args_text.split(None, 1)
    pattern = parts[0]
    content = parts[1] if len(parts) > 1 else ''
    
    logger.info(f"Parsed replace command arguments: pattern='{pattern}', content='{content}'")

    session = get_session()
    try:
        rules = await get_all_rules(session, event)
        if not rules:
            return

        db_ops = await get_db_ops()
        # Add replace rule for each rule
        total_success = 0
        total_duplicate = 0

        for rule in rules:
            # Use add_replace_rules to add replace rule
            success_count, duplicate_count = await db_ops.add_replace_rules(
                session,
                rule.id,
                [(pattern, content)]  # Pass a list of tuples, each containing pattern and content
            )

            # Accumulate success and duplicate counts
            total_success += success_count
            total_duplicate += duplicate_count

            # Ensure replace mode is enabled
            if success_count > 0 and not rule.is_replace:
                rule.is_replace = True

        session.commit()

        # Build reply message
        action_type = "delete" if not content else "replace"
        result_text = f'Added replace rules for {len(rules)} rules:\n'
        if total_success > 0:
            result_text += f'Successfully added: {total_success}\n'
            result_text += f'Match pattern: {pattern}\n'
            result_text += f'Action: {action_type}\n'
            if content:
                result_text += f'Replace with: {content}\n'
        if total_duplicate > 0:
            result_text += f'Skipped duplicate rules: {total_duplicate}'

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'Error batch adding replace rules: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error adding replace rules, please check logs')
    finally:
        session.close()

async def handle_list_rule_command(event, command, parts):
    """Handle list_rule command"""
    session = get_session()
    try:
        # Get page number argument, default to page 1
        try:
            page = int(parts[1]) if len(parts) > 1 else 1
            if page < 1:
                page = 1
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'Page number must be a number')
            return

        # Set items per page
        per_page = 30
        offset = (page - 1) * per_page

        # Get total rule count
        total_rules = session.query(ForwardRule).count()

        if total_rules == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'There are no forwarding rules')
            return

        # Calculate total pages
        total_pages = (total_rules + per_page - 1) // per_page

        # If requested page exceeds range, use last page
        if page > total_pages:
            page = total_pages
            offset = (page - 1) * per_page

        # Get rules for current page
        rules = session.query(ForwardRule).order_by(ForwardRule.id).offset(offset).limit(per_page).all()

        # Build rule list message
        message_parts = [f'📋 Forwarding Rules List (Page {page}/{total_pages}):\n']

        for rule in rules:
            # Get source chat and target chat names
            source_chat = rule.source_chat
            target_chat = rule.target_chat

            # Build rule description
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

        # Add previous page button
        if page > 1:
            nav_row.append(Button.inline('⬅️ Prev', f'page_rule:{page-1}'))
        else:
            nav_row.append(Button.inline('⬅️', 'noop'))  # Disabled state button

        # Add page number button
        nav_row.append(Button.inline(f'{page}/{total_pages}', 'noop'))

        # Add next page button
        if page < total_pages:
            nav_row.append(Button.inline('Next ➡️', f'page_rule:{page+1}'))
        else:
            nav_row.append(Button.inline('➡️', 'noop'))  # Disabled state button

        buttons.append(nav_row)

        # Send message
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'\n'.join(message_parts), buttons=buttons, parse_mode='html')

    except Exception as e:
        logger.error(f'Error listing rules: {str(e)}')
        logger.exception(e)
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error getting rule list, please check logs')
    finally:
        session.close()

async def handle_delete_rule_command(event, command, parts):
    """Handle delete_rule command"""
    if len(parts) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'Usage: /{command} <ID1> [ID2] [ID3] ...\nExample: /{command} 1 2 3')
        return

    try:
        ids_to_remove = [int(x) for x in parts[1:]]
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'ID must be a number')
        return

    session = get_session()
    try:
        success_ids = []
        failed_ids = []
        not_found_ids = []

        for rule_id in ids_to_remove:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                not_found_ids.append(rule_id)
                continue

            try:
                # Delete rule (associated replace rules, keywords and media types will be automatically deleted)
                session.delete(rule)

                # Try to delete rule data from RSS service
                try:
                    rss_url = f"http://{RSS_HOST}:{RSS_PORT}/api/rule/{rule_id}"
                    async with aiohttp.ClientSession() as client_session:
                        async with client_session.delete(rss_url) as response:
                            if response.status == 200:
                                logger.info(f"Successfully deleted RSS rule data: {rule_id}")
                            else:
                                response_text = await response.text()
                                logger.warning(f"Failed to delete RSS rule data {rule_id}, status code: {response.status}, response: {response_text}")
                except Exception as rss_err:
                    logger.error(f"Error calling RSS delete API: {str(rss_err)}")
                    # Does not affect main flow, continue execution

                success_ids.append(rule_id)
            except Exception as e:
                logger.error(f'Error deleting rule {rule_id}: {str(e)}')
                failed_ids.append(rule_id)

        # Commit transaction
        session.commit()
        
        # Clean up unused chat records
        # Clean the entire database at once here, no need to process each rule individually
        # Because all rules have already been deleted from the database
        deleted_chats = await check_and_clean_chats(session)
        if deleted_chats > 0:
            logger.info(f"Cleaned up {deleted_chats} unused chat records after deleting rules")

        # Build response message
        response_parts = []
        if success_ids:
            response_parts.append(f'✅ Successfully deleted rules: {", ".join(map(str, success_ids))}')
        if not_found_ids:
            response_parts.append(f'❓ Rules not found: {", ".join(map(str, not_found_ids))}')
        if failed_ids:
            response_parts.append(f'❌ Failed to delete rules: {", ".join(map(str, failed_ids))}')
        if deleted_chats > 0:
            response_parts.append(f'🧹 Cleaned up {deleted_chats} unused chat records')

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'\n'.join(response_parts) or 'No rules were deleted')

    except Exception as e:
        session.rollback()
        logger.error(f'Error deleting rules: {str(e)}')
        logger.exception(e)
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'Error deleting rules, please check logs')
    finally:
        session.close()


async def handle_delete_rss_user_command(event, command, parts):
    """Handle delete_rss_user command"""
    db_ops = await get_db_ops()
    session = get_session()

    try:
        # Check if username is specified
        specified_username = None
        if len(parts) > 1:
            specified_username = parts[1].strip()

        # Query all users
        users = session.query(models.User).all()

        if not users:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "No user accounts in RSS system")
            return

        # Placeholder, may have multi-user feature in the future. If username specified, try to delete the user
        if specified_username:
            user = session.query(models.User).filter(models.User.username == specified_username).first()
            if user:
                session.delete(user)
                session.commit()
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"Deleted RSS user: {specified_username}")
                return
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"RSS user with username '{specified_username}' not found")
                return

        # If no username specified
        # Default only one user, delete directly
        if len(users) == 1:
            user = users[0]
            username = user.username
            session.delete(user)
            session.commit()
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f"Deleted RSS user: {username}")
            return

        # Placeholder, may have multi-user feature in the future. If multiple users exist, list all and prompt for username
        usernames = [user.username for user in users]
        user_list = "\n".join([f"{i+1}. {username}" for i, username in enumerate(usernames)])

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f"Multiple users in RSS system, please use `/delete_rss_user <username>` to specify the user to delete:\n\n{user_list}")

    except Exception as e:
        session.rollback()
        error_message = f"Error deleting RSS user: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,error_message)
    finally:
        session.close()
