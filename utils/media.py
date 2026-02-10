import logging
import os

logger = logging.getLogger(__name__)

async def get_media_size(media):
    """Get media file size"""
    if not media:
        return 0

    try:
        # For all types of media, first try to get the document
        if hasattr(media, 'document') and media.document:
            return media.document.size

        # For photos, get the largest size
        if hasattr(media, 'photo') and media.photo:
            # Get the photo with the largest size
            largest_photo = max(media.photo.sizes, key=lambda x: x.size if hasattr(x, 'size') else 0)
            return largest_photo.size if hasattr(largest_photo, 'size') else 0

        # If it's another type, try to directly get the size attribute
        if hasattr(media, 'size'):
            return media.size

    except Exception as e:
        logger.error(f'Error getting media size: {str(e)}')

    return 0

async def get_max_media_size():
    """Get media file size upper limit"""
    max_media_size_str = os.getenv('MAX_MEDIA_SIZE')
    if not max_media_size_str:
        logger.error('MAX_MEDIA_SIZE environment variable is not set')
        raise ValueError('MAX_MEDIA_SIZE must be set in the .env file')
    return float(max_media_size_str) * 1024 * 1024  # Convert to bytes, supports decimals
