from sqlalchemy.exc import IntegrityError
from telethon import Button
from models.models import MediaTypes, MediaExtensions
from enums.enums import AddMode, ForwardMode
from models.models import get_session, Keyword, ReplaceRule, User, RuleSync
from utils.common import *
from utils.media import *
from handlers.list_handlers import *
from utils.constants import TEMP_DIR
import traceback
from sqlalchemy import inspect
from version import VERSION, UPDATE_INFO
import shlex
import logging
import os
import aiohttp
from utils.constants import RSS_HOST, RSS_PORT
import models.models as models
from utils.auto_delete import respond_and_delete,reply_and_delete,async_delete_user_message
from utils.common import get_bot_client
from handlers.button.settings_manager import create_settings_text, create_buttons
from utils.topics import parse_bind_args, validate_topic, creates_route_cycle, message_topic_id
from utils.rule_selection import selected_rule, select_rule

logger = logging.getLogger(__name__)


async def handle_topic_command(event):
    chat = await event.get_chat()
    if not getattr(chat, 'forum', False):
        await reply_and_delete(event, '当前聊天未开启话题功能。请在话题群内使用 /topic。')
        return
    topic_id = message_topic_id(event.message, is_forum=True)
    await reply_and_delete(event, f'当前话题 ID: {topic_id}\n绑定时可使用 --source-topic {topic_id} 或 --target-topic {topic_id}')

async def handle_bind_command(event, client, parts):
    """处理 bind 命令"""
    try:
        source_target, target_chat_input, source_topic_id, target_topic_id = parse_bind_args(event.message.text)
    except ValueError as error:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event, f'{error}\n用法: /bind <源聊天链接或名称> [目标聊天链接或名称] [--source-topic ID] [--target-topic ID]\n例如:\n/bind "源群" --source-topic 123\n0 = 全部源话题/默认目标位置，1 = General。省略目标聊天时使用当前聊天；目标为当前群且未指定 --target-topic 时，自动使用命令所在话题。')
        return

    # 检查是否是链接
    is_source_link = source_target.startswith(('https://', 't.me/'))

    # 默认使用当前聊天作为目标聊天
    current_chat = await event.get_chat()
    
    try:
        # 获取 main 模块中的用户客户端
        main = await get_main_module()
        user_client = main.user_client

        # 使用用户客户端获取源聊天的实体信息
        try:
            if is_source_link:
                # 如果是链接，直接获取实体
                source_chat_entity = await user_client.get_entity(source_target)
            else:
                # 如果是名称，获取对话列表并查找匹配的第一个
                async for dialog in user_client.iter_dialogs():
                    if dialog.name and source_target.lower() in dialog.name.lower():
                        source_chat_entity = dialog.entity
                        break
                else:
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,'未找到匹配的源群组/频道，请确保名称正确且账号已加入该群组/频道')
                    return
            
            # 获取目标聊天实体
            if target_chat_input:
                is_target_link = target_chat_input.startswith(('https://', 't.me/'))
                if is_target_link:
                    # 如果是链接，直接获取实体
                    target_chat_entity = await user_client.get_entity(target_chat_input)
                else:
                    # 如果是名称，获取对话列表并查找匹配的第一个
                    async for dialog in user_client.iter_dialogs():
                        if dialog.name and target_chat_input.lower() in dialog.name.lower():
                            target_chat_entity = dialog.entity
                            break
                    else:
                        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                        await reply_and_delete(event,'未找到匹配的目标群组/频道，请确保名称正确且账号已加入该群组/频道')
                        return
            else:
                # 使用当前聊天作为目标
                target_chat_entity = current_chat

            if target_topic_id is None:
                target_topic_id = (
                    message_topic_id(event.message, is_forum=True)
                    if str(target_chat_entity.id) == str(current_chat.id) and getattr(current_chat, 'forum', False)
                    else 0
                )

            await validate_topic(user_client, source_chat_entity, source_topic_id)
            await validate_topic(user_client, target_chat_entity, target_topic_id, destination=True)

        except ValueError as error:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, f'无法绑定: {error}\n请检查聊天、话题 ID，以及账号是否已加入群组。')
            return
        except Exception as e:
            logger.error(f'获取聊天信息时出错: {str(e)}')
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'获取聊天信息时出错，请检查日志')
            return

        # 保存到数据库
        session = get_session()
        try:
            # 保存源聊天
            source_chat_db = session.query(Chat).filter(
                Chat.telegram_chat_id == str(source_chat_entity.id)
            ).first()

            if not source_chat_db:
                source_chat_db = Chat(
                    telegram_chat_id=str(source_chat_entity.id),
                    name=source_chat_entity.title if hasattr(source_chat_entity, 'title') else 'Private Chat'
                )
                session.add(source_chat_db)
                session.flush()

            # 保存目标聊天
            target_chat_db = session.query(Chat).filter(
                Chat.telegram_chat_id == str(target_chat_entity.id)
            ).first()

            if not target_chat_db:
                target_chat_db = Chat(
                    telegram_chat_id=str(target_chat_entity.id),
                    name=target_chat_entity.title if hasattr(target_chat_entity, 'title') else 'Private Chat'
                )
                session.add(target_chat_db)
                session.flush()

            # Topic routes must not feed back into themselves (including indirect cycles).
            existing_rules = session.query(ForwardRule).all()
            has_topics = source_topic_id or target_topic_id or any(r.source_topic_id or r.target_topic_id for r in existing_rules)
            if has_topics and creates_route_cycle(
                existing_rules, source_chat_db.id, source_topic_id,
                target_chat_db.id, target_topic_id
            ):
                session.rollback()
                await reply_and_delete(event, '无法绑定：该话题映射会形成转发循环，请调整源或目标话题。')
                return

            # 创建转发规则
            rule = ForwardRule(
                source_chat_id=source_chat_db.id,
                target_chat_id=target_chat_db.id,
                source_topic_id=source_topic_id,
                target_topic_id=target_topic_id
            )
            
            # 如果是绑定自己，则默认使用白名单模式
            if str(source_chat_entity.id) == str(target_chat_entity.id) and not (source_topic_id or target_topic_id):
                rule.forward_mode = ForwardMode.WHITELIST
                rule.add_mode = AddMode.WHITELIST
                
            session.add(rule)
            session.flush()
            if selected_rule(session, target_chat_db) is None:
                select_rule(target_chat_db, rule)
            session.commit()

            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,
                f'已设置转发规则:\n'
                f'规则 ID: {rule.id}\n'
                f'源聊天: {rule.source_label} ({source_chat_db.telegram_chat_id})\n'
                f'目标聊天: {rule.target_label} ({target_chat_db.telegram_chat_id})\n'
                f'请使用 /add 或 /add_regex 添加关键字',
                buttons=[Button.inline("⚙️ 打开设置", f"rule_settings:{rule.id}")]
            )

        except IntegrityError:
            session.rollback()
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,
                f'已存在相同的转发规则:\n'
                f'源话题 ID: {source_topic_id}\n'
                f'目标话题 ID: {target_topic_id}\n'
                f'如需修改请使用 /settings 命令'
            )
            return
        finally:
            session.close()

    except Exception as e:
        logger.error(f'设置转发规则时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'设置转发规则时出错，请检查日志')
        return

async def handle_settings_command(event, command, parts):
    """处理 settings 命令"""
    # 添加日志
    logger.info(f'处理 settings 命令 - parts: {parts}')
    
    # 获取参数
    args = parts[1:] if len(parts) > 1 else []
    
    # 检查是否提供了规则ID
    if len(args) >= 1 and args[0].isdigit():
        rule_id = int(args[0])
        
        # 直接打开指定规则的设置界面
        session = get_session()
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                await reply_and_delete(event, f'找不到ID为 {rule_id} 的规则')
                return
                
            # 与callback_rule_settings函数相同的处理方式
            settings_message = await event.respond(
                await create_settings_text(rule),
                buttons=await create_buttons(rule)
            )
            
        except Exception as e:
            logger.error(f'打开规则设置时出错: {str(e)}')
            await reply_and_delete(event, '打开规则设置时出错，请检查日志')
        finally:
            session.close()
        return
    
    current_chat = await event.get_chat()
    current_chat_id = str(current_chat.id)
    # 添加日志
    logger.info(f'正在查找聊天ID: {current_chat_id} 的转发规则')

    session = get_session()
    try:
        # 添加日志，显示数据库中的所有聊天
        all_chats = session.query(Chat).all()
        logger.info('数据库中的所有聊天:')
        for chat in all_chats:
            logger.info(f'ID: {chat.id}, telegram_chat_id: {chat.telegram_chat_id}, name: {chat.name}')

        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_id
        ).first()

        if not current_chat_db:
            logger.info(f'在数据库中找不到聊天ID: {current_chat_id}')
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'当前聊天没有任何转发规则')
            return

        # 添加日志
        logger.info(f'找到聊天: {current_chat_db.name} (ID: {current_chat_db.id})')

        # 查找以当前聊天为目标的规则
        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id  # 改为 target_chat_id
        ).all()

        # 添加日志
        logger.info(f'找到 {len(rules)} 条转发规则')
        for rule in rules:
            logger.info(f'规则ID: {rule.id}, 源聊天: {rule.source_chat.name}, 目标聊天: {rule.target_chat.name}')

        if not rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'当前聊天没有任何转发规则')
            return

        # 创建规则选择按钮
        buttons = []
        for rule in rules:
            source_chat = rule.source_chat  # 显示源聊天
            button_text = f'#{rule.id} {rule.route_label}'
            callback_data = f"rule_settings:{rule.id}"
            buttons.append([Button.inline(button_text, callback_data)])
        
        # 删除用户消息
        client = await get_bot_client()
        await async_delete_user_message(client, event.message.chat_id, event.message.id, 0)

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'请选择要管理的转发规则:', buttons=buttons)

    except Exception as e:
        logger.info(f'获取转发规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'获取转发规则时出错，请检查日志')
    finally:
        session.close()

async def handle_switch_command(event):
    """处理 switch 命令"""
    # 显示可切换的规则列表
    current_chat = await event.get_chat()
    current_chat_id = str(current_chat.id)

    session = get_session()
    try:
        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_id
        ).first()

        if not current_chat_db:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'当前聊天没有任何转发规则')
            return

        rules = session.query(ForwardRule).filter(
            ForwardRule.target_chat_id == current_chat_db.id
        ).all()

        if not rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'当前聊天没有任何转发规则')
            return

        current_rule = selected_rule(session, current_chat_db)
        # 创建规则选择按钮
        buttons = []
        for rule in rules:
            source_chat = rule.source_chat
            # 标记当前选中的规则
            current = current_rule is not None and current_rule.id == rule.id
            button_text = f'{"✓ " if current else ""}#{rule.id} {rule.route_label}'
            callback_data = f"switch_rule:{rule.id}"
            buttons.append([Button.inline(button_text, callback_data)])
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'请选择要管理的转发规则:', buttons=buttons)
    finally:
        session.close()

