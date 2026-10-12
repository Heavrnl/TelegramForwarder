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
    AI processing filter — processes message text using an AI provider.
    """

    async def _process(self, context):
        """
        Process message text using AI.

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
                logger.info("AI processing is disabled; returning original message")
                return True

            # Handle media group messages
            if context.is_media_group:
                logger.info(f"is_media_group: {context.is_media_group}")

            # Collect image files to upload
            image_files = []
            has_media_to_process = False

            if rule.enable_ai_upload_image:
                # Check for already-downloaded media files
                if context.media_files:
                    # Files already downloaded; read them into memory
                    for file_path in context.media_files:
                        try:
                            # Verify the file exists
                            if not os.path.exists(file_path):
                                logger.warning(f"File does not exist: {file_path}")
                                continue

                            # Read file content
                            with open(file_path, 'rb') as f:
                                file_content = f.read()

                            # Determine MIME type
                            mime_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"

                            # Store in the in-memory image list
                            image_files.append({
                                "data": base64.b64encode(file_content).decode('utf-8'),
                                "mime_type": mime_type
                            })
                            logger.info(f"Loaded image into memory, type: {mime_type}, size: {len(file_content) // 1024} KB")
                        except Exception as e:
                            logger.error(f"Error reading file into memory: {str(e)}")

                    has_media_to_process = len(image_files) > 0
                    logger.info(f"Loaded {len(image_files)} files into memory")

                # No pre-downloaded files, but there are media group messages — download directly to memory
                elif context.is_media_group and context.media_group_messages:
                    logger.info(f"Detected media group with {len(context.media_group_messages)} messages; downloading directly to memory")
                    # Download images from the media group into memory
                    for msg in context.media_group_messages:
                        if msg.photo or (msg.document and hasattr(msg.document, 'mime_type') and msg.document.mime_type.startswith('image/')):
                            try:
                                # Create an in-memory buffer
                                buffer = io.BytesIO()
                                # Download directly into the buffer
                                await msg.download_media(file=buffer)
                                # Read buffer contents
                                buffer.seek(0)
                                content = buffer.read()

                                # Determine MIME type
                                mime_type = "image/jpeg"  # Default type
                                if msg.photo:
                                    mime_type = "image/jpeg"
                                elif msg.document and hasattr(msg.document, 'mime_type'):
                                    mime_type = msg.document.mime_type

                                # Store in the in-memory image list
                                image_files.append({
                                    "data": base64.b64encode(content).decode('utf-8'),
                                    "mime_type": mime_type
                                })
                                logger.info(f"Downloaded media group image to memory, type: {mime_type}, size: {len(content) // 1024} KB")
                            except Exception as e:
                                logger.error(f"Error downloading media group image to memory: {str(e)}")

                    has_media_to_process = len(image_files) > 0
                    logger.info(f"Downloaded {len(image_files)} images to memory in total")

                # Check whether a single message has media and download it
                elif event.message and event.message.media:
                    logger.info("Detected single message with media; downloading to memory")
                    try:
                        # Create an in-memory buffer
                        buffer = io.BytesIO()
                        # Download directly to memory
                        await event.message.download_media(file=buffer)
                        # Read buffer contents
                        buffer.seek(0)
                        content = buffer.read()

                        # Determine MIME type
                        mime_type = "image/jpeg"  # Default type
                        if hasattr(event.message.media, 'photo'):
                            mime_type = "image/jpeg"
                        elif hasattr(event.message.media, 'document') and hasattr(event.message.media.document, 'mime_type'):
                            mime_type = event.message.media.document.mime_type

                        # Store in the in-memory image list
                        image_files.append({
                            "data": base64.b64encode(content).decode('utf-8'),
                            "mime_type": mime_type
                        })
                        has_media_to_process = True
                        logger.info(f"Downloaded single message media to memory, type: {mime_type}, size: {len(content) // 1024} KB")
                    except Exception as e:
                        logger.error(f"Error downloading single message media to memory: {str(e)}")

            # Process with AI if there is message text or images
            if context.message_text or has_media_to_process:
                try:
                    # Ensure images can be processed even when there is no text
                    text_to_process = context.message_text if context.message_text else "[Photo message]"

                    logger.info(f"Starting AI processing, text length: {len(text_to_process)}, image count: {len(image_files)}")
                    processed_text = await _ai_handle(text_to_process, rule, image_files)
                    context.message_text = processed_text

                    # Re-check keywords after AI processing if required
                    logger.info(f"rule.is_keyword_after_ai:{rule.is_keyword_after_ai}")
                    if rule.is_keyword_after_ai:
                        should_forward = await check_keywords(rule, processed_text, event)

                        if not should_forward:
                            logger.info('AI-processed text failed keyword check; cancelling forward')
                            context.should_forward = False
                            return False
                except Exception as e:
                    logger.error(f'Error processing message with AI: {str(e)}')
                    context.errors.append(f"AI processing error: {str(e)}")
                    # Continue processing even if AI fails
            return True
        finally:
            pass


