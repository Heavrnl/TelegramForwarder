import traceback

from handlers.button.button_helpers import create_media_size_buttons,create_media_settings_buttons,create_media_types_buttons,create_media_extensions_buttons
from models.models import ForwardRule, MediaTypes, MediaExtensions, RuleSync
from enums.enums import AddMode
import logging
from utils.common import get_media_settings_text, get_db_ops
from models.models import get_session
from models.db_operations import DBOperations

logger = logging.getLogger(__name__)



async def callback_media_settings(event, rule_id, session, message, data):
    # Show media settings page
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            await event.edit(await get_media_settings_text(), buttons=await create_media_settings_buttons(rule))
    finally:
        session.close()
    return




async def callback_set_max_media_size(event, rule_id, session, message, data):
        await event.edit("Select maximum media size (MB):", buttons=await create_media_size_buttons(rule_id, page=0))
        return



async def callback_select_max_media_size(event, rule_id, session, message, data):
        parts = data.split(':', 2)  # Split at most 2 times
        if len(parts) == 3:
            _, rule_id, size = parts
            logger.info(f"Setting max media size for rule {rule_id} to: {size}")
            try:
                rule = session.query(ForwardRule).get(int(rule_id))
                if rule:
                    # Record old size
                    old_size = rule.max_media_size

                    # Update max media size
                    rule.max_media_size = int(size)
                    session.commit()
                    logger.info(f"Database updated successfully: {old_size} -> {size}")

                    # Check if sync is enabled
                    if rule.enable_sync:
                        logger.info(f"Rule {rule.id} has sync enabled, syncing media size to associated rules")
                        # Get list of rules to sync
                        sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

                        # Apply same media size to each sync rule
                        for sync_rule in sync_rules:
                            sync_rule_id = sync_rule.sync_rule_id
                            logger.info(f"Syncing media size to rule {sync_rule_id}")

                            # Get sync target rule
                            target_rule = session.query(ForwardRule).get(sync_rule_id)
                            if not target_rule:
                                logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                                continue

                            # Update sync target rule's media size
                            try:
                                # Record old size
                                old_target_size = target_rule.max_media_size

                                # Set new size
                                target_rule.max_media_size = int(size)

                                logger.info(f"Synced rule {sync_rule_id} media size from {old_target_size} to {size}")
                            except Exception as e:
                                logger.error(f"Error syncing media size to rule {sync_rule_id}: {str(e)}")
                                continue

                        # Commit all sync changes
                        session.commit()
                        logger.info("All sync media size changes committed")

                    # Get message object
                    message = await event.get_message()

                    await event.edit("Media settings:", buttons=await create_media_settings_buttons(rule))
                    await event.answer(f"Max media size set to: {size}MB")
                    logger.info("UI update complete")
            except Exception as e:
                logger.error(f"Error setting max media size: {str(e)}")
                logger.error(f"Error details: {traceback.format_exc()}")
            finally:
                session.close()
        return




async def callback_set_media_types(event, rule_id, session, message, data):
    """Handle callback for viewing and setting media types"""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer("Rule not found")
            return

        # Get or create media type settings
        db_ops = await get_db_ops()
        success, msg, media_types = await db_ops.get_media_types(session, rule.id)

        if not success:
            await event.answer(f"Failed to get media type settings: {msg}")
            return

        # Show media type selection interface
        await event.edit("Select media types to block", buttons=await create_media_types_buttons(rule.id, media_types))

    except Exception as e:
        logger.error(f"Error setting media types: {str(e)}")
        logger.error(f"Error details: {traceback.format_exc()}")
        await event.answer(f"Error setting media types: {str(e)}")
    finally:
        session.close()
    return

