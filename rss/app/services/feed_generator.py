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
        """Extract title and content from a Telegram message.

        Args:
            content: Raw message content

        Returns:
            tuple: (title, remaining content)
        """
        if not content:
            logger.info("Input content is empty, returning empty title and content")
            return "", ""

        try:
            # Read title template configuration
            config_path = Path(__file__).parent.parent / 'configs' / 'title_template.json'
            logger.info(f"Reading title template config file: {config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                title_config = json.load(f)

            # Iterate over each pattern
            for pattern_info in title_config['patterns']:
                pattern_str = pattern_info['pattern']
                pattern_desc = pattern_info['description']
                logger.debug(f"Trying to match pattern: {pattern_desc} ({pattern_str})")

                # Compile the regular expression
                pattern = re.compile(pattern_str, re.MULTILINE)

                # Attempt to match
                match = pattern.match(content)
                if match:
                    title = FeedService.clean_title(match.group(1))
                    # Get the start and end positions of the match
                    start, end = match.span(0)
                    # Extract remaining content, stripping leading whitespace
                    remaining_content = content[end:].lstrip()
                    logger.info(f"Successfully matched title pattern: {pattern_desc}")
                    logger.info(f"Raw content: {content[:100]}...")  # Show only first 100 chars
                    logger.info(f"Matched pattern: {pattern_str}")
                    logger.info(f"Extracted title: {title}")
                    logger.info(f"Remaining content length: {len(remaining_content)} chars")
                    return title, remaining_content

            # If no pattern matched, use first 20 characters as title
            logger.info("No title pattern matched, using first 20 characters as title")
            # Strip newlines from content and limit title to 20 characters
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
        """Clean special characters and formatting marks from a title.

        Args:
            title: Raw title text

        Returns:
            str: Cleaned title
        """
        if not title:
            return ""

        # Remove all asterisks
        title = title.replace('*', '')

        # Handle link format [text](url), keeping only the text part
        title = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', title)

        # Remove newlines and surrounding whitespace
        title = title.replace('\n', ' ').strip()

        return title

    @staticmethod
    def clean_content(content: str) -> str:
        """Clean special characters and formatting marks from content.

        Args:
            content: Raw content text

        Returns:
            str: Cleaned content
        """
        if not content:
            return ""

        # Remove 1-2 leading asterisks if present
        content = re.sub(r'^\*{1,2}\s*', '', content)

        # Remove leading blank lines
        content = re.sub(r'^\s*\n+', '', content)

        return content

    @staticmethod
    async def generate_feed_from_entries(rule_id: int, entries: List[Entry], base_url: str = None) -> FeedGenerator:
        """Generate a Feed from real entries"""
        fg = FeedGenerator()
        # Set encoding
        fg.load_extension('base', atom=True)
        rss_config = None

        # Use config default if no base_url provided
        if base_url is None:
            base_url = f"http://{settings.HOST}:{settings.PORT}"

        logger.info(f"Generating Feed - Rule ID: {rule_id}, entry count: {len(entries)}, base URL: {base_url}")

        session = get_session()
        try:
            rss_config = session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()
            logger.info(f"Retrieved RSS config: {rss_config.__dict__}")
            # Set Feed title and description
            if rss_config and rss_config.enable_rss:
                if rss_config.rule_title:
                    fg.title(rss_config.rule_title)
                else:
                    fg.title(f'TG Forwarder RSS - Rule {rule_id}')

                if rss_config.rule_description:
                    fg.description(rss_config.rule_description)
                else:
                    fg.description(f'TG Forwarder RSS - Messages for Rule {rule_id}')

                # Set language
                fg.language(rss_config.language or 'zh-CN')
            else:
                # Default title and description
                fg.title(f'TG Forwarder RSS - Rule {rule_id}')
                fg.description(f'TG Forwarder RSS - Messages for Rule {rule_id}')
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
                            # If not auto-extracting content, use raw content
                            content = FeedService.convert_markdown_to_html(entry.content or "")
                    else:
                        # If not auto-extracting, use raw content directly
                        content = FeedService.convert_markdown_to_html(entry.content or "")

                # Add images - optimized handling for various RSS readers
                all_media_urls = []  # Store all media URLs for later checks

                if entry.media:
                    logger.info(f"Processing media for entry {entry.id}, count: {len(entry.media)}")
                    # Process each media file
                    for idx, media in enumerate(entry.media):
                        # Log the original media URL
                        original_url = media.url if hasattr(media, 'url') else "unknown"
                        logger.info(f"Media {idx+1}/{len(entry.media)} - original URL: {original_url}")

                        # Build normalized media URL including rule ID
                        media_filename = os.path.basename(media.url.split('/')[-1])
                        media_url = f"/media/{entry.rule_id}/{media_filename}"
                        full_media_url = f"{base_url}{media_url}"
                        all_media_urls.append(full_media_url)

                        logger.info(f"Media {idx+1}/{len(entry.media)} - new URL: {full_media_url}")

                        # Handle image types
                        if media.type.startswith('image/'):
                            try:
                                # Build media file path
                                rule_media_path = settings.get_rule_media_path(entry.rule_id)
                                media_path = os.path.join(rule_media_path, media_filename)

                                # Add image tag to content - use URL format with rule ID
                                img_tag = f'<p><img src="{full_media_url}" alt="{media.filename}" style="max-width:100%;height:auto;display:block;" /></p>'
                                content += img_tag

                                logger.info(f"Added image tag to content: {media_filename}")
                            except Exception as e:
                                logger.error(f"Error adding image tag: {str(e)}")
                        elif media.type.startswith('video/'):
                            # Special handling for video
                            display_name = ""
                            if hasattr(media, "original_name") and media.original_name:
                                display_name = media.original_name
                            else:
                                display_name = media.filename

                            # Add HTML5 video player with inline styles
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

                            # Add HTML5 audio player with inline styles
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
                            # Other file types: add a download link
                            display_name = ""
                            if hasattr(media, "original_name") and media.original_name:
                                display_name = media.original_name
                            else:
                                display_name = media.filename

                            # Add a styled download link
                            file_tag = f'''
                            <div style="margin:15px 0;padding:10px;border-radius:5px;background-color:#f5f5f5;text-align:center;">
                                <a href="{full_media_url}" target="_blank" style="display:inline-block;padding:8px 16px;background-color:#4CAF50;color:white;text-decoration:none;border-radius:4px;">
                                    Download file: {display_name}
                                </a>
                            </div>
                            '''
                            content += file_tag

                # Ensure content is not empty; include default text at minimum
                if not content:
                    content = "<p>This message has no text content.</p>"
                    if entry.media and len(entry.media) > 0:
                        content += f"<p>Contains {len(entry.media)} media file(s).</p>"

                # Ensure content is valid HTML
                if not content.startswith("<"):
                    # Pre-process newlines to ensure paragraph structure
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

                # Clean up redundant HTML tags and whitespace while preserving meaningful paragraph structure
                content = re.sub(r'<br>\s*<br>', '<br>', content)
                content = re.sub(r'<p>\s*</p>', '', content)
                content = re.sub(r'<p><br></p>', '<p></p>', content)

                # Check whether content contains hardcoded local addresses
                if "127.0.0.1" in content or "localhost" in content:
                    logger.warning(f"Content contains hardcoded local address, replacing with: {base_url}")
                    content = content.replace(f"http://127.0.0.1:{settings.PORT}", base_url)
                    content = content.replace(f"http://localhost:{settings.PORT}", base_url)
                    content = content.replace(f"http://{settings.HOST}:{settings.PORT}", base_url)

                # Add media enclosures and ensure all media is included in content
                if entry.media:
                    for media in entry.media:
                        try:
                            # Use media URL format with rule ID
                            media_filename = os.path.basename(media.url.split('/')[-1])
                            full_media_url = f"{base_url}/media/{entry.rule_id}/{media_filename}"

                            # Ensure images are already added to content
                            if media.type.startswith('image/') and full_media_url not in content:
                                # Add missing image tag
                                img_tag = f'<p><img src="{full_media_url}" alt="{media.filename}" style="max-width:100%;" /></p>'
                                content += img_tag
                                logger.info(f"Added missing image tag: {media_filename}")

                            # Log the added media enclosure
                            logger.info(f"Adding media enclosure: {full_media_url}, type: {media.type}, size: {media.size}")

                            # Add enclosure
                            fe.enclosure(
                                url=full_media_url,
                                length=str(media.size) if hasattr(media, 'size') else "0",
                                type=media.type if hasattr(media, 'type') else "application/octet-stream"
                            )
                        except Exception as e:
                            logger.error(f"Error adding media enclosure: {str(e)}")

                # Set content field
                fe.content(content, type='html')

                # Set description field using the same content
                fe.description(content)

                # Parse ISO format timestamp and set publish time
                try:
                    published_dt = datetime.fromisoformat(entry.published)
                    fe.published(published_dt)
                except ValueError:
                    # Use current time if timestamp format is invalid
                    try:
                        tz = pytz.timezone(DEFAULT_TIMEZONE)
                        fe.published(datetime.now(tz))
                    except Exception as tz_error:
                        logger.warning(f"Timezone error: {str(tz_error)}, using UTC")
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
        """Extract channel/group name from a Telegram link"""
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
        """Convert Markdown to HTML using the standard markdown library, preserving newline structure"""
        if not text:
            return ""

        # Use the standard markdown library for conversion
        try:
            # Pre-process text: convert consecutive newlines to paragraph markers
            text = re.sub(r'\n{2,}', '\n\n<!-- paragraph -->\n\n', text)

            # Escape lines starting with # to prevent them being treated as headings
            lines = text.split('\n')
            processed_lines = []
            for line in lines:
                if line.startswith('#'):
                    line = '\\' + line
                processed_lines.append(line + '  ')  # Add two spaces to force line break
            text = '\n'.join(processed_lines)

            # Convert using the markdown module
            html = markdown.markdown(text, extensions=['extra'])

            # Process paragraph markers to ensure paragraph separation
            html = html.replace('<p><!-- paragraph --></p>', '</p><p>')

            return html
        except Exception as e:
            # Fall back to basic processing on error
            logger.error(f"Markdown conversion error: {str(e)}")

            # Improved newline handling: convert two or more consecutive newlines to paragraph breaks
            text = re.sub(r'\n{2,}', '</p><p>', text)

            # Convert single newlines to <br>
            text = text.replace('\n', '<br>')

            return f"<p>{text}</p>"

    @staticmethod
    def generate_test_feed(rule_id: int, base_url: str = None) -> FeedGenerator:
        """Generate a test Feed for use when no real entry data is available.

        Args:
            rule_id: Rule ID
            base_url: Request base URL used to generate links

        Returns:
            FeedGenerator: Configured test Feed generator
        """
        fg = FeedGenerator()
        # Set encoding
        fg.load_extension('base', atom=True)
        rss_config = None

        # Use config default if no base_url provided
        if base_url is None:
            base_url = f"http://{settings.HOST}:{settings.PORT}"

        logger.info(f"Generating test Feed - Rule ID: {rule_id}, base URL: {base_url}")

        # Retrieve RSS configuration from database
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
            logger.warning(f"Timezone error: {str(tz_error)}, using UTC")
            tz = pytz.UTC

        # # Add a single test entry
        # try:
        #     fe = fg.add_entry()

        #     # Set test entry ID and title
        #     entry_id = f"test-{rule_id}-1"
        #     fe.id(entry_id)
        #     fe.title(f"Test Entry - Rule {rule_id}")

        #     # Generate content including test description
        #     current_time = datetime.now(tz)
        #     content = f'''
        #     <p>This is a test entry generated automatically because rule {rule_id} currently has no message data.</p>
        #     <p>When messages are forwarded, real entries will appear here.</p>
        #     <hr>
        #     <p>This test entry was generated at: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
        #     '''

        #     # Set content and description
        #     fe.content(content, type='html')
        #     fe.description(content)

        #     # Set publish time for test entry
        #     fe.published(datetime.now(tz))

        #     # Set author and link for test entry
        #     fe.author(name="TG Forwarder System")

        #     # Use correct URL format
        #     entry_url = f"{base_url}/rss/feed/{rule_id}?entry={entry_id}"
        #     logger.info(f"Adding test entry link: {entry_url}")
        #     fe.link(href=entry_url)

        #     logger.info(f"Test entry added successfully")
        # except Exception as e:
        #     logger.error(f"Error adding test entry: {str(e)}")

        # logger.info(f"Test Feed generation complete, contains 1 test entry")
        return fg
