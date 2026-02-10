from feedgen.feed import FeedGenerator
from datetime import datetime, timedelta
from ..core.config import settings
from ..models.entry import Entry
from typing import List
import logging
import os
from pathlib import Path
import markdown
import re
import json
from models.models import get_session, RSSConfig
from utils.constants import DEFAULT_TIMEZONE
import pytz

logger = logging.getLogger(__name__)

class FeedService:


    @staticmethod
    def extract_telegram_title_and_content(content: str) -> tuple[str, str]:
        """Extract title and content from a Telegram message

        Args:
            content: Original message content

        Returns:
            tuple: (title, remaining content)
        """
        if not content:
            logger.info("Input content is empty, returning empty title and content")
            return "", ""

        try:
            # Read title template configuration
            config_path = Path(__file__).parent.parent / 'configs' / 'title_template.json'
            logger.info(f"Reading title template configuration file: {config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                title_config = json.load(f)

            # Iterate through each pattern
            for pattern_info in title_config['patterns']:
                pattern_str = pattern_info['pattern']
                pattern_desc = pattern_info['description']
                logger.debug(f"Trying to match pattern: {pattern_desc} ({pattern_str})")

                # Compile regex
                pattern = re.compile(pattern_str, re.MULTILINE)

                # Try to match
                match = pattern.match(content)
                if match:
                    title = FeedService.clean_title(match.group(1))
                    # Get the start and end positions of the matched portion
                    start, end = match.span(0)
                    # Extract remaining content, strip leading whitespace
                    remaining_content = content[end:].lstrip()
                    logger.info(f"Successfully matched title pattern: {pattern_desc}")
                    logger.info(f"Original content: {content[:100]}...")  # Only show first 100 characters
                    logger.info(f"Matched pattern: {pattern_str}")
                    logger.info(f"Extracted title: {title}")
                    logger.info(f"Remaining content length: {len(remaining_content)} characters")
                    return title, remaining_content

            # If no pattern matched, use the first 20 characters as the title
            logger.info("No title pattern matched, using first 20 characters as title")
            # Remove line breaks from content and limit title length to 20 characters
            clean_content = FeedService.clean_content(content)
            clean_content = clean_content.replace('\n', ' ').strip()
            title = clean_content[:20]
            if len(clean_content) > 20:
                title += "..."
            logger.debug(f"Generated default title: {title}")
            return title, content

        except Exception as e:
            logger.error(f"Error extracting title and content: {str(e)}")
            return "", content


    @staticmethod
    def clean_title(title: str) -> str:
        """Clean special characters and formatting marks from the title

        Args:
            title: Original title text

        Returns:
            str: Cleaned title
        """
        if not title:
            return ""

        # Remove all * characters
        title = title.replace('*', '')

        # Handle link format [text](url), keep the text part
        title = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', title)

        # Remove line breaks and leading/trailing whitespace
        title = title.replace('\n', ' ').strip()

        return title

    @staticmethod
    def clean_content(content: str) -> str:
        """Clean special characters and formatting marks from the content

        Args:
            content: Original content text

        Returns:
            str: Cleaned content
        """
        if not content:
            return ""

        # Remove possible 1-2 asterisks at the beginning
        content = re.sub(r'^\*{1,2}\s*', '', content)

        # Remove empty lines at the beginning
        content = re.sub(r'^\s*\n+', '', content)

        return content

    @staticmethod
    async def generate_feed_from_entries(rule_id: int, entries: List[Entry], base_url: str = None) -> FeedGenerator:
        """Generate Feed from real entries"""
        fg = FeedGenerator()
        # Set encoding
        fg.load_extension('base', atom=True)
        rss_config = None

        # If no base_url is provided, use the default from configuration
        if base_url is None:
            base_url = f"http://{settings.HOST}:{settings.PORT}"

        logger.info(f"Generating Feed - Rule ID: {rule_id}, Entry count: {len(entries)}, Base URL: {base_url}")

        session = get_session()
        try:
            rss_config = session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()
            logger.info(f"Retrieved RSS config: {rss_config.__dict__}")
            # Get Feed title and description
            if rss_config and rss_config.enable_rss:
                if rss_config.rule_title:
                    fg.title(rss_config.rule_title)
                else:
                    fg.title(f'TG Forwarder RSS - Rule {rule_id}')

                if rss_config.rule_description:
                    fg.description(rss_config.rule_description)
                else:
                    fg.description(f'TG Forwarder RSS - Messages for rule {rule_id}')

                # Set language
                fg.language(rss_config.language or 'zh-CN')
            else:
                # Default title and description
                fg.title(f'TG Forwarder RSS - Rule {rule_id}')
                fg.description(f'TG Forwarder RSS - Messages for rule {rule_id}')
                fg.language('zh-CN')
        finally:
            # Ensure session is closed
            session.close()

        # Set Feed link
        fg.link(href=f'{base_url}/rss/feed/{rule_id}')

        # Add entries
        for entry in entries:
            try:
                fe = fg.add_entry()
                fe.id(entry.id or entry.message_id)


                # Initialize content variable
                content = None
                fe.title(entry.title)

                if rss_config.is_ai_extract:
                    fe.title(entry.title)
                    content = entry.content
                else:
                    if rss_config.enable_custom_title_pattern:
                        fe.title(entry.title)
                    if rss_config.enable_custom_content_pattern:
                        content = entry.content
                    # Auto-extract title and content
                    if rss_config.is_auto_title or rss_config.is_auto_content:
                        extracted_title, extracted_content = FeedService.extract_telegram_title_and_content(entry.content or "")
                        if rss_config.is_auto_title:
                            fe.title(extracted_title)
                        if rss_config.is_auto_content:
                            content = FeedService.convert_markdown_to_html(extracted_content)
                        else:
                            # If not auto-extracting content, use original content
                            content = FeedService.convert_markdown_to_html(entry.content or "")
                    else:
                        # If not auto-extracting, use original content directly
                        content = FeedService.convert_markdown_to_html(entry.content or "")

                # Add images - optimized handling for various RSS readers
                all_media_urls = []  # Store all media URLs for subsequent checks

                if entry.media:
                    logger.info(f"Processing media files for entry {entry.id}, count: {len(entry.media)}")
                    # Process each media file
                    for idx, media in enumerate(entry.media):
                        # Log original media URL
                        original_url = media.url if hasattr(media, 'url') else "unknown"
                        logger.info(f"Media {idx+1}/{len(entry.media)} - Original URL: {original_url}")

                        # Build normalized media URL - restored to format including rule ID
                        media_filename = os.path.basename(media.url.split('/')[-1])
                        media_url = f"/media/{entry.rule_id}/{media_filename}"
                        full_media_url = f"{base_url}{media_url}"
                        all_media_urls.append(full_media_url)

                        logger.info(f"Media {idx+1}/{len(entry.media)} - New URL: {full_media_url}")

                        # Handle image types
                        if media.type.startswith('image/'):
                            try:
                                # Build media file path
                                rule_media_path = settings.get_rule_media_path(entry.rule_id)
                                media_path = os.path.join(rule_media_path, media_filename)

                                # Add image tag to content - using URL format with rule ID
                                img_tag = f'<p><img src="{full_media_url}" alt="{media.filename}" style="max-width:100%;height:auto;display:block;" /></p>'
                                content += img_tag

                                logger.info(f"Added image tag to content: {media_filename}")
                            except Exception as e:
                                logger.error(f"Error adding image tag: {str(e)}")
                        elif media.type.startswith('video/'):
                            # Special handling for videos
                            display_name = ""
                            if hasattr(media, "original_name") and media.original_name:
                                display_name = media.original_name
                            else:
                                display_name = media.filename

                            # Add HTML5 video player - using inline styles
                            video_player = f'''
                            <div style="margin:15px 0;border:1px solid #eee;padding:10px;border-radius:5px;background-color:#f9f9f9;">
                                <video controls width="100%" preload="none" poster="" seekable="true" controlsList="nodownload" style="width:100%;max-width:600px;display:block;margin:0 auto;">
                                    <source src="{full_media_url}" type="{media.type}">
                                    Your reader does not support HTML5 video playback/preview
                                </video>
                                <p style="text-align:center;margin-top:8px;font-size:14px;">
                                    <a href="{full_media_url}" target="_blank" style="display:inline-block;padding:6px 12px;background-color:#4CAF50;color:white;text-decoration:none;border-radius:4px;">
                                        <i class="bi bi-download"></i> Download video: {display_name}
                                    </a>
                                </p>
                            </div>
                            '''
                            content += video_player

                            logger.info(f"Added video player to content: {display_name}")
                        elif media.type.startswith('audio/'):
                            # Special handling for audio
                            display_name = ""
                            if hasattr(media, "original_name") and media.original_name:
                                display_name = media.original_name
                            else:
                                display_name = media.filename

                            # Add HTML5 audio player - using inline styles
                            audio_player = f'''
                            <div style="margin:15px 0;border:1px solid #eee;padding:10px;border-radius:5px;background-color:#f9f9f9;">
                                <audio controls style="width:100%;max-width:600px;display:block;margin:0 auto;">
                                    <source src="{full_media_url}" type="{media.type}">
                                    Your reader does not support HTML5 audio playback/preview
                                </audio>
                                <p style="text-align:center;margin-top:8px;font-size:14px;">
                                    <a href="{full_media_url}" target="_blank">Download audio: {display_name}</a>
                                </p>
                            </div>
                            '''
                            content += audio_player

                            logger.info(f"Added audio player to content: {display_name}")
                        else:
                            # Add download link for other file types
                            display_name = ""
                            if hasattr(media, "original_name") and media.original_name:
                                display_name = media.original_name
                            else:
                                display_name = media.filename

                            # Add styled download link
                            file_tag = f'''
                            <div style="margin:15px 0;padding:10px;border-radius:5px;background-color:#f5f5f5;text-align:center;">
                                <a href="{full_media_url}" target="_blank" style="display:inline-block;padding:8px 16px;background-color:#4CAF50;color:white;text-decoration:none;border-radius:4px;">
                                    Download file: {display_name}
                                </a>
                            </div>
                            '''
                            content += file_tag

                # Ensure content is not empty, at least include some default text
                if not content:
                    content = "<p>This message has no text content.</p>"
                    if entry.media and len(entry.media) > 0:
                        content += f"<p>Contains {len(entry.media)} media files.</p>"

                # Ensure content is valid HTML
                if not content.startswith("<"):
                    # Preprocess line breaks in text to ensure paragraph structure
                    processed_content = ""
                    paragraphs = content.split("\n\n")
                    for p in paragraphs:
                        if p.strip():
                            lines = p.split("\n")
                            processed_content += f"<p>{lines[0]}"
                            for line in lines[1:]:
                                if line.strip():
                                    processed_content += f"<br>{line}"
                            processed_content += "</p>"
                    content = processed_content if processed_content else f"<p>{content}</p>"

                # Remove redundant HTML tags and spaces, but preserve meaningful paragraph structure
                content = re.sub(r'<br>\s*<br>', '<br>', content)
                content = re.sub(r'<p>\s*</p>', '', content)
                content = re.sub(r'<p><br></p>', '<p></p>', content)

                # Check if content contains hardcoded local addresses
                if "127.0.0.1" in content or "localhost" in content:
                    logger.warning(f"Content contains hardcoded local addresses, will replace with: {base_url}")
                    content = content.replace(f"http://127.0.0.1:{settings.PORT}", base_url)
                    content = content.replace(f"http://localhost:{settings.PORT}", base_url)
                    content = content.replace(f"http://{settings.HOST}:{settings.PORT}", base_url)

                # Add media attachments and ensure content includes all media
                if entry.media:
                    for media in entry.media:
                        try:
                            # Use media URL format with rule ID
                            media_filename = os.path.basename(media.url.split('/')[-1])
                            full_media_url = f"{base_url}/media/{entry.rule_id}/{media_filename}"

                            # Ensure images and other content have been added
                            if media.type.startswith('image/') and full_media_url not in content:
                                # If the image is not in the content, add it
                                img_tag = f'<p><img src="{full_media_url}" alt="{media.filename}" style="max-width:100%;" /></p>'
                                content += img_tag
                                logger.info(f"Added missing image tag: {media_filename}")

                            # Log added media attachment
                            logger.info(f"Added media attachment: {full_media_url}, type: {media.type}, size: {media.size}")

                            # Add enclosure
                            fe.enclosure(
                                url=full_media_url,
                                length=str(media.size) if hasattr(media, 'size') else "0",
                                type=media.type if hasattr(media, 'type') else "application/octet-stream"
                            )
                        except Exception as e:
                            logger.error(f"Error adding media attachment: {str(e)}")

                # Set content field
                fe.content(content, type='html')

                # Set description field - using the same content
                fe.description(content)

                # Parse ISO format time string, set publish time
                try:
                    published_dt = datetime.fromisoformat(entry.published)
                    fe.published(published_dt)
                except ValueError:
                    # If time format is invalid, use current time
                    try:
                        tz = pytz.timezone(DEFAULT_TIMEZONE)
                        fe.published(datetime.now(tz))
                    except Exception as tz_error:
                        logger.warning(f"Timezone setting error: {str(tz_error)}, using UTC timezone")
                        fe.published(datetime.now(pytz.UTC))

                # Set author and link
                if entry.author:
                    fe.author(name=entry.author)

                if entry.link:
                    fe.link(href=entry.link)
            except Exception as e:
                logger.error(f"Error adding entry to Feed: {str(e)}")
                continue

        return fg

    @staticmethod
    def _extract_chat_name(link: str) -> str:
        """Extract channel/group name from Telegram link"""
        if not link or 't.me/' not in link:
            return ""

        try:
            # e.g. extract channel_name from https://t.me/channel_name/1234
            parts = link.split('t.me/')
            if len(parts) < 2:
                return ""

            channel_part = parts[1].split('/')[0]
            return channel_part
        except Exception:
            return ""



    @staticmethod
    def convert_markdown_to_html(text):
        """Convert Markdown format to HTML using the standard markdown library, preserving line break structure"""
        if not text:
            return ""

        # Use the standard markdown library for conversion
        try:
            # Preprocess text to ensure consecutive line breaks are correctly converted to paragraphs
            # First replace multiple consecutive line breaks with a special marker
            text = re.sub(r'\n{2,}', '\n\n<!-- paragraph -->\n\n', text)

            # Escape tags starting with # to prevent them from being recognized as headings
            lines = text.split('\n')
            processed_lines = []
            for line in lines:
                if line.startswith('#'):
                    line = '\\' + line
                processed_lines.append(line + '  ')  # Add two spaces to ensure line break
            text = '\n'.join(processed_lines)

            # Use the markdown module for conversion
            html = markdown.markdown(text, extensions=['extra'])

            # Process special markers to ensure paragraph separation
            html = html.replace('<p><!-- paragraph --></p>', '</p><p>')

            return html
        except Exception as e:
            # If an exception occurs, fall back to basic processing
            logger.error(f"Markdown conversion exception: {str(e)}")

            # Improved line break handling: convert two or more consecutive line breaks to paragraph separators
            text = re.sub(r'\n{2,}', '</p><p>', text)

            # Convert single line breaks to <br>
            text = text.replace('\n', '<br>')

            return f"<p>{text}</p>"

    @staticmethod
    def generate_test_feed(rule_id: int, base_url: str = None) -> FeedGenerator:
        """Generate a test Feed, used when there are no real entry data

        Args:
            rule_id: Rule ID
            base_url: Base URL of the request, used for generating links

        Returns:
            FeedGenerator: Configured test Feed generator
        """
        fg = FeedGenerator()
        # Set encoding
        fg.load_extension('base', atom=True)
        rss_config = None

        # If no base_url is provided, use the default from configuration
        if base_url is None:
            base_url = f"http://{settings.HOST}:{settings.PORT}"

        logger.info(f"Generating test Feed - Rule ID: {rule_id}, Base URL: {base_url}")

        # Get RSS configuration from database
        session = get_session()
        try:
            rss_config = session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()
            logger.info(f"Retrieved RSS config: {rss_config}")

            # Set Feed basic information
            if rss_config and rss_config.enable_rss:
                if rss_config.rule_title:
                    fg.title(rss_config.rule_title)
                else:
                    fg.title(f'')

                if rss_config.rule_description:
                    fg.description(rss_config.rule_description)
                else:
                    fg.description(f' ')

                # Set language
                fg.language(rss_config.language or 'zh-CN')
        finally:
            # Ensure session is closed
            session.close()

        # Set Feed link
        feed_url = f'{base_url}/rss/feed/{rule_id}'
        logger.info(f"Setting Feed link: {feed_url}")
        fg.link(href=feed_url)

        # Handle timezone
        try:
            tz = pytz.timezone(DEFAULT_TIMEZONE)
        except Exception as tz_error:
            logger.warning(f"Timezone setting error: {str(tz_error)}, using UTC timezone")
            tz = pytz.UTC

        # # Only add one test entry
        # try:
        #     fe = fg.add_entry()

        #     # Set test entry ID and title
        #     entry_id = f"test-{rule_id}-1"
        #     fe.id(entry_id)
        #     fe.title(f"Test entry - Rule {rule_id}")

        #     # Generate content, including test description
        #     current_time = datetime.now(tz)
        #     content = f'''
        #     <p>This is a test entry, automatically generated by the system, because rule {rule_id} currently has no message data.</p>
        #     <p>When messages are forwarded, real entries will be displayed here.</p>
        #     <hr>
        #     <p>This test entry was generated at: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
        #     '''

        #     # Set content and description
        #     fe.content(content, type='html')
        #     fe.description(content)

        #     # Set test entry publish time
        #     fe.published(datetime.now(tz))

        #     # Set test entry author and link
        #     fe.author(name="TG Forwarder System")

        #     # Use correct URL format
        #     entry_url = f"{base_url}/rss/feed/{rule_id}?entry={entry_id}"
        #     logger.info(f"Added test entry link: {entry_url}")
        #     fe.link(href=entry_url)

        #     logger.info(f"Successfully added test entry")
        # except Exception as e:
        #     logger.error(f"Error adding test entry: {str(e)}")

        # logger.info(f"Test Feed generation completed, containing 1 test entry")
        return fg
