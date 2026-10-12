import copy

class MessageContext:
    """
    Message context class — holds all information needed to process a message.
    """

    def __init__(self, client, event, chat_id, rule):
        """
        Initialize the message context.

        Args:
            client: bot client
            event: message event
            chat_id: chat ID
            rule: forwarding rule
        """
        self.client = client
        self.event = event
        self.chat_id = chat_id
        self.rule = rule

        # Original message text, kept unchanged for reference
        self.original_message_text = event.message.text or ''

        # Current message text being processed
        self.message_text = event.message.text or ''

        # Message text used for keyword checking (may include sender info, etc.)
        self.check_message_text = event.message.text or ''

        # Media files collected during processing
        self.media_files = []

        # Source messages carrying media, forwarded by reference (no download)
        self.media_messages = []

        # Sender information
        self.sender_info = ''

        # Time information
        self.time_info = ''

        # Original message link
        self.original_link = ''

        # Buttons
        self.buttons = event.message.buttons if hasattr(event.message, 'buttons') else None

        # Whether to continue forwarding
        self.should_forward = True

        # Media group tracking
        self.is_media_group = event.message.grouped_id is not None
        self.media_group_id = event.message.grouped_id
        self.media_group_messages = []

        # Oversized media that was skipped
        self.skipped_media = []

        # Any errors that occurred during processing
        self.errors = []

        # Forwarded messages
        self.forwarded_messages = []

        # Comment section link
        self.comment_link = None

    def clone(self):
        """Create a deep copy of the context."""
        return copy.deepcopy(self)
