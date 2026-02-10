import logging
import re
from filters.base_filter import BaseFilter

logger = logging.getLogger(__name__)

class ReplaceFilter(BaseFilter):
    """
    Replace filter, replaces message text based on rules
    """

    async def _process(self, context):
        """
        Process message text replacement

        Args:
            context: Message context

        Returns:
            bool: Whether to continue processing
        """
        rule = context.rule
        message_text = context.message_text

        # Print all attributes of context
        # logger.info(f"Before ReplaceFilter processing, context: {context.__dict__}")
        # If replacement is not needed, return directly
        if not rule.is_replace or not message_text:
            return True

        try:
            # Apply all replacement rules
            for replace_rule in rule.replace_rules:
                if replace_rule.pattern == '.*':
                    # Full text replacement
                    logger.info(f'Performing full text replacement:\nOriginal: "{message_text}"\nReplaced with: "{replace_rule.content or ""}"')
                    message_text = replace_rule.content or ''
                    break  # If it's a full text replacement, don't continue processing other rules
                else:
                    try:
                        # Regex replacement
                        old_text = message_text
                        matches = re.finditer(replace_rule.pattern, message_text)
                        message_text = re.sub(
                            replace_rule.pattern,
                            replace_rule.content or '',
                            message_text
                        )
                        if old_text != message_text:
                            matched_texts = [m.group(0) for m in matches]
                            logger.info(f'Performing partial replacement:\nOriginal: "{old_text}"\nMatched content: {matched_texts}\nReplacement rule: "{replace_rule.pattern}" -> "{replace_rule.content}"\nAfter replacement: "{message_text}"')
                    except re.error as e:
                        logger.error(f'Replacement rule format error: {replace_rule.pattern}, error: {str(e)}')

            # Update message text in context
            context.message_text = message_text
            context.check_message_text = message_text

            return True
        except Exception as e:
            logger.error(f'Error applying replacement rules: {str(e)}')
            context.errors.append(f"Replacement rule error: {str(e)}")
            return True  # Even if replacement fails, continue processing
        finally:
            # logger.info(f"After ReplaceFilter processing, context: {context.__dict__}")
            pass