async def handle_add_command(event, command, parts):
    """处理 add 和 add_regex 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'用法: /{command} <关键字1> [关键字2] ...\n例如:\n/{command} keyword1 "key word 2" \'key word 3\'')
        return

    # 分离命令和参数部分
    _, args_text = message_text.split(None, 1)
    logger.info(f"分离出的参数部分: {args_text}")

    keywords = []
    if command in ['add', 'a']:
        try:
            # 使用 shlex 来正确处理带引号的参数
            logger.info("开始使用 shlex 解析参数")
            keywords = shlex.split(args_text)
            logger.info(f"shlex 解析结果: {keywords}")
        except ValueError as e:
            logger.error(f"shlex 解析出错: {str(e)}")
            # 处理未闭合的引号等错误
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'参数格式错误：请确保引号正确配对')
            return
    else:
        # add_regex 命令保持原样
        keywords = parts[1:]
        logger.info(f"add_regex 命令，使用原始参数: {keywords}")

    if not keywords:
        logger.warning("没有提供任何关键字")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'请提供至少一个关键字')
        return

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info
        logger.info(f"当前规则ID: {rule.id}, 源聊天: {source_chat.name}")

        # 使用 db_operations 添加关键字
        db_ops = await get_db_ops()
        logger.info(f"准备添加关键字: {keywords}, is_regex={command == 'add_regex'}, is_blacklist={rule.add_mode == AddMode.BLACKLIST}")
        success_count, duplicate_count = await db_ops.add_keywords(
            session,
            rule.id,
            keywords,
            is_regex=(command == 'add_regex'),
            is_blacklist=(rule.add_mode == AddMode.BLACKLIST)
        )
        logger.info(f"添加结果: 成功={success_count}, 重复={duplicate_count}")

        session.commit()

        # 构建回复消息
        keyword_type = "正则" if command == "add_regex" else "关键字"
        keywords_text = '\n'.join(f'- {k}' for k in keywords)
        result_text = f'已添加 {success_count} 个{keyword_type}'
        if duplicate_count > 0:
            result_text += f'\n跳过重复: {duplicate_count} 个'
        result_text += f'\n关键字列表:\n{keywords_text}\n'
        result_text += f'当前规则: 来自 {source_chat.name}\n'
        mode_text = '白名单' if rule.add_mode == AddMode.WHITELIST else '黑名单'
        result_text += f'当前关键字添加模式: {mode_text}'

        logger.info(f"发送回复消息: {result_text}")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'添加关键字时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'添加关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_replace_command(event, parts):
    """处理 replace 命令"""
    message_text = event.message.text
    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'用法: /replace <匹配规则> [替换内容]\n例如:\n/replace 广告  # 删除匹配内容\n/replace 广告 [已替换]\n/replace "广告 文本" [已替换]\n/replace \'广告 文本\' [已替换]')
        return

    # 直接分割参数，保持正则表达式的原始形式
    try:
        # 去掉命令前缀，获取原始参数字符串
        _, args_text = message_text.split(None, 1)
        
        # 按第一个空格分割，保持后续内容不变
        parts = args_text.split(None, 1)
        if not parts:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'请提供有效的匹配规则')
            return
            
        pattern = parts[0]
        content = parts[1] if len(parts) > 1 else ''
        
        logger.info(f"解析替换命令参数: pattern='{pattern}', content='{content}'")
        
    except ValueError as e:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'参数解析错误: {str(e)}\n请确保引号成对出现')
        return
        
    if not pattern:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'请提供有效的匹配规则')
        return

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 使用 add_replace_rules 添加替换规则
        db_ops = await get_db_ops()
        # 分别传递 patterns 和 contents 参数
        success_count, duplicate_count = await db_ops.add_replace_rules(
            session,
            rule.id,
            [pattern],  # patterns 参数
            [content]   # contents 参数
        )

        # 确保启用替换模式
        if success_count > 0 and not rule.is_replace:
            rule.is_replace = True

        session.commit()

        # 检查是否是全文替换
        rule_type = "全文替换" if pattern == ".*" else "正则替换"
        action_type = "删除" if not content else "替换"

        # 构建回复消息
        result_text = f'已添加{rule_type}规则:\n'
        if success_count > 0:
            result_text += f'匹配: {pattern}\n'
            result_text += f'动作: {action_type}\n'
            result_text += f'{"替换为: " + content if content else "删除匹配内容"}\n'
        if duplicate_count > 0:
            result_text += f'跳过重复规则: {duplicate_count} 个\n'
        result_text += f'当前规则: 来自 {source_chat.name}'

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'添加替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'添加替换规则时出错，请检查日志')
    finally:
        session.close()

async def handle_list_keyword_command(event):
    """处理 list_keyword 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 使用 get_keywords 获取所有关键字
        db_ops = await get_db_ops()
        rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
        keywords = await db_ops.get_keywords(session, rule.id, rule_mode)

        await show_list(
            event,
            'keyword',
            keywords,
            lambda i, kw: f'{i}. {kw.keyword}{" (正则)" if kw.is_regex else ""}',
            f'关键字列表\n当前模式: {"黑名单" if rule.add_mode == AddMode.BLACKLIST else "白名单"}\n规则: 来自 {source_chat.name}'
        )

    finally:
        session.close()

