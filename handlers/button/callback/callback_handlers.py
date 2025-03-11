from handlers.button.button_helpers import create_delay_time_buttons
from handlers.list_handlers import show_list
from handlers.button.settings_manager import create_settings_text, create_buttons, RULE_SETTINGS
from models.models import Chat, ReplaceRule, Keyword,get_session
from telethon import Button
from handlers.button.callback.ai_callback import *
from handlers.button.callback.media_callback import *
import logging
import aiohttp
from utils.constants import RSS_HOST, RSS_PORT
from utils.auto_delete import respond_and_delete,reply_and_delete

logger = logging.getLogger(__name__)


async def callback_switch(event, rule_id, session, message, data):
    """处理切换源聊天的回调"""
    # 获取当前聊天
    current_chat = await event.get_chat()
    current_chat_db = session.query(Chat).filter(
        Chat.telegram_chat_id == str(current_chat.id)
    ).first()

    if not current_chat_db:
        await event.answer('当前聊天不存在')
        return

    # 如果已经选中了这个聊天，就不做任何操作
    if current_chat_db.current_add_id == rule_id:
        await event.answer('已经选中该聊天')
        return

    # 更新当前选中的源聊天
    current_chat_db.current_add_id = rule_id  # 这里的 rule_id 实际上是源聊天的 telegram_chat_id
    session.commit()

    # 更新按钮显示
    rules = session.query(ForwardRule).filter(
        ForwardRule.target_chat_id == current_chat_db.id
    ).all()

    buttons = []
    for rule in rules:
        source_chat = rule.source_chat
        current = source_chat.telegram_chat_id == rule_id
        button_text = f'{"✓ " if current else ""}来自: {source_chat.name}'
        callback_data = f"switch:{source_chat.telegram_chat_id}"
        buttons.append([Button.inline(button_text, callback_data)])

    try:
        await message.edit('请选择要管理的转发规则:', buttons=buttons)
    except Exception as e:
        if 'message was not modified' not in str(e).lower():
            raise  # 如果是其他错误就继续抛出

    source_chat = session.query(Chat).filter(
        Chat.telegram_chat_id == rule_id
    ).first()
    await event.answer(f'已切换到: {source_chat.name if source_chat else "未知聊天"}')

async def callback_settings(event, rule_id, session, message, data):
    """处理显示设置的回调"""
    # 获取当前聊天
    current_chat = await event.get_chat()
    current_chat_db = session.query(Chat).filter(
        Chat.telegram_chat_id == str(current_chat.id)
    ).first()

    if not current_chat_db:
        await event.answer('当前聊天不存在')
        return

    rules = session.query(ForwardRule).filter(
        ForwardRule.target_chat_id == current_chat_db.id
    ).all()

    if not rules:
        await event.answer('当前聊天没有任何转发规则')
        return

    # 创建规则选择按钮
    buttons = []
    for rule in rules:
        source_chat = rule.source_chat
        button_text = f'{source_chat.name}'
        callback_data = f"rule_settings:{rule.id}"
        buttons.append([Button.inline(button_text, callback_data)])

    await message.edit('请选择要管理的转发规则:', buttons=buttons)

async def callback_delete(event, rule_id, session, message, data):
    """处理删除规则的回调"""
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('规则不存在')
        return

    try:
        # 保存源频道ID以供后续检查
        source_chat_id = rule.source_chat_id

        # 先删除替换规则
        session.query(ReplaceRule).filter(
            ReplaceRule.rule_id == rule.id
        ).delete()

        # 再删除关键字
        session.query(Keyword).filter(
            Keyword.rule_id == rule.id
        ).delete()

        # 删除规则
        db_ops = await DBOperations.create()
        success, msg = await db_ops.delete_forward_rule(session, rule_id)
        # session.delete(rule)

        # 检查源频道是否还有其他规则引用
        remaining_rules = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat_id
        ).count()

        # if remaining_rules == 0:
        #     # 如果没有其他规则引用这个源频道，删除源频道记录
            
            
        if not success:
            await event.answer(f'删除失败: {msg}')
            return

        # 提交所有更改
        session.commit()
        
        # 尝试删除RSS服务中的相关数据
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

        # 更新消息
                # 删除机器人的消息
        await message.delete()
        # 发送新的通知消息
        await respond_and_delete(event,('✅ 已删除规则'))
        await event.answer('已删除规则')

    except Exception as e:
        session.rollback()
        logger.error(f'删除规则时出错: {str(e)}')
        logger.exception(e)
        await event.answer('删除规则失败，请检查日志')

