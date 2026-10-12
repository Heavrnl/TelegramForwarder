import os
from dotenv import load_dotenv
from pathlib import Path
import logging
import sys
from utils.constants import RSS_HOST, RSS_PORT,DEFAULT_TIMEZONE,PROJECT_NAME
# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

# Import unified constants
from utils.constants import RSS_MEDIA_DIR, RSS_MEDIA_PATH, RSS_DATA_DIR, get_rule_media_dir, get_rule_data_dir

# Load environment variables
load_dotenv()

class Settings:
    PROJECT_NAME: str = PROJECT_NAME
    HOST: str = RSS_HOST
    PORT: int = RSS_PORT
    TIMEZONE: str = DEFAULT_TIMEZONE
    # Data storage paths
    BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
    DATA_PATH = RSS_DATA_DIR

    # Use unified media path constants
    RSS_MEDIA_PATH = RSS_MEDIA_PATH
    MEDIA_PATH = RSS_MEDIA_DIR


    # Methods to get rule-specific paths
    @classmethod
    def get_rule_media_path(cls, rule_id):
        """Get the media directory for a specific rule."""
        return get_rule_media_dir(rule_id)

    @classmethod
    def get_rule_data_path(cls, rule_id):
        """Get the data directory for a specific rule."""
        return get_rule_data_dir(rule_id)

    # Ensure directories exist
    def __init__(self):
        os.makedirs(self.DATA_PATH, exist_ok=True)
        os.makedirs(self.MEDIA_PATH, exist_ok=True)
        logger = logging.getLogger(__name__)
        logger.info(f"RSS data path: {self.DATA_PATH}")
        logger.info(f"RSS media path: {self.MEDIA_PATH}")

settings = Settings()
