import importlib
import os
import sys
import logging
from telethon.tl.types import ChannelParticipantsAdmins
from ai import get_ai_provider
from enums.enums import ForwardMode
from models.models import Chat, ForwardRule
import re
import telethon
from utils.auto_delete import respond_and_delete,reply_and_delete,async_delete_user_message
from datetime import datetime, timedelta

from utils.constants import AI_SETTINGS_TEXT,MEDIA_SETTINGS_TEXT

logger = logging.getLogger(__name__)

def extract_topic_id(message):
    rt = getattr(message, "reply_to", None)
    if not rt:
        return None

    if not getattr(rt, "forum_topic", False):
        return None

    topic_id = getattr(rt, "reply_to_top_id", None) or getattr(rt, "reply_to_msg_id", None)

    # General 话题视作主聊天
    if topic_id in (None, 1):
        return None

    return topic_id

async def get_main_module():
    """获取 main 模块"""
    try:
        return sys.modules['__main__']
    except KeyError:
        # 如果找不到 main 模块，尝试手动导入
        spec = importlib.util.spec_from_file_location(
            "main",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
        )
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        return main

async def get_user_client():
    """获取用户客户端"""
    main = await get_main_module()
    return main.user_client

async def get_bot_client():
    """获取机器人客户端"""
    main = await get_main_module()
    return main.bot_client

async def get_db_ops():
    """获取 main.py 中的 db_ops 实例"""
    main = await get_main_module()
    if main.db_ops is None:
        main.db_ops = await main.init_db_ops()
    return main.db_ops

async def get_user_id():
    """获取用户ID，确保环境变量已加载"""
    user_id_str = os.getenv('USER_ID')
    if not user_id_str:
        logger.error('未设置 USER_ID 环境变量')
        raise ValueError('必须在 .env 文件中设置 USER_ID')
    return int(user_id_str)


async def get_current_rule(session, event):
    """获取当前选中的规则"""
    try:
        # 获取当前聊天
        current_chat = await event.get_chat()
        logger.info(f'获取当前聊天: {current_chat.id}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == str(current_chat.id)
        ).first()

        if not current_chat_db or not current_chat_db.current_add_id:
            logger.info('未找到当前聊天或未选择源聊天')
            await reply_and_delete(event,'请先使用 /switch 选择一个源聊天')
            return None

        logger.info(f'当前选中的源聊天ID: {current_chat_db.current_add_id}')

        # 查找对应的规则
        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_db.current_add_id
        ).first()

        if source_chat:
            logger.info(f'找到源聊天: {source_chat.name}')
        else:
            logger.error('未找到源聊天')
            return None

        rule = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id,
            ForwardRule.target_chat_id == current_chat_db.id
        ).first()

        if not rule:
            logger.info('未找到对应的转发规则')
            await reply_and_delete(event,'转发规则不存在')
            return None

        logger.info(f'找到转发规则 ID: {rule.id}')
        return rule, source_chat
    except Exception as e:
        logger.error(f'获取当前规则时出错: {str(e)}')
        logger.exception(e)
        await reply_and_delete(event,'获取当前规则时出错，请检查日志')
        return None


async def get_all_rules(session, event):
    """获取当前聊天的所有规则"""
    try:
        # 获取当前聊天
        current_chat = await event.get_chat()
        logger.info(f'获取当前聊天: {current_chat.id}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == str(current_chat.id)
        ).first()

        if not current_chat_db:
            logger.info('未找到当前聊天')
            await reply_and_delete(event,'当前聊天没有任何转发规则')
            return None

        logger.info(f'找到当前聊天数据库记录 ID: {current_chat_db.id}')

        # 查找所有以当前聊天为目标的规则
        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id
        ).all()

        if not rules:
            logger.info('未找到任何转发规则')
            await reply_and_delete(event,'当前聊天没有任何转发规则')
            return None

        logger.info(f'找到 {len(rules)} 条转发规则')
        return rules
    except Exception as e:
        logger.error(f'获取所有规则时出错: {str(e)}')
        logger.exception(e)
        await reply_and_delete(event,'获取规则时出错，请检查日志')
        return None



