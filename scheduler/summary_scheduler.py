import asyncio
from datetime import datetime, timedelta
import pytz
from models.models import get_session, ForwardRule
import logging
import os
from dotenv import load_dotenv
from telethon import TelegramClient, errors
from ai import get_ai_provider
import traceback
from utils.constants import DEFAULT_TIMEZONE,DEFAULT_AI_MODEL,DEFAULT_SUMMARY_PROMPT

logger = logging.getLogger(__name__)

# Telegram's maximum message size limit (4096 characters)
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
# Maximum length for each summary message part, leaving headroom for metadata or formatting
MAX_MESSAGE_PART_LENGTH = TELEGRAM_MAX_MESSAGE_LENGTH - 300
# Maximum number of attempts for sending messages
MAX_SEND_ATTEMPTS = 2

class SummaryScheduler:
    def __init__(self, user_client: TelegramClient, bot_client: TelegramClient):
        self.tasks = {}  # All scheduled tasks {rule_id: task}
        self.timezone = pytz.timezone(DEFAULT_TIMEZONE)
        self.user_client = user_client
        self.bot_client = bot_client
        # Semaphore to limit concurrent requests
        self.request_semaphore = asyncio.Semaphore(2)  # Max 2 concurrent requests
        # Load config from environment variables
        self.batch_size = int(os.getenv('SUMMARY_BATCH_SIZE', 20))
        self.batch_delay = int(os.getenv('SUMMARY_BATCH_DELAY', 2))

    async def schedule_rule(self, rule):
        """Create or update scheduled task for a rule"""
        try:
            # If rule already has a task, cancel it first
            if rule.id in self.tasks:
                old_task = self.tasks[rule.id]
                old_task.cancel()
                logger.info(f"Cancelled old task for rule {rule.id}")
                del self.tasks[rule.id]

            # If AI summary is enabled, create a new task
            if rule.is_summary:
                # Calculate next run time
                now = datetime.now(self.timezone)
                next_time = self._get_next_run_time(now, rule.summary_time)
                wait_seconds = (next_time - now).total_seconds()

                logger.info(f"Next run time for rule {rule.id}: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"Wait time: {wait_seconds:.2f}s")

                task = asyncio.create_task(self._run_summary_task(rule))
                self.tasks[rule.id] = task
                logger.info(f"Created new summary task for rule {rule.id}, time: {rule.summary_time}")
            else:
                logger.info(f"Summary disabled for rule {rule.id}, no task created")

        except Exception as e:
            logger.error(f"Error scheduling rule {rule.id}: {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")

    async def _run_summary_task(self, rule):
        """Run summary task for a single rule"""
        while True:
            try:
                # Calculate next run time
                now = datetime.now(self.timezone)
                target_time = self._get_next_run_time(now, rule.summary_time)

                # Wait until execution time
                wait_seconds = (target_time - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                # Execute summary task
                await self._execute_summary(rule.id)

            except asyncio.CancelledError:
                logger.info(f"Old task for rule {rule.id} cancelled")
                break
            except Exception as e:
                logger.error(f"Summary task error for rule {rule.id}: {str(e)}")
                await asyncio.sleep(60)  # Wait 1 minute before retry on error

    def _split_message(self, text: str, max_length: int = MAX_MESSAGE_PART_LENGTH):
        if not text:
            return []

        parts = []
        while len(text) > 0:
            # Strip any leading whitespace from the remaining text to prevent empty parts.
            text = text.lstrip()
            if not text:
                break

            if len(text) <= max_length:
                parts.append(text)
                break

            # Find the best split position, searching backwards from max_length.
            split_pos = -1
            for sep in ('\n\n', '\n', ' '):
                pos = text.rfind(sep, 0, max_length)
                if pos > 0:
                    split_pos = pos
                    break
            if split_pos == -1:
                split_pos = max_length

            parts.append(text[:split_pos])
            text = text[split_pos:]

        return parts

    def _get_next_run_time(self, now, target_time):
        """Calculate next run time"""
        hour, minute = map(int, target_time.split(':'))
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if next_time <= now:
            next_time += timedelta(days=1)

        return next_time

    async def _execute_summary(self, rule_id, is_now=False):
        """Execute the summary task for a single rule"""
        session = get_session()
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not is_now:
                if not rule or not rule.is_summary:
                    return

            try:
                source_chat_id = int(rule.source_chat.telegram_chat_id)
                target_chat_id = int(rule.target_chat.telegram_chat_id)

                messages = []

                # Calculate time range
                now = datetime.now(self.timezone)
                summary_hour, summary_minute = map(int, rule.summary_time.split(':'))

                # End time is now
                end_time = now

                # Start time is yesterday's summary time
                start_time = now.replace(
                    hour=summary_hour,
                    minute=summary_minute,
                    second=0,
                    microsecond=0
                ) - timedelta(days=1)

                logger.info(f'Rule {rule_id} fetching messages in range: {start_time} to {end_time}')

                async with self.request_semaphore:
                    messages = []
                    current_offset = 0

                    while True:
                        batch = []  # Initialized outside inner loop
                        messages_batch = await self.user_client.get_messages(
                            source_chat_id,
                            limit=self.batch_size,
                            offset_date=end_time,
                            offset_id=current_offset,
                            reverse=False
                        )

                        if not messages_batch:
                            logger.info(f'Rule {rule_id} no new messages, exiting loop')
                            break

                        logger.info(f'Rule {rule_id} fetched batch of {len(messages_batch)} messages')

                        should_break = False
                        for message in messages_batch:
                            msg_time = message.date.astimezone(self.timezone)
                            preview = message.text[:20] + '...' if message.text else 'None'
                            logger.info(f'Rule {rule_id} processing message - time: {msg_time}, preview: {preview}, len: {len(message.text) if message.text else 0}')

                            # Skip messages from the future
                            if msg_time > end_time:
                                continue

                            # Add to batch if within valid time range
                            if start_time <= msg_time <= end_time and message.text:
                                batch.append(message.text)

                            # If message is before start time, mark exit
                            if msg_time < start_time:
                                logger.info(f'Rule {rule_id} message time {msg_time} is before start {start_time}, stopping fetch')
                                should_break = True
                                break

                        # Add batch messages to full list
                        if batch:
                            messages.extend(batch)
                            logger.info(f'Rule {rule_id} added {len(batch)} messages in batch, total: {len(messages)}')

                        # Update offset to last message ID
                        current_offset = messages_batch[-1].id

                        # Exit loop if flagged
                        if should_break:
                            break

                        # Wait between batches
                        await asyncio.sleep(self.batch_delay)

                if not messages:
                    logger.info(f'Rule {rule_id} has no messages to summarize')
                    return

                all_messages = '\n'.join(messages)

                # Check AI model setting, use default if not set
                if not rule.ai_model:
                    rule.ai_model = DEFAULT_AI_MODEL
                    logger.info(f"Using default AI model for summary: {rule.ai_model}")
                else:
                    logger.info(f"Using rule-configured AI model for summary: {rule.ai_model}")

                # Get AI provider and process summary
                provider = await get_ai_provider(rule.ai_model)
                summary = await provider.process_message(
                    all_messages,
                    prompt=rule.summary_prompt or DEFAULT_SUMMARY_PROMPT,
                    model=rule.ai_model
                )


                if summary:
                    duration_hours = round((end_time - start_time).total_seconds() / 3600)
                    header = f"📋 {rule.source_chat.name} - {duration_hours}h Message Summary\n"
                    header += f"🕐 Time range: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')}\n"
                    header += f"📊 Messages: {len(messages)}\n\n"

                    summary_parts = self._split_message(summary, MAX_MESSAGE_PART_LENGTH)

                    summary_message = None
                    for i, part in enumerate(summary_parts):
                        if i == 0:
                            message_to_send = header + part
                        else:
                            message_to_send = f"📋 {rule.source_chat.name} - Summary Report (cont. {i+1}/{len(summary_parts)})\n\n" + part

                        # Send message with retry support
                        current_message = None
                        use_markdown = True
                        attempt = 0

                        while attempt < MAX_SEND_ATTEMPTS:
                            logger.info(f"Retry attempt {attempt + 1}/{MAX_SEND_ATTEMPTS} for sending message to chat ID {target_chat_id}.")
                            try:
                                if use_markdown:
                                    current_message = await self.bot_client.send_message(
                                        target_chat_id,
                                        message_to_send,
                                        parse_mode='markdown'
                                    )
                                else:
                                    # Fallback to plain text
                                    current_message = await self.bot_client.send_message(
                                        target_chat_id,
                                        message_to_send
                                    )
                                break  # Success, exit retry loop

                            except errors.MarkupInvalidError as e:
                                if use_markdown:
                                    logger.warning(f"Markdown parse failed: {e}. Retrying as plain text.")
                                    use_markdown = False
                                    continue  # Retry immediately with plain text
                                else:
                                    # This should not happen, but if it does, it's a bug.
                                    logger.error(f"Unexpected MarkupInvalidError during plain text send: {e}")
                                    raise # Fail fast

                            except errors.FloodWaitError as fwe:
                                if attempt < MAX_SEND_ATTEMPTS - 1:
                                    logger.warning(f"Telegram flood limit hit, waiting {fwe.seconds}s before retry...")
                                    await asyncio.sleep(fwe.seconds)
                                    attempt += 1
                                else:
                                    logger.error("Max retries reached, send failed.")
                                    raise

                            except Exception as send_error:
                                logger.error(f"Error sending summary part {i+1}: {str(send_error)}")
                                if attempt >= MAX_SEND_ATTEMPTS - 1:
                                    raise # Re-raise on last attempt
                                await asyncio.sleep(1) # Wait a bit before retrying on other errors
                                attempt += 1

                        # Track first message
                        if i == 0:
                            summary_message = current_message

                    if rule.is_top_summary and summary_message:
                        try:
                            await self.bot_client.pin_message(target_chat_id, summary_message)
                        except Exception as pin_error:
                            logger.warning(f"Failed to pin summary message: {str(pin_error)}")

                    logger.info(f'Rule {rule_id} summary complete, {len(messages)} messages processed in {len(summary_parts)} part(s)')

            except Exception as e:
                logger.error(f'Error executing summary task for rule {rule_id}: {str(e)}')
                logger.error(f'Error details: {traceback.format_exc()}')

        finally:
            session.close()

    async def start(self):
        """Start the scheduler"""
        logger.info("Starting scheduler...")
        session = get_session()
        try:
            # Get all rules with summary enabled
            rules = session.query(ForwardRule).filter_by(is_summary=True).all()
            logger.info(f"Found {len(rules)} rule(s) with summary enabled")

            for rule in rules:
                logger.info(f"Creating scheduled task for rule {rule.id} ({rule.source_chat.name} -> {rule.target_chat.name})")
                logger.info(f"Summary time: {rule.summary_time}")

                # Calculate next run time
                now = datetime.now(self.timezone)
                next_time = self._get_next_run_time(now, rule.summary_time)
                wait_seconds = (next_time - now).total_seconds()

                logger.info(f"Next run time: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"Wait time: {wait_seconds:.2f}s")

                await self.schedule_rule(rule)

            if not rules:
                logger.info("No rules with summary enabled found")

            logger.info("Scheduler started")
        except Exception as e:
            logger.error(f"Error starting scheduler: {str(e)}")
            logger.error(f"Error details: {traceback.format_exc()}")
        finally:
            session.close()

    def stop(self):
        """Stop all tasks"""
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()

    async def execute_all_summaries(self):
        """Immediately execute all rules with summary enabled"""
        session = get_session()
        try:
            rules = session.query(ForwardRule).filter_by(is_summary=True).all()
            # Use gather with concurrency limit
            tasks = [self._execute_summary(rule.id, is_now=True) for rule in rules]
            for i in range(0, len(tasks), 2):  # Execute 2 tasks at a time
                batch = tasks[i:i+2]
                await asyncio.gather(*batch)
                await asyncio.sleep(1)  # Brief pause between batches

        finally:
            session.close()
