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


from utils.constants import AI_SETTINGS_TEXT,MEDIA_SETTINGS_TEXT

logger = logging.getLogger(__name__)

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
    import main
    return main.user_client

async def get_bot_client():
    """获取机器人客户端"""
    import main
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


async def check_keywords(rule, message_text, event = None):
    """
    检查消息是否匹配关键字规则

    Args:
        rule: 转发规则对象，包含 forward_mode 和 keywords 属性
        message_text: 要检查的消息文本

    Returns:
        bool: 是否应该转发消息
    """

    logger.info(f"是否开启过滤用户选项: {rule.is_filter_user_info}")
    if rule.is_filter_user_info:
        username = await get_sender_info(event, rule.id)  # 调用新的函数获取 sender_info
        name =  (
                event.sender.title if hasattr(event.sender, 'title')
                else f"{event.sender.first_name or ''} {event.sender.last_name or ''}".strip()
                )
        if username and name:
            logger.info(f"成功获取用户信息: {username} {name}")
            message_text = f"{username} {name}:\n{message_text}"
        elif username:
            logger.info(f"成功获取用户信息: {username}")
            message_text = f"{username}:\n{message_text}"
        elif name:
            logger.info(f"成功获取用户信息: {name}")
            message_text = f"{name}:\n{message_text}"
        else:
            logger.warning(f"规则 ID: {rule.id} - 无法获取发送者信息")
            
        logger.info(f'附带用户信息后的消息: {message_text}')    

    logger.info("开始检查关键字规则")
    logger.info(f"当前转发模式: {rule.forward_mode}")
    should_forward = None
    forward_mode = rule.forward_mode

    # 处理仅白名单或仅黑名单模式
    if forward_mode in [ForwardMode.WHITELIST, ForwardMode.BLACKLIST]:
        logger.info("进入仅白名单/仅黑名单模式")
        is_whitelist = (forward_mode == ForwardMode.WHITELIST)
        keywords = [k for k in rule.keywords if k.is_blacklist != is_whitelist]
        logger.info(f"待检查关键词: {[k.keyword for k in keywords]}")
        # 白名单模式默认不转发，黑名单模式默认转发
        should_forward = not is_whitelist  
        logger.info(f"初始 should_forward 设置为: {should_forward}")

        for keyword in keywords:
            logger.info(f"检查{'白名单' if is_whitelist else '黑名单'}关键字: {keyword.keyword} (正则: {keyword.is_regex})")
            matched = False
            if keyword.is_regex:
                try:
                    if re.search(keyword.keyword, message_text):
                        matched = True
                        logger.info(f"正则匹配成功: {keyword.keyword}")
                except re.error:
                    logger.error(f"正则表达式错误: {keyword.keyword}")
            else:
                if keyword.keyword.lower() in message_text.lower():
                    matched = True
                    logger.info(f"关键字匹配成功: {keyword.keyword}")
            if matched:
                should_forward = is_whitelist
                logger.info(f"匹配到关键词 '{keyword.keyword}'，设置 should_forward 为: {should_forward}")
                break
        logger.info("结束仅白名单/仅黑名单模式检查")

    # 处理 先白后黑 模式
    elif forward_mode == ForwardMode.WHITELIST_THEN_BLACKLIST:
        logger.info("进入 先白后黑 模式")
        # 先检查白名单：必须匹配至少一个白名单关键词
        whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
        logger.info(f"白名单关键词: {[k.keyword for k in whitelist_keywords]}")
        should_forward = False
        for keyword in whitelist_keywords:
            logger.info(f"检查白名单关键字: {keyword.keyword} (正则: {keyword.is_regex})")
            matched = False
            if keyword.is_regex:
                try:
                    if re.search(keyword.keyword, message_text):
                        matched = True
                        logger.info(f"白名单正则匹配成功: {keyword.keyword}")
                except re.error:
                    logger.error(f"正则表达式错误: {keyword.keyword}")
            else:
                if keyword.keyword.lower() in message_text.lower():
                    matched = True
                    logger.info(f"白名单关键字匹配成功: {keyword.keyword}")
            if matched:
                should_forward = True
                logger.info(f"匹配到白名单关键词 '{keyword.keyword}'，设置 should_forward 为: True")
                break

        # 如果白名单匹配成功，再检查黑名单
        if should_forward:
            logger.info("白名单匹配成功，开始检查黑名单关键词")
            blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
            logger.info(f"黑名单关键词: {[k.keyword for k in blacklist_keywords]}")
            for keyword in blacklist_keywords:
                logger.info(f"检查黑名单关键字: {keyword.keyword} (正则: {keyword.is_regex})")
                matched = False
                if keyword.is_regex:
                    try:
                        if re.search(keyword.keyword, message_text):
                            matched = True
                            logger.info(f"黑名单正则匹配成功: {keyword.keyword}")
                    except re.error:
                        logger.error(f"正则表达式错误: {keyword.keyword}")
                else:
                    if keyword.keyword.lower() in message_text.lower():
                        matched = True
                        logger.info(f"黑名单关键字匹配成功: {keyword.keyword}")
                if matched:
                    should_forward = False
                    logger.info(f"匹配到黑名单关键词 '{keyword.keyword}'，设置 should_forward 为: False")
                    break
        else:
            logger.info("未匹配到任何白名单关键词，直接不转发")
        logger.info("结束 先白后黑 模式检查")

    # 处理 先黑后白 模式
    elif forward_mode == ForwardMode.BLACKLIST_THEN_WHITELIST:
        logger.info("进入 先黑后白 模式")
        # 先检查黑名单：如果匹配任一黑名单关键词，直接拒绝转发
        blacklist_keywords = [k for k in rule.keywords if k.is_blacklist]
        logger.info(f"黑名单关键词: {[k.keyword for k in blacklist_keywords]}")
        for keyword in blacklist_keywords:
            logger.info(f"检查黑名单关键字: {keyword.keyword} (正则: {keyword.is_regex})")
            matched = False
            if keyword.is_regex:
                try:
                    if re.search(keyword.keyword, message_text):
                        matched = True
                        logger.info(f"黑名单正则匹配成功: {keyword.keyword}")
                except re.error:
                    logger.error(f"正则表达式错误: {keyword.keyword}")
            else:
                if keyword.keyword.lower() in message_text.lower():
                    matched = True
                    logger.info(f"黑名单关键字匹配成功: {keyword.keyword}")
            if matched:
                logger.info("匹配到黑名单关键词，拒绝转发消息")
                return False

        # 如果没有匹配到黑名单，再检查白名单：必须匹配至少一个白名单关键词
        whitelist_keywords = [k for k in rule.keywords if not k.is_blacklist]
        logger.info(f"白名单关键词: {[k.keyword for k in whitelist_keywords]}")
        for keyword in whitelist_keywords:
            logger.info(f"检查白名单关键字: {keyword.keyword} (正则: {keyword.is_regex})")
            matched = False
            if keyword.is_regex:
                try:
                    if re.search(keyword.keyword, message_text):
                        matched = True
                        logger.info(f"白名单正则匹配成功: {keyword.keyword}")
                except re.error:
                    logger.error(f"正则表达式错误: {keyword.keyword}")
            else:
                if keyword.keyword.lower() in message_text.lower():
                    matched = True
                    logger.info(f"白名单关键字匹配成功: {keyword.keyword}")
            if matched:
                logger.info("匹配到白名单关键词，转发消息")
                return True

        logger.info("未匹配到任何白名单关键词，拒绝转发")
        should_forward = False
        logger.info("结束 先黑后白 模式检查")

    logger.info(f"关键字检查最终结果: {'转发' if should_forward else '不转发'}")
    return should_forward