# 添加缓存字典
_admin_cache = {}
_CACHE_DURATION = timedelta(minutes=30)  # 缓存30分钟



async def get_channel_admins(client, chat_id):
    """获取频道管理员列表，带缓存机制"""
    current_time = datetime.now()
    
    # 检查缓存是否存在且未过期
    if chat_id in _admin_cache:
        cache_data = _admin_cache[chat_id]
        if current_time - cache_data['timestamp'] < _CACHE_DURATION:
            return cache_data['admin_ids']
    
    # 缓存不存在或已过期，重新获取管理员列表
    try:
        admins = await client.get_participants(chat_id, filter=ChannelParticipantsAdmins)
        admin_ids = [admin.id for admin in admins]
        
        # 更新缓存
        _admin_cache[chat_id] = {
            'admin_ids': admin_ids,
            'timestamp': current_time
        }
        return admin_ids
    except Exception as e:
        logger.error(f'获取频道管理员列表失败: {str(e)}')
        return None

async def is_admin(event):
    """检查用户是否为频道/群组管理员
    
    Args:
        event: 事件对象
    Returns:
        bool: 是否是管理员
    """
    try:
        # 获取所有机器人管理员列表
        bot_admins = get_admin_list()

        # 检查是否有message属性
        if not hasattr(event, 'message'):
            # 没有message属性,是回调处理
            if event.sender_id in bot_admins:
                return True
            else:
                logger.info(f'用户 {event.sender_id} 非管理员，操作已被忽略')
                return False
            
        message = event.message
        main = await get_main_module()
        client = main.user_client
        
        
    
        if message.is_channel and not message.is_group:
            # 获取频道管理员列表（使用缓存）
            channel_admins = await get_channel_admins(client, event.chat_id)
            if channel_admins is None:
                return False
                
            
            
            # 检查机器人管理员是否在频道管理员列表中
            admin_in_channel = any(admin_id in channel_admins for admin_id in bot_admins)
            if not admin_in_channel:
                logger.info(f'机器人管理员不在频道管理员列表中，已忽略')
                return False
            return True
        else:
            # 检查发送者ID
            user_id = event.sender_id  # 使用 sender_id 作为主要ID来源
            logger.info(f'发送者ID：{user_id}')
            
            bot_admins = get_admin_list()
            # 检查是否是机器人管理员
            if user_id not in bot_admins:
                logger.info(f'非管理员的消息，已忽略')
                return False
            return True
    except Exception as e:
        logger.error(f"检查管理员权限时出错: {str(e)}")
        return False

async def get_media_settings_text():
    """生成媒体设置页面的文本"""
    return MEDIA_SETTINGS_TEXT

async def get_ai_settings_text(rule):
    """生成AI设置页面的文本"""
    ai_prompt = rule.ai_prompt or os.getenv('DEFAULT_AI_PROMPT', '未设置')
    summary_prompt = rule.summary_prompt or os.getenv('DEFAULT_SUMMARY_PROMPT', '未设置')

    return AI_SETTINGS_TEXT.format(
        ai_prompt=ai_prompt,
        summary_prompt=summary_prompt
    )

async def get_sender_info(event, rule_id):
    """
    获取发送者信息
    
    Args:
        event: 消息事件
        rule_id: 规则ID
        
    Returns:
        str: 发送者信息
    """
    try:
        logger.info("开始获取发送者信息")
        sender_name = None

        if hasattr(event.message, 'sender_chat') and event.message.sender_chat:
            # 用户以频道身份发送消息
            sender = event.message.sender_chat
            sender_name = sender.title if hasattr(sender, 'title') else None
            logger.info(f"使用频道信息: {sender_name}")

        elif event.sender:
            # 用户以个人身份发送消息
            sender = event.sender
            sender_name = (
                sender.title if hasattr(sender, 'title')
                else f"{sender.first_name or ''} {sender.last_name or ''}".strip()
            )
            logger.info(f"使用发送者信息: {sender_name}")

        elif hasattr(event.message, 'peer_id') and event.message.peer_id:
            # 尝试从 peer_id 获取信息
            peer = event.message.peer_id
            if hasattr(peer, 'channel_id'):
                try:
                    # 尝试获取频道信息
                    channel = await event.client.get_entity(peer)
                    sender_name = channel.title if hasattr(channel, 'title') else None
                    logger.info(f"使用peer_id信息: {sender_name}")
                except Exception as ce:
                    logger.error(f'获取频道信息失败: {str(ce)}')

        if sender_name:
            return sender_name
        else:
            logger.warning(f"规则 ID: {rule_id} - 无法获取发送者信息")
            return None

    except Exception as e:
        logger.error(f'获取发送者信息出错: {str(e)}')
        return None

