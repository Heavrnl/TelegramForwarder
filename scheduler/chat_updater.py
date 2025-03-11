import asyncio
from datetime import datetime, timedelta
import pytz
import os
import logging
from dotenv import load_dotenv
from telethon import TelegramClient
from models.models import get_session, Chat
import traceback
from utils.constants import DEFAULT_TIMEZONE
logger = logging.getLogger(__name__)

class ChatUpdater:
    def __init__(self, user_client: TelegramClient):
        self.user_client = user_client
        self.timezone = pytz.timezone(DEFAULT_TIMEZONE)
        self.task = None
        # 从环境变量获取更新时间，默认凌晨3点
        self.update_time = os.getenv('CHAT_UPDATE_TIME', "03:00")
    
    async def start(self):
        """启动定时更新任务"""
        logger.info("开始启动聊天信息更新器...")
        try:
            # 计算下一次执行时间
            now = datetime.now(self.timezone)
            next_time = self._get_next_run_time(now, self.update_time)
            wait_seconds = (next_time - now).total_seconds()
            
            logger.info(f"下一次聊天信息更新时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"等待时间: {wait_seconds:.2f} 秒")
            
            # 创建定时任务
            self.task = asyncio.create_task(self._run_update_task())
            logger.info("聊天信息更新器启动完成")
        except Exception as e:
            logger.error(f"启动聊天信息更新器时出错: {str(e)}")
            logger.error(f"错误详情: {traceback.format_exc()}")
    
    def _get_next_run_time(self, now, target_time):
        """计算下一次运行时间"""
        hour, minute = map(int, target_time.split(':'))
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if next_time <= now:
            next_time += timedelta(days=1)
            
        return next_time
    
    async def _run_update_task(self):
        """运行更新任务"""
        while True:
            try:
                # 计算下一次执行时间
                now = datetime.now(self.timezone)
                target_time = self._get_next_run_time(now, self.update_time)
                
                # 等待到执行时间
                wait_seconds = (target_time - now).total_seconds()
                await asyncio.sleep(wait_seconds)
                
                # 执行更新任务
                await self._update_all_chats()
                
            except asyncio.CancelledError:
                logger.info("聊天信息更新任务已取消")
                break
            except Exception as e:
                logger.error(f"聊天信息更新任务出错: {str(e)}")
                logger.error(f"错误详情: {traceback.format_exc()}")
                await asyncio.sleep(60)  # 出错后等待一分钟再重试
    
    async def _update_all_chats(self):
        """更新所有聊天信息"""
        logger.info("开始更新所有聊天信息...")
        session = get_session()
        try:
            # 获取所有聊天
            chats = session.query(Chat).all()
            total_chats = len(chats)
            logger.info(f"找到 {total_chats} 个聊天需要更新信息")
            
            updated_count = 0
            skipped_count = 0
            error_count = 0
            
            # 处理每个聊天
            for i, chat in enumerate(chats, 1):
                try:
                    # 每10个聊天报告一次进度
                    if i % 10 == 0 or i == total_chats:
                        logger.info(f"进度: {i}/{total_chats} ({i/total_chats*100:.1f}%)")
                    
                    chat_id = chat.telegram_chat_id
                    # 尝试获取聊天实体
                    try:
                        # 尝试转换聊天ID为整数
                        try:
                            chat_id_int = int(chat_id)
                        except ValueError:
                            logger.warning(f"聊天ID '{chat_id}' 不是有效的数字格式")
                            skipped_count += 1
                            continue
                            
                        entity = await self.user_client.get_entity(chat_id_int)
                        # 更新聊天名称
                        new_name = entity.title if hasattr(entity, 'title') else (
                            f"{entity.first_name} {entity.last_name}" if hasattr(entity, 'last_name') and entity.last_name 
                            else entity.first_name if hasattr(entity, 'first_name') 
                            else "私聊"
                        )
                        
                        # 只有当名称有变化时才更新
                        if chat.name != new_name:
                            old_name = chat.name or "未命名"
                            chat.name = new_name
                            session.commit()
                            logger.info(f"已更新聊天 {chat_id}: {old_name} -> {new_name}")
                            updated_count += 1
                        else:
                            skipped_count += 1
                            
                    except ValueError as e:
                        logger.warning(f"无法获取聊天 {chat_id} 的信息: 无效的ID格式 - {str(e)}")
                        skipped_count += 1
                        continue
                    except Exception as e:
                        logger.warning(f"无法获取聊天 {chat_id} 的信息: {str(e)}")
                        skipped_count += 1
                        continue
                        
                except Exception as e:
                    logger.error(f"处理聊天 {chat.telegram_chat_id} 时出错: {str(e)}")
                    error_count += 1
                    continue
                    
                # 每个聊天处理后暂停一会，避免请求过于频繁
                await asyncio.sleep(1)
                
            logger.info(f"聊天信息更新完成。总计: {total_chats}, 更新: {updated_count}, 跳过: {skipped_count}, 错误: {error_count}")
            
        except Exception as e:
            logger.error(f"更新聊天信息时出错: {str(e)}")
            logger.error(f"错误详情: {traceback.format_exc()}")
        finally:
            session.close()
    
    def stop(self):
        """停止定时任务"""
        if self.task:
            self.task.cancel()
            logger.info("聊天信息更新任务已停止") 