async def handle_list_replace_command(event):
    """处理 list_replace 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 使用 get_replace_rules 获取所有替换规则
        db_ops = await get_db_ops()
        replace_rules = await db_ops.get_replace_rules(session, rule.id)

        await show_list(
            event,
            'replace',
            replace_rules,
            lambda i, rr: f'{i}. 匹配: {rr.pattern} -> {"删除" if not rr.content else f"替换为: {rr.content}"}',
            f'替换规则列表\n规则: 来自 {source_chat.name}'
        )

    finally:
        session.close()

async def handle_remove_command(event, command, parts):
    """处理 remove_keyword 和 remove_replace 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    # 如果是替换规则，保持原来的 ID 删除方式
    if command == 'remove_replace':
        if len(parts) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'用法: /{command} <ID1> [ID2] [ID3] ...\n例如: /{command} 1 2 3')
            return

        try:
            ids_to_remove = [int(x) for x in parts[1:]]
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'ID必须是数字')
            return
    elif command in ['remove_keyword_by_id', 'rkbi']:  # 添加按ID删除关键字的处理
        if len(parts) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'用法: /{command} <ID1> [ID2] [ID3] ...\n例如: /{command} 1 2 3')
            return

        try:
            ids_to_remove = [int(x) for x in parts[1:]]
            logger.info(f"准备按ID删除关键字: {ids_to_remove}")
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'ID必须是数字')
            return
    else:  # remove_keyword
        if len(message_text.split(None, 1)) < 2:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'用法: /{command} <关键字1> [关键字2] ...\n例如:\n/{command} keyword1 "key word 2" \'key word 3\'')
            return

        # 分离命令和参数部分
        _, args_text = message_text.split(None, 1)
        logger.info(f"分离出的参数部分: {args_text}")

        try:
            # 使用 shlex 来正确处理带引号的参数
            logger.info("开始使用 shlex 解析参数")
            keywords_to_remove = shlex.split(args_text)
            logger.info(f"shlex 解析结果: {keywords_to_remove}")
        except ValueError as e:
            logger.error(f"shlex 解析出错: {str(e)}")
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'参数格式错误：请确保引号正确配对')
            return

        if not keywords_to_remove:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'请提供至少一个关键字')
            return

    # 在 try 块外定义 item_type
    item_type = '关键字' if command in ['remove_keyword', 'remove_keyword_by_id', 'rkbi'] else '替换规则'

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info
        rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
        mode_name = "黑名单" if rule.add_mode == AddMode.BLACKLIST else "白名单"

        db_ops = await get_db_ops()
        if command == 'remove_keyword':
            # 获取当前模式下的关键字
            items = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'当前规则在{mode_name}模式下没有任何关键字')
                return

            # 修改：删除匹配的关键字
            removed_count = 0
            removed_indices = [] # 存储要删除的关键字索引
            
            for keyword in keywords_to_remove:
                logger.info(f"尝试删除关键字: {keyword}")
                for i, item in enumerate(items):
                    if item.keyword == keyword:
                        logger.info(f"找到匹配的关键字: {item.keyword}")
                        removed_indices.append(i + 1) # 转为1-based索引
                        removed_count += 1
                        break
            
            if removed_indices:
                # 使用db_ops删除关键字（支持同步功能）
                await db_ops.delete_keywords(session, rule.id, removed_indices)
                session.commit()
                logger.info(f"成功删除 {removed_count} 个关键字")
            
            # 重新获取更新后的列表
            remaining_items = await db_ops.get_keywords(session, rule.id, rule_mode)

            # 显示删除结果
            if removed_count > 0:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"已从{mode_name}中删除 {removed_count} 个关键字")
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"在{mode_name}中未找到匹配的关键字")

        elif command in ['remove_keyword_by_id', 'rkbi']:
            # 获取当前模式下的关键字
            items = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'当前规则在{mode_name}模式下没有任何关键字')
                return

            # 检查ID是否有效
            max_id = len(items)
            invalid_ids = [id for id in ids_to_remove if id < 1 or id > max_id]
            if invalid_ids:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'无效的ID: {", ".join(map(str, invalid_ids))}')
                return

            # 修改：记录要删除的关键字
            removed_count = 0
            removed_keywords = []
            valid_ids = [id for id in ids_to_remove if 1 <= id <= max_id]
            
            for id in valid_ids:
                removed_keywords.append(items[id - 1].keyword)
                
            # 使用db_ops删除关键字（支持同步功能）
            removed_count, _ = await db_ops.delete_keywords(session, rule.id, valid_ids)
            session.commit()
            logger.info(f"成功删除 {removed_count} 个关键字")

            # 构建回复消息
            if removed_count > 0:
                keywords_text = '\n'.join(f'- {k}' for k in removed_keywords)
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,
                    f"已从{mode_name}中删除 {removed_count} 个关键字:\n"
                    f"{keywords_text}"
                )
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"在{mode_name}中未找到匹配的关键字")

        else:  # remove_replace
            # 处理替换规则的删除（保持原有逻辑）
            items = await db_ops.get_replace_rules(session, rule.id)
            if not items:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'当前规则没有任何{item_type}')
                return

            max_id = len(items)
            invalid_ids = [id for id in ids_to_remove if id < 1 or id > max_id]
            if invalid_ids:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'无效的ID: {", ".join(map(str, invalid_ids))}')
                return

            await db_ops.delete_replace_rules(session, rule.id, ids_to_remove)
            session.commit()

            remaining_items = await db_ops.get_replace_rules(session, rule.id)
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'已删除 {len(ids_to_remove)} 个替换规则')

    except Exception as e:
        session.rollback()
        logger.error(f'删除{item_type}时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'删除{item_type}时出错，请检查日志')
    finally:
        session.close()

async def handle_clear_all_command(event):
    """处理 clear_all 命令"""
    session = get_session()
    try:
        # 删除所有替换规则
        replace_count = session.query(ReplaceRule).delete(synchronize_session=False)

        # 删除所有关键字
        keyword_count = session.query(Keyword).delete(synchronize_session=False)

        # 删除所有转发规则
        rule_count = session.query(ForwardRule).delete(synchronize_session=False)

        # 删除所有聊天
        chat_count = session.query(Chat).delete(synchronize_session=False)

        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            '已清空所有数据:\n'
            f'- {chat_count} 个聊天\n'
            f'- {rule_count} 条转发规则\n'
            f'- {keyword_count} 个关键字\n'
            f'- {replace_count} 条替换规则'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清空数据时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'清空数据时出错，请检查日志')
    finally:
        session.close()


async def handle_changelog_command(event):
    """处理 changelog 命令"""
    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,UPDATE_INFO, parse_mode='html')


async def handle_start_command(event):
    """处理 start 命令"""

    welcome_text = f"""
    👋 欢迎使用 Telegram 消息转发机器人！
    
    📱 当前版本：v{VERSION}

    📖 查看完整命令列表请使用 /help

    """
    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,welcome_text)

