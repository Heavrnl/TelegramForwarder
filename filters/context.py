import copy

class MessageContext:
    """
    Message context class, contains all information needed for processing messages
    """

    def __init__(self, client, event, chat_id, rule):
        """
        Initialize message context

        Args:
            client: Bot client
            event: Message event
            chat_id: Chat ID
            rule: Forwarding rule
        """
        self.client = client
        self.event = event
        self.chat_id = chat_id
        self.rule = rule

        # Initial message text, kept unchanged for reference
        self.original_message_text = event.message.text or ''

        # Current processed message text
        self.message_text = event.message.text or ''

        # Message text for checking (may include sender info, etc.)
        self.check_message_text = event.message.text or ''

        # Record media files during processing
        self.media_files = []

        # Record sender information
        self.sender_info = ''

        # Record time information
        self.time_info = ''

        # Original link
        self.original_link = ''

        # Buttons
        self.buttons = event.message.buttons if hasattr(event.message, 'buttons') else None

        # Whether to continue processing
        self.should_forward = True

        # Used to record media group messages
        self.is_media_group = event.message.grouped_id is not None
        self.media_group_id = event.message.grouped_id
        self.media_group_messages = []

        # Used to track skipped oversized media
        self.skipped_media = []

        # Record any possible errors
        self.errors = []

        # Record forwarded messages
        self.forwarded_messages = []

        # Comment section link
        self.comment_link = None

    def clone(self):
        """Create a copy of the context"""
        return copy.deepcopy(self)