async def check_and_clean_chats(session, rule=None):
    """
    检查并清理不再与任何规则关联的聊天记录
    
    Args:
        session: 数据库会话
        rule: 被删除的规则对象（可选），如果提供则从中获取聊天ID
        
    Returns:
        int: 删除的聊天记录数量
    """
    deleted_count = 0
    
    try:
        # 获取所有聊天ID
        chat_ids_to_check = set()
        
        # 如果提供了规则，先检查这些受影响的聊天
        if rule:
            if rule.source_chat_id:
                chat_ids_to_check.add(rule.source_chat_id)
            if rule.target_chat_id:
                chat_ids_to_check.add(rule.target_chat_id)
        else:
            # 如果没有提供规则，则获取所有聊天
            all_chats = session.query(Chat.id).all()
            chat_ids_to_check = set(chat[0] for chat in all_chats)
        
        # 对每个聊天ID进行检查
        for chat_id in chat_ids_to_check:
            # 检查此聊天是否还被任何规则引用
            as_source = session.query(ForwardRule).filter(
                ForwardRule.source_chat_id == chat_id
            ).count()
            
            as_target = session.query(ForwardRule).filter(
                ForwardRule.target_chat_id == chat_id
            ).count()
            
            # 如果聊天不再被任何规则引用
            if as_source == 0 and as_target == 0:
                chat = session.query(Chat).get(chat_id)
                if chat:
                    # 获取telegram_chat_id以便日志记录
                    telegram_chat_id = chat.telegram_chat_id
                    name = chat.name or "未命名聊天"
                    
                    # 清理所有引用此聊天作为current_add_id的记录
                    chats_using_this = session.query(Chat).filter(
                        Chat.current_add_id == telegram_chat_id
                    ).all()
                    
                    for other_chat in chats_using_this:
                        other_chat.current_add_id = None
                        logger.info(f'清除聊天 {other_chat.name} 的current_add_id设置')
                    
                    # 删除聊天记录
                    session.delete(chat)
                    logger.info(f'删除未使用的聊天: {name} (ID: {telegram_chat_id})')
                    deleted_count += 1
        
        # 如果有删除操作，提交更改
        if deleted_count > 0:
            session.commit()
            logger.info(f'共清理了 {deleted_count} 个未使用的聊天记录')
        
        return deleted_count
        
    except Exception as e:
        logger.error(f'检查和清理聊天记录时出错: {str(e)}')
        session.rollback()
        return 0

def get_admin_list():
    """获取管理员ID列表，如果ADMINS为空则使用USER_ID"""
    admin_str = os.getenv('ADMINS', '')
    if not admin_str:
        user_id = os.getenv('USER_ID')
        if not user_id:
            logger.error('未设置 USER_ID 环境变量')
            raise ValueError('必须在 .env 文件中设置 USER_ID')
        return [int(user_id)]
    return [int(admin.strip()) for admin in admin_str.split(',') if admin.strip()]




