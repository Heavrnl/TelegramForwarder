import asyncio
from datetime import datetime, timedelta
import pytz
import os
import logging
from dotenv import load_dotenv
from telethon import TelegramClient
from models.models import get_session, Chat
import traceback
from utils.constants import DEFAULT_TIMEZONE
logger = logging.getLogger(__name__)

class ChatUpdater:
    def __init__(self, user_client: TelegramClient):
        self.user_client = user_client
        self.timezone = pytz.timezone(DEFAULT_TIMEZONE)
        self.task = None
        # Get update time from environment variable, default is 3:00 AM
        self.update_time = os.getenv('CHAT_UPDATE_TIME', "03:00")

    async def start(self):
        """Start the scheduled update task"""
        logger.info("Starting chat info updater...")
        try:
            # Calculate the next execution time
            now = datetime.now(self.timezone)
            next_time = self._get_next_run_time(now, self.update_time)
            wait_seconds = (next_time - now).total_seconds()

            logger.info(f"Next chat info update time: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"Wait time: {wait_seconds:.2f} seconds")

            # Create scheduled task
            self.task = asyncio.create_task(self._run_update_task())
            logger.info("Chat info updater startup completed")
        except Exception as e:
            logger.error(f"Error starting chat info updater: {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")

    def _get_next_run_time(self, now, target_time):
        """Calculate the next run time"""
        hour, minute = map(int, target_time.split(':'))
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if next_time <= now:
            next_time += timedelta(days=1)

        return next_time

    async def _run_update_task(self):
        """Run the update task"""
        while True:
            try:
                # Calculate the next execution time
                now = datetime.now(self.timezone)
                target_time = self._get_next_run_time(now, self.update_time)

                # Wait until execution time
                wait_seconds = (target_time - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                # Execute the update task
                await self._update_all_chats()

            except asyncio.CancelledError:
                logger.info("Chat info update task has been cancelled")
                break
            except Exception as e:
                logger.error(f"Chat info update task encountered an error: {str(e)}")
                logger.error(f"Error details: {traceback.format_exc()}")
                await asyncio.sleep(60)  # Wait one minute before retrying after an error

    async def _update_all_chats(self):
        """Update all chat info"""
        logger.info("Starting to update all chat info...")
        session = get_session()
        try:
            # Get all chats
            chats = session.query(Chat).all()
            total_chats = len(chats)
            logger.info(f"Found {total_chats} chats that need info updates")

            updated_count = 0
            skipped_count = 0
            error_count = 0

            # Process each chat
            for i, chat in enumerate(chats, 1):
                try:
                    # Report progress every 10 chats
                    if i % 10 == 0 or i == total_chats:
                        logger.info(f"Progress: {i}/{total_chats} ({i/total_chats*100:.1f}%)")

                    chat_id = chat.telegram_chat_id
                    # Try to get chat entity
                    try:
                        # Try to convert chat ID to integer
                        try:
                            chat_id_int = int(chat_id)
                        except ValueError:
                            logger.warning(f"Chat ID '{chat_id}' is not a valid numeric format")
                            skipped_count += 1
                            continue

                        entity = await self.user_client.get_entity(chat_id_int)
                        # Update chat name
                        new_name = entity.title if hasattr(entity, 'title') else (
                            f"{entity.first_name} {entity.last_name}" if hasattr(entity, 'last_name') and entity.last_name
                            else entity.first_name if hasattr(entity, 'first_name')
                            else "Private Chat"
                        )

                        # Only update when the name has changed
                        if chat.name != new_name:
                            old_name = chat.name or "Unnamed"
                            chat.name = new_name
                            session.commit()
                            logger.info(f"Updated chat {chat_id}: {old_name} -> {new_name}")
                            updated_count += 1
                        else:
                            skipped_count += 1

                    except ValueError as e:
                        logger.warning(f"Unable to get info for chat {chat_id}: Invalid ID format - {str(e)}")
                        skipped_count += 1
                        continue
                    except Exception as e:
                        logger.warning(f"Unable to get info for chat {chat_id}: {str(e)}")
                        skipped_count += 1
                        continue

                except Exception as e:
                    logger.error(f"Error processing chat {chat.telegram_chat_id}: {str(e)}")
                    error_count += 1
                    continue

                # Pause briefly after processing each chat to avoid excessive request frequency
                await asyncio.sleep(1)

            logger.info(f"Chat info update completed. Total: {total_chats}, Updated: {updated_count}, Skipped: {skipped_count}, Errors: {error_count}")

        except Exception as e:
            logger.error(f"Error updating chat info: {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")
        finally:
            session.close()

    def stop(self):
        """Stop the scheduled task"""
        if self.task:
            self.task.cancel()
            logger.info("Chat info update task has been stopped")
