"""Select by rule ID, with a fallback for databases using source-chat selection."""
from models.models import Chat, ForwardRule


def selected_rule(session, chat):
    if chat.current_rule_id is not None:
        return session.query(ForwardRule).filter_by(id=chat.current_rule_id, target_chat_id=chat.id).first()
    if not chat.current_add_id:
        return None
    return (session.query(ForwardRule).join(Chat, ForwardRule.source_chat_id == Chat.id)
            .filter(ForwardRule.target_chat_id == chat.id, Chat.telegram_chat_id == chat.current_add_id)
            .order_by(ForwardRule.id).first())


def select_rule(chat, rule):
    chat.current_rule_id = rule.id
    chat.current_add_id = rule.source_chat.telegram_chat_id
