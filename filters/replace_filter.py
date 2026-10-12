import logging
import re
from filters.base_filter import BaseFilter

logger = logging.getLogger(__name__)

class ReplaceFilter(BaseFilter):
    """
    Replace filter — replaces message text according to the rule's replacement settings.
    """

    async def _process(self, context):
        """
        Apply text replacement to the message.

        Args:
            context: message context

        Returns:
            bool: whether to continue processing
        """
        rule = context.rule
        message_text = context.message_text

        # Print all attributes of context
        # logger.info(f"ReplaceFilter before processing, context: {context.__dict__}")
        # If no replacement is needed, return immediately
        if not rule.is_replace or not message_text:
            return True

        try:
            # Apply all replacement rules
            for replace_rule in rule.replace_rules:
                if replace_rule.pattern == '.*':
                    # Full-text replacement
                    logger.info(f'Full-text replacement:\nOriginal: "{message_text}"\nReplaced with: "{replace_rule.content or ""}"')
                    message_text = replace_rule.content or ''
                    break  # Stop processing further rules after a full-text replacement
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
                            logger.info(f'Partial replacement:\nOriginal: "{old_text}"\nMatched: {matched_texts}\nRule: "{replace_rule.pattern}" -> "{replace_rule.content}"\nResult: "{message_text}"')
                    except re.error as e:
                        logger.error(f'Invalid replacement rule pattern: {replace_rule.pattern}, error: {str(e)}')

            # Update message text in the context
            context.message_text = message_text
            context.check_message_text = message_text

            return True
        except Exception as e:
            logger.error(f'Error applying replacement rules: {str(e)}')
            context.errors.append(f"Replacement rule error: {str(e)}")
            return True  # Continue processing even if replacement fails
        finally:
            # logger.info(f"ReplaceFilter after processing, context: {context.__dict__}")
            pass
