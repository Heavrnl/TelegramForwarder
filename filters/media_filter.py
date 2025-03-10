import logging
import os
import asyncio
from utils.media import get_media_size
from utils.constants import TEMP_DIR
from filters.base_filter import BaseFilter
from utils.media import get_max_media_size
from enums.enums import PreviewMode
from models.models import MediaTypes
from models.models import get_session
from sqlalchemy import text
from utils.common import get_db_ops
from enums.enums import AddMode
logger = logging.getLogger(__name__)

class MediaFilter(BaseFilter):
    """
    媒体过滤器，处理消息中的媒体内容
    """
    
    async def _process(self, context):
        """
        处理媒体内容
        
        Args:
            context: 消息上下文
            
        Returns:
            bool: 是否继续处理
        """
        # 确保临时目录存在
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        rule = context.rule
        event = context.event
        client = context.client
        
        
        # 如果是媒体组消息
        if event.message.grouped_id:
            await self._process_media_group(context)
        else:
            await self._process_single_media(context)
        
        return True
    
    async def _process_media_group(self, context):
        """处理媒体组消息"""
        event = context.event
        rule = context.rule
        client = context.client
        
        logger.info(f'处理媒体组消息 组ID: {event.message.grouped_id}')
        
        # 等待更长时间让所有媒体消息到达
        await asyncio.sleep(1)
        
        # 获取媒体类型设置
        media_types = None
        if rule.enable_media_type_filter:
            session = get_session()
            try:
                media_types = session.query(MediaTypes).filter_by(rule_id=rule.id).first()
            finally:
                session.close()
        
        # 收集媒体组的所有消息
        total_media_count = 0  # 总媒体数量
        blocked_media_count = 0  # 被屏蔽的媒体数量
        try:
            async for message in event.client.iter_messages(
                event.chat_id,
                limit=20,
                min_id=event.message.id - 10,
                max_id=event.message.id + 10
            ):
                if message.grouped_id == event.message.grouped_id:
                    if message.media:
                        total_media_count += 1
                        # 检查媒体类型
                        if rule.enable_media_type_filter and media_types and message.media:
                            if await self._is_media_type_blocked(message.media, media_types):
                                logger.info(f'媒体类型被屏蔽，跳过消息 ID={message.id}')
                                blocked_media_count += 1
                                continue
                        
                        # 检查媒体扩展名
                        if rule.enable_extension_filter and message.media:
                            if not await self._is_media_extension_allowed(rule, message.media):
                                logger.info(f'媒体扩展名被屏蔽，跳过消息 ID={message.id}')
                                blocked_media_count += 1
                                continue
                    
                    # 检查媒体大小
                    if message.media:
                        file_size = await get_media_size(message.media)
                        file_size = round(file_size/1024/1024, 2)  # 转换为MB
                        logger.info(f'媒体文件大小: {file_size}MB')
                        logger.info(f'规则最大媒体大小: {rule.max_media_size}MB')
                        logger.info(f'是否启用媒体大小过滤: {rule.enable_media_size_filter}')
                        logger.info(f'是否发送媒体大小超限提醒: {rule.is_send_over_media_size_message}')
                        
                        if rule.max_media_size and (file_size > rule.max_media_size) and rule.enable_media_size_filter:
                            file_name = ''
                            if hasattr(message.media, 'document') and message.media.document:
                                for attr in message.media.document.attributes:
                                    if hasattr(attr, 'file_name'):
                                        file_name = attr.file_name
                                        break
                            logger.info(f'媒体文件 {file_name} 超过大小限制 ({rule.max_media_size}MB)')
                            context.skipped_media.append((message, file_size, file_name))
                            continue
                    
                    context.media_group_messages.append(message)
                    logger.info(f'找到媒体组消息: ID={message.id}, 类型={type(message.media).__name__ if message.media else "无媒体"}')
        except Exception as e:
            logger.error(f'收集媒体组消息时出错: {str(e)}')
            context.errors.append(f"收集媒体组消息错误: {str(e)}")
        
        logger.info(f'共找到 {len(context.media_group_messages)} 条媒体组消息，{len(context.skipped_media)} 条超限')
        
        # 如果所有媒体都被屏蔽，设置不转发
        if total_media_count > 0 and total_media_count == blocked_media_count:
            logger.info('媒体组中所有媒体都被屏蔽，设置不转发')
            context.should_forward = False
            return True
            
        # 如果所有媒体都超限且不发送超限提醒，则设置不转发
        if len(context.skipped_media) > 0 and len(context.media_group_messages) == 0 and not rule.is_send_over_media_size_message:
            context.should_forward = False
            logger.info('所有媒体都超限且不发送超限提醒，设置不转发')
    
    async def _process_single_media(self, context):
        """处理单条媒体消息"""
        event = context.event
        rule = context.rule
        # logger.info(f'context属性: {context.rule.__dict__}')
        # 检查是否是纯链接预览消息
        is_pure_link_preview = (
            event.message.media and
            hasattr(event.message.media, 'webpage') and
            not any([
                getattr(event.message.media, 'photo', None),
                getattr(event.message.media, 'document', None),
                getattr(event.message.media, 'video', None),
                getattr(event.message.media, 'audio', None),
                getattr(event.message.media, 'voice', None)
            ])
        )
        
        # 检查是否有实际媒体
        has_media = (
            event.message.media and
            any([
                getattr(event.message.media, 'photo', None),
                getattr(event.message.media, 'document', None),
                getattr(event.message.media, 'video', None),
                getattr(event.message.media, 'audio', None),
                getattr(event.message.media, 'voice', None)
            ])
        )

        # 处理实际媒体
        if has_media:
            # 检查媒体类型是否被屏蔽
            if rule.enable_media_type_filter:
                session = get_session()
                try:
                    media_types = session.query(MediaTypes).filter_by(rule_id=rule.id).first()
                    if media_types and await self._is_media_type_blocked(event.message.media, media_types):
                        logger.info(f'媒体类型被屏蔽，跳过消息 ID={event.message.id}')
                        context.should_forward = False
                        return True
                finally:
                    session.close()
            
            # 检查媒体扩展名
            if rule.enable_extension_filter and event.message.media:
                if not await self._is_media_extension_allowed(rule, event.message.media):
                    logger.info(f'媒体扩展名被屏蔽，跳过消息 ID={event.message.id}')
                    context.should_forward = False
                    return True
            
            # 检查媒体大小
            file_size = await get_media_size(event.message.media)
            file_size = round(file_size/1024/1024, 2)
            logger.info(f'event.message.document: {event.message.document}')
            
            logger.info(f'媒体文件大小: {file_size}MB')
            logger.info(f'规则最大媒体大小: {rule.max_media_size}MB')
            
            logger.info(f'是否启用媒体大小过滤: {rule.enable_media_size_filter}')
            if rule.max_media_size and (file_size > rule.max_media_size) and rule.enable_media_size_filter:
                file_name = ''
                if event.message.document:
                    # 正确地从文档属性中获取文件名
                    for attr in event.message.document.attributes:
                        if hasattr(attr, 'file_name'):
                            file_name = attr.file_name
                            break
                
                logger.info(f'媒体文件超过大小限制 ({rule.max_media_size}MB)')
                if rule.is_send_over_media_size_message:
                    logger.info(f'是否发送媒体大小超限提醒: {rule.is_send_over_media_size_message}')
                    context.should_forward = True
                else:
                    context.should_forward = False
                context.skipped_media.append((event.message, file_size, file_name))
            else:
                # 如果只转发到RSS，则跳过下载媒体文件，交给RSS处理下载
                if rule.only_rss:
                    return True
                try:
                    # 下载媒体文件
                    file_path = await event.message.download_media(TEMP_DIR)
                    if file_path:
                        context.media_files.append(file_path)
                        logger.info(f'媒体文件已下载到: {file_path}')
                except Exception as e:
                    logger.error(f'下载媒体文件时出错: {str(e)}')
                    context.errors.append(f"下载媒体文件错误: {str(e)}")
        elif is_pure_link_preview:
            # 记录这是纯链接预览消息
            context.is_pure_link_preview = True
            logger.info('这是一条纯链接预览消息')
            
    async def _is_media_type_blocked(self, media, media_types):
        """
        检查媒体类型是否被屏蔽
        
        Args:
            media: 媒体对象
            media_types: MediaTypes对象
            
        Returns:
            bool: 如果媒体类型被屏蔽返回True，否则返回False
        """
        # 检查各种媒体类型
        if getattr(media, 'photo', None) and media_types.photo:
            logger.info('媒体类型为图片，已被屏蔽')
            return True
        
        if getattr(media, 'document', None) and media_types.document:
            logger.info('媒体类型为文档，已被屏蔽')
            return True
        
        if getattr(media, 'video', None) and media_types.video:
            logger.info('媒体类型为视频，已被屏蔽')
            return True
        
        if getattr(media, 'audio', None) and media_types.audio:
            logger.info('媒体类型为音频，已被屏蔽')
            return True
        
        if getattr(media, 'voice', None) and media_types.voice:
            logger.info('媒体类型为语音，已被屏蔽')
            return True
        
        return False 
    
    async def _is_media_extension_allowed(self, rule, media):
        """
        检查媒体扩展名是否被允许
        
        Args:
            rule: 转发规则
            media: 媒体对象
            
        Returns:
            bool: 如果扩展名被允许返回True，否则返回False
        """
        # 如果没有启用扩展名过滤，默认允许
        if not rule.enable_extension_filter:
            return True
            
        # 获取文件名
        file_name = None
     
        for attr in media.document.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break

            
        # 如果没有文件名，则无法判断扩展名，默认允许
        if not file_name:
            logger.info("无法获取文件名，无法判断扩展名")
            return True
            
        # 提取扩展名
        _, extension = os.path.splitext(file_name)
        extension = extension.lstrip('.').lower()  # 移除点号并转为小写
        
        # 特殊处理：如果文件没有扩展名，将extension设为特殊值"无扩展名"
        if not extension:
            logger.info(f"文件 {file_name} 没有扩展名")
            extension = "无扩展名"
        else:
            logger.info(f"文件 {file_name} 的扩展名: {extension}")
        
        # 获取规则中保存的扩展名列表
        db_ops = await get_db_ops()
        session = get_session()
        allowed = True
        try:
            # 使用db_operations中的函数获取扩展名列表
            extensions = await db_ops.get_media_extensions(session, rule.id)
            extension_list = [ext["extension"].lower() for ext in extensions]
            
            # 判断是否允许该扩展名
            if rule.extension_filter_mode == AddMode.BLACKLIST:
                # 黑名单模式：如果扩展名在列表中，则不允许
                if extension in extension_list:
                    logger.info(f"扩展名 {extension} 在黑名单中，不允许")
                    allowed = False
                else:
                    logger.info(f"扩展名 {extension} 不在黑名单中，允许")
                    allowed = True
            else:
                # 白名单模式：如果扩展名不在列表中，则不允许
                if extension in extension_list:
                    logger.info(f"扩展名 {extension} 在白名单中，允许")
                    allowed = True
                else:
                    logger.info(f"扩展名 {extension} 不在白名单中，不允许")
                    allowed = False
        except Exception as e:
            logger.error(f"检查媒体扩展名时出错: {str(e)}")
            allowed = True  # 出错时默认允许
        finally:
            session.close()
            
        return allowed

