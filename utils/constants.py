import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Directory configuration
BASE_DIR = Path(__file__).parent.parent
TEMP_DIR = os.path.join(BASE_DIR, 'temp')

RSS_HOST = os.getenv('RSS_HOST', '127.0.0.1')
RSS_PORT = os.getenv('RSS_PORT', '8000')

# RSS base URL — if not set, uses the request URL
RSS_BASE_URL = os.environ.get('RSS_BASE_URL', None)

# RSS media base URL for generating media links — if not set, uses the request URL
RSS_MEDIA_BASE_URL = os.getenv('RSS_MEDIA_BASE_URL', '')

RSS_ENABLED = os.getenv('RSS_ENABLED', 'false')

RULES_PER_PAGE = int(os.getenv('RULES_PER_PAGE', 20))

PUSH_CHANNEL_PER_PAGE = int(os.getenv('PUSH_CHANNEL_PER_PAGE', 10))

DEFAULT_TIMEZONE = os.getenv('DEFAULT_TIMEZONE', 'Asia/Shanghai')
PROJECT_NAME = os.getenv('PROJECT_NAME', 'TG Forwarder RSS')
# RSS media path
RSS_MEDIA_PATH = os.getenv('RSS_MEDIA_PATH', './rss/media')

# Convert to absolute path
RSS_MEDIA_DIR = os.path.abspath(os.path.join(BASE_DIR, RSS_MEDIA_PATH)
                              if not os.path.isabs(RSS_MEDIA_PATH)
                              else RSS_MEDIA_PATH)

# RSS data path
RSS_DATA_PATH = os.getenv('RSS_DATA_PATH', './rss/data')
RSS_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, RSS_DATA_PATH)
                            if not os.path.isabs(RSS_DATA_PATH)
                            else RSS_DATA_PATH)

# Default AI model
DEFAULT_AI_MODEL = os.getenv('DEFAULT_AI_MODEL', 'gpt-4o')
# Default AI summary prompt
DEFAULT_SUMMARY_PROMPT = os.getenv('DEFAULT_SUMMARY_PROMPT', 'Please summarize the messages from this channel/group over the past 24 hours.')
# Default AI processing prompt
DEFAULT_AI_PROMPT = os.getenv('DEFAULT_AI_PROMPT', 'Please rewrite the following content in English, preserving the original meaning and formatting:')

# Pagination
MODELS_PER_PAGE = int(os.getenv('AI_MODELS_PER_PAGE', 10))
KEYWORDS_PER_PAGE = int(os.getenv('KEYWORDS_PER_PAGE', 50))

# Button layout
SUMMARY_TIME_ROWS = int(os.getenv('SUMMARY_TIME_ROWS', 10))
SUMMARY_TIME_COLS = int(os.getenv('SUMMARY_TIME_COLS', 6))

DELAY_TIME_ROWS = int(os.getenv('DELAY_TIME_ROWS', 10))
DELAY_TIME_COLS = int(os.getenv('DELAY_TIME_COLS', 6))

MEDIA_SIZE_ROWS = int(os.getenv('MEDIA_SIZE_ROWS', 10))
MEDIA_SIZE_COLS = int(os.getenv('MEDIA_SIZE_COLS', 6))

MEDIA_EXTENSIONS_ROWS = int(os.getenv('MEDIA_EXTENSIONS_ROWS', 6))
MEDIA_EXTENSIONS_COLS = int(os.getenv('MEDIA_EXTENSIONS_COLS', 6))

LOG_MAX_SIZE_MB = 10
LOG_BACKUP_COUNT = 3

# Default bot message auto-delete timeout (seconds)
BOT_MESSAGE_DELETE_TIMEOUT = int(os.getenv("BOT_MESSAGE_DELETE_TIMEOUT", 300))

# Auto-delete user command messages after processing
USER_MESSAGE_DELETE_ENABLE = os.getenv("USER_MESSAGE_DELETE_ENABLE", "false")

# Enable UFB (Universal Filter Bridge)
UFB_ENABLED = os.getenv("UFB_ENABLED", "false")

# Settings menu text
AI_SETTINGS_TEXT = """
Current AI prompt:

`{ai_prompt}`

Current summary prompt:

`{summary_prompt}`
"""

# Media settings text
MEDIA_SETTINGS_TEXT = """
Media settings:
"""
PUSH_SETTINGS_TEXT = """
Push notification settings:
See https://github.com/caronc/apprise/wiki for push configuration format
Example: `ntfy://ntfy.sh/your-topic-name`
"""


# Generate rule-specific paths
def get_rule_media_dir(rule_id):
    """Get the media directory for a specific rule"""
    rule_path = os.path.join(RSS_MEDIA_DIR, str(rule_id))
    os.makedirs(rule_path, exist_ok=True)
    return rule_path

def get_rule_data_dir(rule_id):
    """Get the data directory for a specific rule"""
    rule_path = os.path.join(RSS_DATA_DIR, str(rule_id))
    os.makedirs(rule_path, exist_ok=True)
    return rule_path