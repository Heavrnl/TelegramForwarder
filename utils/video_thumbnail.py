import hashlib
import json
import logging
import os
import shutil
import subprocess
from typing import Optional

from telethon import functions, types, utils as telethon_utils

from utils.constants import TEMP_DIR

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def is_video_file(file_path: str) -> bool:
    return os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS


def build_send_file_video_kwargs(file_path: str) -> dict:
    if not is_video_file(file_path):
        return {}

    thumb_path = generate_video_thumbnail(file_path)
    kwargs = {
        "supports_streaming": True,
        "attributes": build_video_attributes(file_path),
    }
    if thumb_path:
        kwargs["thumb"] = thumb_path
    return kwargs


def cleanup_video_kwargs(kwargs: dict) -> None:
    thumb_path = kwargs.get("thumb") if kwargs else None
    if not thumb_path:
        return
    try:
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
    except OSError as e:
        logger.warning("删除视频缩略图失败 %s: %s", thumb_path, e)


async def send_album_with_video_thumbnails(client, entity, files, caption=None, parse_mode=None):
    """Send an album while binding generated thumbnails to every video item."""
    input_entity = await client.get_input_entity(entity)
    sent_messages = []

    for chunk_start in range(0, len(files), 10):
        media_items = []
        chunk = files[chunk_start:chunk_start + 10]

        for index, file_path in enumerate(chunk):
            global_index = chunk_start + index
            video_kwargs = build_send_file_video_kwargs(file_path)
            try:
                _, media, _ = await client._file_to_media(
                    file_path,
                    attributes=video_kwargs.get("attributes"),
                    supports_streaming=video_kwargs.get("supports_streaming", False),
                    thumb=video_kwargs.get("thumb"),
                    nosound_video=True,
                )

                if isinstance(media, (types.InputMediaUploadedPhoto, types.InputMediaPhotoExternal)):
                    uploaded = await client(functions.messages.UploadMediaRequest(
                        input_entity,
                        media=media,
                    ))
                    media = telethon_utils.get_input_media(uploaded.photo)
                elif isinstance(media, types.InputMediaUploadedDocument):
                    uploaded = await client(functions.messages.UploadMediaRequest(
                        input_entity,
                        media=media,
                    ))
                    media = telethon_utils.get_input_media(
                        uploaded.document,
                        supports_streaming=video_kwargs.get("supports_streaming", False),
                    )

                item_caption = caption if global_index == 0 else ""
                if item_caption:
                    item_caption, entities = await client._parse_message_text(item_caption, parse_mode)
                else:
                    entities = None

                media_items.append(types.InputSingleMedia(
                    media=media,
                    message=item_caption or "",
                    entities=entities,
                ))
            finally:
                cleanup_video_kwargs(video_kwargs)

        request = functions.messages.SendMultiMediaRequest(
            input_entity,
            multi_media=media_items,
        )
        result = await client(request)
        random_ids = [media.random_id for media in media_items]
        response = client._get_response_message(random_ids, result, input_entity)
        if isinstance(response, list):
            sent_messages.extend(response)
        else:
            sent_messages.append(response)

    return sent_messages


def build_video_attributes(file_path: str) -> list:
    metadata = get_video_metadata(file_path)
    if not metadata:
        return []

    return [types.DocumentAttributeVideo(
        duration=metadata["duration"],
        w=metadata["width"],
        h=metadata["height"],
        supports_streaming=True,
    )]


def get_video_metadata(file_path: str) -> Optional[dict]:
    if not shutil.which("ffprobe"):
        logger.warning("未找到 ffprobe，视频缩略图可能被 Telegram 忽略")
        return None

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration:format=duration",
        "-of",
        "json",
        file_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        duration = stream.get("duration") or data.get("format", {}).get("duration") or 0
        width = int(stream.get("width") or 1)
        height = int(stream.get("height") or 1)
        return {
            "duration": int(float(duration) or 0),
            "width": width,
            "height": height,
        }
    except Exception as e:
        logger.warning("读取视频元数据失败 %s: %s", file_path, e)
        return None


def generate_video_thumbnail(file_path: str) -> Optional[str]:
    if not shutil.which("ffmpeg"):
        logger.warning("未找到 ffmpeg，视频将使用 Telegram 默认预览")
        return None

    digest = hashlib.sha256(file_path.encode("utf-8", errors="ignore")).hexdigest()[:16]
    os.makedirs(TEMP_DIR, exist_ok=True)

    for offset in ("00:00:01", "00:00:02", "00:00:05", "00:00:10"):
        for quality in ("5", "7", "9"):
            thumb_path = os.path.join(
                TEMP_DIR,
                f"thumb_{digest}_{offset.replace(':', '')}_q{quality}.jpg",
            )
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                offset,
                "-i",
                file_path,
                "-frames:v",
                "1",
                "-vf",
                "scale=320:320:force_original_aspect_ratio=decrease",
                "-q:v",
                quality,
                thumb_path,
            ]
            try:
                subprocess.run(cmd, check=True, timeout=20)
                if os.path.exists(thumb_path):
                    thumb_size = os.path.getsize(thumb_path)
                    if 1024 < thumb_size <= 20 * 1024:
                        return thumb_path
            except Exception as e:
                logger.warning("生成视频缩略图失败 %s offset=%s q=%s: %s", file_path, offset, quality, e)

            try:
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
            except OSError:
                pass

    return None
