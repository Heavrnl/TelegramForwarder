import enum

# Four modes: blacklist only, whitelist only, blacklist then whitelist, whitelist then blacklist
class ForwardMode(enum.Enum):
    WHITELIST = 'whitelist'
    BLACKLIST = 'blacklist'
    BLACKLIST_THEN_WHITELIST = 'blacklist_then_whitelist'
    WHITELIST_THEN_BLACKLIST = 'whitelist_then_blacklist'


class PreviewMode(enum.Enum):
    ON = 'on'
    OFF = 'off'
    FOLLOW = 'follow'  # Follow the preview setting of the original message

class MessageMode(enum.Enum):
    MARKDOWN = 'Markdown'
    HTML = 'HTML' 

class AddMode(enum.Enum):
    WHITELIST = 'whitelist'
    BLACKLIST = 'blacklist'

class HandleMode(enum.Enum):
    FORWARD = 'FORWARD'
    EDIT = 'EDIT'