async def is_admin(channel_id, user_id, client):
    """检查用户是否为频道/群组管理员
    
    Args:
        channel_id: 频道/群组ID
        user_id: 用户ID
        client: Telethon客户端实例
    
    Returns:
        bool: 是否是管理员
    """
    try:
        # 获取频道的管理员列表
        admins = await client.get_participants(channel_id, filter=ChannelParticipantsAdmins)
        # 检查用户是否在管理员列表中
        return any(admin.id == user_id for admin in admins)
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
    """获取消息发送者信息，处理各种情况并返回 sender_info 字符串"""
    sender_info = ""
    if hasattr(event.message, 'from_user'):
        if event.message.from_user:
            sender_info = f"{event.message.from_user.mention} ({event.message.from_user.id})"
        else:
            logger.warning(f"规则 ID: {rule_id} - event.message.from_user 存在但为 None")
            sender_info = "未知发送者 (from_user 为 None)"
    elif hasattr(event.message, 'sender'):
        if event.message.sender:
            sender = await event.get_sender()
            if sender:
                if isinstance(sender, telethon.tl.types.Channel):
                    sender_info = f"{sender.title} ({sender.id})"
                elif isinstance(sender, telethon.tl.types.User):
                    sender_info = f"{sender.username or sender.first_name or '未知用户'} ({sender.id})"
                else:
                    sender_info = f"未知类型发送者 ({sender.id})"
            else:
                logger.warning(f"规则 ID: {rule_id} - event.message.sender 存在但 get_sender() 返回 None")
                sender_info = "未知发送者 (sender 为 None after get_sender)"
        else:
            logger.warning(f"规则 ID: {rule_id} - event.message.sender 存在但为 None")
            sender_info = "未知发送者 (sender 为 None)"
    else:
        logger.warning(f"规则 ID: {rule_id} - event.message 既没有 from_user 也没有 sender 属性")
        sender_info = "未知发送者 (无法获取用户信息)"
    return sender_info

