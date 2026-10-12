import os
import logging
import asyncio
import aiohttp
import mimetypes
import json
from pathlib import Path
from datetime import datetime
import shutil
from filters.base_filter import BaseFilter
import uuid
from utils.constants import TEMP_DIR, RSS_MEDIA_DIR, get_rule_media_dir,RSS_HOST,RSS_PORT,RSS_ENABLED
from models.models import get_session
from utils.common import get_db_ops

logger = logging.getLogger(__name__)

class RSSFilter(BaseFilter):
    """
    RSS filter — adds qualifying messages to the RSS feed
    """
    
    def __init__(self):
        super().__init__()
        self.rss_host = RSS_HOST
        self.rss_port = RSS_PORT
        self.rss_base_url = f"http://{self.rss_host}:{self.rss_port}"
        
        # Use unified path constants
        self.rss_media_path = RSS_MEDIA_DIR
        self.temp_dir = TEMP_DIR
        
        logger.info(f"RSS media root directory: {self.rss_media_path}")
        logger.info(f"Temp file directory: {self.temp_dir}")
        
        # Ensure RSS media root directory exists
        Path(self.rss_media_path).mkdir(parents=True, exist_ok=True)
    
    def _get_rule_media_path(self, rule_id):
        """Get the rule-specific media directory"""
        return get_rule_media_dir(rule_id)
    
    async def _process(self, context):
        """Process RSS filter logic"""
        
        if not RSS_ENABLED:
            logger.info("RSS not enabled, skipping RSS processing")
            return True
        
        if not context.should_forward:
            return False
        
        db_ops = await get_db_ops()
        session = get_session()
        rss_config = await db_ops.get_rss_config(session, context.rule.id)
        logger.info(f"Rule ID: {context.rule.id}")
        logger.info(f"RSS config: {rss_config}")

        # Check if RSS config exists
        if rss_config is None:
            logger.error(f"No RSS config found for rule ID {context.rule.id}, skipping RSS processing")
            session.close()
            return True
        
        # Check if RSS is enabled
        if not rss_config.enable_rss:
            logger.info(f"RSS not enabled for rule ID {context.rule.id}, skipping RSS processing")
            session.close()
            return True

        # Ensure media is downloaded before processing RSS
        # Media group messages need special handling
        if context.is_media_group:
            rule = context.rule
            await self._process_media_group(context, rule)
        else:
            # Get message and rule
            message = context.event.message
            client = context.client
            rule = context.rule
            
            try:
                # Prepare entry data
                entry_data = await self._prepare_entry_data(client, message, rule, context)
                
                # If data prep fails, log error and try to create minimal data
                if entry_data is None:
                    logger.warning("Failed to generate RSS entry data, attempting minimal data")
                    # Extract bare minimum info from the message
                    message_text = getattr(message, 'text', '') or getattr(message, 'caption', '') or 'File message'
                    entry_data = {
                        "id": str(message.id),
                        "title": message_text[:20] + ('...' if len(message_text) > 20 else ''),
                        "content": message_text,
                        "published": datetime.now().isoformat(),
                        "author": "",
                        "link": "",
                        "media": []
                    }
                    
                    # If message has media, try to process it
                    if hasattr(message, 'media') and message.media:
                        media_info = await self._process_media(client, message, context)
                        if media_info:
                            if isinstance(media_info, list):
                                entry_data["media"].extend(media_info)
                            else:
                                entry_data["media"].append(media_info)
                
                # Send to RSS service
                if entry_data:
                    success = await self._send_to_rss_service(rule.id, entry_data)
                    if success:
                        logger.info(f"Message added to RSS feed for rule {rule.id}")
                    else:
                        logger.error(f"Failed to add message to RSS feed for rule {rule.id}")
                else:
                    logger.error("Failed to generate valid RSS entry data")
            
            except Exception as e:
                logger.error(f"Error during RSS processing: {str(e)}")
        
        if rule.only_rss:
            logger.info('RSS-only mode, RSS filter complete, ending filter chain')
            return False
        
        return True
    
    async def _prepare_entry_data(self, client, message, rule, context=None):
        """Prepare RSS entry data"""
        try:
            # Get title (using custom method)
            title = self._get_message_title(message)
            
            # Safely get message content
            content = ""
            if hasattr(message, 'text') and message.text:
                content = message.text
            elif hasattr(message, 'caption') and message.caption:
                content = message.caption
            
            # Get sender name
            author = await self._get_sender_name(client, message)
            
            # Get message link (if available)
            link = self._get_message_link(message)
            
            # Get media (if available)
            media_list = []
            
            # Handle media group messages
            if context and hasattr(context, "is_media_group") and context.is_media_group:
                logger.debug("Processing media group message")
                # Media group already processed elsewhere, skip here
                # Log only
                logger.debug("Media group handled elsewhere")
            else:
                # Process media for single message
                media_info = await self._process_media(client, message, context)
                if media_info:
                    if isinstance(media_info, list):
                        media_list.extend(media_info)
                    else:
                        media_list.append(media_info)
                elif media_list:
                    logger.debug(f"_process_media returned multiple media: {len(media_list)}")
                
                # Check if media is in skipped_media list
                if context and hasattr(context, 'skipped_media') and context.skipped_media:
                    for skipped_msg, size, name in context.skipped_media:
                        if skipped_msg.id == message.id:
                            logger.info(f"Media file {name or ''} (size: {size}MB) is in skipped_media list, marking entry data")
                            # Add note to content indicating media was skipped due to size limit
                            note = f"\n\n[Note: media file {name or ''} exceeds size limit ({size}MB), not included]"
                            if hasattr(message, 'text') and message.text:
                                content = message.text + note
                            elif hasattr(message, 'caption') and message.caption:
                                content = message.caption + note
                            else:
                                content = note.strip()
                
                # Log media info
                if media_list:
                    for i, media in enumerate(media_list):
                        logger.debug(f"Media {i+1}: {media.get('filename', 'unknown')}, type: {media.get('type', 'unknown')}, original name: {media.get('original_name', 'unknown')}")
            
            # Build entry data
            entry_data = {
                "id": str(message.id),
                "title": title,
                "content": content,
                "published": message.date.isoformat(),
                "author": author,
                "link": link,
                "media": media_list,
                "original_link": context.original_link,
                "sender_info": context.sender_info,
            }
            
            return entry_data
            
        except Exception as e:
            logger.error(f"Error preparing RSS entry data: {str(e)}")
            return None
    
    def _get_message_title(self, message):
        """Get message title"""
        # Use the first 20 characters of the message as title
        text = ""
        if hasattr(message, 'text') and message.text:
            text = message.text
        elif hasattr(message, 'caption') and message.caption:
            text = message.caption
            
        title = text.split('\n')[0][:20].strip() + "..." if text and len(text.split('\n')[0]) >= 20 else text.split('\n')[0].strip() if text else ""
        
        # If title is empty, use default
        if not title:
            # Detect media type
            has_photo = hasattr(message, 'photo') and message.photo
            has_video = hasattr(message, 'video') and message.video
            has_document = hasattr(message, 'document') and message.document
            has_audio = hasattr(message, 'audio') and message.audio
            has_voice = hasattr(message, 'voice') and message.voice
            
            if has_photo:
                title = "Photo"
            elif has_video:
                title = "Video"
            elif has_document:
                doc_name = ""
                if hasattr(message.document, 'file_name') and message.document.file_name:
                    doc_name = message.document.file_name
                title = f"File: {doc_name}" if doc_name else "File"
            elif has_audio:
                audio_name = ""
                if hasattr(message.audio, 'file_name') and message.audio.file_name:
                    audio_name = message.audio.file_name
                title = f"Audio: {audio_name}" if audio_name else "Audio"
            elif has_voice:
                title = "Voice"
            else:
                title = "New Message"
        
        return title
    
    async def _get_sender_name(self, client, message):
        """Get sender name"""
        try:
            # Check if this is a channel message
            if hasattr(message, 'sender_chat') and message.sender_chat:
                return message.sender_chat.title
            # Check if sender info is available
            elif hasattr(message, 'from_user') and message.from_user:
                return message.from_user.first_name + (f" {message.from_user.last_name}" if message.from_user.last_name else "")
            # Try to get name from chat
            elif hasattr(message, 'chat') and message.chat:
                if hasattr(message.chat, 'title') and message.chat.title:
                    return message.chat.title
                elif hasattr(message.chat, 'first_name'):
                    return message.chat.first_name + (f" {message.chat.last_name}" if hasattr(message.chat, 'last_name') and message.chat.last_name else "")
            return "Unknown User"
        except Exception as e:
            logger.error(f"Error getting sender name: {str(e)}")
            return "Unknown User"
    
    def _get_message_link(self, message):
        """Get message link"""
        try:
            if hasattr(message, 'chat') and message.chat:
                chat_id = getattr(message.chat, 'id', None)
                username = getattr(message.chat, 'username', None)
                message_id = getattr(message, 'id', None)
                
                if message_id is None:
                    return ""
                    
                if username:
                    return f"https://t.me/{username}/{message_id}"
                elif chat_id:
                    # Build link using chat_id
                    chat_id_str = str(chat_id)
                    # Strip leading minus sign if present
                    if chat_id_str.startswith('-100'):
                        chat_id_str = chat_id_str[4:]  # Strip '-100' prefix
                    elif chat_id_str.startswith('-'):
                        chat_id_str = chat_id_str[1:]  # Strip '-' prefix
                    return f"https://t.me/c/{chat_id_str}/{message_id}"
            return ""
        except Exception as e:
            logger.error(f"Error getting message link: {str(e)}")
            return ""
    
    async def _process_media(self, client, message, context=None, rule_id=None):
        """Process media content"""
        media_list = []
        
        try:
            # Check if message is in skipped_media list
            if context and hasattr(context, 'skipped_media') and context.skipped_media:
                for skipped_msg, size, name in context.skipped_media:
                    if skipped_msg.id == message.id:
                        logger.info(f"Media file {name or ''} (size: {size}MB) in skipped_media list, skipping download")
                        return media_list

            # Handle document
            if hasattr(message, 'document') and message.document:
                # Get original filename
                original_name = None
                for attr in message.document.attributes:
                    if hasattr(attr, 'file_name'):
                        original_name = attr.file_name
                        break
                
                # Generate filename
                message_id = getattr(message, 'id', 'unknown')
                file_name = original_name if original_name else f"document_{message_id}"
                file_name = self._sanitize_filename(file_name)
                
                # Get rule ID, prefer passed rule_id
                current_rule_id = rule_id
                if current_rule_id is None and context and hasattr(context, 'rule') and hasattr(context.rule, 'id'):
                    current_rule_id = context.rule.id
                
                # Use rule-specific media directory
                rule_media_path = self._get_rule_media_path(current_rule_id) if current_rule_id else self.rss_media_path
                
                # Download file
                local_path = os.path.join(rule_media_path, file_name)
                try:
                    if not os.path.exists(local_path):
                        await message.download_media(local_path)
                        logger.info(f"Downloaded media to: {local_path}")
                    
                    # Get file size and MIME type
                    file_size = os.path.getsize(local_path)
                    mime_type = message.document.mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
                    
                    # Add to media list with rule-specific URL
                    media_info = {
                        "url": f"/media/{current_rule_id}/{file_name}" if current_rule_id else f"/media/{file_name}",
                        "type": mime_type,
                        "size": file_size,
                        "filename": file_name,
                        "original_name": original_name or file_name
                    }
                    media_list.append(media_info)
                    logger.info(f"Added document to RSS: {file_name}, original name: {original_name or 'unknown'}")
                except Exception as e:
                    logger.error(f"Error processing document: {str(e)}")
            
            # Handle photo
            elif hasattr(message, 'photo') and message.photo:
                message_id = getattr(message, 'id', 'unknown')
                
                # Get rule ID, prefer passed rule_id
                current_rule_id = rule_id
                if current_rule_id is None and context and hasattr(context, 'rule') and hasattr(context.rule, 'id'):
                    current_rule_id = context.rule.id
                
                # Use rule-specific media directory
                rule_media_path = self._get_rule_media_path(current_rule_id) if current_rule_id else self.rss_media_path
                local_path = os.path.join(rule_media_path, f"photo_{message_id}.jpg")
                
                try:
                    if not os.path.exists(local_path):
                        await message.download_media(local_path)
                        logger.info(f"Downloaded photo to: {local_path}")
                    
                    # Get file size
                    file_size = os.path.getsize(local_path)
                    
                    # Add to media list with rule-specific URL
                    media_info = {
                        "url": f"/media/{current_rule_id}/{f'photo_{message_id}.jpg'}" if current_rule_id else f"/media/{f'photo_{message_id}.jpg'}",
                        "type": "image/jpeg",
                        "size": file_size,
                        "filename": f"photo_{message_id}.jpg",
                        "original_name": "photo.jpg"  # Photos have no original filename
                    }
                    media_list.append(media_info)
                    logger.info(f"Added photo to RSS: photo_{message_id}.jpg")
                except Exception as e:
                    logger.error(f"Error processing photo: {str(e)}")
            
            # Handle video
            elif hasattr(message, 'video') and message.video:
                message_id = getattr(message, 'id', 'unknown')
                
                # Get original filename
                original_name = None
                for attr in message.video.attributes:
                    if hasattr(attr, 'file_name'):
                        original_name = attr.file_name
                        break
                
                file_name = original_name if original_name else f"video_{message_id}.mp4"
                file_name = self._sanitize_filename(file_name)
                
                # Get rule ID, prefer passed rule_id
                current_rule_id = rule_id
                if current_rule_id is None and context and hasattr(context, 'rule') and hasattr(context.rule, 'id'):
                    current_rule_id = context.rule.id
                
                # Use rule-specific media directory
                rule_media_path = self._get_rule_media_path(current_rule_id) if current_rule_id else self.rss_media_path
                local_path = os.path.join(rule_media_path, file_name)
                
                try:
                    if not os.path.exists(local_path):
                        await message.download_media(local_path)
                        logger.info(f"Downloaded video to: {local_path}")
                    
                    # Get file size and MIME type
                    file_size = os.path.getsize(local_path)
                    mime_type = message.video.mime_type or "video/mp4"
                    
                    # Add to media list with rule-specific URL
                    media_info = {
                        "url": f"/media/{current_rule_id}/{file_name}" if current_rule_id else f"/media/{file_name}",
                        "type": mime_type,
                        "size": file_size,
                        "filename": file_name,
                        "original_name": original_name or file_name
                    }
                    media_list.append(media_info)
                    logger.info(f"Added video to RSS: {file_name}")
                except Exception as e:
                    logger.error(f"Error processing video: {str(e)}")
            
            # Handle audio
            elif hasattr(message, 'audio') and message.audio:
                message_id = getattr(message, 'id', 'unknown')
                
                # Get original filename
                original_name = None
                for attr in message.audio.attributes:
                    if hasattr(attr, 'file_name'):
                        original_name = attr.file_name
                        break
                
                file_name = original_name if original_name else f"audio_{message_id}.mp3"
                file_name = self._sanitize_filename(file_name)
                
                # Get rule ID, prefer passed rule_id
                current_rule_id = rule_id
                if current_rule_id is None and context and hasattr(context, 'rule') and hasattr(context.rule, 'id'):
                    current_rule_id = context.rule.id
                
                # Use rule-specific media directory
                rule_media_path = self._get_rule_media_path(current_rule_id) if current_rule_id else self.rss_media_path
                local_path = os.path.join(rule_media_path, file_name)
                
                try:
                    if not os.path.exists(local_path):
                        await message.download_media(local_path)
                        logger.info(f"Downloaded audio to: {local_path}")
                    
                    # Get file size and MIME type
                    file_size = os.path.getsize(local_path)
                    mime_type = message.audio.mime_type or "audio/mpeg"
                    
                    # Add to media list with rule-specific URL
                    media_info = {
                        "url": f"/media/{current_rule_id}/{file_name}" if current_rule_id else f"/media/{file_name}",
                        "type": mime_type,
                        "size": file_size,
                        "filename": file_name,
                        "original_name": original_name or file_name
                    }
                    media_list.append(media_info)
                    logger.info(f"Added audio to RSS: {file_name}")
                except Exception as e:
                    logger.error(f"Error processing audio: {str(e)}")
            
            # Handle voice message
            elif hasattr(message, 'voice') and message.voice:
                message_id = getattr(message, 'id', 'unknown')
                file_name = f"voice_{message_id}.ogg"
                
                # Get rule ID, prefer passed rule_id
                current_rule_id = rule_id
                if current_rule_id is None and context and hasattr(context, 'rule') and hasattr(context.rule, 'id'):
                    current_rule_id = context.rule.id
                
                # Use rule-specific media directory
                rule_media_path = self._get_rule_media_path(current_rule_id) if current_rule_id else self.rss_media_path
                local_path = os.path.join(rule_media_path, file_name)
                
                try:
                    if not os.path.exists(local_path):
                        await message.download_media(local_path)
                        logger.info(f"Downloaded voice to: {local_path}")
                    
                    # Get file size
                    file_size = os.path.getsize(local_path)
                    
                    # Add to media list with rule-specific URL
                    media_info = {
                        "url": f"/media/{current_rule_id}/{file_name}" if current_rule_id else f"/media/{file_name}",
                        "type": "audio/ogg",
                        "size": file_size,
                        "filename": file_name,
                        "original_name": "voice.ogg"  # Voice messages have no original filename
                    }
                    media_list.append(media_info)
                    logger.info(f"Added voice to RSS: {file_name}")
                except Exception as e:
                    logger.error(f"Error processing voice: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error processing media content: {str(e)}")
        
        return media_list
    
    def _sanitize_filename(self, filename):
        """Sanitize filename, removing illegal characters"""
        # Replace characters invalid in Windows and Unix filenames
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename
    
    async def _send_to_rss_service(self, rule_id, entry_data):
        """Send data to RSS service"""
        try:
            url = f"{self.rss_base_url}/api/entries/{rule_id}/add"
            
            # Log data to send (non-binary only)
            debug_data = entry_data.copy()
            if "media" in debug_data:
                media_files = []
                for media in debug_data["media"]:
                    if isinstance(media, dict):
                        original_name = media.get("original_name", "unknown")
                        filename = media.get("filename", "unknown")
                        media_files.append(f"{original_name}({filename})")
                    else:
                        media_files.append(str(media))
                debug_data["media"] = f"{len(debug_data['media'])} media file(s): {', '.join(media_files)}"
            logger.info(f"Sending to RSS service: {url}, data: {debug_data}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=entry_data) as response:
                    response_text = await response.text()
                    if response.status != 200:
                        logger.error(f"Failed to send to RSS service: {response.status} - {response_text}")
                        return False
                    
                    logger.info(f"Successfully sent to RSS service, rule ID: {rule_id}, response: {response_text}")
                    return True
                    
        except Exception as e:
            logger.error(f"Error sending to RSS service: {str(e)}")
            return False
    
    async def _process_media_group(self, context, rule):
        """Handle media group messages"""
        try:
            # Get rule ID
            rule_id = rule.id
            
            # Get rule-specific media directory
            rule_media_path = self._get_rule_media_path(rule_id)
            
            # Get locally downloaded media files
            local_media_files = []
            if hasattr(context, 'media_files') and context.media_files:
                local_media_files = context.media_files
            
            # Log number of downloaded media files
            logger.info(f"Processing media group, downloaded files: {len(local_media_files)}")
            
            # Prepare media list
            media_list = []
            
            # Use already-downloaded media files if available
            if local_media_files:
                # Use downloaded media files
                for local_file in local_media_files:
                    try:
                        # Guess media type from filename
                        media_type = mimetypes.guess_type(local_file)[0] or "application/octet-stream"
                        filename = os.path.basename(local_file)
                        
                        # Copy file to rule-specific RSS media directory
                        target_path = os.path.join(rule_media_path, filename)
                        if not os.path.exists(target_path):
                            shutil.copy2(local_file, target_path)
                            logger.info(f"Copied media file to: {target_path}")
                        
                        # Get file size
                        file_size = os.path.getsize(target_path)
                        
                        # Try to get original filename from source message
                        original_name = None
                        for msg in context.media_group_messages:
                            if hasattr(msg, 'document') and msg.document:
                                original_name = getattr(msg.document, 'file_name', None)
                                if original_name:
                                    break
                        
                        # Add to media list with rule-specific URL
                        media_info = {
                            "url": f"/media/{rule_id}/{filename}",
                            "type": media_type,
                            "size": file_size,
                            "filename": filename,
                            "original_name": original_name or filename
                        }
                        media_list.append(media_info)
                        logger.info(f"Added media group file to RSS: {filename}, original name: {original_name or 'unknown'}")
                    except Exception as e:
                        logger.error(f"Error processing media group file: {str(e)}")
            else:
                # No downloaded media files, try downloading directly from media group messages
                if hasattr(context, 'media_group_messages') and context.media_group_messages:
                    logger.warning("Media group has no downloaded files, attempting from media_group_messages")
                    
                    # Process media group messages directly
                    for msg in context.media_group_messages:
                        try:
                            # Check if message is in skipped_media list
                            if hasattr(context, 'skipped_media') and context.skipped_media:
                                skip_msg = False
                                for skipped_msg, size, name in context.skipped_media:
                                    if skipped_msg.id == msg.id:
                                        logger.info(f"Media group file {name or ''} (size: {size}MB) in skipped_media list, skipping download")
                                        skip_msg = True
                                        break
                                if skip_msg:
                                    continue

                            # Handle photo
                            if hasattr(msg, 'photo') and msg.photo:
                                message_id = getattr(msg, 'id', 'unknown')
                                file_name = f"photo_{message_id}.jpg"
                                
                                try:
                                    # Use rule-specific media directory
                                    local_path = os.path.join(rule_media_path, file_name)
                                    
                                    # Skip download if file already exists and has content
                                    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                                        logger.info(f"Media file already exists, skipping download: {local_path}")
                                    else:
                                        try:
                                            await msg.download_media(local_path)
                                            logger.info(f"Downloading photo directly to: {local_path}")
                                        except Exception as e:
                                            if "file reference has expired" in str(e):
                                                logger.warning(f"File reference expired, re-fetching message")
                                                try:
                                                    # Try re-fetching the message
                                                    refreshed_msg = await context.client.get_messages(
                                                        msg.chat_id, ids=msg.id
                                                    )
                                                    if refreshed_msg:
                                                        await refreshed_msg.download_media(local_path)
                                                        logger.info(f"Re-downloaded photo to: {local_path}")
                                                    else:
                                                        logger.error("Failed to re-fetch message")
                                                        continue
                                                except Exception as refresh_error:
                                                    logger.error(f"Error re-fetching message: {str(refresh_error)}")
                                                    continue
                                            else:
                                                logger.error(f"Error downloading media group photo: {str(e)}")
                                                continue
                                    
                                    # Get file size
                                    if os.path.exists(local_path):
                                        file_size = os.path.getsize(local_path)
                                        
                                        # Add to media list with rule-specific URL
                                        media_info = {
                                            "url": f"/media/{rule_id}/{file_name}",
                                            "type": "image/jpeg",
                                            "size": file_size,
                                            "filename": file_name,
                                            "original_name": "photo.jpg"  # Photos have no original filename
                                        }
                                        media_list.append(media_info)
                                        logger.info(f"Added media group photo to RSS: {file_name}")
                                except Exception as e:
                                    logger.error(f"Error processing media group photo: {str(e)}")
                            elif hasattr(msg, 'document') and msg.document:
                                # Get message ID for default filename
                                message_id = getattr(msg, 'id', 'unknown')
                                original_name = None
                                for attr in msg.document.attributes:
                                    if hasattr(attr, 'file_name'):
                                        original_name = attr.file_name
                                        break
                                
                                file_name = original_name if original_name else f"document_{message_id}"
                                file_name = self._sanitize_filename(file_name)
                                
                                try:
                                    # Use rule-specific media directory
                                    local_path = os.path.join(rule_media_path, file_name)
                                    
                                    # Skip download if file already exists and has content
                                    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                                        logger.info(f"Media file already exists, skipping download: {local_path}")
                                    else:
                                        try:
                                            await msg.download_media(local_path)
                                            logger.info(f"Downloading document directly to: {local_path}")
                                        except Exception as e:
                                            if "file reference has expired" in str(e):
                                                logger.warning(f"File reference expired, re-fetching message")
                                                try:
                                                    # Try re-fetching the message
                                                    refreshed_msg = await context.client.get_messages(
                                                        msg.chat_id, ids=msg.id
                                                    )
                                                    if refreshed_msg:
                                                        await refreshed_msg.download_media(local_path)
                                                        logger.info(f"Re-downloaded document to: {local_path}")
                                                    else:
                                                        logger.error("Failed to re-fetch message")
                                                        continue
                                                except Exception as refresh_error:
                                                    logger.error(f"Error re-fetching message: {str(refresh_error)}")
                                                    continue
                                            else:
                                                logger.error(f"Error downloading media group document: {str(e)}")
                                                continue
                                    
                                    # Get file size and MIME type
                                    if os.path.exists(local_path):
                                        file_size = os.path.getsize(local_path)
                                        mime_type = msg.document.mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
                                        
                                        # Add to media list with rule-specific URL
                                        media_info = {
                                            "url": f"/media/{rule_id}/{file_name}",
                                            "type": mime_type,
                                            "size": file_size,
                                            "filename": file_name,
                                            "original_name": original_name or file_name
                                        }
                                        media_list.append(media_info)
                                        logger.info(f"Added media group document to RSS: {file_name}, original name: {original_name or 'unknown'}")
                                except Exception as e:
                                    logger.error(f"Error processing media group document: {str(e)}")
                            
                            # Other media types can be added similarly
                        
                        except Exception as e:
                            logger.error(f"Error processing media group message: {str(e)}")
            
            # Prepare entry data
            # Get message text content
            message_text = context.message_text or ""
            
            # Build title: prefer message text, fall back to default when empty
            if message_text.strip():
                # Use first line or first 30 chars (whichever is shorter) as title
                first_line = message_text.split('\n')[0].strip()
                title = first_line[:30] + ('...' if len(first_line) > 30 else '')
            else:
                # No text content, use default title
                if media_list:
                    title = f"Media Group ({len(media_list)} file(s))"
                else:
                    title = "Media Group"
            
            # Build entry data
            entry_data = {
                "id": str(context.event.message.id),
                "title": title,
                "content": context.message_text or "",
                "published": context.event.message.date.isoformat(),
                "author": await self._get_sender_name(context.client, context.event.message),
                "link": self._get_message_link(context.event.message),
                "media": media_list
            }
            
            # Log media group entry data
            logger.info(f"Media group entry: title={title}, media count={len(media_list)}")
            
            # If there are valid media files, add to RSS feed
            if media_list:
                await self._send_to_rss_service(rule.id, entry_data)
                logger.info(f"Successfully added media group to RSS feed for rule {rule.id}")
            else:
                logger.warning("Media group has no valid media files, skipping RSS feed addition")
        
        except Exception as e:
            logger.error(f"Error processing media group: {str(e)}")
            return False
        
        return True