async def handle_help_command(event, command):
    """处理帮助命令"""
    help_text = (
        f"🤖 **Telegram 消息转发机器人 v{VERSION}**\n\n"

        "**基础命令**\n"
        "/start - 开始使用\n"
        "/help(/h) - 显示此帮助信息\n\n"

        "**绑定和设置**\n"
        "/bind(/b) <源聊天链接或名称> [目标聊天链接或名称] [--source-topic ID] [--target-topic ID]\n"
        "/topic - 查看当前话题 ID（1 为 General）\n"
        "/settings(/s) [规则ID] - 管理转发规则\n"
        "/switch(/sw) - 选择当前操作的具体规则\n"
        "/changelog(/cl) - 查看更新日志\n\n"

        "**转发规则管理**\n"
        "/copy_rule(/cr)  <源规则ID> [目标规则ID] - 复制指定规则的所有设置到当前规则或目标规则ID\n"
        "/list_rule(/lr) - 列出所有转发规则\n"
        "/delete_rule(/dr) <规则ID> [规则ID] [规则ID] ... - 删除指定规则\n\n"

        "**关键字管理**\n"
        "/add(/a) <关键字> [关键字] [\"关 键 字\"] [\'关 键 字\'] ... - 添加普通关键字\n"
        "/add_regex(/ar) <正则表达式> [正则表达式] [正则表达式] ... - 添加正则表达式\n"
        "/add_all(/aa) <关键字> [关键字] [关键字] ... - 添加普通关键字到当前频道绑定的所有规则\n"
        "/add_regex_all(/ara) <正则表达式> [正则表达式] [正则表达式] ... - 添加正则表达式到所有规则\n"
        "/list_keyword(/lk) - 列出所有关键字\n"
        "/remove_keyword(/rk) <关键词1> [\"关 键 字\"] [\'关 键 字\'] ... - 删除关键字\n"
        "/remove_keyword_by_id(/rkbi) <ID> [ID] [ID] ... - 按ID删除关键字\n"
        "/remove_all_keyword(/rak) [关键字] [\"关 键 字\"] [\'关 键 字\'] ... - 删除当前频道绑定的所有规则的指定关键字\n"
        "/clear_all_keywords(/cak) - 清除当前规则的所有关键字\n"
        "/clear_all_keywords_regex(/cakr) - 清除当前规则的所有正则关键字\n"
        "/copy_keywords(/ck) <规则ID> - 复制指定规则的关键字到当前规则\n"
        "/copy_keywords_regex(/ckr) <规则ID> - 复制指定规则的正则关键字到当前规则\n\n"

        "**替换规则管理**\n"
        "/replace(/r) <正则表达式> [替换内容] - 添加替换规则\n"
        "/replace_all(/ra) <正则表达式> [替换内容] - 添加替换规则到所有规则\n"
        "/list_replace(/lrp) - 列出所有替换规则\n"
        "/remove_replace(/rr) <序号> - 删除替换规则\n"
        "/clear_all_replace(/car) - 清除当前规则的所有替换规则\n"
        "/copy_replace(/crp) <规则ID> - 复制指定规则的替换规则到当前规则\n\n"

        "**导入导出**\n"
        "/export_keyword(/ek) - 导出当前规则的关键字\n"
        "/export_replace(/er) - 导出当前规则的替换规则\n"
        "/import_keyword(/ik) <同时发送文件> - 导入普通关键字\n"
        "/import_regex_keyword(/irk) <同时发送文件> - 导入正则关键字\n"
        "/import_replace(/ir) <同时发送文件> - 导入替换规则\n\n"

        "**RSS相关**\n"
        "/delete_rss_user(/dru) [用户名] - 删除RSS用户\n"

        "**UFB相关**\n"
        "/ufb_bind(/ub) <域名> - 绑定UFB域名\n"
        "/ufb_unbind(/uu) - 解绑UFB域名\n"
        "/ufb_item_change(/uic) - 切换UFB同步配置类型\n\n"

        "💡 **提示**\n"
        "• 括号内为命令的简写形式\n"
        "• 尖括号 <> 表示必填参数\n"
        "• 方括号 [] 表示可选参数\n"
        "• 导入命令需要同时发送文件"
    )

    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)

    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
    await reply_and_delete(event,help_text, parse_mode='markdown')

