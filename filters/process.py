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
    Process forwarding rule

    Args:
        client: Bot client
        event: Message event
        chat_id: Chat ID
        rule: Forwarding rule

    Returns:
        bool: Whether processing was successful
    """
    logger.info(f'Processing rule with filter chain, ID: {rule.id}')

    # Create filter chain
    filter_chain = FilterChain()

    # Add initialization filter
    filter_chain.add_filter(InitFilter())

    # Delay processing filter (if delay processing is enabled)
    filter_chain.add_filter(DelayFilter())

    # Add keyword filter (if the message doesn't match keywords, it will interrupt the processing chain)
    filter_chain.add_filter(KeywordFilter())

    # Add replace filter
    filter_chain.add_filter(ReplaceFilter())

    # Add media filter (process media content)
    filter_chain.add_filter(MediaFilter())

    # Add AI processing filter (if keyword check after AI processing is enabled, it may interrupt the processing chain)
    filter_chain.add_filter(AIFilter())

    # Add info filter (process original link and sender information)
    filter_chain.add_filter(InfoFilter())

    # Add comment section button filter
    filter_chain.add_filter(CommentButtonFilter())

    # Add RSS filter
    filter_chain.add_filter(RSSFilter())

    # Add edit filter (edit original message)
    filter_chain.add_filter(EditFilter())

    # Add sender filter (send message)
    filter_chain.add_filter(SenderFilter())

    # Add reply filter (handle comment section buttons for media group messages)
    filter_chain.add_filter(ReplyFilter())

    # Add push filter
    filter_chain.add_filter(PushFilter())

    # Add delete original message filter (executed last)
    filter_chain.add_filter(DeleteOriginalFilter())

    # Execute filter chain
    result = await filter_chain.process(client, event, chat_id, rule)

    return result
