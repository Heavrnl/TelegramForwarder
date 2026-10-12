import logging
import os
import pytz
import re
from datetime import datetime
from filters.base_filter import BaseFilter

logger = logging.getLogger(__name__)

class InfoFilter(BaseFilter):
    """
    Info filter — appends original link and sender info
    """
    
    async def _process(self, context):
        """
        Add original link and sender info
        
        Args:
            context: message context
            
        Returns:
            bool: whether to continue processing
        """
        rule = context.rule
        event = context.event

        # logger.info(f"InfoFilter before processing, context: {context.__dict__}")
        try:

            # Add original link
            if rule.is_original_link:
                # Get basic info for original link
                original_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"
                
                # Check for custom link template
                if hasattr(rule, 'original_link_template') and rule.original_link_template:
                    try:
                        # Use custom link template
                        link_info = rule.original_link_template
                        link_info = link_info.replace("{original_link}", original_link)
                        
                        context.original_link = f"\n\n{link_info}"
                    except Exception as le:
                        logger.error(f'Error using custom link template: {str(le)}, using default format')
                        context.original_link = f"\n\nOriginal message: {original_link}"
                else:
                    # Use default format
                    context.original_link = f"\n\nOriginal message: {original_link}"
                
                logger.info(f'Added original link: {context.original_link}')
            
            # Add sender info
            if rule.is_original_sender:
                try:
                    logger.info("Fetching sender info")
                    sender_name = "Unknown Sender"  # Default value
                    sender_id = "Unknown"

                    if hasattr(event.message, 'sender_chat') and event.message.sender_chat:
                        # User sending as a channel
                        sender = event.message.sender_chat
                        sender_name = sender.title if hasattr(sender, 'title') else "Unknown Channel"
                        sender_id = sender.id
                        logger.info(f"Using channel info: {sender_name} (ID: {sender_id})")

                    elif event.sender:
                        # User sending as an individual
                        sender = event.sender
                        sender_name = (
                            sender.title if hasattr(sender, 'title')
                            else f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                        )
                        sender_id = sender.id
                        logger.info(f"Using sender info: {sender_name} (ID: {sender_id})")

                    elif hasattr(event.message, 'peer_id') and event.message.peer_id:
                        # Try to get info from peer_id
                        peer = event.message.peer_id
                        if hasattr(peer, 'channel_id'):
                            sender_id = peer.channel_id
                            try:
                                # Try to get channel info
                                channel = await event.client.get_entity(peer)
                                sender_name = channel.title if hasattr(channel, 'title') else "Unknown Channel"
                            except Exception as ce:
                                logger.error(f'Failed to get channel info: {str(ce)}')
                                sender_name = "Unknown Channel"
                        logger.info(f"Using peer_id info: {sender_name} (ID: {sender_id})")
                    
                    # Check for user-defined template
                    if hasattr(rule, 'userinfo_template') and rule.userinfo_template:
                        # Replace template variables
                        user_info = rule.userinfo_template
                        user_info = user_info.replace("{name}", sender_name)
                        user_info = user_info.replace("{id}", str(sender_id))
                        
                        context.sender_info = f"{user_info}\n\n"
                    else:
                        # Use default format
                        context.sender_info = f"{sender_name}\n\n"
                    
                    logger.info(f'Added sender info: {context.sender_info}')
                except Exception as e:
                    logger.error(f'Error getting sender info: {str(e)}')
            
            # Add time info
            if rule.is_original_time:
                try:
                    # Create timezone object
                    timezone = pytz.timezone(os.getenv('DEFAULT_TIMEZONE', 'Asia/Shanghai'))
                    local_time = event.message.date.astimezone(timezone)
                    
                    # Default formatted time
                    formatted_time = local_time.strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Check for time template
                    if hasattr(rule, 'time_template') and rule.time_template:
                        try:
                            # Use custom time template
                            time_info = rule.time_template.replace("{time}", formatted_time)
                            context.time_info = f"\n\n{time_info}"
                        except Exception as te:
                            logger.error(f'Error using custom time template: {str(te)}, using default format')
                            context.time_info = f"\n\n{formatted_time}"
                    else:
                        # Use default format
                        context.time_info = f"\n\n{formatted_time}"
                    
                    logger.info(f'Added time info: {context.time_info}')
                except Exception as e:
                    logger.error(f'Error processing time info: {str(e)}')
            
            return True 
        finally:
            # logger.info(f"InfoFilter after processing, context: {context.__dict__}")
            pass