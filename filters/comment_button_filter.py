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
    Comment-section button filter — adds a button to messages that links
    to the corresponding message in the channel's linked discussion group.
    """

    async def _process(self, context):
        """
        Add a comment-section button to the message.

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        if context.rule.only_rss:
            logger.info('RSS-only forwarding; skipping comment button filter')
            return True

        # logger.info(f"CommentButtonFilter processing message, context: {context.__dict__}")
        try:
            # If the rule does not exist or the comment button feature is not enabled, skip
            if not context.rule or not context.rule.enable_comment_button:
                return True

            # If the message content is empty, skip
            if not context.original_message_text and not context.event.message.media:
                return True

            try:
                # Use the user client rather than the bot client
                main = await get_main_module()
                client = main.user_client if (main and hasattr(main, 'user_client')) else context.client

                event = context.event

                # Get the originating channel entity
                channel_entity = await client.get_entity(event.chat_id)

                # Get the channel's actual username
                channel_username = None
                # logger.info(f"Channel entity: {channel_entity}")
                # logger.info(f"Channel attributes: {channel_entity.__dict__}")
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

                # Get the channel ID (strip prefix)
                channel_id_str = str(channel_entity.id)
                if channel_id_str.startswith('-100'):
                    channel_id_str = channel_id_str[4:]
                elif channel_id_str.startswith('100'):
                    channel_id_str = channel_id_str[3:]

                logger.info(f"Processing channel ID: {channel_id_str}")

                # Only process channel messages
                if not hasattr(channel_entity, 'broadcast') or not channel_entity.broadcast:
                    return True

                # Get the linked group ID
                try:
                    # Fetch full channel info
                    full_channel = await client(GetFullChannelRequest(channel_entity))

                    # Check whether the channel has a linked group
                    if not full_channel.full_chat.linked_chat_id:
                        logger.info(f"Channel {channel_entity.id} has no linked group; skipping comment button")
                        return True

                    linked_group_id = full_channel.full_chat.linked_chat_id

                    # Get the linked group entity
                    linked_group = await client.get_entity(linked_group_id)

                    # Check whether the message belongs to a media group
                    channel_msg_id = event.message.id

                    if hasattr(event.message, 'grouped_id') and event.message.grouped_id:
                        logger.info(f"Detected media group message, group ID: {event.message.grouped_id}")
                        # Collect all messages in the same media group
                        media_group_messages = []

                        try:
                            # Iterate over recent channel history
                            async for message in client.iter_messages(
                                channel_entity,
                                limit=20,  # Limit the number of messages queried
                                offset_date=event.message.date,  # Start from the current message's timestamp
                                reverse=False  # Newest first
                            ):
                                # Check whether this message belongs to the same media group
                                if (hasattr(message, 'grouped_id') and
                                    message.grouped_id == event.message.grouped_id):
                                    media_group_messages.append(message)

                            if media_group_messages:
                                # Use the message with the smallest ID in the group
                                min_id_message = min(media_group_messages, key=lambda x: x.id)
                                channel_msg_id = min_id_message.id
                                logger.info(f"Using media group message with smallest ID: {channel_msg_id}")
                        except Exception as e:
                            logger.error(f"Failed to retrieve media group messages: {e}")
                            # Fall back to the original message ID on failure
                            logger.info(f"Using original message ID: {channel_msg_id}")

                    # Brief delay to allow message sync to complete
                    logger.info("Waiting 2 seconds for message sync to complete...")
                    await asyncio.sleep(2)

                    # Build the comment section link — does not depend on matching a group message
                    comment_link = None
                    if channel_username:
                        # Public channel — use username-based link
                        comment_link = f"https://t.me/{channel_username}/{channel_msg_id}?comment=1"
                        logger.info(f"Built public channel comment link: {comment_link}")
                    else:
                        # Private channel — use ID-based link
                        comment_link = f"https://t.me/c/{channel_id_str}/{channel_msg_id}?comment=1"
                        logger.info(f"Built private channel comment link: {comment_link}")


                    # If group messages are accessible, try to find an exact match for a better experience
                    try:
                        # Find the corresponding message in the linked group using the user client
                        logger.info(f"Attempting to fetch messages from group {linked_group_id} using user client")
                        group_messages = await client.get_messages(linked_group, limit=5)
                        logger.info(f"Successfully retrieved {len(group_messages)} messages from linked group {linked_group_id}")

                        # Try to find a matching message
                        matched_msg = None

                        # 1. First try exact content match
                        original_message = context.original_message_text
                        if original_message:
                            logger.info(f"Trying exact content match; original content length: {len(original_message)}")

                            for msg in group_messages:
                                if hasattr(msg, 'message') and msg.message and msg.message == original_message:
                                    matched_msg = msg
                                    logger.info(f"Found exact match: group message ID {msg.id}")
                                    break

                        # 2. If no exact match, use SequenceMatcher on the first 20 characters
                        if not matched_msg and original_message and len(original_message) > 20:

                            message_start = original_message[:20]
                            logger.info(f"Trying similarity match on first 20 chars: '{message_start}'")

                            for msg in group_messages:
                                if hasattr(msg, 'message') and msg.message and len(msg.message) > 20:
                                    msg_start = msg.message[:20]
                                    similarity = SequenceMatcher(None, message_start, msg_start).ratio()
                                    if similarity > 0.75:
                                        matched_msg = msg
                                        logger.info(f"Found similarity match: group message ID {msg.id}, first-20-char similarity: {similarity}")
                                        break

                        # 3. If still no match, try matching by timestamp
                        if not matched_msg and hasattr(event.message, 'date'):
                            message_time = event.message.date
                            logger.info(f"Trying timestamp match; original message time: {message_time}")

                            # Look for messages within 1 minute of the original
                            time_window = 1  # minutes

                            for msg in group_messages:
                                if hasattr(msg, 'date'):
                                    time_diff = abs((msg.date - message_time).total_seconds())
                                    if time_diff < time_window * 60:
                                        matched_msg = msg
                                        logger.info(f"Found time-based match: group message ID {msg.id}, time difference: {time_diff}s")
                                        break

                        # 4. If still nothing found, use the latest message
                        if not matched_msg:
                            logger.info("No matching message found; falling back to latest message")
                            # Use the latest message as the default
                            if group_messages:
                                matched_msg = group_messages[0]
                                logger.info(f"Using latest message: group message ID {matched_msg.id}")

                        # If a matching message was found, update the link
                        if matched_msg:
                            group_msg_id = matched_msg.id
                            if channel_username:
                                # Public channel — use username-based link
                                comment_link = f"https://t.me/{channel_username}/{channel_msg_id}?comment={group_msg_id}"
                            else:
                                # Private channel — use ID-based link
                                comment_link = f"https://t.me/c/{channel_id_str}/{channel_msg_id}?comment={group_msg_id}"
                            logger.info(f"Updated to precise comment link: {comment_link}")

                    except Exception as e:
                        logger.warning(f"Failed to retrieve group messages (possibly not a group member): {str(e)}")
                        logger.info("Will use the basic comment link")
                        # Keep using the basic comment=1 link

                    # Build a fallback group link
                    group_link = None
                    if hasattr(linked_group, 'username') and linked_group.username:
                        group_link = f"https://t.me/{linked_group.username}"
                        logger.info(f"Generated fallback group link: {group_link}")

                    # Store the comment link in context for subsequent filters
                    context.comment_link = comment_link

                    # For media group messages, skip adding the button here (handled by ReplyFilter)
                    if context.is_media_group:
                        logger.info("Comment button for media group message will be handled by ReplyFilter")
                        return True

                    # Add buttons
                    buttons_added = False

                    # Add the comment section button
                    if comment_link:
                        # Create the comment button
                        comment_button = Button.url("💬 View Comments", comment_link)

                        # Attach the button to the message
                        if not context.buttons:
                            context.buttons = [[comment_button]]
                        else:
                            # If buttons already exist, prepend to the first row
                            context.buttons.insert(0, [comment_button])

                        logger.info(f"Added comment button to message, link: {comment_link}")
                        buttons_added = True


                    if not buttons_added:
                        logger.warning("Failed to add any buttons")
                except Exception as e:
                    logger.error(f"Error retrieving linked group messages: {str(e)}")
                    tb = traceback.format_exc()
                    logger.debug(f"Detailed error: {tb}")

            except Exception as e:
                logger.error(f"Error adding comment button: {str(e)}")
                logger.error(traceback.format_exc())

            return True
        finally:
            # logger.info(f"CommentButtonFilter finished processing message, context: {context.__dict__}")
            pass
