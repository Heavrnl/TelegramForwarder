import asyncio
import os
import logging
from functools import wraps
from utils.constants import BOT_MESSAGE_DELETE_TIMEOUT, USER_MESSAGE_DELETE_ENABLE
logger = logging.getLogger(__name__)

# 从环境变量获取默认超时时间

async def delete_after(message, seconds):
    """等待指定秒数后删除消息
    
    参数:
        message: 要删除的消息
        seconds: 等待多少秒后删除, 0表示立即删除, -1表示不删除
    """
    if seconds == -1:  # -1 表示不删除
        return
    
    if seconds > 0:  # 正数表示等待指定秒数再删除
        await asyncio.sleep(seconds)
        
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"删除消息失败: {e}")

async def reply_and_delete(event, text, delete_after_seconds=None, **kwargs):
    """回复消息并安排自动删除
    
    参数:
        event: Telethon事件对象
        text: 要发送的文本
        delete_after_seconds: 多少秒后删除消息，None使用默认值，0表示立即删除，-1表示不删除
        **kwargs: 传递给reply方法的其他参数
    """
    # 如果没有指定删除时间，使用环境变量中的默认值
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds
    
    # 发送回复
    message = await event.reply(text, **kwargs)
    
    # 安排删除任务，只有当deletion_timeout不等于-1时才删除
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))
    
    return message

async def respond_and_delete(event, text, delete_after_seconds=None, **kwargs):
    """使用respond回复消息并安排自动删除
    
    参数:
        event: Telethon事件对象
        text: 要发送的文本
        delete_after_seconds: 多少秒后删除消息，None使用默认值，0表示立即删除，-1表示不删除
        **kwargs: 传递给respond方法的其他参数
    """
    # 如果没有指定删除时间，使用环境变量中的默认值
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds
    
    # 发送回复
    message = await event.respond(text, **kwargs)
    
    # 安排删除任务，只有当deletion_timeout不等于-1时才删除
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))
    
    return message

async def send_message_and_delete(client, entity, text, delete_after_seconds=None, **kwargs):
    """发送消息并安排自动删除
    
    参数:
        client: Telethon客户端对象
        entity: 聊天对象或ID
        text: 要发送的文本
        delete_after_seconds: 多少秒后删除消息，None使用默认值，0表示立即删除，-1表示不删除
        **kwargs: 传递给send_message方法的其他参数
    """
    # 如果没有指定删除时间，使用环境变量中的默认值
    if delete_after_seconds is None:
        deletion_timeout = BOT_MESSAGE_DELETE_TIMEOUT
    else:
        deletion_timeout = delete_after_seconds
    
    # 发送消息
    message = await client.send_message(entity, text, **kwargs)
    
    # 安排删除任务，只有当deletion_timeout不等于-1时才删除
    if deletion_timeout != -1:
        asyncio.create_task(delete_after(message, deletion_timeout))
    
    return message

# 删除用户消息
async def async_delete_user_message(client, chat_id, message_id, seconds):
    """删除用户消息
    
    参数:
        client: bot客户端
        chat_id: 聊天ID
        message_id: 消息ID
        seconds: 等待多少秒后删除, 0表示立即删除, -1表示不删除
    """
    if USER_MESSAGE_DELETE_ENABLE == "false":
        return
    
    if seconds == -1:  # -1 表示不删除
        return
        
    if seconds > 0:  # 正数表示等待指定秒数再删除
        await asyncio.sleep(seconds)
        
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.error(f"删除用户消息失败: {e}")