async def callback_page(event, rule_id, session, message, data):
    """处理翻页的回调"""
    logger.info(f'翻页回调数据: action=page, rule_id={rule_id}')

    try:
        # 解析页码和命令
        page_number, command = rule_id.split(':')
        page = int(page_number)

        # 获取当前聊天和规则
        current_chat = await event.get_chat()
        current_chat_db = session.query(Chat).filter(
            Chat.telegram_chat_id == str(current_chat.id)
        ).first()

        if not current_chat_db or not current_chat_db.current_add_id:
            await event.answer('请先选择一个源聊天')
            return

        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == current_chat_db.current_add_id
        ).first()

        rule = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id,
            ForwardRule.target_chat_id == current_chat_db.id
        ).first()

        if command == 'keyword':
            # 获取关键字列表
            keywords = session.query(Keyword).filter(
                Keyword.rule_id == rule.id
            ).all()

            await show_list(
                event,
                'keyword',
                keywords,
                lambda i, kw: f'{i}. {kw.keyword}{" (正则)" if kw.is_regex else ""}',
                f'关键字列表\n规则: 来自 {source_chat.name}',
                page
            )

        elif command == 'replace':
            # 获取替换规则列表
            replace_rules = session.query(ReplaceRule).filter(
                ReplaceRule.rule_id == rule.id
            ).all()

            await show_list(
                event,
                'replace',
                replace_rules,
                lambda i, rr: f'{i}. 匹配: {rr.pattern} -> {"删除" if not rr.content else f"替换为: {rr.content}"}',
                f'替换规则列表\n规则: 来自 {source_chat.name}',
                page
            )

        # 标记回调已处理
        await event.answer()

    except Exception as e:
        logger.error(f'处理翻页时出错: {str(e)}')
        await event.answer('处理翻页时出错，请检查日志')



async def callback_rule_settings(event, rule_id, session, message, data):
    """处理规则设置的回调"""
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('规则不存在')
        return

    await message.edit(
        await create_settings_text(rule),
        buttons=await create_buttons(rule,event)
    )

async def callback_toggle_current(event, rule_id, session, message, data):
    """处理切换当前规则的回调"""
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('规则不存在')
        return

    # 更新当前选中的源聊天
    db_ops = await get_db_ops()
    await db_ops.update_apply_rule_chat(session,rule_id,event.chat_id)

    # 更新按钮显示
    await message.edit(
        await create_settings_text(rule),
        buttons=await create_buttons(rule,event)
    )

    await event.answer(f'已切换到')



async def callback_set_delay_time(event, rule_id, session, message, data):
    await event.edit("请选择延迟时间：", buttons=await create_delay_time_buttons(rule_id, page=0))
    return



async def callback_delay_time_page(event, rule_id, session, message, data):
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("请选择延迟时间：", buttons=await create_delay_time_buttons(rule_id, page=page))
    return

            


async def callback_select_delay_time(event, rule_id, session, message, data):
    parts = data.split(':', 2)  # 最多分割2次
    if len(parts) == 3:
        _, rule_id, time = parts
        logger.info(f"设置规则 {rule_id} 的延迟时间为: {time}")
        try:
            rule = session.query(ForwardRule).get(int(rule_id))
            if rule:
                # 记录旧时间
                old_time = rule.delay_seconds

                # 更新时间
                rule.delay_seconds = int(time)
                session.commit()
                logger.info(f"数据库更新成功: {old_time} -> {time}")

                # 获取消息对象
                message = await event.get_message()

                await message.edit(
                    await create_settings_text(rule),
                    buttons=await create_buttons(rule,event)
                )
                logger.info("界面更新完成")
        except Exception as e:
            logger.error(f"设置延迟时间时出错: {str(e)}")
            logger.error(f"错误详情: {traceback.format_exc()}")
        finally:
            session.close()
    return


async def callback_close_settings(event, rule_id, session, message, data):
    """处理关闭设置按钮的回调，删除当前消息"""
    try:
        logger.info("执行关闭设置操作，准备删除消息")
        await message.delete()
    except Exception as e:
        logger.error(f"删除消息时出错: {str(e)}")
        await event.answer("关闭设置失败，请检查日志")

async def callback_noop(event, rule_id, session, message, data):
    # 用于页码按钮，不做任何操作
    await event.answer("当前页码")
    return


async def callback_page_rule(event, page_str, session, message, data):
    """处理规则列表分页的回调"""
    try:
        page = int(page_str)
        if page < 1:
            await event.answer('已经是第一页了')
            return

        per_page = 30
        offset = (page - 1) * per_page

        # 获取总规则数
        total_rules = session.query(ForwardRule).count()
        
        if total_rules == 0:
            await event.answer('没有任何规则')
            return

        # 计算总页数
        total_pages = (total_rules + per_page - 1) // per_page

        if page > total_pages:
            await event.answer('已经是最后一页了')
            return

        # 获取当前页的规则
        rules = session.query(ForwardRule).order_by(ForwardRule.id).offset(offset).limit(per_page).all()
            
        # 构建规则列表消息
        message_parts = [f'📋 转发规则列表 (第{page}/{total_pages}页)：\n']
        
        for rule in rules:
            source_chat = rule.source_chat
            target_chat = rule.target_chat
            
            rule_desc = (
                f'<b>ID: {rule.id}</b>\n'
                f'<blockquote>来源: {source_chat.name} ({source_chat.telegram_chat_id})\n'
                f'目标: {target_chat.name} ({target_chat.telegram_chat_id})\n'
                '</blockquote>'
            )
            message_parts.append(rule_desc)

        # 创建分页按钮
        buttons = []
        nav_row = []

        if page > 1:
            nav_row.append(Button.inline('⬅️ 上一页', f'page_rule:{page-1}'))
        else:
            nav_row.append(Button.inline('⬅️', 'noop'))

        nav_row.append(Button.inline(f'{page}/{total_pages}', 'noop'))

        if page < total_pages:
            nav_row.append(Button.inline('下一页 ➡️', f'page_rule:{page+1}'))
        else:
            nav_row.append(Button.inline('➡️', 'noop'))

        buttons.append(nav_row)

        await message.edit('\n'.join(message_parts), buttons=buttons, parse_mode='html')
        await event.answer()

    except Exception as e:
        logger.error(f'处理规则列表分页时出错: {str(e)}')
        await event.answer('处理分页请求时出错，请检查日志')