async def callback_toggle_media_type(event, rule_id, session, message, data):
    """Handle callback for toggling media type"""
    try:
        # Correctly parse data to get rule_id and media type
        parts = data.split(':')
        if len(parts) < 3:
            await event.answer("Invalid data format")
            return

        # toggle_media_type:31:voice
        action = parts[0]
        rule_id = parts[1]
        media_type = parts[2]
        # Check if media type is valid
        if media_type not in ['photo', 'document', 'video', 'audio', 'voice']:
            await event.answer(f"Invalid media type: {media_type}")
            return

        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer("Rule not found")
            return

        # Toggle media type status
        db_ops = await get_db_ops()
        success, msg = await db_ops.toggle_media_type(session, rule.id, media_type)

        if not success:
            await event.answer(f"Failed to toggle media type: {msg}")
            return

        # Check if sync is enabled
        if rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing media type settings to associated rules")

            # Get current media type status for this rule
            success, _, current_media_types = await db_ops.get_media_types(session, rule.id)
            if not success:
                logger.warning(f"Failed to get media type settings, cannot sync")
            else:
                # Get list of rules to sync
                sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

                # Apply same media type settings to each sync rule
                for sync_rule in sync_rules:
                    sync_rule_id = sync_rule.sync_rule_id
                    logger.info(f"Syncing media type {media_type} to rule {sync_rule_id}")

                    # Get sync target rule
                    target_rule = session.query(ForwardRule).get(sync_rule_id)
                    if not target_rule:
                        logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                        continue

                    # Update sync target rule's media type settings
                    try:
                        # Get target rule's current media type settings
                        target_success, _, target_media_types = await db_ops.get_media_types(session, sync_rule_id)
                        if not target_success:
                            logger.warning(f"Failed to get media types for target rule {sync_rule_id}, skipping")
                            continue

                        # Get the new status for the current type
                        current_type_status = getattr(current_media_types, media_type)

                        # If target media type status differs from main rule, update it
                        if getattr(target_media_types, media_type) != current_type_status:
                            # Force set to same status as main rule
                            if current_type_status:
                                # Main rule is enabled, ensure target rule is also enabled
                                if not getattr(target_media_types, media_type):
                                    await db_ops.toggle_media_type(session, sync_rule_id, media_type)
                                    logger.info(f"Synced rule {sync_rule_id} media type {media_type} enabled")
                            else:
                                # Main rule is disabled, ensure target rule is also disabled
                                if getattr(target_media_types, media_type):
                                    await db_ops.toggle_media_type(session, sync_rule_id, media_type)
                                    logger.info(f"Synced rule {sync_rule_id} media type {media_type} disabled")
                        else:
                            logger.info(f"Target rule {sync_rule_id} media type {media_type} already has status {current_type_status}, no change needed")

                    except Exception as e:
                        logger.error(f"Error syncing media type to rule {sync_rule_id}: {str(e)}")
                        continue

        # Re-fetch media type settings
        success, _, media_types = await db_ops.get_media_types(session, rule.id)

        if not success:
            await event.answer("Failed to get media type settings")
            return

        # Update UI
        await event.edit("Select media types to block", buttons=await create_media_types_buttons(rule.id, media_types))
        await event.answer(msg)

    except Exception as e:
        logger.error(f"Error toggling media type: {str(e)}")
        logger.error(f"Error details: {traceback.format_exc()}")
        await event.answer(f"Error toggling media type: {str(e)}")
    finally:
        session.close()
    return


async def callback_set_media_extensions(event, rule_id, session, message, data):
    await event.edit("Select media extensions to filter:", buttons=await create_media_extensions_buttons(rule_id, page=0))
    return


async def callback_media_extensions_page(event, rule_id, session, message, data):
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("Select media extensions to filter:", buttons=await create_media_extensions_buttons(rule_id, page=page))
    return