async def _ai_handle(message: str, rule, image_files=None) -> str:
    """Process a message using AI.

    Args:
        message: Raw message text
        rule: Forward rule object containing AI-related settings
        image_files: List of image file paths to upload, or in-memory image data

    Returns:
        str: Processed message text
    """
    try:
        if not rule.is_ai:
            logger.info("AI processing is disabled; returning original message")
            return message
        # Read from database first; fall back to the default model from .env if ai_model is empty
        if not rule.ai_model:
            rule.ai_model = DEFAULT_AI_MODEL
            logger.info(f"Using default AI model: {rule.ai_model}")
        else:
            logger.info(f"Using AI model from rule config: {rule.ai_model}")

        provider = await get_ai_provider(rule.ai_model)

        if not rule.ai_prompt:
            rule.ai_prompt = DEFAULT_AI_PROMPT
            logger.info("Using default AI prompt")
        else:
            logger.info("Using AI prompt from rule config")

        # Handle special prompt format strings
        prompt = rule.ai_prompt
        if prompt:
            # Handle chat-history prompt placeholders

            # Match context format for source and target chats
            source_context_match = re.search(r'\{source_message_context:(\d+)\}', prompt)
            target_context_match = re.search(r'\{target_message_context:(\d+)\}', prompt)
            # Match time-window format for source and target chats
            source_time_match = re.search(r'\{source_message_time:(\d+)\}', prompt)
            target_time_match = re.search(r'\{target_message_time:(\d+)\}', prompt)

            if any([source_context_match, target_context_match, source_time_match, target_time_match]):

                main = await get_main_module()
                client = main.user_client

                # Get source and target chat IDs
                source_chat_id = int(rule.source_chat.telegram_chat_id)
                target_chat_id = int(rule.target_chat.telegram_chat_id)

                # Fetch messages from the source chat
                if source_context_match:
                    count = int(source_context_match.group(1))
                    chat_history = await _get_chat_messages(client, source_chat_id, count=count)
                    prompt = prompt.replace(source_context_match.group(0), chat_history)

                if source_time_match:
                    minutes = int(source_time_match.group(1))
                    chat_history = await _get_chat_messages(client, source_chat_id, minutes=minutes)
                    prompt = prompt.replace(source_time_match.group(0), chat_history)

                # Fetch messages from the target chat
                if target_context_match:
                    count = int(target_context_match.group(1))
                    chat_history = await _get_chat_messages(client, target_chat_id, count=count)
                    prompt = prompt.replace(target_context_match.group(0), chat_history)

                if target_time_match:
                    minutes = int(target_time_match.group(1))
                    chat_history = await _get_chat_messages(client, target_chat_id, minutes=minutes)
                    prompt = prompt.replace(target_time_match.group(0), chat_history)

            # Replace the message placeholder
            if '{Message}' in prompt:
                prompt = prompt.replace('{Message}', message)

        logger.info(f"Final AI prompt after processing: {prompt}")

        # Handle image uploads — new version supporting in-memory image data
        img_data = []
        if rule.enable_ai_upload_image and image_files and len(image_files) > 0:
            # Check whether the images are already in memory format
            if isinstance(image_files[0], dict) and "data" in image_files[0] and "mime_type" in image_files[0]:
                # Already in memory format; use directly
                img_data = image_files
                logger.info(f"Using in-memory image data; total images: {len(img_data)}")
            else:
                # File path format; read files from disk
                for img_file in image_files:
                    try:
                        logger.info("Preparing to read image from file")
                        with open(img_file, "rb") as f:
                            img_bytes = f.read()
                            encoded_img = base64.b64encode(img_bytes).decode('utf-8')

                            # Determine MIME type
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
                            # Log image size, not content
                            logger.info(f"Image read from file, type: {mime_type}, size: {len(img_bytes) // 1024} KB")
                    except Exception as e:
                        logger.error("Error reading image file")

        logger.info(f"Total images to upload to AI: {len(img_data)}")

        processed_text = await provider.process_message(
            message=message,
            prompt=prompt,
            model=rule.ai_model,
            images=img_data if img_data else None
        )
        logger.info(f"AI processing complete: {processed_text}")
        return processed_text

    except Exception as e:
        logger.error(f"Error processing message with AI: {str(e)}")
        return message


async def _get_chat_messages(client, chat_id, minutes=None, count=None, delay_seconds: float = 0.5) -> str:
    """Fetch chat message history.

    Args:
        client: Telegram client
        chat_id: Chat ID
        minutes: Fetch messages from the last N minutes
        count: Fetch the latest N messages
        delay_seconds: Delay in seconds between message fetches; default 0.5s

    Returns:
        str: Chat history as a formatted string
    """
    try:
        messages = []
        limit = count if count else 500  # Set a reasonable default limit
        processed_count = 0

        if minutes:
            # Calculate the time window
            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=minutes)

            # Fetch messages within the specified time range
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
                    if processed_count % 20 == 0:  # Pause every 20 messages
                        await asyncio.sleep(delay_seconds)
        else:
            # Fetch the specified number of latest messages
            async for message in client.iter_messages(
                chat_id,
                limit=count
            ):
                if message.text:
                    messages.append(message.text)
                    processed_count += 1
                    if processed_count % 20 == 0:  # Pause every 20 messages
                        await asyncio.sleep(delay_seconds)

        return "\n---\n".join(messages) if messages else ""

    except Exception as e:
        logger.error(f"Error fetching chat history: {str(e)}")
        return ""
