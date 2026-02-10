import json
import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..models.entry import Entry
from ..core.config import settings

logger = logging.getLogger(__name__)

# Ensure data storage directory exists
def ensure_storage_exists():
    """Ensure data storage directory exists"""
    entries_dir = Path(settings.DATA_PATH)
    entries_dir.mkdir(parents=True, exist_ok=True)

# Get the entry storage file path for a rule
def get_rule_entries_path(rule_id: int) -> Path:
    """Get the entry storage file path for a rule"""
    # Use rule-specific data directory
    rule_data_path = settings.get_rule_data_path(rule_id)
    return Path(rule_data_path) / "entries.json"

async def get_entries(rule_id: int, limit: int = 100, offset: int = 0) -> List[Entry]:
    """Get entries for a rule"""
    try:
        file_path = get_rule_entries_path(rule_id)

        # If file does not exist, return empty list
        if not file_path.exists():
            return []

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)

        # Convert data to Entry objects
        entries = [Entry(**entry) for entry in data]

        # Sort by publish time (newest first)
        entries.sort(key=lambda x: x.published, reverse=True)

        # Apply pagination
        return entries[offset:offset + limit]
    except Exception as e:
        logger.error(f"Error getting entries: {str(e)}")
        return []

async def create_entry(entry: Entry) -> bool:
    """Create a new entry"""
    try:
        # Set entry ID and creation time
        if not entry.id:
            entry.id = str(uuid.uuid4())

        entry.created_at = datetime.now().isoformat()

        # Get entries for the rule
        file_path = get_rule_entries_path(entry.rule_id)

        entries = []
        # If file already exists, read existing entries
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    entries = json.load(file)
                except json.JSONDecodeError:
                    logger.warning(f"Error parsing entry file, will create new file: {file_path}")
                    entries = []

        # Convert Entry object to dictionary and add to list
        entries.append(entry.dict())

        # Get RSS configuration for the rule to get maximum entry count
        try:
            from models.models import get_session, RSSConfig
            session = get_session()
            rss_config = session.query(RSSConfig).filter(RSSConfig.rule_id == entry.rule_id).first()
            max_items = rss_config.max_items if rss_config and hasattr(rss_config, 'max_items') else 50
            session.close()
        except Exception as e:
            logger.warning(f"Failed to get RSS configuration, using default maximum entry count (50): {str(e)}")
            max_items = 50

        # Limit entry count, keep the most recent N entries
        if len(entries) > max_items:
            # Sort by publish time (newest first)
            entries.sort(key=lambda x: x.get('published', ''), reverse=True)
            entries = entries[:max_items]

        # Save to file
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(entries, file, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        logger.error(f"Error creating entry: {str(e)}")
        return False

async def update_entry(rule_id: int, entry_id: str, updated_data: Dict[str, Any]) -> bool:
    """Update an entry"""
    try:
        file_path = get_rule_entries_path(rule_id)

        # If file does not exist, return False
        if not file_path.exists():
            return False

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as file:
            entries = json.load(file)

        # Find and update the entry
        found = False
        for i, entry in enumerate(entries):
            if entry.get('id') == entry_id:
                entries[i].update(updated_data)
                found = True
                break

        if not found:
            return False

        # Save to file
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(entries, file, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        logger.error(f"Error updating entry: {str(e)}")
        return False

async def delete_entry(rule_id: int, entry_id: str) -> bool:
    """Delete an entry"""
    try:
        file_path = get_rule_entries_path(rule_id)

        # If file does not exist, return False
        if not file_path.exists():
            return False

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as file:
            entries = json.load(file)

        # Find and delete the entry
        original_length = len(entries)
        entries = [entry for entry in entries if entry.get('id') != entry_id]

        if len(entries) == original_length:
            return False  # No entry with the corresponding ID found

        # Save to file
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(entries, file, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        logger.error(f"Error deleting entry: {str(e)}")
        return False