async def callback_toggle_media_extension(event, rule_id, session, message, data):
    """Handle callback for toggling media extension"""
    try:
        # Parse data to get rule_id and extension
        parts = data.split(':')
        if len(parts) < 3:
            await event.answer("Invalid data format")
            return

        # toggle_media_extension:31:jpg:0
        action = parts[0]
        rule_id = parts[1]
        extension = parts[2]

        # Get current page number if provided
        current_page = 0
        if len(parts) > 3 and parts[3].isdigit():
            current_page = int(parts[3])

        # Get rule
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer("Rule not found")
            return

        # Get currently selected extensions for this rule
        db_ops = await get_db_ops()
        selected_extensions = await db_ops.get_media_extensions(session, rule.id)
        selected_extension_list = [ext["extension"] for ext in selected_extensions]

        # Toggle extension status
        was_selected = extension in selected_extension_list
        if was_selected:
            # If exists, remove it
            extension_id = next((ext["id"] for ext in selected_extensions if ext["extension"] == extension), None)
            if extension_id:
                success, msg = await db_ops.delete_media_extensions(session, rule.id, [extension_id])
                if success:
                    await event.answer(f"Extension removed: {extension}")

                    # Check if sync is enabled
                    if rule.enable_sync:
                        logger.info(f"Rule {rule.id} has sync enabled, syncing media extension removal to associated rules")

                        # Get list of rules to sync
                        sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

                        # Apply same media extension settings to each sync rule
                        for sync_rule in sync_rules:
                            sync_rule_id = sync_rule.sync_rule_id
                            logger.info(f"Syncing removal of media extension {extension} to rule {sync_rule_id}")

                            # Get sync target rule
                            target_rule = session.query(ForwardRule).get(sync_rule_id)
                            if not target_rule:
                                logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                                continue

                            # Update sync target rule's media extension settings
                            try:
                                # Get target rule's current extension settings
                                target_extensions = await db_ops.get_media_extensions(session, sync_rule_id)
                                target_extension_list = [ext["extension"] for ext in target_extensions]

                                # If extension exists in target rule, remove it
                                if extension in target_extension_list:
                                    target_extension_id = next((ext["id"] for ext in target_extensions if ext["extension"] == extension), None)
                                    if target_extension_id:
                                        await db_ops.delete_media_extensions(session, sync_rule_id, [target_extension_id])
                                        logger.info(f"Synced rule {sync_rule_id} media extension {extension} removed")
                                    else:
                                        logger.warning(f"Cannot find ID for extension {extension} in target rule {sync_rule_id}")
                                else:
                                    logger.info(f"Extension {extension} not found in target rule {sync_rule_id}, no need to delete")
                            except Exception as e:
                                logger.error(f"Error syncing media extension removal to rule {sync_rule_id}: {str(e)}")
                                continue
                else:
                    await event.answer(f"Failed to remove extension: {msg}")
        else:
            # If not exists, add it
            success, msg = await db_ops.add_media_extensions(session, rule.id, [extension])
            if success:
                await event.answer(f"Extension added: {extension}")

                # Check if sync is enabled
                if rule.enable_sync:
                    logger.info(f"Rule {rule.id} has sync enabled, syncing media extension addition to associated rules")

                    # Get list of rules to sync
                    sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

                    # Apply same media extension settings to each sync rule
                    for sync_rule in sync_rules:
                        sync_rule_id = sync_rule.sync_rule_id
                        logger.info(f"Syncing addition of media extension {extension} to rule {sync_rule_id}")

                        # Get sync target rule
                        target_rule = session.query(ForwardRule).get(sync_rule_id)
                        if not target_rule:
                            logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                            continue

                        # Update sync target rule's media extension settings
                        try:
                            # Get target rule's current extension settings
                            target_extensions = await db_ops.get_media_extensions(session, sync_rule_id)
                            target_extension_list = [ext["extension"] for ext in target_extensions]

                            # If extension not in target rule, add it
                            if extension not in target_extension_list:
                                await db_ops.add_media_extensions(session, sync_rule_id, [extension])
                                logger.info(f"Synced rule {sync_rule_id} media extension {extension} added")
                            else:
                                logger.info(f"Extension {extension} already exists in target rule {sync_rule_id}, no need to add")
                        except Exception as e:
                            logger.error(f"Error syncing media extension addition to rule {sync_rule_id}: {str(e)}")
                            continue
            else:
                await event.answer(f"Failed to add extension: {msg}")

        # Update UI using previously obtained page number
        await event.edit("Select media extensions to filter:", buttons=await create_media_extensions_buttons(rule_id, page=current_page))

    except Exception as e:
        logger.error(f"Error toggling media extension: {str(e)}")
        logger.error(f"Error details: {traceback.format_exc()}")
        await event.answer(f"Error toggling media extension: {str(e)}")
    finally:
        session.close()
    return

async def callback_toggle_media_allow_text(event, rule_id, session, message, data):
    """Handle callback for toggling text pass-through."""
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer("Rule not found")
            return

        # Toggle the status
        rule.media_allow_text = not rule.media_allow_text

        # Check if sync is enabled
        if rule.enable_sync:
            logger.info(f"Rule {rule.id} has sync enabled, syncing 'allow text' setting to associated rules")

            # Get list of rules to sync
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule.id).all()

            # Apply the same setting to each sync rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing 'allow text' setting to rule {sync_rule_id}")

                # Get the sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} not found, skipping")
                    continue

                # Update the sync target rule's setting
                try:
                    target_rule.media_allow_text = rule.media_allow_text
                    logger.info(f"Rule {sync_rule_id} 'allow text' setting updated to {rule.media_allow_text}")
                except Exception as e:
                    logger.error(f"Error syncing 'allow text' setting to rule {sync_rule_id}: {str(e)}")
                    continue

        # Commit changes
        session.commit()

        # Update UI
        await event.edit(await get_media_settings_text(), buttons=await create_media_settings_buttons(rule))

        # Show result to user
        status = "enabled" if rule.media_allow_text else "disabled"
        await event.answer(f"Text pass-through {status}")

    except Exception as e:
        session.rollback()
        logger.error(f"Error toggling text pass-through setting: {str(e)}")
        logger.error(f"Error details: {traceback.format_exc()}")
        await event.answer(f"Error toggling text pass-through: {str(e)}")
    finally:
        session.close()
    return
