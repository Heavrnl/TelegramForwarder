import logging
from models.models import get_session, ForwardRule, RuleSync
from managers.state_manager import state_manager
from utils.common import get_ai_settings_text
from handlers import bot_handler
from utils.auto_delete import async_delete_user_message
from utils.common import get_bot_client
from utils.common import get_main_module
import traceback
from utils.auto_delete import send_message_and_delete
from models.models import PushConfig

logger = logging.getLogger(__name__)

async def handle_prompt_setting(event, client, sender_id, chat_id, current_state, message):
    """Handle the logic for setting prompts"""
    logger.info(f"Starting to process prompt setting, user ID: {sender_id}, chat ID: {chat_id}, current state: {current_state}")
    
    if not current_state:
        logger.info("No current state, returning False")
        return False

    rule_id = None
    field_name = None 
    prompt_type = None
    template_type = None

    if current_state.startswith("set_summary_prompt:"):
        rule_id = current_state.split(":")[1]
        field_name = "summary_prompt"
        prompt_type = "AI Summary"
        template_type = "ai"
        logger.info(f"Detected setting summary prompt, rule ID: {rule_id}")
    elif current_state.startswith("set_ai_prompt:"):
        rule_id = current_state.split(":")[1]
        field_name = "ai_prompt"
        prompt_type = "AI"
        template_type = "ai"
        logger.info(f"Detected setting AI prompt, rule ID: {rule_id}")
    elif current_state.startswith("set_userinfo_template:"):
        rule_id = current_state.split(":")[1]
        field_name = "userinfo_template"
        prompt_type = "User Info"
        template_type = "userinfo"
        logger.info(f"Detected setting user info template, rule ID: {rule_id}")
    elif current_state.startswith("set_time_template:"):
        rule_id = current_state.split(":")[1]
        field_name = "time_template"
        prompt_type = "Time"
        template_type = "time"
        logger.info(f"Detected setting time template, rule ID: {rule_id}")
    elif current_state.startswith("set_original_link_template:"):
        rule_id = current_state.split(":")[1]
        field_name = "original_link_template"
        prompt_type = "Original Link"
        template_type = "link"
        logger.info(f"Detected setting original link template, rule ID: {rule_id}")
    elif current_state.startswith("add_push_channel:"):
        # Handle adding push channel
        rule_id = current_state.split(":")[1]
        logger.info(f"Detected adding push channel, rule ID: {rule_id}")
        return await handle_add_push_channel(event, client, sender_id, chat_id, rule_id, message)
    else:
        logger.info(f"Unknown state type: {current_state}")
        return False

    logger.info(f"Processing setting {prompt_type} prompt/template, rule ID: {rule_id}, field name: {field_name}")
    session = get_session()
    try:
        logger.info(f"Querying rule ID: {rule_id}")
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            old_prompt = getattr(rule, field_name) if hasattr(rule, field_name) else None
            new_prompt = event.message.text
            logger.info(f"Rule found, original prompt/template: {old_prompt}")
            logger.info(f"Preparing to update to new prompt/template: {new_prompt}")
            
            setattr(rule, field_name, new_prompt)
            session.commit()
            logger.info(f"Updated rule {rule_id}'s {prompt_type} prompt/template")

            # Check if sync feature is enabled
            if rule.enable_sync:
                logger.info(f"Rule {rule.id} has sync enabled, syncing prompt/template settings to associated rules")
                # Get list of rules that need to be synced
                sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
                
                # Apply the same prompt settings for each sync rule
                for sync_rule in sync_rules:
                    sync_rule_id = sync_rule.sync_rule_id
                    logger.info(f"Syncing {prompt_type} prompt/template to rule {sync_rule_id}")

                    # Get sync target rule
                    target_rule = session.query(ForwardRule).get(sync_rule_id)
                    if not target_rule:
                        logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                        continue

                    # Update sync target rule's prompt settings
                    try:
                        # Record old prompt
                        old_target_prompt = getattr(target_rule, field_name) if hasattr(target_rule, field_name) else None
                        
                        # Set new prompt
                        setattr(target_rule, field_name, new_prompt)
                        
                        logger.info(f"Synced rule {sync_rule_id}'s {prompt_type} prompt/template from '{old_target_prompt}' to '{new_prompt}'")
                    except Exception as e:
                        logger.error(f"Error syncing {prompt_type} prompt/template to rule {sync_rule_id}: {str(e)}")
                        continue
                
                session.commit()
                logger.info("All synced prompt/template changes have been committed")
            
            logger.info(f"Clearing user state, user ID: {sender_id}, chat ID: {chat_id}")
            state_manager.clear_state(sender_id, chat_id)
            
            
            message_chat_id = event.message.chat_id
            bot_client = await get_bot_client()
            
            
            try:
                await async_delete_user_message(bot_client, message_chat_id, event.message.id, 0)
            except Exception as e:
                logger.error(f"Failed to delete user message: {str(e)}")

            await message.delete()
            logger.info("Preparing to send updated settings message")

            # Choose different display page based on template type
            if template_type == "ai":
                # AI settings page
                await client.send_message(
                    chat_id,
                    await get_ai_settings_text(rule),
                    buttons=await bot_handler.create_ai_settings_buttons(rule)
                )
            elif template_type in ["userinfo", "time", "link"]:
                # Other settings page
                await client.send_message(
                    chat_id,
                    f"Updated rule {rule_id}'s {prompt_type} template",
                    buttons=await bot_handler.create_other_settings_buttons(rule_id=rule_id)
                )
            
            # Delete user message
            logger.info("Settings message sent successfully")
            return True
        else:
            logger.warning(f"Rule ID not found: {rule_id}")
    except Exception as e:
        logger.error(f"Error occurred while processing prompt/template setting: {str(e)}")
        raise
    finally:
        session.close()
        logger.info("Database session closed")
    return True