async def check_keywords(rule, message_text, event = None):
    """
    检查消息是否匹配关键字规则

    Args:
        rule: 转发规则对象，包含 forward_mode 和 keywords 属性
        message_text: 要检查的消息文本
        event: 可选的消息事件对象

    Returns:
        bool: 是否应该转发消息
    """
    reverse_blacklist = rule.enable_reverse_blacklist
    reverse_whitelist = rule.enable_reverse_whitelist
    logger.info(f"反转黑名单: {reverse_blacklist}, 反转白名单: {reverse_whitelist}")

    # 处理用户信息过滤
    if rule.is_filter_user_info and event:
        message_text = await process_user_info(event, rule.id, message_text)

    logger.info("开始检查关键字规则")
    logger.info(f"当前转发模式: {rule.forward_mode}")
    forward_mode = rule.forward_mode

    # 仅白名单模式
    if forward_mode == ForwardMode.WHITELIST:
        return await process_whitelist_mode(rule, message_text, reverse_blacklist)

    # 仅黑名单模式
    elif forward_mode == ForwardMode.BLACKLIST:
        return await process_blacklist_mode(rule, message_text, reverse_whitelist)

    # 先白后黑模式
    elif forward_mode == ForwardMode.WHITELIST_THEN_BLACKLIST:
        return await process_whitelist_then_blacklist_mode(rule, message_text, reverse_blacklist)

    # 先黑后白模式
    elif forward_mode == ForwardMode.BLACKLIST_THEN_WHITELIST:
        return await process_blacklist_then_whitelist_mode(rule, message_text, reverse_whitelist)

    logger.error(f"未知的转发模式: {forward_mode}")
    return False

async def process_whitelist_mode(rule, message_text, reverse_blacklist):
    """处理仅白名单模式"""
    logger.info("进入仅白名单模式")
    should_forward = False

    # 检查普通白名单关键词
    whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
    logger.info(f"普通白名单关键词: {[k.keyword for k in whitelist_keywords]}")
    
    for keyword in whitelist_keywords:
        if await check_keyword_match(keyword, message_text):
            should_forward = True
            break
    
    if not should_forward:
        logger.info("未匹配到普通白名单关键词，不转发")
        return False

    # 如果启用了黑名单反转，还需要匹配反转后的黑名单（作为第二重白名单）
    if reverse_blacklist:
        logger.info("检查反转后的黑名单关键词（作为白名单）")
        reversed_blacklist = [k for k in rule.keywords if k.is_blacklist]
        logger.info(f"反转后的黑名单关键词: {[k.keyword for k in reversed_blacklist]}")
        
        reversed_match = False
        for keyword in reversed_blacklist:
            if await check_keyword_match(keyword, message_text):
                reversed_match = True
                break
        
        if not reversed_match:
            logger.info("未匹配到反转后的黑名单关键词，不转发")
            return False

    logger.info("所有白名单条件都满足，允许转发")
    return True

async def process_blacklist_mode(rule, message_text, reverse_whitelist):
    """处理仅黑名单模式"""
    logger.info("进入仅黑名单模式")

    # 检查普通黑名单关键词
    blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
    logger.info(f"普通黑名单关键词: {[k.keyword for k in blacklist_keywords]}")
    
    for keyword in blacklist_keywords:
        if await check_keyword_match(keyword, message_text):
            logger.info(f"匹配到黑名单关键词 '{keyword.keyword}'，不转发")
            return False

    # 如果启用了白名单反转，检查反转后的白名单（作为黑名单）
    if reverse_whitelist:
        logger.info("检查反转后的白名单关键词（作为黑名单）")
        reversed_whitelist = [k for k in rule.keywords if not k.is_blacklist]
        logger.info(f"反转后的白名单关键词: {[k.keyword for k in reversed_whitelist]}")
        
        for keyword in reversed_whitelist:
            if await check_keyword_match(keyword, message_text):
                logger.info(f"匹配到反转后的白名单关键词 '{keyword.keyword}'，不转发")
                return False

    logger.info("未匹配到任何黑名单关键词，允许转发")
    return True

async def check_keyword_match(keyword, message_text):
    """检查单个关键词是否匹配"""
    logger.info(f"检查关键字: {keyword.keyword} (正则: {keyword.is_regex})")
    if keyword.is_regex:
        try:
            if re.search(keyword.keyword, message_text):
                logger.info(f"正则匹配成功: {keyword.keyword}")
                return True
        except re.error:
            logger.error(f"正则表达式错误: {keyword.keyword}")
    else:
        if keyword.keyword.lower() in message_text.lower():
            logger.info(f"关键字匹配成功: {keyword.keyword}")
            return True
    return False

