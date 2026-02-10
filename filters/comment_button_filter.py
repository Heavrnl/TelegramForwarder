import logging
import asyncio
import time
import telethon
import traceback
from telethon import Button
from filters.base_filter import BaseFilter
from telethon.tl.functions.channels import GetFullChannelRequest
from utils.common import get_main_module
from difflib import SequenceMatcher
import traceback
logger = logging.getLogger(__name__)

class CommentButtonFilter(BaseFilter):
    """
    Comment section button filter, used to add buttons pointing to associated group messages in messages
    """

    async def _process(self, context):
        """
        Add comment section button to messages

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        if context.rule.only_rss:
            logger.info('Only forwarding to RSS, skipping comment section button filter')
            return True

        # logger.info(f"Before CommentButtonFilter processing, context: {context.__dict__}")
        try:
            # If the rule doesn't exist or comment button feature is not enabled, skip directly
            if not context.rule or not context.rule.enable_comment_button:
                return True

            # If message content is empty, skip directly
            if not context.original_message_text and not context.event.message.media:
                return True

            try:
                # Get user client instead of Bot client
                main = await get_main_module()
                client = main.user_client if (main and hasattr(main, 'user_client')) else context.client

                event = context.event

                # Get original channel entity
                channel_entity = await client.get_entity(event.chat_id)

                # Get channel's actual username
                channel_username = None
                # logger.info(f"Got channel entity: {channel_entity}")
                # logger.info(f"Channel attribute content: {channel_entity.__dict__}")
                if hasattr(channel_entity, 'username') and channel_entity.username:
                    channel_username = channel_entity.username
                    logger.info(f"Got channel username: {channel_username}")
                elif hasattr(channel_entity, 'usernames') and channel_entity.usernames:
                    # Get the first active username
                    for username_obj in channel_entity.usernames:
                        if username_obj.active:
                            channel_username = username_obj.username
                            logger.info(f"Got channel username from usernames list: {channel_username}")
                            break

                # Get channel ID (remove prefix)
                channel_id_str = str(channel_entity.id)
                if channel_id_str.startswith('-100'):
                    channel_id_str = channel_id_str[4:]
                elif channel_id_str.startswith('100'):
                    channel_id_str = channel_id_str[3:]

                logger.info(f"Processing channel ID: {channel_id_str}")

                # Only process channel messages
                if not hasattr(channel_entity, 'broadcast') or not channel_entity.broadcast:
                    return True

                # Get associated group ID
                try:
                    # Get full channel information
                    full_channel = await client(GetFullChannelRequest(channel_entity))

                    # Check if there is an associated group
                    if not full_channel.full_chat.linked_chat_id:
                        logger.info(f"Channel {channel_entity.id} has no associated group, skipping comment button addition")
                        return True

                    linked_group_id = full_channel.full_chat.linked_chat_id

                    # Get associated group entity
                    linked_group = await client.get_entity(linked_group_id)

                    # Check if the message belongs to a media group
                    channel_msg_id = event.message.id

                    if hasattr(event.message, 'grouped_id') and event.message.grouped_id:
                        logger.info(f"Detected media group message, group ID: {event.message.grouped_id}")
                        # Get all messages in the same media group
                        media_group_messages = []

                        try:
                            # Get channel history messages
                            async for message in client.iter_messages(
                                channel_entity,
                                limit=20,  # Limit query message count
                                offset_date=event.message.date,  # Start query from current message time
                                reverse=False  # From newest to oldest
                            ):
                                # Check if it belongs to the same media group
                                if (hasattr(message, 'grouped_id') and
                                    message.grouped_id == event.message.grouped_id):
                                    media_group_messages.append(message)

                            if media_group_messages:
                                # Find the message with the smallest ID
                                min_id_message = min(media_group_messages, key=lambda x: x.id)
                                channel_msg_id = min_id_message.id
                                logger.info(f"Using message with smallest ID in media group: {channel_msg_id}")
                        except Exception as e:
                            logger.error(f"Failed to get media group messages: {e}")
                            # Use original message ID on failure
                            logger.info(f"Using original message ID: {channel_msg_id}")

                    # Add brief delay to ensure message sync is complete
                    logger.info("Waiting 2 seconds to ensure message sync is complete...")
                    await asyncio.sleep(2)

                    # Build comment section link - does not depend on matching group messages
                    comment_link = None
                    if channel_username:
                        # Public channel - use username link
                        comment_link = f"https://t.me/{channel_username}/{channel_msg_id}?comment=1"
                        logger.info(f"Built public channel comment section link: {comment_link}")
                    else:
                        # Private channel - use ID link
                        comment_link = f"https://t.me/c/{channel_id_str}/{channel_msg_id}?comment=1"
                        logger.info(f"Built private channel comment section link: {comment_link}")


                    # If group messages can be obtained, try to find exact match for better experience
                    try:
                        # Find corresponding message in associated group - use user client
                        logger.info(f"Trying to use user client to get messages from group {linked_group_id}")
                        group_messages = await client.get_messages(linked_group, limit=5)
                        logger.info(f"Successfully got {len(group_messages)} messages from associated group {linked_group_id}")

                        # Try to find a message with matching content
                        matched_msg = None

                        # 1. First try exact content match
                        original_message = context.original_message_text
                        if original_message:
                            logger.info(f"Trying to find exact content match, original content length: {len(original_message)}")

                            for msg in group_messages:
                                if hasattr(msg, 'message') and msg.message and msg.message == original_message:
                                    matched_msg = msg
                                    logger.info(f"Found exact match: group message ID {msg.id}")
                                    break

                        # 2. If exact match fails, try using SequenceMatcher for first 20 characters similarity match
                        if not matched_msg and original_message and len(original_message) > 20:

                            message_start = original_message[:20]
                            logger.info(f"Trying similarity match on first 20 characters: '{message_start}'")

                            for msg in group_messages:
                                if hasattr(msg, 'message') and msg.message and len(msg.message) > 20:
                                    msg_start = msg.message[:20]
                                    similarity = SequenceMatcher(None, message_start, msg_start).ratio()
                                    if similarity > 0.75:
                                        matched_msg = msg
                                        logger.info(f"Found similarity match: group message ID {msg.id}, first 20 characters similarity: {similarity}")
                                        break

                        # 3. If no match found, try time-based matching
                        if not matched_msg and hasattr(event.message, 'date'):
                            message_time = event.message.date
                            logger.info(f"Trying time-based matching, original message time: {message_time}")

                            # Get messages within 1 minute before and after the message time
                            time_window = 1  # minutes

                            for msg in group_messages:
                                if hasattr(msg, 'date'):
                                    time_diff = abs((msg.date - message_time).total_seconds())
                                    if time_diff < time_window * 60:
                                        matched_msg = msg
                                        logger.info(f"Found time-proximate message: group message ID {msg.id}, time difference: {time_diff} seconds")
                                        break

                        # 4. If still not found, use the latest message
                        if not matched_msg:
                            logger.info("No matching message found, trying to use the latest message")
                            # Use the latest message as default
                            if group_messages:
                                matched_msg = group_messages[0]
                                logger.info(f"Using latest message: group message ID {matched_msg.id}")

                        # If a matching message was found, update the link
                        if matched_msg:
                            group_msg_id = matched_msg.id
                            if channel_username:
                                # Public channel - use username link
                                comment_link = f"https://t.me/{channel_username}/{channel_msg_id}?comment={group_msg_id}"
                            else:
                                # Private channel - use ID link
                                comment_link = f"https://t.me/c/{channel_id_str}/{channel_msg_id}?comment={group_msg_id}"
                            logger.info(f"Updated to precise comment section link: {comment_link}")

                    except Exception as e:
                        logger.warning(f"Failed to get group messages, possibly because not joined the group: {str(e)}")
                        logger.info("Will use basic comment section link")
                        # Keep using the basic comment=1 link

                    # Create group backup link
                    group_link = None
                    if hasattr(linked_group, 'username') and linked_group.username:
                        group_link = f"https://t.me/{linked_group.username}"
                        logger.info(f"Generated group backup link: {group_link}")

                    # Save comment section link to context for subsequent filters to use
                    context.comment_link = comment_link

                    # If it's a media group message, skip adding button (handled by ReplyFilter)
                    if context.is_media_group:
                        logger.info("Media group message comment section button will be handled by ReplyFilter")
                        return True

                    # Add buttons
                    buttons_added = False

                    # Add comment section button
                    if comment_link:
                        # Create comment section button
                        comment_button = Button.url("💬 View comments", comment_link)

                        # Add button to message
                        if not context.buttons:
                            context.buttons = [[comment_button]]
                        else:
                            # If there are already buttons, add to the first row
                            context.buttons.insert(0, [comment_button])

                        logger.info(f"Added comment section button to message, link: {comment_link}")
                        buttons_added = True


                    if not buttons_added:
                        logger.warning("Failed to add any buttons")
                except Exception as e:
                    logger.error(f"Error getting associated group messages: {str(e)}")
                    tb = traceback.format_exc()
                    logger.debug(f"Detailed error info: {tb}")

            except Exception as e:
                logger.error(f"Error adding comment section button: {str(e)}")
                logger.error(traceback.format_exc())

            return True
        finally:
            # logger.info(f"After CommentButtonFilter processing, context: {context.__dict__}")
            pass