async def handle_export_keyword_command(event, command):
    """处理 export_keyword 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取所有关键字
        normal_keywords = []
        regex_keywords = []

        # 直接从规则对象获取关键字
        for keyword in rule.keywords:
            if keyword.is_regex:
                regex_keywords.append(f"{keyword.keyword} {1 if keyword.is_blacklist else 0}")
            else:
                normal_keywords.append(f"{keyword.keyword} {1 if keyword.is_blacklist else 0}")

        # 创建临时文件
        normal_file = os.path.join(TEMP_DIR, 'keywords.txt')
        regex_file = os.path.join(TEMP_DIR, 'regex_keywords.txt')

        # 写入普通关键字，确保每行一个
        with open(normal_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(normal_keywords))

        # 写入正则关键字，确保每行一个
        with open(regex_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(regex_keywords))

        # 如果两个文件都是空的
        if not normal_keywords and not regex_keywords:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "当前规则没有任何关键字")
            return

        try:
            # 先发送文件
            files = []
            if normal_keywords:
                files.append(normal_file)
            if regex_keywords:
                files.append(regex_file)

            await event.client.send_file(
                event.chat_id,
                files
            )

            # 然后单独发送说明文字
            await respond_and_delete(event,(f"规则: {source_chat.name}"))

        finally:
            # 删除临时文件
            if os.path.exists(normal_file):
                os.remove(normal_file)
            if os.path.exists(regex_file):
                os.remove(regex_file)

    except Exception as e:
        logger.error(f'导出关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'导出关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_import_command(event, command):
    """处理导入命令"""
    try:
        # 检查是否有附件
        if not event.message.file:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'请将文件和 /{command} 命令一起发送')
            return

        # 获取当前规则
        session = get_session()
        try:
            rule_info = await get_current_rule(session, event)
            if not rule_info:
                return

            rule, source_chat = rule_info

            # 下载文件
            file_path = await event.message.download_media(TEMP_DIR)

            try:
                # 读取文件内容
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]

                # 根据命令类型处理
                if command == 'import_replace':
                    success_count = 0
                    logger.info(f'开始导入替换规则,共 {len(lines)} 行')
                    for i, line in enumerate(lines, 1):
                        try:
                            # 按第一个制表符分割
                            parts = line.split('\t', 1)
                            pattern = parts[0].strip()
                            content = parts[1].strip() if len(parts) > 1 else ''

                            logger.info(f'处理第 {i} 行: pattern="{pattern}", content="{content}"')

                            # 创建替换规则
                            replace_rule = ReplaceRule(
                                rule_id=rule.id,
                                pattern=pattern,
                                content=content
                            )
                            session.add(replace_rule)
                            success_count += 1
                            logger.info(f'成功添加替换规则: pattern="{pattern}", content="{content}"')

                            # 确保启用替换模式
                            if not rule.is_replace:
                                rule.is_replace = True
                                logger.info('已启用替换模式')

                        except Exception as e:
                            logger.error(f'处理第 {i} 行替换规则时出错: {str(e)}\n{traceback.format_exc()}')
                            continue

                    session.commit()
                    logger.info(f'导入完成,成功导入 {success_count} 条替换规则')
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,f'成功导入 {success_count} 条替换规则\n规则: 来自 {source_chat.name}')


                else:
                    # 处理关键字导入
                    success_count = 0
                    duplicate_count = 0
                    is_regex = (command == 'import_regex_keyword')
                    for i, line in enumerate(lines, 1):
                        try:
                            # 按空格分割，提取关键字和标志
                            parts = line.split()
                            if len(parts) < 2:
                                raise ValueError("行格式无效，至少需要关键字和标志")
                            flag_str = parts[-1]  # 最后一个部分为标志
                            if flag_str not in ('0', '1'):
                                raise ValueError("标志值必须为 0 或 1")
                            is_blacklist = (flag_str == '1')  # 转换为布尔值
                            keyword = ' '.join(parts[:-1])  # 前面的部分组合为关键字
                            if not keyword:
                                raise ValueError("关键字为空")
                            # 检查是否已存在相同的关键字
                            existing = session.query(Keyword).filter_by(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=is_regex
                            ).first()

                            if existing:
                                duplicate_count += 1
                                continue

                            # 创建新的 Keyword 对象
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=is_regex,
                                is_blacklist=is_blacklist
                            )
                            session.add(new_keyword)
                            success_count += 1

                        except Exception as e:
                            logger.error(f'处理第 {i} 行时出错: {line}\n{str(e)}')
                            continue

                    session.commit()
                    keyword_type = "正则表达式" if is_regex else "关键字"
                    result_text = f'成功导入 {success_count} 个{keyword_type}'
                    if duplicate_count > 0:
                        result_text += f'\n跳过重复: {duplicate_count} 个'
                    result_text += f'\n规则: 来自 {source_chat.name}'
                    await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                    await reply_and_delete(event,result_text)
            finally:
                # 删除临时文件
                if os.path.exists(file_path):
                    os.remove(file_path)

        finally:
            session.close()

    except Exception as e:
        logger.error(f'导入过程出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'导入过程出错，请检查日志')

async def handle_ufb_item_change_command(event, command):
    """处理 ufb_item_change 命令"""

    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 创建4个按钮
        buttons = [
            [
                Button.inline("主页关键字", "ufb_item:main"),
                Button.inline("内容页关键字", "ufb_item:content")
            ],
            [
                Button.inline("主页用户名", "ufb_item:main_username"),
                Button.inline("内容页用户名", "ufb_item:content_username")
            ]
        ]

        # 发送带按钮的消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event, "请选择要切换的UFB同步配置类型:", buttons=buttons)

    except Exception as e:
        session.rollback()
        logger.error(f'切换UFB配置类型时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'切换UFB配置类型时出错，请检查日志')
    finally:
        session.close()

async def handle_ufb_bind_command(event, command):
    """处理 ufb_bind 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 从消息中获取域名和类型
        parts = event.message.text.split()
        if len(parts) < 2 or len(parts) > 3:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'用法: /ufb_bind <域名> [类型]\n类型可选: main, content, main_username, content_username\n例如: /ufb_bind example.com main')
            return

        domain = parts[1].strip().lower()
        item = 'main'  # 默认值

        if len(parts) == 3:
            item = parts[2].strip().lower()
            if item not in ['main', 'content', 'main_username', 'content_username']:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,'类型必须是以下之一: main, content, main_username, content_username')
                return

        # 更新规则的 ufb_domain 和 ufb_item
        rule.ufb_domain = domain
        rule.ufb_item = item
        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'已绑定 UFB 域名: {domain}\n类型: {item}\n规则: 来自 {source_chat.name}')

    except Exception as e:
        session.rollback()
        logger.error(f'绑定 UFB 域名时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'绑定 UFB 域名时出错，请检查日志')
    finally:
        session.close()

async def handle_ufb_unbind_command(event, command):
    """处理 ufb_unbind 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 清除规则的 ufb_domain
        old_domain = rule.ufb_domain
        rule.ufb_domain = None
        session.commit()

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'已解绑 UFB 域名: {old_domain or "无"}\n规则: 来自 {source_chat.name}')

    except Exception as e:
        session.rollback()
        logger.error(f'解绑 UFB 域名时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'解绑 UFB 域名时出错，请检查日志')
    finally:
        session.close()

async def handle_clear_all_keywords_command(event, command):
    """处理清除所有关键字命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取当前规则的关键字数量
        keyword_count = len(rule.keywords)

        if keyword_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "当前规则没有任何关键字")
            return

        # 删除所有关键字
        for keyword in rule.keywords:
            session.delete(keyword)

        session.commit()

        # 发送成功消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已清除规则 `{rule.id}` 的所有关键字\n"
            f"源聊天: {source_chat.name}\n"
            f"共删除: {keyword_count} 个关键字",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清除关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'清除关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_clear_all_keywords_regex_command(event, command):
    """处理清除所有正则关键字命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取当前规则的正则关键字数量
        regex_keywords = [kw for kw in rule.keywords if kw.is_regex]
        keyword_count = len(regex_keywords)

        if keyword_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "当前规则没有任何正则关键字")
            return

        # 删除所有正则关键字
        for keyword in regex_keywords:
            session.delete(keyword)

        session.commit()

        # 发送成功消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已清除规则 `{rule.id}` 的所有正则关键字\n"
            f"源聊天: {source_chat.name}\n"
            f"共删除: {keyword_count} 个正则关键字",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清除正则关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'清除正则关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_clear_all_replace_command(event, command):
    """处理清除所有替换规则命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取当前规则的替换规则数量
        replace_count = len(rule.replace_rules)

        if replace_count == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "当前规则没有任何替换规则")
            return

        # 删除所有替换规则
        for replace_rule in rule.replace_rules:
            session.delete(replace_rule)

        # 如果没有替换规则了，关闭替换模式
        rule.is_replace = False

        session.commit()

        # 发送成功消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已清除规则 `{rule.id}` 的所有替换规则\n"
            f"源聊天: {source_chat.name}\n"
            f"共删除: {replace_count} 个替换规则\n"
            "已自动关闭替换模式",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'清除替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'清除替换规则时出错，请检查日志')
    finally:
        session.close()

async def handle_copy_keywords_command(event, command):
    """处理复制关键字命令"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'用法: /copy_keywords <规则ID>')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'规则ID必须是数字')
        return

    session = get_session()
    try:
        # 获取当前规则
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'找不到规则ID: {source_rule_id}')
            return

        # 复制关键字
        success_count = 0
        skip_count = 0

        for keyword in source_rule.keywords:
            if not keyword.is_regex:  # 只复制普通关键字
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and not k.is_regex
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    success_count += 1
                else:
                    skip_count += 1

        session.commit()

        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已从规则 `{source_rule_id}` 复制关键字到规则 `{target_rule.id}`\n"
            f"成功复制: {success_count} 个\n"
            f"跳过重复: {skip_count} 个",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'复制关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_copy_keywords_regex_command(event, command):
    """处理复制正则关键字命令"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'用法: /copy_keywords_regex <规则ID>')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'规则ID必须是数字')
        return

    session = get_session()
    try:
        # 获取当前规则
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'找不到规则ID: {source_rule_id}')
            return

        # 复制正则关键字
        success_count = 0
        skip_count = 0

        for keyword in source_rule.keywords:
            if keyword.is_regex:  # 只复制正则关键字
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and k.is_regex
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    success_count += 1
                else:
                    skip_count += 1

        session.commit()

        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已从规则 `{source_rule_id}` 复制正则关键字到规则 `{target_rule.id}`\n"
            f"成功复制: {success_count} 个\n"
            f"跳过重复: {skip_count} 个",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制正则关键字时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'复制正则关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_copy_replace_command(event, command):
    """处理复制替换规则命令"""
    parts = event.message.text.split()
    if len(parts) != 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'用法: /copy_replace <规则ID>')
        return

    try:
        source_rule_id = int(parts[1])
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'规则ID必须是数字')
        return

    session = get_session()
    try:
        # 获取当前规则
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        target_rule, source_chat = rule_info

        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'找不到规则ID: {source_rule_id}')
            return

        # 复制替换规则
        success_count = 0
        skip_count = 0

        for replace_rule in source_rule.replace_rules:
            # 检查是否已存在
            exists = any(r.pattern == replace_rule.pattern
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                success_count += 1
            else:
                skip_count += 1

        session.commit()

        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已从规则 `{source_rule_id}` 复制替换规则到规则 `{target_rule.id}`\n"
            f"成功复制: {success_count} 个\n"
            f"跳过重复: {skip_count} 个\n",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'复制替换规则时出错，请检查日志')
    finally:
        session.close()