async def process_user_info(event, rule_id, message_text):
    """处理用户信息过滤"""
    username = await get_sender_info(event, rule_id)
    name = None
    
    if hasattr(event.message, 'sender_chat') and event.message.sender_chat:
        sender = event.message.sender_chat
        name = sender.title if hasattr(sender, 'title') else None
    elif event.sender:
        sender = event.sender
        name = (
            sender.title if hasattr(sender, 'title')
            else f"{sender.first_name or ''} {sender.last_name or ''}".strip()
        )
        
    if username and name:
        logger.info(f"成功获取用户信息: {username} {name}")
        return f"{username} {name}:\n{message_text}"
    elif username:
        logger.info(f"成功获取用户信息: {username}")
        return f"{username}:\n{message_text}"
    elif name:
        logger.info(f"成功获取用户信息: {name}")
        return f"{name}:\n{message_text}"
    else:
        logger.warning(f"规则 ID: {rule_id} - 无法获取发送者信息")
        return message_text


async def process_whitelist_then_blacklist_mode(rule, message_text, reverse_blacklist):
    """处理先白后黑模式
    
    先检查白名单（必须匹配），然后检查黑名单（不能匹配）
    如果启用黑名单反转，则黑名单变成第二重白名单（必须匹配）
    """
    logger.info("进入先白后黑模式")

    # 检查普通白名单（必须匹配）
    whitelist_match = False
    whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
    logger.info(f"检查普通白名单关键词: {[k.keyword for k in whitelist_keywords]}")
    
    for keyword in whitelist_keywords:
        if await check_keyword_match(keyword, message_text):
            whitelist_match = True
            break
    
    if not whitelist_match:
        logger.info("未匹配到白名单关键词，不转发")
        return False

    # 根据反转设置处理黑名单
    blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
    
    if reverse_blacklist:
        # 黑名单反转为白名单，必须匹配才转发
        logger.info("黑名单已反转，作为第二重白名单检查")
        logger.info(f"反转后的黑名单关键词: {[k.keyword for k in blacklist_keywords]}")
        
        blacklist_match = False
        for keyword in blacklist_keywords:
            if await check_keyword_match(keyword, message_text):
                blacklist_match = True
                break
        
        if not blacklist_match:
            logger.info("未匹配到反转后的黑名单关键词，不转发")
            return False
    else:
        # 正常黑名单，匹配则不转发
        logger.info(f"检查普通黑名单关键词: {[k.keyword for k in blacklist_keywords]}")
        for keyword in blacklist_keywords:
            if await check_keyword_match(keyword, message_text):
                logger.info(f"匹配到黑名单关键词 '{keyword.keyword}'，不转发")
                return False

    logger.info("所有条件都满足，允许转发")
    return True

async def process_blacklist_then_whitelist_mode(rule, message_text, reverse_whitelist):
    """处理先黑后白模式
    
    先检查黑名单（不能匹配），然后检查白名单（必须匹配）
    如果启用白名单反转，则白名单变成第二重黑名单（不能匹配）
    """
    logger.info("进入先黑后白模式")

    # 检查普通黑名单（匹配则拒绝）
    blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
    logger.info(f"检查普通黑名单关键词: {[k.keyword for k in blacklist_keywords]}")
    
    for keyword in blacklist_keywords:
        if await check_keyword_match(keyword, message_text):
            logger.info(f"匹配到黑名单关键词 '{keyword.keyword}'，不转发")
            return False

    # 处理白名单
    whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
    
    if reverse_whitelist:
        # 白名单反转为黑名单，匹配则不转发
        logger.info("白名单已反转，作为第二重黑名单检查")
        logger.info(f"反转后的白名单关键词: {[k.keyword for k in whitelist_keywords]}")
        
        for keyword in whitelist_keywords:
            if await check_keyword_match(keyword, message_text):
                logger.info(f"匹配到反转后的白名单关键词 '{keyword.keyword}'，不转发")
                return False
    else:
        # 正常白名单，必须匹配才转发
        logger.info(f"检查普通白名单关键词: {[k.keyword for k in whitelist_keywords]}")
        whitelist_match = False
        for keyword in whitelist_keywords:
            if await check_keyword_match(keyword, message_text):
                whitelist_match = True
                break
        
        if not whitelist_match:
            logger.info("未匹配到白名单关键词，不转发")
            return False

    logger.info("所有条件都满足，允许转发")
    return True
