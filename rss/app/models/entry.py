from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class Media(BaseModel):
    """Media file information."""
    url: str
    type: str
    size: int = 0
    filename: str
    original_name: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        """Get an attribute value, returning the default if it doesn't exist."""
        return getattr(self, key, default)

class Entry(BaseModel):
    """RSS entry data model."""
    id: Optional[str] = None
    rule_id: int
    message_id: str
    title: str
    content: str
    published: str  # ISO-format datetime string
    author: str = ""
    link: str = ""
    media: List[Media] = []
    created_at: Optional[str] = None  # Time the entry was added to the system
    original_link: Optional[str] = None
    sender_info: Optional[str] = None


    def __init__(self, **data):
        # Process media data, ensuring it is a list of Media objects
        if "media" in data and isinstance(data["media"], list):
            media_list = []
            for item in data["media"]:
                try:
                    if isinstance(item, dict):
                        media_list.append(Media(**item))
                    elif not isinstance(item, Media):
                        # Try to convert to a dict
                        if hasattr(item, '__dict__'):
                            media_list.append(Media(**item.__dict__))
                    else:
                        media_list.append(item)
                except Exception as e:
                    # Ignore media items that cannot be converted
                    pass
            data["media"] = media_list

        # Ensure required fields have default values
        if "message_id" not in data and "id" in data:
            data["message_id"] = data["id"]

        # Call the parent initializer
        super().__init__(**data)