async def get_chat_name_by_id(chat_id, use_bot=False):
    """
    根据聊天ID获取聊天名称
    
    参数:
        chat_id: 聊天ID
        use_bot: 是否使用机器人客户端，默认使用用户客户端
        
    返回:
        聊天名称，如果获取失败则返回聊天ID
    """
    try:
        # 获取客户端
        main = await get_main_module()
        client = main.user_client
        if not client:
            return str(chat_id)
            
        # 获取聊天实体
        entity = await client.get_entity(int(chat_id) if str(chat_id).lstrip('-').isdigit() else chat_id)
        
        # 获取名称
        if hasattr(entity, 'title'):
            return entity.title
        elif hasattr(entity, 'first_name'):
            name = entity.first_name
            if hasattr(entity, 'last_name') and entity.last_name:
                name += f" {entity.last_name}"
            return name
        else:
            return str(chat_id)
    except Exception as e:
        logger.error(f"获取聊天名称失败: {e}")
        return str(chat_id)




# async def ai_handle(message: str, rule) -> str:
#     """使用AI处理消息
    
#     Args:
#         message: 原始消息文本
#         rule: 转发规则对象，包含AI相关设置
        
#     Returns:
#         str: 处理后的消息文本
#     """
#     try:
#         if not rule.is_ai:
#             logger.info("AI处理未开启，返回原始消息")
#             return message
#         # 先读取数据库，如果ai模型为空，则使用.env中的默认模型
#         if not rule.ai_model:
#             rule.ai_model = os.getenv('DEFAULT_AI_MODEL')
#             logger.info(f"使用默认AI模型: {rule.ai_model}")
#         else:
#             logger.info(f"使用规则配置的AI模型: {rule.ai_model}")
            
#         provider = await get_ai_provider(rule.ai_model)
        
#         if not rule.ai_prompt:
#             rule.ai_prompt = os.getenv('DEFAULT_AI_PROMPT')
#             logger.info("使用默认AI提示词")
#         else:
#             logger.info("使用规则配置的AI提示词")
        
#         # 处理特殊提示词格式
#         prompt = rule.ai_prompt


#         processed_text = await provider.process_message(
#             message=message,
#             prompt=prompt,
#             model=rule.ai_model
#         )
#         logger.info(f"AI处理完成: {processed_text}")
#         return processed_text
        
#     except Exception as e:
#         logger.error(f"AI处理消息时出错: {str(e)}")
#         return message  