from fastapi import APIRouter, HTTPException, Depends, Body, Request
from fastapi.responses import Response, FileResponse
from typing import Dict, Any
import logging
import os
import json
from pathlib import Path
from ...services.feed_generator import FeedService
from ...models.entry import Entry
from ...core.config import settings
from ...crud.entry import get_entries, create_entry, delete_entry
import mimetypes
from models.models import get_session, RSSConfig
from datetime import datetime
from ai import get_ai_provider
from models.models import get_session, ForwardRule
import re
from models.models import RSSPattern
import shutil
import time
import os
import subprocess
import platform
from pydantic import ValidationError
from utils.constants import RSS_MEDIA_BASE_URL

logger = logging.getLogger(__name__)
router = APIRouter()

# Add local access verification dependency
async def verify_local_access(request: Request):
    """Verify that the request comes from local or Docker internal network"""
    client_host = request.client.host if request.client else None

    # List of allowed local IP addresses
    local_addresses = ['127.0.0.1', '::1', 'localhost', '0.0.0.0']

    # If the HOST environment variable is set, add it to the allowed list
    if hasattr(settings, 'HOST') and settings.HOST:
        local_addresses.append(settings.HOST)

    # Check if it's a Docker internal network IP (common private network ranges)
    docker_ip = False
    if client_host:
        docker_prefixes = ['172.', '192.168.', '10.']
        docker_ip = any(client_host.startswith(prefix) for prefix in docker_prefixes)

    # If it's a local address or Docker internal network IP, allow access
    if client_host in local_addresses or docker_ip:
        logger.debug(f"Access verified: {client_host}")
        return True

    # Deny access from external networks
    logger.warning(f"Denied access from external network: {client_host}")
    raise HTTPException(
        status_code=403,
        detail="This API endpoint only allows local or internal network access"
    )

@router.get("/")
async def root():
    """Service status check"""
    return {
        "status": "ok",
        "service": "TG Forwarder RSS"
    }

