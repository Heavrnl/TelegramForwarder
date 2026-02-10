import logging
from filters.base_filter import BaseFilter
from filters.keyword_filter import KeywordFilter
from utils.common import check_keywords
from utils.common import get_main_module
from ai import get_ai_provider
from utils.constants import DEFAULT_AI_MODEL,DEFAULT_SUMMARY_PROMPT,DEFAULT_AI_PROMPT
from datetime import datetime, timedelta
import asyncio
import re
import base64
import os
import io
import mimetypes

logger = logging.getLogger(__name__)

class AIFilter(BaseFilter):
    """
    AI processing filter, uses AI to process message text
    """

    async def _process(self, context):
        """
        Use AI to process message text

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        message_text = context.message_text
        original_message_text = context.original_message_text
        event = context.event

        try:
            if not rule.is_ai:
                logger.info("AI processing not enabled, returning original message")
                return True

            # Process media group messages
            if context.is_media_group:
                logger.info(f"is_media_group: {context.is_media_group}")

            # Get image files that need to be uploaded
            image_files = []
            has_media_to_process = False

            if rule.enable_ai_upload_image:
                # Check if there are already downloaded media files
                if context.media_files:
                    # Files already downloaded, need to read into memory
                    for file_path in context.media_files:
                        try:
                            # Check if file exists
                            if not os.path.exists(file_path):
                                logger.warning(f"File does not exist: {file_path}")
                                continue

                            # Read file content
                            with open(file_path, 'rb') as f:
                                file_content = f.read()

                            # Get MIME type
                            mime_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"

                            # Save to in-memory image list
                            image_files.append({
                                "data": base64.b64encode(file_content).decode('utf-8'),
                                "mime_type": mime_type
                            })
                            logger.info(f"Loaded image into memory, type: {mime_type}, size: {len(file_content) // 1024} KB")
                        except Exception as e:
                            logger.error(f"Error reading file into memory: {str(e)}")

                    has_media_to_process = len(image_files) > 0
                    logger.info(f"Loaded {len(image_files)} files into memory")

                # If no downloaded files but there are media group messages, download directly to memory
                elif context.is_media_group and context.media_group_messages:
                    logger.info(f"Detected media group messages: {len(context.media_group_messages)} messages, downloading directly to memory")
                    # Download images from the media group to memory
                    for msg in context.media_group_messages:
                        if msg.photo or (msg.document and hasattr(msg.document, 'mime_type') and msg.document.mime_type.startswith('image/')):
                            try:
                                # Create memory buffer
                                buffer = io.BytesIO()
                                # Download directly to memory buffer
                                await msg.download_media(file=buffer)
                                # Get image content
                                buffer.seek(0)
                                content = buffer.read()

                                # Get MIME type
                                mime_type = "image/jpeg"  # Default type
                                if msg.photo:
                                    mime_type = "image/jpeg"
                                elif msg.document and hasattr(msg.document, 'mime_type'):
                                    mime_type = msg.document.mime_type

                                # Save to in-memory image list
                                image_files.append({
                                    "data": base64.b64encode(content).decode('utf-8'),
                                    "mime_type": mime_type
                                })
                                logger.info(f"Downloaded media group image to memory, type: {mime_type}, size: {len(content) // 1024} KB")
                            except Exception as e:
                                logger.error(f"Error downloading media group image to memory: {str(e)}")

                    has_media_to_process = len(image_files) > 0
                    logger.info(f"Downloaded {len(image_files)} images to memory in total")

                # Check if single message has media and download to memory
                elif event.message and event.message.media:
                    logger.info("Detected single message has media, downloading to memory")
                    try:
                        # Create memory buffer
                        buffer = io.BytesIO()
                        # Download directly to memory
                        await event.message.download_media(file=buffer)
                        # Get image content
                        buffer.seek(0)
                        content = buffer.read()

                        # Get MIME type
                        mime_type = "image/jpeg"  # Default type
                        if hasattr(event.message.media, 'photo'):
                            mime_type = "image/jpeg"
                        elif hasattr(event.message.media, 'document') and hasattr(event.message.media.document, 'mime_type'):
                            mime_type = event.message.media.document.mime_type

                        # Save to in-memory image list
                        image_files.append({
                            "data": base64.b64encode(content).decode('utf-8'),
                            "mime_type": mime_type
                        })
                        has_media_to_process = True
                        logger.info(f"Downloaded single message media to memory, type: {mime_type}, size: {len(content) // 1024} KB")
                    except Exception as e:
                        logger.error(f"Error downloading single message media to memory: {str(e)}")

            # If there is message text or images, use AI to process
            if context.message_text or has_media_to_process:
                try:
                    # Ensure images can be processed even without text
                    text_to_process = context.message_text if context.message_text else "[Image message]"

                    logger.info(f"Starting AI processing, text length: {len(text_to_process)}, image count: {len(image_files)}")
                    processed_text = await _ai_handle(text_to_process, rule, image_files)
                    context.message_text = processed_text


                    # If keyword check after AI processing is needed
                    logger.info(f"rule.is_keyword_after_ai:{rule.is_keyword_after_ai}")
                    if rule.is_keyword_after_ai:
                        should_forward = await check_keywords(rule, processed_text, event)

                        if not should_forward:
                            logger.info('Text after AI processing did not pass keyword check, canceling forwarding')
                            context.should_forward = False
                            return False
                except Exception as e:
                    logger.error(f'Error during AI message processing: {str(e)}')
                    context.errors.append(f"AI processing error: {str(e)}")
                    # Even if AI processing fails, continue processing
            return True
        finally:
            pass


async def _ai_handle(message: str, rule, image_files=None) -> str:
    """Use AI to process message

    Args:
        message: Original message text
        rule: Forwarding rule object, contains AI-related settings
        image_files: List of image file paths to upload or in-memory image data

    Returns:
        str: Processed message text
    """
    try:
        if not rule.is_ai:
            logger.info("AI processing not enabled, returning original message")
            return message
        # First read the database, if ai model is empty, use the default model from .env
        if not rule.ai_model:
            rule.ai_model = DEFAULT_AI_MODEL
            logger.info(f"Using default AI model: {rule.ai_model}")
        else:
            logger.info(f"Using rule-configured AI model: {rule.ai_model}")

        provider = await get_ai_provider(rule.ai_model)

        if not rule.ai_prompt:
            rule.ai_prompt = DEFAULT_AI_PROMPT
            logger.info("Using default AI prompt")
        else:
            logger.info("Using rule-configured AI prompt")

        # Process special prompt format
        prompt = rule.ai_prompt
        if prompt:
            # Process chat history prompt

            # Match source chat and target chat context format
            source_context_match = re.search(r'\{source_message_context:(\d+)\}', prompt)
            target_context_match = re.search(r'\{target_message_context:(\d+)\}', prompt)
            # Match source chat and target chat time format
            source_time_match = re.search(r'\{source_message_time:(\d+)\}', prompt)
            target_time_match = re.search(r'\{target_message_time:(\d+)\}', prompt)

            if any([source_context_match, target_context_match, source_time_match, target_time_match]):

                main = await get_main_module()
                client = main.user_client

                # Get source chat and target chat IDs
                source_chat_id = int(rule.source_chat.telegram_chat_id)
                target_chat_id = int(rule.target_chat.telegram_chat_id)

                # Process message retrieval for source chat
                if source_context_match:
                    count = int(source_context_match.group(1))
                    chat_history = await _get_chat_messages(client, source_chat_id, count=count)
                    prompt = prompt.replace(source_context_match.group(0), chat_history)

                if source_time_match:
                    minutes = int(source_time_match.group(1))
                    chat_history = await _get_chat_messages(client, source_chat_id, minutes=minutes)
                    prompt = prompt.replace(source_time_match.group(0), chat_history)

                # Process message retrieval for target chat
                if target_context_match:
                    count = int(target_context_match.group(1))
                    chat_history = await _get_chat_messages(client, target_chat_id, count=count)
                    prompt = prompt.replace(target_context_match.group(0), chat_history)

                if target_time_match:
                    minutes = int(target_time_match.group(1))
                    chat_history = await _get_chat_messages(client, target_chat_id, minutes=minutes)
                    prompt = prompt.replace(target_time_match.group(0), chat_history)

            # Replace message placeholder
            if '{Message}' in prompt:
                prompt = prompt.replace('{Message}', message)

        logger.info(f"Processed AI prompt: {prompt}")

        # Process image upload - new version, supports in-memory image data
        img_data = []
        if rule.enable_ai_upload_image and image_files and len(image_files) > 0:
            # Check if images are already in memory format
            if isinstance(image_files[0], dict) and "data" in image_files[0] and "mime_type" in image_files[0]:
                # Already in memory format, use directly
                img_data = image_files
                logger.info(f"Using in-memory image data, total {len(img_data)} images")
            else:
                # File path format, need to read files
                for img_file in image_files:
                    try:
                        logger.info("Preparing to read image from file")
                        with open(img_file, "rb") as f:
                            img_bytes = f.read()
                            encoded_img = base64.b64encode(img_bytes).decode('utf-8')

                            # Get MIME type
                            mime_type = "image/jpeg"  # Default type
                            if str(img_file).lower().endswith(".png"):
                                mime_type = "image/png"
                            elif str(img_file).lower().endswith(".gif"):
                                mime_type = "image/gif"
                            elif str(img_file).lower().endswith(".webp"):
                                mime_type = "image/webp"

                            img_data.append({
                                "data": encoded_img,
                                "mime_type": mime_type
                            })
                            # Log image size instead of content
                            logger.info(f"Read image, type: {mime_type}, size: {len(img_bytes) // 1024} KB")
                    except Exception as e:
                        logger.error("Error reading image file")

        logger.info(f"Total {len(img_data)} images will be uploaded to AI")

        processed_text = await provider.process_message(
            message=message,
            prompt=prompt,
            model=rule.ai_model,
            images=img_data if img_data else None
        )
        logger.info(f"AI processing completed: {processed_text}")
        return processed_text

    except Exception as e:
        logger.error(f"Error during AI message processing: {str(e)}")
        return message


async def _get_chat_messages(client, chat_id, minutes=None, count=None, delay_seconds: float = 0.5) -> str:
    """Get chat history

    Args:
        client: Telegram client
        chat_id: Chat ID
        minutes: Get messages from the last N minutes
        count: Get the latest N messages
        delay_seconds: Delay in seconds between fetching each message, default 0.5 seconds

    Returns:
        str: Chat history text
    """
    try:
        messages = []
        limit = count if count else 500  # Set a reasonable default value
        processed_count = 0

        if minutes:
            # Calculate time range

            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=minutes)

            # Get messages within the specified time range
            async for message in client.iter_messages(
                chat_id,
                limit=limit,
                offset_date=end_time,
                reverse=True
            ):
                if message.date < start_time:
                    break
                if message.text:
                    messages.append(message.text)
                    processed_count += 1
                    if processed_count % 20 == 0:  # Rest after processing every 20 messages
                        await asyncio.sleep(delay_seconds)
        else:
            # Get the specified number of latest messages
            async for message in client.iter_messages(
                chat_id,
                limit=count
            ):
                if message.text:
                    messages.append(message.text)
                    processed_count += 1
                    if processed_count % 20 == 0:  # Rest after processing every 20 messages
                        await asyncio.sleep(delay_seconds)

        return "\n---\n".join(messages) if messages else ""

    except Exception as e:
        logger.error(f"Error getting chat history: {str(e)}")
        return ""
