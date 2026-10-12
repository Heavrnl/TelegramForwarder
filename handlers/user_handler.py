from models.models import ForwardMode
import re
import logging
import asyncio
from utils.common import check_keywords, get_sender_info


logger = logging.getLogger(__name__)

async def process_forward_rule(client, event, chat_id, rule):
    """Handle forwarding rule (user mode)"""

    
    if not rule.enable_rule:
        logger.info(f'Rule ID: {rule.id} is disabled, skipping')
        return
    
    message_text = event.message.text or ''
    check_message_text = message_text
    # Log info
    logger.info(f'Processing rule ID: {rule.id}')
    logger.info(f'Message content: {message_text}')
    logger.info(f'Rule mode: {rule.forward_mode.value}')


    if rule.is_filter_user_info:
        sender_info = await get_sender_info(event, rule.id)  # Get sender info
        if sender_info:
            check_message_text = f"{sender_info}:\n{message_text}"
            logger.info(f'Message with sender info: {message_text}')
        else:
            logger.warning(f"Rule ID: {rule.id} - Unable to get sender info")
    
    should_forward = await check_keywords(rule,check_message_text)
    
    logger.info(f'Final decision: {"forward" if should_forward else "skip"}')
    
    if should_forward:
        target_chat = rule.target_chat
        target_chat_id = int(target_chat.telegram_chat_id)
        
        try:
            
            
            if event.message.grouped_id:
                # Wait briefly to ensure all media group messages are received
                await asyncio.sleep(1)
                
                # Collect all messages in the media group
                messages = []
                async for message in client.iter_messages(
                    event.chat_id,
                    limit=20,  # Limit search range
                    min_id=event.message.id - 10,
                    max_id=event.message.id + 10
                ):
                    if message.grouped_id == event.message.grouped_id:
                        messages.append(message.id)
                        logger.info(f'Found media group message: ID={message.id}')
                
                # Sort by ID to ensure correct forwarding order
                messages.sort()
                
                # Forward all messages at once
                await client.forward_messages(
                    target_chat_id,
                    messages,
                    event.chat_id
                )
                logger.info(f'[User] Forwarded {len(messages)} media group message(s) to: {target_chat.name} ({target_chat_id})')
                
            else:
                # Handle single message
                await client.forward_messages(
                    target_chat_id,
                    event.message.id,
                    event.chat_id
                )
                logger.info(f'[User] Message forwarded to: {target_chat.name} ({target_chat_id})')
                
                
        except Exception as e:
            logger.error(f'Error forwarding message: {str(e)}')
            logger.exception(e) 