@router.get("/rss/feed/{rule_id}")
async def get_feed(rule_id: int, request: Request):
    """Return the RSS Feed for a rule"""
    session = None
    try:
        # Create database session
        session = get_session()

        # Query rule configuration
        rss_config = session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()
        if not rss_config or not rss_config.enable_rss:
            logger.warning(f"RSS for rule {rule_id} is not enabled or does not exist")
            raise HTTPException(status_code=404, detail="RSS feed is not enabled or does not exist")

        # Get the base part of the request URL
        base_url = str(request.base_url).rstrip('/')
        logger.info(f"Request base URL: {base_url}")
        logger.info(f"Request headers: {request.headers}")
        logger.info(f"Request client: {request.client}")

        # Check if there is a base URL configured in environment variables
        if RSS_MEDIA_BASE_URL:
            logger.info(f"Using media base URL from environment variable: {RSS_MEDIA_BASE_URL}")
            base_url = RSS_MEDIA_BASE_URL.rstrip('/')
        else:
            # Check if there is an X-Forwarded-Host or Host header
            forwarded_host = request.headers.get("X-Forwarded-Host")
            host_header = request.headers.get("Host")
            if forwarded_host:
                logger.info(f"Detected X-Forwarded-Host: {forwarded_host}")
                # Build URL based on forwarded_host
                scheme = request.headers.get("X-Forwarded-Proto", "http")
                base_url = f"{scheme}://{forwarded_host}"
                logger.info(f"Media base URL based on X-Forwarded-Host: {base_url}")
            elif host_header and host_header != f"{settings.HOST}:{settings.PORT}":
                logger.info(f"Detected custom Host: {host_header}")
                # Build URL based on Host
                scheme = request.url.scheme
                base_url = f"{scheme}://{host_header}"
                logger.info(f"Media base URL based on Host: {base_url}")

        logger.info(f"Final media base URL: {base_url}")

        # Get entries for the rule
        entries = await get_entries(rule_id)
        logger.info(f"Retrieved {len(entries)} entries")

        # If no entries, return test data
        if not entries:
            logger.warning(f"Rule {rule_id} has no entry data, returning test data")
            try:
                fg = FeedService.generate_test_feed(rule_id, base_url)

                # Generate RSS XML
                rss_xml = fg.rss_str(pretty=True)

                # Ensure rss_xml is string type
                if isinstance(rss_xml, bytes):
                    logger.info("Converting RSS XML from bytes to string")
                    rss_xml = rss_xml.decode('utf-8')

                # Log a portion of the XML content
                xml_sample = rss_xml[:500] + "..." if len(rss_xml) > 500 else rss_xml
                logger.info(f"Generated test RSS XML (first 500 chars): {xml_sample}")

                # Check if XML still contains hardcoded localhost or 127.0.0.1 addresses
                if "127.0.0.1" in rss_xml or "localhost" in rss_xml:
                    logger.warning(f"RSS XML still contains hardcoded local addresses")

                    # Replace hardcoded addresses
                    rss_xml = rss_xml.replace(f"http://127.0.0.1:{settings.PORT}", base_url)
                    rss_xml = rss_xml.replace(f"http://localhost:{settings.PORT}", base_url)
                    rss_xml = rss_xml.replace(f"http://{settings.HOST}:{settings.PORT}", base_url)

                    logger.info(f"Replaced hardcoded local addresses with: {base_url}")

                # Ensure return type is bytes
                if isinstance(rss_xml, str):
                    rss_xml = rss_xml.encode('utf-8')

                return Response(
                    content=rss_xml,
                    media_type="application/xml; charset=utf-8"
                )
            except Exception as e:
                logger.error(f"Error generating test Feed: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to generate test Feed: {str(e)}")
        else:
            # Generate Feed from real data, pass in base URL
            try:
                fg = await FeedService.generate_feed_from_entries(rule_id, entries, base_url)

                # Generate RSS XML
                rss_xml = fg.rss_str(pretty=True)

                # Ensure rss_xml is string type
                if isinstance(rss_xml, bytes):
                    logger.info("Converting RSS XML from bytes to string")
                    rss_xml = rss_xml.decode('utf-8')

                # Log a portion of the XML content
                xml_sample = rss_xml[:500] + "..." if len(rss_xml) > 500 else rss_xml
                logger.info(f"Generated RSS XML (first 500 chars): {xml_sample}")

                # Check if XML still contains hardcoded localhost or 127.0.0.1 addresses
                if "127.0.0.1" in rss_xml or "localhost" in rss_xml:
                    logger.warning(f"RSS XML still contains hardcoded local addresses")

                    # Replace hardcoded addresses
                    rss_xml = rss_xml.replace(f"http://127.0.0.1:{settings.PORT}", base_url)
                    rss_xml = rss_xml.replace(f"http://localhost:{settings.PORT}", base_url)
                    rss_xml = rss_xml.replace(f"http://{settings.HOST}:{settings.PORT}", base_url)

                    logger.info(f"Replaced hardcoded local addresses with: {base_url}")

                # Ensure return type is bytes
                if isinstance(rss_xml, str):
                    rss_xml = rss_xml.encode('utf-8')

                return Response(
                    content=rss_xml,
                    media_type="application/xml; charset=utf-8"
                )
            except Exception as e:
                logger.error(f"Error generating Feed from real entries: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to generate Feed: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating RSS feed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    finally:
        # Ensure session is closed
        if session:
            session.close()

@router.get("/media/{rule_id}/{filename}")
async def get_media(rule_id: int, filename: str, request: Request):
    """Return a media file"""
    # Log request information
    logger.info(f"Media request - Rule ID: {rule_id}, Filename: {filename}")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Request headers: {request.headers}")

    # Get base URL for logging
    base_url = str(request.base_url).rstrip('/')
    if RSS_MEDIA_BASE_URL:
        logger.info(f"Media base URL from environment variable: {RSS_MEDIA_BASE_URL}")
        base_url = RSS_MEDIA_BASE_URL.rstrip('/')
    else:
        # Check if there is an X-Forwarded-Host or Host header
        forwarded_host = request.headers.get("X-Forwarded-Host")
        host_header = request.headers.get("Host")
        if forwarded_host:
            logger.info(f"Detected X-Forwarded-Host: {forwarded_host}")
            scheme = request.headers.get("X-Forwarded-Proto", "http")
            base_url = f"{scheme}://{forwarded_host}"
        elif host_header and host_header != f"{settings.HOST}:{settings.PORT}":
            logger.info(f"Detected custom Host: {host_header}")
            scheme = request.url.scheme
            base_url = f"{scheme}://{host_header}"

    logger.info(f"Final media base URL: {base_url}")

    # Build rule-specific media file path
    media_path = Path(settings.get_rule_media_path(rule_id)) / filename

    # Log the attempted access path
    logger.info(f"Attempting to access media file: {media_path}")

    # Check if file exists
    if not media_path.exists():
        # File does not exist, return 404
        logger.error(f"Media file not found: {filename}")
        raise HTTPException(status_code=404, detail=f"Media file not found: {filename}")

    # Determine the correct MIME type
    mime_type = mimetypes.guess_type(str(media_path))[0]
    if not mime_type:
        # If MIME type cannot be determined, guess based on file extension
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        if ext in ['mp4', 'mov', 'avi', 'webm']:
            mime_type = f"video/{ext}"
        elif ext in ['mp3', 'wav', 'ogg', 'flac']:
            mime_type = f"audio/{ext}"
        elif ext in ['jpg', 'jpeg', 'png', 'gif']:
            mime_type = f"image/{ext}"
        else:
            mime_type = "application/octet-stream"

    logger.info(f"Sending media file: {filename}, MIME type: {mime_type}, Size: {os.path.getsize(media_path)} bytes")

    # Return file with correct Content-Type
    return FileResponse(
        path=media_path,
        media_type=mime_type,
        filename=filename
    )

@router.post("/api/entries/{rule_id}/add", dependencies=[Depends(verify_local_access)])
async def add_entry(rule_id: int, entry_data: Dict[str, Any] = Body(...)):
    """Add a new entry (local access only)"""
    try:
        # Log summary of received data
        media_count = len(entry_data.get("media", []))
        has_context = "context" in entry_data and entry_data["context"] is not None
        logger.info(f"Received new entry data: Rule ID={rule_id}, Title='{entry_data.get('title', 'No title')}', Media count={media_count}, Has context={has_context}")

        # Get RSS configuration to determine maximum entry count
        session = get_session()
        max_items = None
        try:
            rss_config = session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()
            max_items = rss_config.max_items
        finally:
            session.close()

        # Validate media data
        if media_count > 0:
            media_filenames = []
            for m in entry_data.get("media", []):
                if isinstance(m, dict):
                    media_filenames.append(m.get('filename', 'unknown'))
                else:
                    media_filenames.append(getattr(m, 'filename', 'unknown'))
            logger.info(f"Media file list: {media_filenames}")

            # Ensure media files exist
            for media in entry_data.get("media", []):
                if isinstance(media, dict):
                    filename = media.get("filename", "")
                else:
                    filename = getattr(media, "filename", "")

                media_path = os.path.join(settings.MEDIA_PATH, filename)
                if not os.path.exists(media_path):
                    logger.warning(f"Media file does not exist: {media_path}")

        # Log context information
        if has_context:
            logger.info(f"Entry contains original context object, attributes: {', '.join(entry_data['context'].keys()) if hasattr(entry_data['context'], 'keys') else 'unable to get attributes'}")

        # Ensure required fields exist
        entry_data["rule_id"] = rule_id
        if not entry_data.get("message_id"):
            entry_data["message_id"] = entry_data.get("id", "")

        # Check current entry count, delete oldest entries if approaching the limit
        current_entries = await get_entries(rule_id)
        if len(current_entries) >= max_items - 1:
            # Calculate the number of entries to delete, ensuring total does not exceed maximum after adding new entry
            to_delete_count = len(current_entries) - (max_items - 1)
            if to_delete_count > 0:
                logger.info(f"Current entry count ({len(current_entries)}) will exceed limit ({max_items}), need to delete {to_delete_count} oldest entries")

                # Sort entries by publish time (oldest first)
                sorted_entries = sorted(current_entries, key=lambda e: datetime.fromisoformat(e.published) if hasattr(e, 'published') else datetime.now())

                # Get entries to delete
                entries_to_delete = sorted_entries[:to_delete_count]

                # Delete excess entries
                for entry in entries_to_delete:
                    try:
                        # Process media files before deleting the entry
                        if hasattr(entry, 'media') and entry.media:
                            logger.info(f"Entry {entry.id} contains {len(entry.media)} media files, will be deleted together")

                            # Delete media files
                            media_dir = Path(settings.get_rule_media_path(rule_id))
                            for media in entry.media:
                                if hasattr(media, 'filename'):
                                    media_path = media_dir / media.filename
                                    if media_path.exists():
                                        try:
                                            os.remove(media_path)
                                            logger.info(f"Deleted media file: {media_path}")
                                        except Exception as e:
                                            logger.error(f"Failed to delete media file: {media_path}, Error: {str(e)}")

                        # Delete entry
                        success = await delete_entry(rule_id, entry.id)
                        if success:
                            logger.info(f"Deleted entry: {entry.id}")
                        else:
                            logger.warning(f"Failed to delete entry: {entry.id}")
                    except Exception as e:
                        logger.error(f"Error processing expired entry: {str(e)}")

        # Convert to Entry object
        entry = Entry(
            rule_id=rule_id,
            message_id=entry_data.get("message_id", entry_data.get("id", "")),
            title=entry_data.get("title", "New message"),
            content=entry_data.get("content", ""),
            published=entry_data.get("published"),
            author=entry_data.get("author", ""),
            link=entry_data.get("link", ""),
            media=entry_data.get("media", []),
            original_link=entry_data.get("original_link"),
            sender_info=entry_data.get("sender_info")
        )



        # Use AI to extract content
        if rss_config.is_ai_extract:
            try:
                rule = session.query(ForwardRule).filter(ForwardRule.id == rule_id).first()
                provider = await get_ai_provider(rule.ai_model)
                json_text = await provider.process_message(
                    message=entry.content or "",
                    prompt=rss_config.ai_extract_prompt,
                    model=rule.ai_model
                )
                logger.info(f"AI extracted content: {json_text}")

                # Remove code block markers if present
                if "```" in json_text:
                    # Remove all code block markers, including language identifiers and closing markers
                    json_text = re.sub(r'```(\w+)?\n', '', json_text)  # Opening marker (with optional language identifier)
                    json_text = re.sub(r'\n```', '', json_text)  # Closing marker
                    json_text = json_text.strip()
                    logger.info(f"Content after removing code block markers: {json_text}")

                # Parse JSON data
                try:
                    json_data = json.loads(json_text)
                    logger.info(f"Parsed JSON data: {json_data}")

                    # Extract title and content
                    title = json_data.get("title", "")
                    content = json_data.get("content", "")
                    entry.title = title
                    entry.content = content
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parse error: {str(e)}, Original text: {json_text}")
                    # Try alternative cleaning approach
                    try:
                        # Match JSON content between curly braces
                        json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
                        if json_match:
                            clean_json = json_match.group(0)
                            logger.info(f"Attempting to extract JSON: {clean_json}")
                            json_data = json.loads(clean_json)

                            # Extract title and content
                            title = json_data.get("title", "")
                            content = json_data.get("content", "")
                            entry.title = title
                            entry.content = content
                            logger.info(f"Successfully extracted JSON data from text")
                        else:
                            logger.error("Unable to extract valid JSON from AI response")
                    except Exception as inner_e:
                        logger.error(f"Error during secondary JSON parsing attempt: {str(inner_e)}")
                except Exception as e:
                    logger.error(f"Error processing JSON data: {str(e)}")
            except Exception as e:
                logger.error(f"Error during AI content extraction: {str(e)}")
            finally:
                if session:
                    session.close()

        logger.info(f"Custom title pattern enabled: {rss_config.enable_custom_title_pattern}, Custom content pattern enabled: {rss_config.enable_custom_content_pattern}")
        if rss_config.enable_custom_title_pattern or rss_config.enable_custom_content_pattern:
            try:
                # Get original content
                original_content = entry.content or ""
                original_title = entry.title

                # If title regex extraction is enabled
                if rss_config.enable_custom_title_pattern:
                    # Query title patterns directly using session and sort by priority
                    title_patterns = session.query(RSSPattern).filter_by(
                        rss_config_id=rss_config.id,
                        pattern_type='title'
                    ).order_by(RSSPattern.priority).all()

                    logger.info(f"Found {len(title_patterns)} title patterns")

                    # Set initial processing text
                    processing_content = original_content
                    logger.info(f"Title extraction initial text: {processing_content[:100]}..." if len(processing_content) > 100 else processing_content)

                    # Apply each pattern sequentially, using the result of each as input for the next
                    for pattern in title_patterns:
                        logger.info(f"Trying title pattern: {pattern.pattern}")
                        try:
                            logger.info(f"Applying regex to content: {pattern.pattern}")
                            match = re.search(pattern.pattern, processing_content)
                            if match:
                                logger.info(f"Match found: {match.groups()}")
                                if match.groups():
                                    entry.title = match.group(1)
                                    logger.info(f"Extracted title using pattern '{pattern.pattern}': {entry.title}")
                                else:
                                    logger.warning(f"Pattern '{pattern.pattern}' matched but has no capture groups")
                            else:
                                logger.info(f"Pattern '{pattern.pattern}' found no match")
                        except Exception as e:
                            logger.error(f"Error applying title regex '{pattern.pattern}': {str(e)}")
                            logger.exception("Detailed error info:")

                # If content regex extraction is enabled
                if rss_config.enable_custom_content_pattern:
                    # Query content patterns directly using session and sort by priority
                    content_patterns = session.query(RSSPattern).filter_by(
                        rss_config_id=rss_config.id,
                        pattern_type='content'
                    ).order_by(RSSPattern.priority).all()

                    logger.info(f"Found {len(content_patterns)} content patterns")

                    # Set initial processing text
                    processing_content = original_content
                    logger.info(f"Content extraction initial text: {processing_content[:100]}..." if len(processing_content) > 100 else processing_content)

                    # Apply each pattern sequentially, using the result of each as input for the next
                    for i, pattern in enumerate(content_patterns):
                        try:
                            logger.info(f"[Step {i+1}/{len(content_patterns)}] Applying regex to content: {pattern.pattern}")
                            logger.info(f"Content length before processing: {len(processing_content)}, Preview: {processing_content[:150]}..." if len(processing_content) > 150 else processing_content)

                            match = re.search(pattern.pattern, processing_content)
                            if match and match.groups():
                                extracted_content = match.group(1)
                                processing_content = extracted_content  # Update processing content with extracted result
                                entry.content = extracted_content

                                logger.info(f"Extracted content using pattern '{pattern.pattern}', length: {len(extracted_content)}")
                                logger.info(f"Content length after processing: {len(processing_content)}, Preview: {processing_content[:150]}..." if len(processing_content) > 150 else processing_content)
                            else:
                                logger.info(f"Pattern '{pattern.pattern}' found no match or has no capture groups, content remains unchanged")
                        except Exception as e:
                            logger.error(f"Error applying content regex '{pattern.pattern}': {str(e)}")


                # If no title was extracted by this point, restore the original title
                if not entry.title and original_title:
                    entry.title = original_title
                    logger.info(f"Restored original title: {entry.title}")

            except Exception as e:
                logger.error(f"Error extracting title and content using regex: {str(e)}")


        if entry.sender_info:
            # Strip spaces and line breaks
            entry.sender_info = entry.sender_info.strip()
            entry.content = entry.sender_info +":" +"\n\n" + entry.content

        # Add original link
        if entry.original_link:
            # Clean prefix, line breaks, and extra spaces from the link
            clean_link = entry.original_link.replace("Original message:", "").strip()
            # Remove all line breaks from the link
            clean_link = clean_link.replace("\n", "").replace("\r", "")
            # Handle extra spaces in the link
            clean_link = re.sub(r'\s+', ' ', clean_link).strip()

            # Ensure the link is in URL format
            if clean_link.startswith("http"):
                if entry.author:
                    # Use Markdown format link
                    entry.content += f'\n\n[Source: {entry.author}]({clean_link})'
                else:
                    # Use Markdown format link
                    entry.content += f'\n\n[Source]({clean_link})'
                logger.info(f"Added cleaned link (Markdown format): {clean_link}")
            else:
                logger.warning(f"Link format is incorrect, skipping: {clean_link}")

        # Processed message
        logger.info(f"Processed message: {entry.content}")



        # Add entry
        success = await create_entry(entry)
        if success:
            return {"status": "success", "message": f"Entry added, media file count: {media_count}"}
        else:
            logger.error("Failed to add entry")
            raise HTTPException(status_code=500, detail="Failed to add entry")

    except ValidationError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding entry: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/api/entries/{rule_id}/{entry_id}", dependencies=[Depends(verify_local_access)])
async def delete_entry_api(rule_id: int, entry_id: str):
    """Delete an entry (local access only)"""
    try:
        # Delete entry
        success = await delete_entry(rule_id, entry_id)
        if not success:
            raise HTTPException(status_code=404, detail="Entry not found")

        return {"status": "success", "message": "Entry deleted"}
    except Exception as e:
        logger.error(f"Error deleting entry: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/entries/{rule_id}")
async def list_entries(rule_id: int, limit: int = 20, offset: int = 0):
    """List all entries for a rule"""
    try:
        entries = await get_entries(rule_id, limit, offset)
        return {"entries": entries, "total": len(entries), "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"Error getting entry list: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/api/rule/{rule_id}", dependencies=[Depends(verify_local_access)])
async def delete_rule_data(rule_id: int):
    """Delete all data and media files for a rule (local access only)"""
    try:


        # Get the data directory and media directory for the rule
        data_path = Path(settings.get_rule_data_path(rule_id))
        media_path = Path(settings.get_rule_media_path(rule_id))

        deleted_files = 0
        deleted_dirs = 0
        failed_paths = []

        # Helper function: force delete directory
        def force_delete_directory(dir_path):
            if not dir_path.exists():
                return True, "Directory does not exist"

            # Method 1: Use shutil.rmtree
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
                if not dir_path.exists():
                    return True, "Successfully deleted using shutil.rmtree"
            except Exception as e:
                pass

            # Method 2: Use system commands
            try:
                system = platform.system()
                if system == "Windows":
                    # Windows: Use rd /s /q
                    subprocess.run(["rd", "/s", "/q", str(dir_path)],
                                  shell=True,
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
                else:
                    # Linux/Mac: Use rm -rf
                    subprocess.run(["rm", "-rf", str(dir_path)],
                                  stderr=subprocess.PIPE,
                                  stdout=subprocess.PIPE)

                if not dir_path.exists():
                    return True, "Successfully deleted using system command"
            except Exception as e:
                pass

            # Method 3: Rename then delete
            try:
                temp_path = dir_path.parent / f"temp_delete_{time.time()}"
                os.rename(dir_path, temp_path)
                shutil.rmtree(temp_path, ignore_errors=True)
                if not dir_path.exists() and not temp_path.exists():
                    return True, "Successfully deleted after renaming"
            except Exception as e:
                pass

            return False, "All deletion methods failed"

        # Delete media directory
        if media_path.exists():
            logger.info(f"Starting to delete media directory: {media_path}")
            success, method = force_delete_directory(media_path)
            if success:
                deleted_dirs += 1
                logger.info(f"Deleted media directory: {media_path} - {method}")
            else:
                logger.error(f"Unable to delete media directory: {media_path} - {method}")
                failed_paths.append(str(media_path))

        # Delete data directory
        if data_path.exists():
            logger.info(f"Starting to delete data directory: {data_path}")
            success, method = force_delete_directory(data_path)
            if success:
                deleted_dirs += 1
                logger.info(f"Deleted data directory: {data_path} - {method}")
            else:
                logger.error(f"Unable to delete data directory: {data_path} - {method}")
                failed_paths.append(str(data_path))

        # Verify deletion results
        remaining_paths = []
        if media_path.exists():
            remaining_paths.append(str(media_path))
        if data_path.exists():
            remaining_paths.append(str(data_path))

        # Return deletion results
        status = "success" if not remaining_paths else "failed"
        return {
            "status": status,
            "message": f"Processing rule {rule_id} data {'failed, directories still exist' if remaining_paths else 'succeeded, directories deleted'}",
            "details": {
                "data_path": str(data_path),
                "media_path": str(media_path),
                "deleted_files": deleted_files,
                "deleted_dirs": deleted_dirs,
                "failed_paths": failed_paths,
                "remaining_paths": remaining_paths,
                "data_dir_exists": data_path.exists(),
                "media_dir_exists": media_path.exists()
            }
        }
    except Exception as e:
        logger.error(f"Error deleting rule data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting rule data: {str(e)}")
