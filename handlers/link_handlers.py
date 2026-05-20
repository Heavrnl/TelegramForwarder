import re
import os
import logging
from utils.common import get_main_module, get_user_id
from utils.constants import TEMP_DIR
from utils.video_thumbnail import (
    build_send_file_video_kwargs,
    cleanup_video_kwargs,
    is_video_file,
    send_album_with_video_thumbnails,
)

logger = logging.getLogger(__name__)

async def handle_message_link(client, event):
    """处理 Telegram 消息链接"""
    if not event.message.text:
        return

    # 解析消息链接
    match = re.match(r'https?://t\.me/(?:c/(\d+)|([^/]+))/(\d+)', event.message.text)
    if not match:
        return

    try:
        chat_id = None
        message_id = int(match.group(3))

        if match.group(1):  # 私有频道格式
            chat_id = int('-100' + match.group(1))
        else:  # 公开频道格式
            chat_name = match.group(2)
            try:
                entity = await client.get_entity(chat_name)
                chat_id = entity.id
            except Exception as e:
                logger.error(f'获取频道信息失败: {str(e)}')
                await reply_and_delete(event,'⚠️ 无法访问该频道，请确保已关注该频道。')
                return

        # 获取用户客户端
        main = await get_main_module()
        user_client = main.user_client

        # 获取原始消息
        message = await user_client.get_messages(chat_id, ids=message_id)
        if not message:
            await reply_and_delete(event,'⚠️ 无法获取该消息，可能是消息已被删除或无权限访问。')
            return

        # 检查是否是媒体组消息
        if message.grouped_id:
            await handle_media_group(client, user_client, chat_id, message, event)
        else:
            await handle_single_message(client, message, event)


    except Exception as e:
        logger.error(f'处理消息链接时出错: {str(e)}')
        await reply_and_delete(event,'⚠️ 处理消息时出错，请确保链接正确且有权限访问该消息。')

async def handle_media_group(client, user_client, chat_id, message, event):
    """处理媒体组消息"""
    files = []  # 将 files 移到外层作用域
    try:
        # 收集媒体组的所有消息
        media_group_messages = []
        caption = None
        buttons = None
        
        # 在消息ID前后范围内搜索同组消息
        async for grouped_message in user_client.iter_messages(
            chat_id,
            limit=20,
            min_id=message.id - 10,
            max_id=message.id + 10
        ):
            if grouped_message.grouped_id == message.grouped_id:
                media_group_messages.append(grouped_message)
                # 保存第一条消息的文本和按钮
                if not caption:
                    caption = grouped_message.text
                    buttons = grouped_message.buttons if hasattr(grouped_message, 'buttons') else None

        if media_group_messages:
            # 下载所有媒体文件
            for msg in media_group_messages:
                if msg.media:
                    try:
                        file_path = await msg.download_media(TEMP_DIR)
                        if file_path:
                            files.append(file_path)
                            logger.info(f'已下载媒体文件: {file_path}')
                    except Exception as e:
                        logger.error(f'下载媒体文件失败: {str(e)}')

            if files:
                if any(is_video_file(file_path) for file_path in files):
                    await send_album_with_video_thumbnails(
                        client,
                        event.chat_id,
                        files,
                        caption=caption,
                        parse_mode='Markdown',
                    )
                else:
                    # 发送媒体组
                    await client.send_file(
                        event.chat_id,
                        files,
                        caption=caption,
                        parse_mode='Markdown',
                        buttons=buttons
                    )
                logger.info(f'已转发媒体组消息，共 {len(files)} 个文件')

    except Exception as e:
        logger.error(f'处理媒体组消息时出错: {str(e)}')
        raise
    finally:
        # 确保清理所有临时文件
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f'已删除临时文件: {file_path}')
            except Exception as e:
                logger.error(f'删除临时文件失败 {file_path}: {str(e)}')

async def handle_single_message(client, message, event):
    """处理单条消息"""
    parse_mode = 'Markdown'
    buttons = message.buttons if hasattr(message, 'buttons') else None
    file_path = None
    video_kwargs = {}

    try:
        if message.media:
            # 处理媒体消息
            file_path = await message.download_media(TEMP_DIR)
            if file_path:
                logger.info(f'已下载媒体文件: {file_path}')
                caption = message.text if message.text else ''
                video_kwargs = build_send_file_video_kwargs(file_path)
                await client.send_file(
                    event.chat_id,
                    file_path,
                    caption=caption,
                    parse_mode=parse_mode,
                    buttons=buttons,
                    **video_kwargs
                )
                logger.info('已转发单条媒体消息')
        else:
            # 处理纯文本消息
            await client.send_message(
                event.chat_id,
                message.text,
                parse_mode=parse_mode,
                link_preview=True,
                buttons=buttons
            )
            logger.info('已转发文本消息')

    except Exception as e:
        logger.error(f'处理单条消息时出错: {str(e)}')
        raise
    finally:
        # 确保清理临时文件
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f'已删除临时文件: {file_path}')
            except Exception as e:
                logger.error(f'删除临时文件失败 {file_path}: {str(e)}')
        cleanup_video_kwargs(video_kwargs)