async def handle_callback(event):
    """处理按钮回调"""
    try:
        data = event.data.decode()
        logger.info(f'收到回调数据: {data}')


        # 解析回调数据
        parts = data.split(':')
        action = parts[0]
        rule_id = ':'.join(parts[1:]) if len(parts) > 1 else None
        logger.info(f'解析回调数据: action={action}, rule_id={rule_id}')

        # 获取消息对象
        message = await event.get_message()

        # 使用会话
        session = get_session()
        try:  

            # 获取对应的处理器
            handler = CALLBACK_HANDLERS.get(action)
            if handler:
                await handler(event, rule_id, session, message, data)
            else:
                # 处理规则设置的切换
                for field_name, config in RULE_SETTINGS.items():
                    if action == config['toggle_action']:
                        rule = session.query(ForwardRule).get(int(rule_id))
                        if not rule:
                            await event.answer('规则不存在')
                            return

                        current_value = getattr(rule, field_name)
                        new_value = config['toggle_func'](current_value)
                        setattr(rule, field_name, new_value)

                        try:
                            session.commit()
                            logger.info(f'更新规则 {rule.id} 的 {field_name} 从 {current_value} 到 {new_value}')

                            # 如果切换了转发方式，立即更新按钮
                            try:
                                await message.edit(
                                    await create_settings_text(rule),
                                    buttons=await create_buttons(rule,event)
                                )
                            except Exception as e:
                                if 'message was not modified' not in str(e).lower():
                                    raise

                            display_name = config['display_name']
                            if field_name == 'use_bot':
                                await event.answer(f'已切换到{"机器人" if new_value else "用户账号"}模式')
                            else:
                                await event.answer(f'已更新{display_name}')
                        except Exception as e:
                            session.rollback()
                            logger.error(f'更新规则设置时出错: {str(e)}')
                            await event.answer('更新设置失败，请检查日志')
                        break
        finally:
            session.close()

    except Exception as e:
        if 'message was not modified' not in str(e).lower():
            logger.error(f'处理按钮回调时出错: {str(e)}')
            logger.error(f'错误堆栈: {traceback.format_exc()}')
            await event.answer('处理请求时出错，请检查日志')



# 回调处理器字典
CALLBACK_HANDLERS = {
    'toggle_current': callback_toggle_current,
    'switch': callback_switch,
    'settings': callback_settings,
    'delete': callback_delete,
    'page': callback_page,
    'rule_settings': callback_rule_settings,
    'set_summary_time': callback_set_summary_time,
    'set_delay_time': callback_set_delay_time,
    'select_delay_time': callback_select_delay_time,
    'delay_time_page': callback_delay_time_page,
    'page_rule': callback_page_rule,
    'close_settings': callback_close_settings,
    # AI设置
    'set_summary_prompt': callback_set_summary_prompt,
    'set_ai_prompt': callback_set_ai_prompt,
    'toggle_top_summary': callback_toggle_top_summary,
    'ai_settings': callback_ai_settings,
    'toggle_summary': callback_toggle_summary,
    'time_page': callback_time_page,
    'select_time': callback_select_time,
    'select_model': callback_select_model,
    'model_page': callback_model_page,
    'toggle_keyword_after_ai': callback_toggle_keyword_after_ai,
    'toggle_ai': callback_toggle_ai,
    'change_model': callback_change_model,
    'cancel_set_prompt': callback_cancel_set_prompt,
    'cancel_set_summary': callback_cancel_set_summary,
    'summary_now':callback_summary_now,
    # 媒体设置
    'select_max_media_size': callback_select_max_media_size,
    'set_max_media_size': callback_set_max_media_size,
    'toggle_enable_media_size_filter': callback_toggle_enable_media_size_filter,
    'toggle_send_over_media_size_message': callback_toggle_send_over_media_size_message,
    'toggle_enable_media_type_filter': callback_toggle_enable_media_type_filter,
    'toggle_enable_media_extension_filter': callback_toggle_enable_media_extension_filter,
    'toggle_media_extension_filter_mode': callback_toggle_media_extension_filter_mode,
    'media_settings': callback_media_settings,
    'set_media_types': callback_set_media_types,
    'toggle_media_type': callback_toggle_media_type,
    'set_media_extensions': callback_set_media_extensions,
    'media_extensions_page': callback_media_extensions_page,
    'toggle_media_extension': callback_toggle_media_extension,
    'noop': callback_noop,
}