async def handle_copy_rule_command(event, command):
    """处理复制规则命令 - 复制一个规则的所有设置到当前规则或指定规则"""
    parts = event.message.text.split()
    
    # 检查参数数量
    if len(parts) not in [2, 3]:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'用法: /copy_rule <源规则ID> [目标规则ID]')
        return

    try:
        source_rule_id = int(parts[1])
        
        # 确定目标规则ID
        if len(parts) == 3:
            # 如果提供了两个参数，使用第二个参数作为目标规则ID
            target_rule_id = int(parts[2])
            use_current_rule = False
        else:
            # 如果只提供了一个参数，使用当前规则作为目标
            target_rule_id = None
            use_current_rule = True
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'规则ID必须是数字')
        return

    session = get_session()
    try:
        # 获取源规则
        source_rule = session.query(ForwardRule).get(source_rule_id)
        if not source_rule:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f'找不到源规则ID: {source_rule_id}')
            return

        # 获取目标规则
        if use_current_rule:
            # 获取当前规则
            rule_info = await get_current_rule(session, event)
            if not rule_info:
                return
            target_rule, source_chat = rule_info
        else:
            # 使用指定的目标规则ID
            target_rule = session.query(ForwardRule).get(target_rule_id)
            if not target_rule:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f'找不到目标规则ID: {target_rule_id}')
                return

        if source_rule.id == target_rule.id:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'不能复制规则到自身')
            return

        # 记录复制的各个部分成功数量
        keywords_normal_success = 0
        keywords_normal_skip = 0
        keywords_regex_success = 0
        keywords_regex_skip = 0
        replace_rules_success = 0
        replace_rules_skip = 0
        media_extensions_success = 0
        media_extensions_skip = 0


        # 复制普通关键字
        for keyword in source_rule.keywords:
            if not keyword.is_regex:
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and not k.is_regex and k.is_blacklist == keyword.is_blacklist
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=False,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_normal_success += 1
                else:
                    keywords_normal_skip += 1

        # 复制正则关键字
        for keyword in source_rule.keywords:
            if keyword.is_regex:
                # 检查是否已存在
                exists = any(k.keyword == keyword.keyword and k.is_regex and k.is_blacklist == keyword.is_blacklist
                             for k in target_rule.keywords)
                if not exists:
                    new_keyword = Keyword(
                        rule_id=target_rule.id,
                        keyword=keyword.keyword,
                        is_regex=True,
                        is_blacklist=keyword.is_blacklist
                    )
                    session.add(new_keyword)
                    keywords_regex_success += 1
                else:
                    keywords_regex_skip += 1

        # 复制替换规则
        for replace_rule in source_rule.replace_rules:
            # 检查是否已存在
            exists = any(r.pattern == replace_rule.pattern and r.content == replace_rule.content
                         for r in target_rule.replace_rules)
            if not exists:
                new_rule = ReplaceRule(
                    rule_id=target_rule.id,
                    pattern=replace_rule.pattern,
                    content=replace_rule.content
                )
                session.add(new_rule)
                replace_rules_success += 1
            else:
                replace_rules_skip += 1

        # 复制媒体扩展名设置
        if hasattr(source_rule, 'media_extensions') and source_rule.media_extensions:
            for extension in source_rule.media_extensions:
                # 检查是否已存在
                exists = any(e.extension == extension.extension for e in target_rule.media_extensions)
                if not exists:
                    new_extension = MediaExtensions(
                        rule_id=target_rule.id,
                        extension=extension.extension
                    )
                    session.add(new_extension)
                    media_extensions_success += 1
                else:
                    media_extensions_skip += 1

        # 复制媒体类型设置
        if hasattr(source_rule, 'media_types') and source_rule.media_types:
            target_media_types = session.query(MediaTypes).filter_by(rule_id=target_rule.id).first()

            if not target_media_types:
                # 如果目标规则没有媒体类型设置，创建新的
                target_media_types = MediaTypes(rule_id=target_rule.id)

                # 使用inspect自动复制所有字段（除了id和rule_id）
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

                session.add(target_media_types)
            else:
                # 如果已有设置，更新现有设置
                # 使用inspect自动复制所有字段（除了id和rule_id）
                media_inspector = inspect(MediaTypes)
                for column in media_inspector.columns:
                    column_name = column.key
                    if column_name not in ['id', 'rule_id']:
                        setattr(target_media_types, column_name, getattr(source_rule.media_types, column_name))

        # 复制规则同步表数据
        rule_syncs_success = 0
        rule_syncs_skip = 0
        
        # 检查源规则是否有同步关系
        if hasattr(source_rule, 'rule_syncs') and source_rule.rule_syncs:
            for sync in source_rule.rule_syncs:
                # 检查是否已存在
                exists = any(s.sync_rule_id == sync.sync_rule_id for s in target_rule.rule_syncs)
                if not exists:
                    # 确保不会创建自引用的同步关系
                    if sync.sync_rule_id != target_rule.id:
                        new_sync = RuleSync(
                            rule_id=target_rule.id,
                            sync_rule_id=sync.sync_rule_id
                        )
                        session.add(new_sync)
                        rule_syncs_success += 1
                        
                        # 启用目标规则的同步功能
                        if rule_syncs_success > 0:
                            target_rule.enable_sync = True
                else:
                    rule_syncs_skip += 1

        # 复制规则设置
        # 获取ForwardRule模型的所有字段
        inspector = inspect(ForwardRule)
        for column in inspector.columns:
            column_name = column.key
            if column_name not in ['id', 'source_chat_id', 'target_chat_id', 'source_topic_id', 'target_topic_id', 'source_chat', 'target_chat',
                                      'keywords', 'replace_rules', 'media_types']:
                # 获取源规则的值并设置到目标规则
                value = getattr(source_rule, column_name)
                setattr(target_rule, column_name, value)

        session.commit()


        # 发送结果消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,
            f"✅ 已从规则 `{source_rule_id}` 复制到规则 `{target_rule.id}`\n\n"
            f"普通关键字: 成功复制 {keywords_normal_success} 个, 跳过重复 {keywords_normal_skip} 个\n"
            f"正则关键字: 成功复制 {keywords_regex_success} 个, 跳过重复 {keywords_regex_skip} 个\n"
            f"替换规则: 成功复制 {replace_rules_success} 个, 跳过重复 {replace_rules_skip} 个\n"
            f"媒体扩展名: 成功复制 {media_extensions_success} 个, 跳过重复 {media_extensions_skip} 个\n"
            f"同步规则: 成功复制 {rule_syncs_success} 个, 跳过重复 {rule_syncs_skip} 个\n"
            f"媒体类型设置和其他规则设置已复制\n",
            parse_mode='markdown'
        )

    except Exception as e:
        session.rollback()
        logger.error(f'复制规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'复制规则时出错，请检查日志')
    finally:
        session.close()

async def handle_export_replace_command(event, client):
    """处理 export_replace 命令"""
    session = get_session()
    try:
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        rule, source_chat = rule_info

        # 获取所有替换规则
        replace_rules = []
        for rule in rule.replace_rules:
            replace_rules.append((rule.pattern, rule.content))

        # 如果没有替换规则
        if not replace_rules:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "当前规则没有任何替换规则")
            return

        # 创建并写入文件
        replace_file = os.path.join(TEMP_DIR, 'replace_rules.txt')

        # 写入替换规则，每行一个规则，用制表符分隔
        with open(replace_file, 'w', encoding='utf-8') as f:
            for pattern, content in replace_rules:
                line = f"{pattern}\t{content if content else ''}"
                f.write(line + '\n')

        try:
            # 先发送文件
            await event.client.send_file(
                event.chat_id,
                replace_file
            )

            # 然后单独发送说明文字
            await respond_and_delete(event,(f"规则: {source_chat.name}"))

        finally:
            # 删除临时文件
            if os.path.exists(replace_file):
                os.remove(replace_file)

    except Exception as e:
        logger.error(f'导出替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'导出替换规则时出错，请检查日志')
    finally:
        session.close()


async def handle_remove_all_keyword_command(event, command, parts):
    """处理 remove_all_keyword 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'用法: /{command} <关键字1> [关键字2] ...\n例如:\n/{command} keyword1 "key word 2" \'key word 3\'')
        return

    # 分离命令和参数部分
    _, args_text = message_text.split(None, 1)
    logger.info(f"分离出的参数部分: {args_text}")

    try:
        # 使用 shlex 来正确处理带引号的参数
        logger.info("开始使用 shlex 解析参数")
        keywords_to_remove = shlex.split(args_text)
        logger.info(f"shlex 解析结果: {keywords_to_remove}")
    except ValueError as e:
        logger.error(f"shlex 解析出错: {str(e)}")
        # 处理未闭合的引号等错误
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'参数格式错误：请确保引号正确配对')
        return

    if not keywords_to_remove:
        logger.warning("没有提供任何关键字")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'请提供至少一个关键字')
        return

    session = get_session()
    try:
        # 获取当前规则以确定黑白名单模式
        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return
        current_rule, source_chat = rule_info
        mode_name = "黑名单" if current_rule.add_mode == AddMode.BLACKLIST else "白名单"

        # 获取所有相关规则
        rules = await get_all_rules(session, event)
        if not rules:
            return

        db_ops = await get_db_ops()
        total_removed = 0
        total_not_found = 0
        removed_details = {}  # 用于记录每个规则删除的关键字

        # 从每个规则中删除关键字
        for rule in rules:
            # 获取当前规则的关键字
            rule_mode = "blacklist" if rule.add_mode == AddMode.BLACKLIST else "whitelist"
            keywords = await db_ops.get_keywords(session, rule.id, rule_mode)

            if not keywords:
                continue

            rule_removed = 0
            rule_removed_keywords = []

            # 删除匹配的关键字
            for keyword in keywords:
                if keyword.keyword in keywords_to_remove:
                    logger.info(f"在规则 {rule.id} 中删除关键字: {keyword.keyword}")
                    session.delete(keyword)
                    rule_removed += 1
                    rule_removed_keywords.append(keyword.keyword)

            if rule_removed > 0:
                removed_details[rule.id] = rule_removed_keywords
                total_removed += rule_removed
            else:
                total_not_found += 1

        session.commit()

        # 构建回复消息
        if total_removed > 0:
            result_text = f"已从{mode_name}中删除关键字:\n\n"
            for rule_id, keywords in removed_details.items():
                rule = next((r for r in rules if r.id == rule_id), None)
                if rule:
                    result_text += f"规则 {rule_id} (来自: {rule.source_chat.name}):\n"
                    result_text += "\n".join(f"- {k}" for k in keywords)
                    result_text += "\n\n"
            result_text += f"总计删除: {total_removed} 个关键字"

            logger.info(f"发送回复消息: {result_text}")
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,result_text)
        else:
            msg = f"在{mode_name}中未找到匹配的关键字"
            logger.info(msg)
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,msg)

    except Exception as e:
        session.rollback()
        logger.error(f'批量删除关键字时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'删除关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_add_all_command(event, command, parts):
    """处理 add_all 和 add_regex_all 命令"""
    message_text = event.message.text
    logger.info(f"收到原始消息: {message_text}")

    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'用法: /{command} <关键字1> [关键字2] ...\n例如:\n/{command} keyword1 "key word 2" \'key word 3\'')
        return

    # 分离命令和参数部分
    _, args_text = message_text.split(None, 1)
    logger.info(f"分离出的参数部分: {args_text}")

    keywords = []
    if command == 'add_all':
        try:
            # 使用 shlex 来正确处理带引号的参数
            logger.info("开始使用 shlex 解析参数")
            keywords = shlex.split(args_text)
            logger.info(f"shlex 解析结果: {keywords}")
        except ValueError as e:
            logger.error(f"shlex 解析出错: {str(e)}")
            # 处理未闭合的引号等错误
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'参数格式错误：请确保引号正确配对')
            return
    else:
        # add_regex_all 命令使用简单分割，保持正则表达式的原始形式
        if len(args_text.split()) > 0:
            keywords = args_text.split()
        else:
            keywords = [args_text]
        logger.info(f"add_regex_all 命令，使用原始参数: {keywords}")

    if not keywords:
        logger.warning("没有提供任何关键字")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'请提供至少一个关键字')
        return

    session = get_session()
    try:
        rules = await get_all_rules(session, event)
        if not rules:
            return

        rule_info = await get_current_rule(session, event)
        if not rule_info:
            return

        current_rule, source_chat = rule_info

        db_ops = await get_db_ops()
        # 为每个规则添加关键字
        success_count = 0
        duplicate_count = 0
        for rule in rules:
            # 使用 add_keywords 添加关键字
            s_count, d_count = await db_ops.add_keywords(
                session,
                rule.id,
                keywords,
                is_regex=(command == 'add_regex_all'),
                is_blacklist=(current_rule.add_mode == AddMode.BLACKLIST)
            )
            success_count += s_count
            duplicate_count += d_count

        session.commit()

        # 构建回复消息
        keyword_type = "正则表达式" if command == "add_regex_all" else "关键字"
        keywords_text = '\n'.join(f'- {k}' for k in keywords)
        result_text = f'已添加 {success_count} 个{keyword_type}\n'
        if duplicate_count > 0:
            result_text += f'跳过重复: {duplicate_count} 个\n'
        result_text += f'关键字列表:\n{keywords_text}'

        logger.info(f"发送回复消息: {result_text}")
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'批量添加关键字时出错: {str(e)}\n{traceback.format_exc()}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'添加关键字时出错，请检查日志')
    finally:
        session.close()

async def handle_replace_all_command(event, parts):
    """处理 replace_all 命令"""
    message_text = event.message.text
    
    if len(message_text.split(None, 1)) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'用法: /replace_all <匹配规则> [替换内容]\n例如:\n/replace_all 广告  # 删除匹配内容\n/replace_all 广告 [已替换]')
        return

    # 直接分割参数，保持正则表达式的原始形式
    _, args_text = message_text.split(None, 1)
    
    # 按第一个空格分割，保持后续内容不变
    parts = args_text.split(None, 1)
    pattern = parts[0]
    content = parts[1] if len(parts) > 1 else ''
    
    logger.info(f"解析替换命令参数: pattern='{pattern}', content='{content}'")

    session = get_session()
    try:
        rules = await get_all_rules(session, event)
        if not rules:
            return

        db_ops = await get_db_ops()
        # 为每个规则添加替换规则
        total_success = 0
        total_duplicate = 0

        for rule in rules:
            # 使用 add_replace_rules 添加替换规则
            success_count, duplicate_count = await db_ops.add_replace_rules(
                session,
                rule.id,
                [(pattern, content)]  # 传入一个元组列表，每个元组包含 pattern 和 content
            )

            # 累计成功和重复的数量
            total_success += success_count
            total_duplicate += duplicate_count

            # 确保启用替换模式
            if success_count > 0 and not rule.is_replace:
                rule.is_replace = True

        session.commit()

        # 构建回复消息
        action_type = "删除" if not content else "替换"
        result_text = f'已为 {len(rules)} 个规则添加替换规则:\n'
        if total_success > 0:
            result_text += f'成功添加: {total_success} 个\n'
            result_text += f'匹配模式: {pattern}\n'
            result_text += f'动作: {action_type}\n'
            if content:
                result_text += f'替换为: {content}\n'
        if total_duplicate > 0:
            result_text += f'跳过重复规则: {total_duplicate} 个'

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,result_text)

    except Exception as e:
        session.rollback()
        logger.error(f'批量添加替换规则时出错: {str(e)}')
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'添加替换规则时出错，请检查日志')
    finally:
        session.close()

async def handle_list_rule_command(event, command, parts):
    """处理 list_rule 命令"""
    session = get_session()
    try:
        # 获取页码参数，默认为第1页
        try:
            page = int(parts[1]) if len(parts) > 1 else 1
            if page < 1:
                page = 1
        except ValueError:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'页码必须是数字')
            return

        # 设置每页显示的数量
        per_page = 30
        offset = (page - 1) * per_page

        # 获取总规则数
        total_rules = session.query(ForwardRule).count()

        if total_rules == 0:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,'当前没有任何转发规则')
            return

        # 计算总页数
        total_pages = (total_rules + per_page - 1) // per_page

        # 如果请求的页码超出范围，使用最后一页
        if page > total_pages:
            page = total_pages
            offset = (page - 1) * per_page

        # 获取当前页的规则
        rules = session.query(ForwardRule).order_by(ForwardRule.id).offset(offset).limit(per_page).all()

        # 构建规则列表消息
        message_parts = [f'📋 转发规则列表 (第{page}/{total_pages}页)：\n']

        for rule in rules:
            # 获取源聊天和目标聊天的名称
            source_chat = rule.source_chat
            target_chat = rule.target_chat

            # 构建规则描述
            rule_desc = (
                f'<b>ID: {rule.id}</b>\n'
                f'<blockquote>来源: {rule.source_label} ({source_chat.telegram_chat_id})\n'
                f'目标: {rule.target_label} ({target_chat.telegram_chat_id})\n'
                '</blockquote>'
            )
            message_parts.append(rule_desc)

        # 创建分页按钮
        buttons = []
        nav_row = []

        # 添加上一页按钮
        if page > 1:
            nav_row.append(Button.inline('⬅️ 上一页', f'page_rule:{page-1}'))
        else:
            nav_row.append(Button.inline('⬅️', 'noop'))  # 禁用状态的按钮

        # 添加页码按钮
        nav_row.append(Button.inline(f'{page}/{total_pages}', 'noop'))

        # 添加下一页按钮
        if page < total_pages:
            nav_row.append(Button.inline('下一页 ➡️', f'page_rule:{page+1}'))
        else:
            nav_row.append(Button.inline('➡️', 'noop'))  # 禁用状态的按钮

        buttons.append(nav_row)

        # 发送消息
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'\n'.join(message_parts), buttons=buttons, parse_mode='html')

    except Exception as e:
        logger.error(f'列出规则时出错: {str(e)}')
        logger.exception(e)
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'获取规则列表时发生错误，请检查日志')
    finally:
        session.close()

async def handle_delete_rule_command(event, command, parts):
    """处理 delete_rule 命令"""
    if len(parts) < 2:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f'用法: /{command} <ID1> [ID2] [ID3] ...\n例如: /{command} 1 2 3')
        return

    try:
        ids_to_remove = [int(x) for x in parts[1:]]
    except ValueError:
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'ID必须是数字')
        return

    session = get_session()
    try:
        success_ids = []
        failed_ids = []
        not_found_ids = []

        for rule_id in ids_to_remove:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                not_found_ids.append(rule_id)
                continue

            try:
                # 删除规则（关联的替换规则、关键字和媒体类型会自动删除）
                session.query(Chat).filter(Chat.current_rule_id == rule.id).update(
                    {Chat.current_rule_id: None, Chat.current_add_id: None}, synchronize_session='fetch')
                session.delete(rule)

                # 尝试从RSS服务删除规则数据
                try:
                    rss_url = f"http://{RSS_HOST}:{RSS_PORT}/api/rule/{rule_id}"
                    async with aiohttp.ClientSession() as client_session:
                        async with client_session.delete(rss_url) as response:
                            if response.status == 200:
                                logger.info(f"成功删除RSS规则数据: {rule_id}")
                            else:
                                response_text = await response.text()
                                logger.warning(f"删除RSS规则数据失败 {rule_id}, 状态码: {response.status}, 响应: {response_text}")
                except Exception as rss_err:
                    logger.error(f"调用RSS删除API时出错: {str(rss_err)}")
                    # 不影响主要流程，继续执行

                success_ids.append(rule_id)
            except Exception as e:
                logger.error(f'删除规则 {rule_id} 时出错: {str(e)}')
                failed_ids.append(rule_id)

        # 提交事务
        session.commit()
        
        # 清理不再使用的聊天记录
        # 这里直接对整个数据库进行一次清理，不需要单独处理每个规则
        # 因为所有规则都已经从数据库中删除
        deleted_chats = await check_and_clean_chats(session)
        if deleted_chats > 0:
            logger.info(f"删除规则后清理了 {deleted_chats} 个未使用的聊天记录")

        # 构建响应消息
        response_parts = []
        if success_ids:
            response_parts.append(f'✅ 成功删除规则: {", ".join(map(str, success_ids))}')
        if not_found_ids:
            response_parts.append(f'❓ 未找到规则: {", ".join(map(str, not_found_ids))}')
        if failed_ids:
            response_parts.append(f'❌ 删除失败的规则: {", ".join(map(str, failed_ids))}')
        if deleted_chats > 0:
            response_parts.append(f'🧹 清理了 {deleted_chats} 个未使用的聊天记录')

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'\n'.join(response_parts) or '没有规则被删除')

    except Exception as e:
        session.rollback()
        logger.error(f'删除规则时出错: {str(e)}')
        logger.exception(e)
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,'删除规则时发生错误，请检查日志')
    finally:
        session.close()


async def handle_delete_rss_user_command(event, command, parts):
    """处理 delete_rss_user 命令"""
    db_ops = await get_db_ops()
    session = get_session()

    try:
        # 检查是否指定了用户名
        specified_username = None
        if len(parts) > 1:
            specified_username = parts[1].strip()

        # 查询所有用户
        users = session.query(models.User).all()

        if not users:
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event, "RSS系统中没有用户账户")
            return

        # 占位，不排除以后有多用户功能，如果指定了用户名，尝试删除该用户
        if specified_username:
            user = session.query(models.User).filter(models.User.username == specified_username).first()
            if user:
                session.delete(user)
                session.commit()
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"已删除RSS用户: {specified_username}")
                return
            else:
                await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
                await reply_and_delete(event,f"未找到用户名为 '{specified_username}' 的RSS用户")
                return

        # 如果没有指定用户名
        # 默认只有一个用户，直接删除
        if len(users) == 1:
            user = users[0]
            username = user.username
            session.delete(user)
            session.commit()
            await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
            await reply_and_delete(event,f"已删除RSS用户: {username}")
            return

        # 占位，不排除以后有多用户功能，如果有多个用户，则列出所有用户并提示指定用户名
        usernames = [user.username for user in users]
        user_list = "\n".join([f"{i+1}. {username}" for i, username in enumerate(usernames)])

        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,f"RSS系统中有多个用户，请使用 `/delete_rss_user <用户名>` 指定要删除的用户:\n\n{user_list}")

    except Exception as e:
        session.rollback()
        error_message = f"删除RSS用户时出错: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
        await async_delete_user_message(event.client, event.message.chat_id, event.message.id, 0)
        await reply_and_delete(event,error_message)
    finally:
        session.close()