async def handle_add_push_channel(event, client, sender_id, chat_id, rule_id, message):
    """Handle the logic for adding push channel"""
    logger.info(f"Starting to process adding push channel, rule ID: {rule_id}")
    
    session = get_session()
    try:
        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            logger.warning(f"Rule ID not found: {rule_id}")
            return False
        
        # Get push channel info entered by user
        push_channel = event.message.text.strip()
        logger.info(f"Push channel entered by user: {push_channel}")
        
        try:
            # Create new push configuration
            is_email = push_channel.startswith(('mailto://', 'mailtos://', 'email://'))
            push_config = PushConfig(
                rule_id=int(rule_id),
                push_channel=push_channel,
                enable_push_channel=True,
                media_send_mode="Multiple" if is_email else "Single"
            )
            session.add(push_config)
            
            # Enable push feature for the rule
            rule.enable_push = True
            
            # Check if sync feature is enabled
            if rule.enable_sync:
                logger.info(f"Rule {rule.id} has sync enabled, syncing push configuration to associated rules")

                # Get list of rules that need to be synced
                sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()
                
                # Create the same push configuration for each sync rule
                for sync_rule in sync_rules:
                    sync_rule_id = sync_rule.sync_rule_id
                    logger.info(f"Syncing push configuration to rule {sync_rule_id}")

                    # Get sync target rule
                    target_rule = session.query(ForwardRule).get(sync_rule_id)
                    if not target_rule:
                        logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                        continue

                    # Check if target rule already has the same push channel
                    existing_config = session.query(PushConfig).filter_by(
                        rule_id=sync_rule_id, 
                        push_channel=push_channel
                    ).first()
                    
                    if existing_config:
                        logger.info(f"Target rule {sync_rule_id} already has push channel {push_channel}, skipping")
                        continue
                    
                    # Create new push configuration
                    try:
                        sync_push_config = PushConfig(
                            rule_id=sync_rule_id,
                            push_channel=push_channel,
                            enable_push_channel=True,
                            media_send_mode=push_config.media_send_mode
                        )
                        session.add(sync_push_config)
                        
                        # Enable push feature for target rule
                        target_rule.enable_push = True
                        
                        logger.info(f"Added push channel {push_channel} for rule {sync_rule_id}")
                    except Exception as e:
                        logger.error(f"Error adding push configuration for rule {sync_rule_id}: {str(e)}")
                        continue
            
            # Commit changes
            session.commit()
            success = True
            message_text = "Successfully added push configuration"
        except Exception as db_error:
            session.rollback()
            success = False
            message_text = f"Failed to add push configuration: {str(db_error)}"
            logger.error(f"Error adding push configuration to database: {str(db_error)}")
        
        # Clear state
        state_manager.clear_state(sender_id, chat_id)
        
        # Delete user message
        message_chat_id = event.message.chat_id
        bot_client = await get_bot_client()
        try:
            await async_delete_user_message(bot_client, message_chat_id, event.message.id, 0)
        except Exception as e:
            logger.error(f"Failed to delete user message: {str(e)}")

        # Delete original message and display result
        await message.delete()
        
        # Get main module
        main_module = await get_main_module()
        bot_client = main_module.bot_client
        
        # Send result notification
        if success:
            await send_message_and_delete(
                bot_client,
                chat_id,
                f"Successfully added push channel: {push_channel}",
                buttons=await bot_handler.create_push_settings_buttons(rule_id)
            )
        else:
            await send_message_and_delete(
                bot_client,
                chat_id,
                f"Failed to add push channel: {message_text}",
                buttons=await bot_handler.create_push_settings_buttons(rule_id)
            )
        
        return True
    except Exception as e:
        logger.error(f"Error processing adding push channel: {str(e)}")
        logger.error(traceback.format_exc())
        return False
    finally:
        session.close()