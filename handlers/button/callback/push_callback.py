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
    """Handle callback for toggling push enable status"""
    try:
        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
        
        rule.enable_push = not rule.enable_push
        
        # Check if sync is enabled
        if rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing push status to associated rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Apply the same settings to each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing push status to rule {sync_rule_id}")
                
                # Get sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                    continue
                
                try:
                    # Update push status of sync target rule
                    target_rule.enable_push = rule.enable_push
                    logger.info(f"Push status of synced rule {sync_rule_id} updated to {rule.enable_push}")
                except Exception as e:
                    logger.error(f"Error syncing push status to rule {sync_rule_id}: {str(e)}")
                    continue
        
        session.commit()

        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)

        status = "enabled" if rule.enable_push else "disabled"
        await event.answer(f'Push function {status}')
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling push status: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, please check logs')



async def callback_add_push_channel(event, rule_id, session, message, data):
    """Handle callback for adding push configuration"""
    try:
        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer('Rule does not exist')
            return
            
        # Check if it is a channel message
        if isinstance(event.chat, types.Channel):
            # Check if user is admin
            if not await is_admin(event):
                await event.answer('Only admins can modify settings')
                return
            user_id = os.getenv('USER_ID')
        else:
            user_id = event.sender_id

        # Set user state
        chat_id = abs(event.chat_id)
        state = f"add_push_channel:{rule_id}"
        
        logger.info(f"Preparing to set state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
        state_manager.set_state(user_id, chat_id, state, message, state_type="push")
        
        # Start timeout cancellation task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        
        await message.edit(
            f"Please send push configuration\n"
            f"Will be automatically cancelled if not set within 5 minutes",
            buttons=[[Button.inline("Cancel", f"cancel_add_push_channel:{rule_id}")]]
        )
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding push configuration: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, please check logs')

async def callback_cancel_add_push_channel(event, rule_id, session, message, data):
    """Cancel adding push configuration"""
    try:
        rule_id = data.split(':')[1]
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer('Rule does not exist')
            return
            
        # Clear state
        if isinstance(event.chat, types.Channel):
            user_id = os.getenv('USER_ID')
        else:
            user_id = event.sender_id
            
        chat_id = abs(event.chat_id)
        state_manager.clear_state(user_id, chat_id)

        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)
        await event.answer("Push configuration addition cancelled")
        
    except Exception as e:
        logger.error(f"Error cancelling push configuration addition: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, please check logs')

async def cancel_state_after_timeout(user_id: int, chat_id: int, timeout_minutes: int = 5):
    """Automatically cancel state after specified timeout"""
    await asyncio.sleep(timeout_minutes * 60)
    current_state, _, _ = state_manager.get_state(user_id, chat_id)
    if current_state:  # Only clear if state still exists
        logger.info(f"State auto-cancelled due to timeout - user_id: {user_id}, chat_id: {chat_id}")
        state_manager.clear_state(user_id, chat_id)

async def callback_toggle_push_config(event, config_id, session, message, data):
    """Handle callback for clicking push configuration"""
    try:

        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push configuration does not exist")
            return

        await event.edit(
            f"Push config: `{config.push_channel}`\n",
            buttons=await create_push_config_details_buttons(config.id)
        )
        
    except Exception as e:
        logger.error(f"Error displaying push configuration details: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, please check logs")

async def callback_toggle_push_config_status(event, config_id, session, message, data):
    """Handle callback for toggling push configuration status"""
    try:
        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push configuration does not exist")
            return
        
        rule_id = config.rule_id
        push_channel = config.push_channel
        
        config.enable_push_channel = not config.enable_push_channel
        
        # Get rule object
        rule = session.query(ForwardRule).get(int(rule_id))
        
        # Check if sync is enabled
        if rule and rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing push configuration status to associated rules")
            
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Update the same push channel status for each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing push channel {push_channel} status for rule {sync_rule_id}")
                
                # Find the same push channel config for target rule
                target_config = session.query(PushConfig).filter_by(
                    rule_id=sync_rule_id, 
                    push_channel=push_channel
                ).first()
                
                if not target_config:
                    logger.warning(f"Sync target rule {sync_rule_id} does not have push channel {push_channel}, skipping")
                    continue
                
                try:
                    # Update the push config status for target rule
                    target_config.enable_push_channel = config.enable_push_channel
                    logger.info(f"Updated push channel {push_channel} status for rule {sync_rule_id} to {config.enable_push_channel}")
                except Exception as e:
                    logger.error(f"Error updating push config status for rule {sync_rule_id}: {str(e)}")
                    continue
        
        session.commit()

        await event.edit(
            f"Push config: `{config.push_channel}`\n",
            buttons=await create_push_config_details_buttons(config.id)
        )
        
        status = "enabled" if config.enable_push_channel else "disabled"
        await event.answer(f"Push configuration {status}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling push configuration status: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, please check logs")

async def callback_delete_push_config(event, config_id, session, message, data):
    """Handle callback for deleting push configuration"""
    try:
        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push configuration does not exist")
            return
        
        rule_id = config.rule_id
        push_channel = config.push_channel
        
        # Get rule object
        rule = session.query(ForwardRule).get(int(rule_id))
        
        # Check if sync is enabled
        if rule and rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing push config deletion to associated rules")
            
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Delete the same push config for each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing deletion of push channel {push_channel} for rule {sync_rule_id}")
                
                # Find the same push channel config for target rule
                target_config = session.query(PushConfig).filter_by(
                    rule_id=sync_rule_id, 
                    push_channel=push_channel
                ).first()
                
                if not target_config:
                    logger.warning(f"Sync target rule {sync_rule_id} does not have push channel {push_channel}, skipping")
                    continue
                
                try:
                    # Delete target rule's push config
                    session.delete(target_config)
                    logger.info(f"Deleted push channel {push_channel} for rule {sync_rule_id}")
                except Exception as e:
                    logger.error(f"Error deleting push config for rule {sync_rule_id}: {str(e)}")
                    continue
        
        # Delete config
        session.delete(config)
        session.commit()
        
        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)
        await event.answer("Push configuration deleted")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting push configuration: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, please check logs")

