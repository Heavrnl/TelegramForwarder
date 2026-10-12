import traceback
import aiohttp
import os
import asyncio
from telethon.tl import types

from handlers.button.button_helpers import create_media_size_buttons,create_media_settings_buttons,create_media_types_buttons,create_media_extensions_buttons, create_push_config_details_buttons
from models.models import ForwardRule, MediaTypes, MediaExtensions, RuleSync, Keyword, ReplaceRule, PushConfig
from enums.enums import AddMode
import logging
from utils.common import get_media_settings_text, get_db_ops
from models.models import get_session
from models.db_operations import DBOperations
from handlers.button.button_helpers import create_push_settings_buttons
from telethon import Button
from sqlalchemy import inspect
from utils.constants import RSS_HOST, RSS_PORT,RULES_PER_PAGE,PUSH_SETTINGS_TEXT
from utils.common import check_and_clean_chats, is_admin
from utils.auto_delete import reply_and_delete, send_message_and_delete, respond_and_delete
from managers.state_manager import state_manager

logger = logging.getLogger(__name__)



async def callback_push_settings(event, rule_id, session, message, data):
    await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id=rule_id), link_preview=False)
    return

async def callback_toggle_enable_push(event, rule_id, session, message, data):
    """Handle push enable/disable toggle callback"""
    try:
        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
        
        rule.enable_push = not rule.enable_push
        
        # Check if sync is enabled
        if rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing push status to linked rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Apply same setting to each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing push status to rule {sync_rule_id}")
                
                # Get sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                    continue
                
                try:
                    # Update sync target rule push status
                    target_rule.enable_push = rule.enable_push
                    logger.info(f"Rule {sync_rule_id} push status updated to {rule.enable_push}")
                except Exception as e:
                    logger.error(f"Error syncing push status to rule {sync_rule_id}: {str(e)}")
                    continue
        
        session.commit()

        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)

        status = "enabled" if rule.enable_push else "disabled"
        await event.answer(f'Push notifications {status}')
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling push status: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, check the logs')



async def callback_add_push_channel(event, rule_id, session, message, data):
    """Handle add push config callback"""
    try:
        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
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

        # Set user state
        chat_id = abs(event.chat_id)
        state = f"add_push_channel:{rule_id}"
        
        logger.info(f"Setting state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
        state_manager.set_state(user_id, chat_id, state, message, state_type="push")
        
        # Start timeout cancel task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        
        await message.edit(
            f"Please send the push configuration\n"
            f"Will auto-cancel in 5 minutes if not set",
            buttons=[[Button.inline("Cancel", f"cancel_add_push_channel:{rule_id}")]]
        )
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding push config: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, check the logs')

async def callback_cancel_add_push_channel(event, rule_id, session, message, data):
    """Cancel adding push config"""
    try:
        rule_id = data.split(':')[1]
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer('Rule not found')
            return
            
        # Clear state
        if isinstance(event.chat, types.Channel):
            user_id = os.getenv('USER_ID')
        else:
            user_id = event.sender_id
            
        chat_id = abs(event.chat_id)
        state_manager.clear_state(user_id, chat_id)

        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)
        await event.answer("Cancelled")
        
    except Exception as e:
        logger.error(f"Error cancelling add push config: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, check the logs')

async def cancel_state_after_timeout(user_id: int, chat_id: int, timeout_minutes: int = 5):
    """Auto-cancel state after the specified timeout"""
    await asyncio.sleep(timeout_minutes * 60)
    current_state, _, _ = state_manager.get_state(user_id, chat_id)
    if current_state:  # Only clear if state still exists
        logger.info(f"State auto-cancelled due to timeout - user_id: {user_id}, chat_id: {chat_id}")
        state_manager.clear_state(user_id, chat_id)

async def callback_toggle_push_config(event, config_id, session, message, data):
    """Handle push config click callback"""
    try:

        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push config not found")
            return

        await event.edit(
            f"Push config: `{config.push_channel}`\n",
            buttons=await create_push_config_details_buttons(config.id)
        )
        
    except Exception as e:
        logger.error(f"Error displaying push config details: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, check the logs")

async def callback_toggle_push_config_status(event, config_id, session, message, data):
    """Handle push config status toggle callback"""
    try:
        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push config not found")
            return
        
        rule_id = config.rule_id
        push_channel = config.push_channel
        
        config.enable_push_channel = not config.enable_push_channel
        
        # Get rule object
        rule = session.query(ForwardRule).get(int(rule_id))
        
        # Check if sync is enabled
        if rule and rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing push config status to linked rules")
            
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Update same push channel status in each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing push channel {push_channel} status to rule {sync_rule_id}")
                
                # Find matching push channel config in target rule
                target_config = session.query(PushConfig).filter_by(
                    rule_id=sync_rule_id, 
                    push_channel=push_channel
                ).first()
                
                if not target_config:
                    logger.warning(f"Sync target rule {sync_rule_id} missing push channel {push_channel}, skipping")
                    continue
                
                try:
                    # Update target rule push config status
                    target_config.enable_push_channel = config.enable_push_channel
                    logger.info(f"Updated rule {sync_rule_id} push channel {push_channel} status to {config.enable_push_channel}")
                except Exception as e:
                    logger.error(f"Error updating rule {sync_rule_id} push config status: {str(e)}")
                    continue
        
        session.commit()

        await event.edit(
            f"Push config: `{config.push_channel}`\n",
            buttons=await create_push_config_details_buttons(config.id)
        )
        
        status = "enabled" if config.enable_push_channel else "disabled"
        await event.answer(f"Push config {status}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling push config status: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, check the logs")

async def callback_delete_push_config(event, config_id, session, message, data):
    """Handle delete push config callback"""
    try:
        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push config not found")
            return
        
        rule_id = config.rule_id
        push_channel = config.push_channel
        
        # Get rule object
        rule = session.query(ForwardRule).get(int(rule_id))
        
        # Check if sync is enabled
        if rule and rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing push config deletion to linked rules")
            
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Delete same push config in each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing deletion of push channel {push_channel} from rule {sync_rule_id}")
                
                # Find matching push channel config in target rule
                target_config = session.query(PushConfig).filter_by(
                    rule_id=sync_rule_id, 
                    push_channel=push_channel
                ).first()
                
                if not target_config:
                    logger.warning(f"Sync target rule {sync_rule_id} missing push channel {push_channel}, skipping")
                    continue
                
                try:
                    # Delete target rule push config
                    session.delete(target_config)
                    logger.info(f"Deleted push channel {push_channel} from rule {sync_rule_id}")
                except Exception as e:
                    logger.error(f"Error deleting rule {sync_rule_id} push config: {str(e)}")
                    continue
        
        # Delete config
        session.delete(config)
        session.commit()
        
        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)
        await event.answer("Push config deleted")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting push config: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, check the logs")

