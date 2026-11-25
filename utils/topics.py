"""Forum topic routing. 0 means unrestricted/default; 1 is General."""
import shlex
import secrets


def message_topic_id(message, is_forum=False):
    """Ordinary replies must never be mistaken for forum topics."""
    header = getattr(message, 'reply_to', None)
    if header and getattr(header, 'forum_topic', False):
        return (getattr(header, 'reply_to_top_id', None)
                or getattr(header, 'reply_to_msg_id', None) or 1)
    return 1 if is_forum else 0


def matches_topic(message, topic_id, is_forum=False):
    return not topic_id or message_topic_id(message, is_forum) == topic_id


def topic_reply_id(topic_id):
    # General has no topic-creation message to reply to.
    return topic_id if topic_id and topic_id != 1 else None


def forum_peer(chat_id):
    from telethon.tl.types import PeerChannel
    return PeerChannel(int(str(chat_id).removeprefix('-100')))


async def forward_to_topic(client, target_chat_id, messages, source_chat_id, topic_id):
    """Telethon 1.38's high-level forward_messages has no top_msg_id argument."""
    if not topic_id:
        return await client.forward_messages(target_chat_id, messages, source_chat_id)
    from telethon.tl.functions.messages import ForwardMessagesRequest
    message_ids = messages if isinstance(messages, list) else [messages]
    destination = await client.get_input_entity(forum_peer(target_chat_id))
    source = await client.get_input_entity(source_chat_id)
    return await client(ForwardMessagesRequest(
        from_peer=source, to_peer=destination, id=message_ids,
        random_id=[secrets.randbits(63) for _ in message_ids], top_msg_id=topic_reply_id(topic_id)
    ))


def endpoint_label(chat, topic_id, source=False):
    label = chat.name or chat.telegram_chat_id
    if topic_id:
        return f'{label} / {"General" if topic_id == 1 else "Topic " + str(topic_id)}'
    return f'{label} / 全部话题' if source else label


def parse_bind_args(text):
    """Keep quoted names; None distinguishes an omitted target topic from explicit 0."""
    args = shlex.split(text)[1:]
    chats, topics = [], {'--source-topic': 0, '--target-topic': None}
    seen = set()
    index = 0
    while index < len(args):
        arg = args[index]
        # Mobile smart punctuation can turn the leading "--" into a single dash.
        # Normalize only known option tokens, leaving chat names untouched.
        if arg.startswith(('—', '–')) and '--' + arg[1:] in topics:
            arg = '--' + arg[1:]
        if arg.startswith('--'):
            if arg not in topics or arg in seen:
                raise ValueError(f'未知或重复参数: {arg}')
            index += 1
            if index >= len(args) or not args[index].isascii() or not args[index].isdigit():
                raise ValueError(f'{arg} 需要非负整数话题 ID')
            value = int(args[index])
            if value > 2147483647:
                raise ValueError('话题 ID 超出范围')
            topics[arg] = value
            seen.add(arg)
        else:
            chats.append(arg)
        index += 1
    if len(chats) not in (1, 2):
        raise ValueError('请提供一个源聊天和可选的目标聊天')
    return chats[0], chats[1] if len(chats) == 2 else None, topics['--source-topic'], topics['--target-topic']


async def validate_topic(client, chat, topic_id, destination=False):
    if not topic_id:
        return
    if not getattr(chat, 'forum', False):
        raise ValueError('指定话题的聊天必须是已开启话题功能的超级群组')
    from telethon.tl.functions.channels import GetForumTopicsByIDRequest
    # The current chat can come from the bot session; resolve its access hash
    # using the user session before making a user-authenticated request.
    try:
        peer = await client.get_input_entity(forum_peer(chat.id))
    except ValueError:
        # A target omitted from /bind may only be cached by the bot session.
        async for _ in client.iter_dialogs():
            pass
        peer = await client.get_input_entity(forum_peer(chat.id))
    result = await client(GetForumTopicsByIDRequest(channel=peer, topics=[topic_id]))
    topic = next((t for t in result.topics if t.id == topic_id), None)
    if topic is None or not hasattr(topic, 'title'):
        raise ValueError(f'话题 {topic_id} 不存在或已删除')
    if destination and (getattr(topic, 'closed', False) or getattr(topic, 'hidden', False)):
        raise ValueError(f'目标话题 {topic_id} 已关闭或隐藏，请先打开话题')


def creates_route_cycle(rules, source_chat_id, source_topic_id, target_chat_id, target_topic_id):
    """Reject routes that can feed back into themselves, including wildcard sources."""
    pending = [(target_chat_id, target_topic_id or 1, bool(source_topic_id or target_topic_id))]
    visited = set()
    while pending:
        chat_id, topic_id, uses_topics = pending.pop()
        if (chat_id, topic_id, uses_topics) in visited:
            continue
        visited.add((chat_id, topic_id, uses_topics))
        if uses_topics and chat_id == source_chat_id and (not source_topic_id or source_topic_id == topic_id):
            return True
        for rule in rules:
            if rule.source_chat_id == chat_id and (not rule.source_topic_id or rule.source_topic_id == topic_id):
                pending.append((rule.target_chat_id, rule.target_topic_id or 1,
                                uses_topics or bool(rule.source_topic_id or rule.target_topic_id)))
    return False
