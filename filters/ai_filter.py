import logging
from filters.base_filter import BaseFilter
from filters.keyword_filter import KeywordFilter
from utils.common import check_keywords
from utils.common import get_main_module
from ai import get_ai_provider
from utils.constants import DEFAULT_AI_MODEL,DEFAULT_SUMMARY_PROMPT,DEFAULT_AI_PROMPT
from datetime import datetime, timedelta
import asyncio
import re

logger = logging.getLogger(__name__)

class AIFilter(BaseFilter):
    """
    AI处理过滤器，使用AI处理消息文本
    """
    
    async def _process(self, context):
        """
        使用AI处理消息文本
        
        Args:
            context: 消息上下文
            
        Returns:
            bool: 是否继续处理
        """
        rule = context.rule
        message_text = context.message_text
        original_message_text = context.original_message_text

        # logger.info(f"AIFilter处理消息前，context: {context.__dict__}")
        try:
            if not rule.is_ai:
                logger.info("AI处理未开启，返回原始消息")
                return True

            # 处理媒体组消息
            if context.is_media_group:
                logger.info(f"is_media_group: {context.is_media_group}")
            
            # 如果有消息文本，使用AI处理
            if original_message_text:
                try:
                    processed_text = await _ai_handle(message_text, rule)
                    context.message_text = processed_text
                    
                    # 如果需要在AI处理后再次检查关键字
                    if rule.is_keyword_after_ai:
                        should_forward = await check_keywords(rule, processed_text)
                        
                        if not should_forward:
                            logger.info('AI处理后的文本未通过关键字检查，取消转发')
                            context.should_forward = False
                            return False
                except Exception as e:
                    logger.error(f'AI处理消息时出错: {str(e)}')
                    context.errors.append(f"AI处理错误: {str(e)}")
                    # 即使AI处理失败，仍然继续处理
            return True 
        finally:
            # logger.info(f"AIFilter处理消息后，context: {context.__dict__}")
            pass


async def _ai_handle(message: str, rule) -> str:
    """使用AI处理消息
    
    Args:
        message: 原始消息文本
        rule: 转发规则对象，包含AI相关设置
        
    Returns:
        str: 处理后的消息文本
    """
    try:
        if not rule.is_ai:
            logger.info("AI处理未开启，返回原始消息")
            return message
        # 先读取数据库，如果ai模型为空，则使用.env中的默认模型
        if not rule.ai_model:
            rule.ai_model = DEFAULT_AI_MODEL
            logger.info(f"使用默认AI模型: {rule.ai_model}")
        else:
            logger.info(f"使用规则配置的AI模型: {rule.ai_model}")
            
        provider = await get_ai_provider(rule.ai_model)
        
        if not rule.ai_prompt:
            rule.ai_prompt = DEFAULT_AI_PROMPT
            logger.info("使用默认AI提示词")
        else:
            logger.info("使用规则配置的AI提示词")
        
        # 处理特殊提示词格式
        prompt = rule.ai_prompt
        if prompt:
            # 处理聊天记录提示词
            
            # 匹配源聊天和目标聊天的context格式
            source_context_match = re.search(r'\{source_message_context:(\d+)\}', prompt)
            target_context_match = re.search(r'\{target_message_context:(\d+)\}', prompt)
            # 匹配源聊天和目标聊天的time格式
            source_time_match = re.search(r'\{source_message_time:(\d+)\}', prompt)
            target_time_match = re.search(r'\{target_message_time:(\d+)\}', prompt)
            
            if any([source_context_match, target_context_match, source_time_match, target_time_match]):
                
                main = await get_main_module()
                client = main.user_client
                
                # 获取源聊天和目标聊天ID
                source_chat_id = int(rule.source_chat.telegram_chat_id)
                target_chat_id = int(rule.target_chat.telegram_chat_id)
                
                # 处理源聊天的消息获取
                if source_context_match:
                    count = int(source_context_match.group(1))
                    chat_history = await _get_chat_messages(client, source_chat_id, count=count)
                    prompt = prompt.replace(source_context_match.group(0), chat_history)
                    
                if source_time_match:
                    minutes = int(source_time_match.group(1))
                    chat_history = await _get_chat_messages(client, source_chat_id, minutes=minutes)
                    prompt = prompt.replace(source_time_match.group(0), chat_history)
                
                # 处理目标聊天的消息获取
                if target_context_match:
                    count = int(target_context_match.group(1))
                    chat_history = await _get_chat_messages(client, target_chat_id, count=count)
                    prompt = prompt.replace(target_context_match.group(0), chat_history)
                    
                if target_time_match:
                    minutes = int(target_time_match.group(1))
                    chat_history = await _get_chat_messages(client, target_chat_id, minutes=minutes)
                    prompt = prompt.replace(target_time_match.group(0), chat_history)
            
            # 替换消息占位符
            if '{Message}' in prompt:
                prompt = prompt.replace('{Message}', message)
                
        logger.info(f"处理后的AI提示词: {prompt}")
        processed_text = await provider.process_message(
            message=message,
            prompt=prompt,
            model=rule.ai_model
        )
        logger.info(f"AI处理完成: {processed_text}")
        return processed_text
        
    except Exception as e:
        logger.error(f"AI处理消息时出错: {str(e)}")
        return message  


async def _get_chat_messages(client, chat_id, minutes=None, count=None, delay_seconds: float = 0.5) -> str:
    """获取聊天记录
    
    Args:
        client: Telegram客户端
        chat_id: 聊天ID
        minutes: 获取最近几分钟的消息
        count: 获取最新的几条消息
        delay_seconds: 每条消息获取之间的延迟秒数，默认0.5秒
        
    Returns:
        str: 聊天记录文本
    """
    try:
        messages = []
        limit = count if count else 500  # 设置一个合理的默认值
        processed_count = 0
        
        if minutes:
            # 计算时间范围
            
            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=minutes)
            
            # 获取指定时间范围内的消息
            async for message in client.iter_messages(
                chat_id,
                limit=limit,
                offset_date=end_time,
                reverse=True
            ):
                if message.date < start_time:
                    break
                if message.text:
                    messages.append(message.text)
                    processed_count += 1
                    if processed_count % 20 == 0:  # 每处理20条消息休息一次
                        await asyncio.sleep(delay_seconds)
        else:
            # 获取指定数量的最新消息
            async for message in client.iter_messages(
                chat_id,
                limit=count
            ):
                if message.text:
                    messages.append(message.text)
                    processed_count += 1
                    if processed_count % 20 == 0:  # 每处理20条消息休息一次
                        await asyncio.sleep(delay_seconds)
                
        return "\n---\n".join(messages) if messages else ""
        
    except Exception as e:
        logger.error(f"获取聊天记录时出错: {str(e)}")
        return ""