import logging
from filters.filter_chain import FilterChain
from filters.keyword_filter import KeywordFilter
from filters.replace_filter import ReplaceFilter
from filters.ai_filter import AIFilter
from filters.info_filter import InfoFilter
from filters.media_filter import MediaFilter
from filters.sender_filter import SenderFilter
from filters.delete_original_filter import DeleteOriginalFilter
from filters.delay_filter import DelayFilter
from filters.edit_filter import EditFilter
from filters.comment_button_filter import CommentButtonFilter
from filters.init_filter import InitFilter
from filters.reply_filter import ReplyFilter
from filters.rss_filter import RSSFilter
from filters.push_filter import PushFilter
logger = logging.getLogger(__name__)

async def process_forward_rule(client, event, chat_id, rule):
    """
    Process a forwarding rule.

    Args:
        client: bot client
        event: message event
        chat_id: chat ID
        rule: forwarding rule

    Returns:
        bool: whether processing succeeded
    """
    logger.info(f'Processing rule ID: {rule.id} using filter chain')

    # Create the filter chain
    filter_chain = FilterChain()

    # Add the initialization filter
    filter_chain.add_filter(InitFilter())

    # Delay filter (if delay processing is enabled)
    filter_chain.add_filter(DelayFilter())

    # Add the keyword filter (breaks the chain if the message doesn't match keywords)
    filter_chain.add_filter(KeywordFilter())

    # Add the replace filter
    filter_chain.add_filter(ReplaceFilter())

    # Add the media filter (handles media content)
    filter_chain.add_filter(MediaFilter())

    # Add the AI filter (may break the chain if keyword check after AI processing fails)
    filter_chain.add_filter(AIFilter())

    # Add the info filter (handles original link and sender info)
    filter_chain.add_filter(InfoFilter())

    # Add the comment button filter
    filter_chain.add_filter(CommentButtonFilter())

    # Add the RSS filter
    filter_chain.add_filter(RSSFilter())

    # Add the edit filter (edits the original message)
    filter_chain.add_filter(EditFilter())

    # Add the sender filter (sends the message)
    filter_chain.add_filter(SenderFilter())

    # Add the reply filter (handles comment buttons for media group messages)
    filter_chain.add_filter(ReplyFilter())

    # Add the push filter
    filter_chain.add_filter(PushFilter())

    # Add the delete-original filter (runs last)
    filter_chain.add_filter(DeleteOriginalFilter())

    # Execute the filter chain
    result = await filter_chain.process(client, event, chat_id, rule)

    return result
