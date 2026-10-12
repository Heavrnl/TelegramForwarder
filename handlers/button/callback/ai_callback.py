import os
import traceback
from managers.state_manager import state_manager
import asyncio
from telethon.tl import types

from handlers.button.button_helpers import create_ai_settings_buttons, create_model_buttons, create_summary_time_buttons
from models.models import ForwardRule, RuleSync
from telethon import Button
import logging
from utils.common import get_main_module, get_ai_settings_text
from utils.common import is_admin
from scheduler.summary_scheduler import SummaryScheduler


logger = logging.getLogger(__name__)


async def callback_ai_settings(event, rule_id, session, message, data):
    # Show AI settings page
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
    finally:
        session.close()
    return



async def callback_set_summary_time(event, rule_id, session, message, data):
    await event.edit("Select summary time:", buttons=await create_summary_time_buttons(rule_id, page=0))
    return

async def callback_set_summary_prompt(event, rule_id, session, message, data):
    """Handle callback for setting AI summary prompt"""
    logger.info(f"Starting to handle set AI summary prompt callback - event: {event}, rule_id: {rule_id}")

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
    state = f"set_summary_prompt:{rule_id}"

    logger.info(f"Preparing to set state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message, state_type="ai")
        # Start timeout cancel task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("State set successfully")
    except Exception as e:
        logger.error(f"Error setting state: {str(e)}")
        logger.exception(e)

    try:
        current_prompt = rule.summary_prompt or os.getenv('DEFAULT_SUMMARY_PROMPT', 'Not set')
        await message.edit(
            f"Send the new AI summary prompt\n"
            f"Current rule ID: `{rule_id}`\n"
            f"Current AI summary prompt:\n\n`{current_prompt}`\n\n"
            f"Will auto-cancel if not set within 5 minutes",
            buttons=[[Button.inline("Cancel", f"cancel_set_summary:{rule_id}")]]
        )
        logger.info("Message edited successfully")
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        logger.exception(e)


async def cancel_state_after_timeout(user_id: int, chat_id: int, timeout_minutes: int = 5):
    """Automatically cancel state after specified time"""
    await asyncio.sleep(timeout_minutes * 60)
    current_state, _, _ = state_manager.get_state(user_id, chat_id)
    if current_state:  # Only clear if state still exists
        logger.info(f"State auto-cancelled due to timeout - user_id: {user_id}, chat_id: {chat_id}")
        state_manager.clear_state(user_id, chat_id)


async def callback_set_ai_prompt(event, rule_id, session, message, data):
    """Handle callback for setting AI prompt"""
    logger.info(f"Starting to handle set AI prompt callback - event: {event}, rule_id: {rule_id}")

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
    state = f"set_ai_prompt:{rule_id}"

    logger.info(f"Preparing to set state - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message, state_type="ai")
        # Start timeout cancel task
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("State set successfully")
    except Exception as e:
        logger.error(f"Error setting state: {str(e)}")
        logger.exception(e)

    try:
        current_prompt = rule.ai_prompt or os.getenv('DEFAULT_AI_PROMPT', 'Not set')
        await message.edit(
            f"Send the new AI prompt\n"
            f"Current rule ID: `{rule_id}`\n"
            f"Current AI prompt:\n\n`{current_prompt}`\n\n"
            f"Will auto-cancel if not set within 5 minutes",
            buttons=[[Button.inline("Cancel", f"cancel_set_prompt:{rule_id}")]]
        )
        logger.info("Message edited successfully")
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        logger.exception(e)


   
            

async def callback_time_page(event, rule_id, session, message, data):
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("Select summary time:", buttons=await create_summary_time_buttons(rule_id, page=page))
    return


async def callback_select_time(event, rule_id, session, message, data):
    parts = data.split(':', 2)  # Split at most 2 times
    if len(parts) == 3:
        _, rule_id, time = parts
        logger.info(f"Setting summary time for rule {rule_id} to: {time}")
        try:
            rule = session.query(ForwardRule).get(int(rule_id))
            if rule:
                # Record old time
                old_time = rule.summary_time

                # Update time
                rule.summary_time = time
                session.commit()
                logger.info(f"Database updated successfully: {old_time} -> {time}")

                # Check if sync is enabled
                if rule.enable_sync:
                    logger.info(f"Rule {rule.id} has sync enabled, syncing summary time to associated rules")
                    # Get list of rules to sync
                    sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

                    # Apply same summary time to each sync rule
                    for sync_rule in sync_rules:
                        sync_rule_id = sync_rule.sync_rule_id
                        logger.info(f"Syncing summary time to rule {sync_rule_id}")

                        # Get sync target rule
                        target_rule = session.query(ForwardRule).get(sync_rule_id)
                        if not target_rule:
                            logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                            continue

                        # Update sync target rule's summary time
                        try:
                            # Record old time
                            old_target_time = target_rule.summary_time

                            # Set new time
                            target_rule.summary_time = time

                            # If target rule has summary enabled, also update its schedule
                            if target_rule.is_summary:
                                logger.info(f"Target rule {sync_rule_id} has summary enabled, updating its schedule")
                                main = await get_main_module()
                                if hasattr(main, 'scheduler') and main.scheduler:
                                    await main.scheduler.schedule_rule(target_rule)
                                    logger.info(f"Target rule schedule updated successfully, new time: {time}")
                                else:
                                    logger.warning("Scheduler not initialized")

                            logger.info(f"Synced rule {sync_rule_id} summary time from {old_target_time} to {time}")
                        except Exception as e:
                            logger.error(f"Error syncing summary time to rule {sync_rule_id}: {str(e)}")
                            continue

                    # Commit all sync changes
                    session.commit()
                    logger.info("All sync summary time changes committed")

                # If summary is enabled, reschedule task
                if rule.is_summary:
                    logger.info("Rule has summary enabled, updating schedule")
                    main = await get_main_module()
                    if hasattr(main, 'scheduler') and main.scheduler:
                        await main.scheduler.schedule_rule(rule)
                        logger.info(f"Schedule updated successfully, new time: {time}")
                    else:
                        logger.warning("Scheduler not initialized")
                else:
                    logger.info("Rule does not have summary enabled, skipping schedule update")

                await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
                logger.info("UI update complete")
        except Exception as e:
            logger.error(f"Error setting summary time: {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")
        finally:
            session.close()
    return


async def callback_select_model(event, rule_id, session, message, data):
    # Split data, at most 2 times, treating the third part as the full model name
    parts = data.split(':', 2)
    _, rule_id_part, model = parts

    try:
        rule = session.query(ForwardRule).get(int(rule_id_part))
        if rule:
            # Record old model
            old_model = rule.ai_model

            # Update model
            rule.ai_model = model
            session.commit()
            logger.info(f"Updated AI model for rule {rule_id_part} to: {model}")

            # Check if sync is enabled
            if rule.enable_sync:
                logger.info(f"Rule {rule.id} has sync enabled, syncing AI model to associated rules")
                # Get list of rules to sync
                sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

                # Apply same AI model to each sync rule
                for sync_rule in sync_rules:
                    sync_rule_id = sync_rule.sync_rule_id
                    logger.info(f"Syncing AI model to rule {sync_rule_id}")

                    # Get sync target rule
                    target_rule = session.query(ForwardRule).get(sync_rule_id)
                    if not target_rule:
                        logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                        continue

                    # Update sync target rule's AI model
                    try:
                        # Record old model
                        old_target_model = target_rule.ai_model

                        # Set new model
                        target_rule.ai_model = model

                        logger.info(f"Synced rule {sync_rule_id} AI model from {old_target_model} to {model}")
                    except Exception as e:
                        logger.error(f"Error syncing AI model to rule {sync_rule_id}: {str(e)}")
                        continue

                # Commit all sync changes
                session.commit()
                logger.info("All sync AI model changes committed")

            # Return to AI settings page
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
    finally:
        session.close()
    return



async def callback_model_page(event, rule_id, session, message, data):
    # Handle pagination
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("Select AI model:", buttons=await create_model_buttons(rule_id, page=page))
    return



async def callback_change_model(event, rule_id, session, message, data):
    await event.edit("Select AI model:", buttons=await create_model_buttons(rule_id, page=0))
    return



async def callback_cancel_set_prompt(event, rule_id, session, message, data):
    # Handle cancel set prompt
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # Clear state
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # Return to AI settings page
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
            await event.answer("Setting cancelled")
    finally:
        session.close()
    return




async def callback_cancel_set_summary(event, rule_id, session, message, data):
    # Handle cancel set summary
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # Clear state
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # Return to AI settings page
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
            await event.answer("Setting cancelled")
    finally:
        session.close()
    return

async def callback_summary_now(event, rule_id, session, message, data):
    # Handle immediate summary execution callback
    logger.info(f"Handling immediate summary callback - rule_id: {rule_id}")

    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer("Rule not found")
            return

        main = await get_main_module()
        user_client = main.user_client
        bot_client = main.bot_client

        scheduler = SummaryScheduler(user_client, bot_client)
        await event.answer("Starting summary, please wait...")

        await message.edit(
            f"Generating summary for rule {rule_id} ({rule.source_chat.name} -> {rule.target_chat.name})...\n"
            f"Processing may take some time, please be patient.",
            buttons=[[Button.inline("Back", f"ai_settings:{rule_id}")]]
        )

        try:
            # Execute summary task
            await asyncio.create_task(scheduler._execute_summary(rule.id,is_now=True))
            logger.info(f"Immediate summary task started for rule {rule_id}")
        except Exception as e:
            logger.error(f"Summary task failed: {str(e)}")
            logger.error(traceback.format_exc())
            await message.edit(
                f"Summary generation failed: {str(e)}",
                buttons=[[Button.inline("Back", f"ai_settings:{rule_id}")]]
            )
    except Exception as e:
        logger.error(f"Error handling summary: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer(f"Error processing: {str(e)}")
    finally:
        session.close()

    return
