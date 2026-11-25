import logging
import asyncio
from telethon import Button
from filters.base_filter import BaseFilter
from utils.common import get_main_module
from utils.topics import forum_peer
import traceback
logger = logging.getLogger(__name__)

class ReplyFilter(BaseFilter):
    """
    回复过滤器，用于处理媒体组消息的评论区按钮
    由于媒体组消息无法直接添加按钮，此过滤器会使用bot回复已转发的消息，并添加评论区按钮
    """
    
    async def _process(self, context):
        """
        处理媒体组消息的评论区按钮
        
        Args:
            context: 消息上下文
            
        Returns:
            bool: 是否继续处理
        """
        try:
            # 如果规则不存在或未启用评论按钮功能，直接跳过
            if not context.rule or not context.rule.enable_comment_button:
                return True
                
            # 只处理媒体组消息
            if not context.is_media_group:
                return True
                
            # 检查是否有评论区链接和已转发的消息
            if not context.comment_link or not context.forwarded_messages:
                logger.info("没有评论区链接或已转发消息，无法添加评论区按钮回复")
                return True
                
            # 使用bot客户端（context.client）
            client = context.client
            
            # 获取目标聊天信息
            rule = context.rule
            target_chat = rule.target_chat
            target_chat_id = int(target_chat.telegram_chat_id)
            if rule.target_topic_id:
                target_chat_id = forum_peer(target_chat_id)
            
            # 获取已转发的第一条消息ID
            first_forwarded_msg = context.forwarded_messages[0]
            
            # 创建评论区按钮
            comment_button = Button.url("💬 查看评论区", context.comment_link)
            buttons = [[comment_button]]
            
            # 回复已转发的媒体组消息
            logger.info(f"正在使用Bot给已转发的媒体组消息 {first_forwarded_msg.id} 发送评论区按钮回复")
            
            # 发送回复消息，附带评论区按钮
            await client.send_message(
                entity=target_chat_id,
                message="💬 评论区",
                buttons=buttons,
                reply_to=first_forwarded_msg.id,
            )
            logger.info("成功发送评论区按钮回复")
                
            return True
            
        except Exception as e:
            logger.error(f"ReplyFilter处理消息时出错: {str(e)}")

            logger.error(traceback.format_exc())
            return True