async def callback_push_page(event, rule_id_data, session, message, data):
    """Handle push settings page navigation callback"""
    try:
        # Parse data
        parts = rule_id_data.split(":")
        if len(parts) != 2:
            await event.answer("Invalid data format")
            return
            
        rule_id = int(parts[0])
        page = int(parts[1])

        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id, page), link_preview=False)
        await event.answer(f"Page {page+1}")
        
    except Exception as e:
        logger.error(f"Error handling push settings pagination: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, check the logs")

async def callback_toggle_enable_only_push(event, rule_id, session, message, data):
    """Handle forward-to-push-only toggle callback"""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
       
        rule.enable_only_push = not rule.enable_only_push
        
        # Check if sync is enabled
        if rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing 'push-only' setting to linked rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Apply same setting to each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing 'push-only' setting to rule {sync_rule_id}")
                
                # Get sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                    continue
                
                try:
                    # Update sync target rule setting
                    target_rule.enable_only_push = rule.enable_only_push
                    logger.info(f"Rule {sync_rule_id} push-only setting updated to {rule.enable_only_push}")
                except Exception as e:
                    logger.error(f"Error syncing push-only setting to rule {sync_rule_id}: {str(e)}")
                    continue
        
        session.commit()
        
        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)

        status = "enabled" if rule.enable_only_push else "disabled"
        await event.answer(f'Forward to push only: {status}')
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling push-only status: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, check the logs')

async def callback_toggle_media_send_mode(event, config_id, session, message, data):
    """Handle media send mode toggle callback"""
    try:
        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push config not found")
            return
            
        rule_id = config.rule_id
        
        # Toggle media send mode
        if config.media_send_mode == "Single":
            config.media_send_mode = "Multiple"
            new_mode = "All"
        else:
            config.media_send_mode = "Single"
            new_mode = "Single"
            
        session.commit()
        
        # Check if sync is enabled
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule and rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing media send mode to linked rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Get push channel of current config
            push_channel = config.push_channel
            
            # Find and update same push channel config in each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing media send mode to rule {sync_rule_id} push channel")
                
                # Find matching push channel config in target rule
                target_config = session.query(PushConfig).filter_by(rule_id=sync_rule_id, push_channel=push_channel).first()
                if not target_config:
                    logger.warning(f"Sync target rule {sync_rule_id} missing push channel {push_channel}, skipping")
                    continue
                
                try:
                    # Update sync target config media send mode
                    target_config.media_send_mode = config.media_send_mode
                    logger.info(f"Rule {sync_rule_id} push channel {push_channel} media send mode updated to {config.media_send_mode}")
                except Exception as e:
                    logger.error(f"Error syncing media send mode to rule {sync_rule_id}: {str(e)}")
                    continue
                    
            session.commit()
        
        # Update UI
        await event.edit(
            f"Push config: `{config.push_channel}`\n",
            buttons=await create_push_config_details_buttons(config.id)
        )
        
        await event.answer(f"Media send mode set to: {new_mode}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling media send mode: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, check the logs")