async def callback_push_page(event, rule_id_data, session, message, data):
    """Handle callback for push settings page navigation"""
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
        await event.answer("Error processing request, please check logs")

async def callback_toggle_enable_only_push(event, rule_id, session, message, data):
    """Handle callback for toggling forward-to-push-only mode"""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
       
        rule.enable_only_push = not rule.enable_only_push
        
        # Check if sync is enabled
        if rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing 'forward-to-push-only' setting to associated rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Apply the same settings to each synced rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing 'forward-to-push-only' setting to rule {sync_rule_id}")
                
                # Get sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                    continue
                
                try:
                    # Update sync target rule's setting
                    target_rule.enable_only_push = rule.enable_only_push
                    logger.info(f"'Forward-to-push-only' setting of synced rule {sync_rule_id} updated to {rule.enable_only_push}")
                except Exception as e:
                    logger.error(f"Error syncing 'forward-to-push-only' setting to rule {sync_rule_id}: {str(e)}")
                    continue
        
        session.commit()
        
        await event.edit(PUSH_SETTINGS_TEXT, buttons=await create_push_settings_buttons(rule_id), link_preview=False)

        status = "enabled" if rule.enable_only_push else "disabled"
        await event.answer(f'Forward-to-push-only mode {status}')
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling forward-to-push-only status: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer('Error processing request, please check logs')

async def callback_toggle_media_send_mode(event, config_id, session, message, data):
    """Handle callback for toggling media send mode"""
    try:
        config = session.query(PushConfig).get(int(config_id))
        if not config:
            await event.answer("Push configuration does not exist")
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
            logger.info(f"Rule {rule.id} has sync enabled, syncing media send mode to push configs of associated rules")
            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
            
            # Get the push channel of current push config
            push_channel = config.push_channel
            
            # Find the same push channel config for each synced rule and apply the same settings
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing media send mode to the same push channel of rule {sync_rule_id}")
                
                # Find the same push channel config under target rule
                target_config = session.query(PushConfig).filter_by(rule_id=sync_rule_id, push_channel=push_channel).first()
                if not target_config:
                    logger.warning(f"Sync target rule {sync_rule_id} does not have push channel {push_channel}, skipping")
                    continue
                
                try:
                    # Update media send mode of sync target config
                    target_config.media_send_mode = config.media_send_mode
                    logger.info(f"Media send mode of push channel {push_channel} for synced rule {sync_rule_id} updated to {config.media_send_mode}")
                except Exception as e:
                    logger.error(f"Error syncing media send mode to rule {sync_rule_id}: {str(e)}")
                    continue
                    
            session.commit()
        
        # Update interface
        await event.edit(
            f"Push config: `{config.push_channel}`\n",
            buttons=await create_push_config_details_buttons(config.id)
        )
        
        await event.answer(f"Media send mode set to: {new_mode}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling media send mode: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer("Error processing request, please check logs")
