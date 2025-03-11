import os
import traceback
from managers.state_manager import state_manager
import asyncio
from telethon.tl import types

from handlers.button.button_helpers import create_ai_settings_buttons, create_model_buttons, create_summary_time_buttons
from models.models import ForwardRule
from telethon import Button
import logging
from utils.common import get_main_module, get_ai_settings_text
from utils.common import is_admin
from scheduler.summary_scheduler import SummaryScheduler


logger = logging.getLogger(__name__)


async def callback_ai_settings(event, rule_id, session, message, data):
    # 显示 AI 设置页面
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
    finally:
        session.close()
    return



async def callback_set_summary_time(event, rule_id, session, message, data):
    await event.edit("请选择总结时间：", buttons=await create_summary_time_buttons(rule_id, page=0))
    return

async def callback_set_summary_prompt(event, rule_id, session, message, data):
    """处理设置AI总结提示词的回调"""
    logger.info(f"开始处理设置AI总结提示词回调 - event: {event}, rule_id: {rule_id}")
    
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('规则不存在')
        return

    # 检查是否频道消息
    if isinstance(event.chat, types.Channel):
        # 检查是否是管理员
        if not await is_admin(event.chat_id, event.sender_id, event.client):
            await event.answer('只有管理员可以修改设置')
            return
        user_id = os.getenv('USER_ID')
    else:
        user_id = event.sender_id

    chat_id = abs(event.chat_id)
    state = f"set_summary_prompt:{rule_id}"
    
    logger.info(f"准备设置状态 - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message)
        # 启动超时取消任务
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("状态设置成功")
    except Exception as e:
        logger.error(f"设置状态时出错: {str(e)}")
        logger.exception(e)

    try:
        current_prompt = rule.summary_prompt or os.getenv('DEFAULT_SUMMARY_PROMPT', '未设置')
        await message.edit(
            f"请发送新的AI总结提示词\n"
            f"当前规则ID: `{rule_id}`\n"
            f"当前AI总结提示词：\n\n`{current_prompt}`\n\n"
            f"5分钟内未设置将自动取消",
            buttons=[[Button.inline("取消", f"cancel_set_summary:{rule_id}")]]
        )
        logger.info("消息编辑成功")
    except Exception as e:
        logger.error(f"编辑消息时出错: {str(e)}")
        logger.exception(e)


async def cancel_state_after_timeout(user_id: int, chat_id: int, timeout_minutes: int = 5):
    """在指定时间后自动取消状态"""
    await asyncio.sleep(timeout_minutes * 60)
    current_state = state_manager.get_state(user_id, chat_id)
    if current_state:  # 只有当状态还存在时才清除
        logger.info(f"状态超时自动取消 - user_id: {user_id}, chat_id: {chat_id}")
        state_manager.clear_state(user_id, chat_id)


async def callback_set_ai_prompt(event, rule_id, session, message, data):
    """处理设置AI提示词的回调"""
    logger.info(f"开始处理设置AI提示词回调 - event: {event}, rule_id: {rule_id}")

    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('规则不存在')
        return

    # 检查是否频道消息
    if isinstance(event.chat, types.Channel):
        # 检查是否是管理员
        if not await is_admin(event.chat_id, event.sender_id, event.client):
            await event.answer('只有管理员可以修改设置')
            return
        user_id = os.getenv('USER_ID')
    else:
        user_id = event.sender_id

    chat_id = abs(event.chat_id)
    state = f"set_ai_prompt:{rule_id}"

    logger.info(f"准备设置状态 - user_id: {user_id}, chat_id: {chat_id}, state: {state}")
    try:
        state_manager.set_state(user_id, chat_id, state, message)
        # 启动超时取消任务
        asyncio.create_task(cancel_state_after_timeout(user_id, chat_id))
        logger.info("状态设置成功")
    except Exception as e:
        logger.error(f"设置状态时出错: {str(e)}")
        logger.exception(e)

    try:
        current_prompt = rule.ai_prompt or os.getenv('DEFAULT_AI_PROMPT', '未设置')
        await message.edit(
            f"请发送新的AI提示词\n"
            f"当前规则ID: `{rule_id}`\n"
            f"当前AI提示词：\n\n`{current_prompt}`\n\n"
            f"5分钟内未设置将自动取消",
            buttons=[[Button.inline("取消", f"cancel_set_prompt:{rule_id}")]]
        )
        logger.info("消息编辑成功")
    except Exception as e:
        logger.error(f"编辑消息时出错: {str(e)}")
        logger.exception(e)



async def callback_toggle_top_summary(event, rule_id, session, message, data):
    """处理切换顶置总结消息的回调"""
    logger.info(f"处理切换顶置总结消息回调 - rule_id: {rule_id}")
    rule = session.query(ForwardRule).get(rule_id)
    if not rule:
        await event.answer('规则不存在')
        return

    # 切换状态
    rule.is_top_summary = not rule.is_top_summary
    session.commit()
    logger.info(f"已更新规则 {rule_id} 的顶置总结状态为: {rule.is_top_summary}")

    # 更新按钮
    await message.edit(
        buttons=await create_ai_settings_buttons(rule)
    )
    
    # 显示提示
    await event.answer(f"已{'开启' if rule.is_top_summary else '关闭'}顶置总结消息")


async def callback_toggle_summary(event, rule_id, session, message, data):
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            rule.is_summary = not rule.is_summary
            session.commit()

            # 更新调度任务
            main = await get_main_module()
            if hasattr(main, 'scheduler') and main.scheduler:
                await main.scheduler.schedule_rule(rule)
            else:
                logger.warning("调度器未初始化")

            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
    finally:
        session.close()
    return        
            

async def callback_time_page(event, rule_id, session, message, data):
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("请选择总结时间：", buttons=await create_summary_time_buttons(rule_id, page=page))
    return


async def callback_select_time(event, rule_id, session, message, data):
    parts = data.split(':', 2)  # 最多分割2次
    if len(parts) == 3:
        _, rule_id, time = parts
        logger.info(f"设置规则 {rule_id} 的总结时间为: {time}")
        try:
            rule = session.query(ForwardRule).get(int(rule_id))
            if rule:
                # 记录旧时间
                old_time = rule.summary_time

                # 更新时间
                rule.summary_time = time
                session.commit()
                logger.info(f"数据库更新成功: {old_time} -> {time}")

                # 如果总结功能已开启，重新调度任务
                if rule.is_summary:
                    logger.info("规则已启用总结功能，开始更新调度任务")
                    main = await get_main_module()
                    if hasattr(main, 'scheduler') and main.scheduler:
                        await main.scheduler.schedule_rule(rule)
                        logger.info(f"调度任务更新成功，新时间: {time}")
                    else:
                        logger.warning("调度器未初始化")
                else:
                    logger.info("规则未启用总结功能，跳过调度任务更新")

                await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
                logger.info("界面更新完成")
        except Exception as e:
            logger.error(f"设置总结时间时出错: {str(e)}")
            logger.error(f"错误详情: {traceback.format_exc()}")
        finally:
            session.close()
    return


async def callback_select_model(event, rule_id, session, message, data):
    # 处理模型选择
    _, rule_id, model = data.split(':')
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            rule.ai_model = model
            session.commit()
            logger.info(f"已更新规则 {rule_id} 的AI模型为: {model}")

            # 返回到 AI 设置页面
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
    finally:
        session.close()
    return



async def callback_model_page(event, rule_id, session, message, data):
    # 处理翻页
    _, rule_id, page = data.split(':')
    page = int(page)
    await event.edit("请选择AI模型：", buttons=await create_model_buttons(rule_id, page=page))
    return


async def callback_toggle_keyword_after_ai(event, rule_id, session, message, data):
    try:
        rule = session.query(ForwardRule).get(int(rule_id))             
        rule.is_keyword_after_ai = not rule.is_keyword_after_ai
        session.commit()
        await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
        await event.answer(f'AI处理后关键字过滤已{"开启" if rule.is_keyword_after_ai else "关闭"}')
        return
    finally:
        session.close()


async def callback_toggle_ai(event, rule_id, session, message, data):
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        rule.is_ai = not rule.is_ai
        session.commit()
        await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
        return
    finally:
        session.close()


async def callback_change_model(event, rule_id, session, message, data):
    await event.edit("请选择AI模型：", buttons=await create_model_buttons(rule_id, page=0))
    return



async def callback_cancel_set_prompt(event, rule_id, session, message, data):
    # 处理取消设置提示词
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # 清除状态
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # 返回到 AI 设置页面
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
            await event.answer("已取消设置")
    finally:
        session.close()
    return




async def callback_cancel_set_summary(event, rule_id, session, message, data):
    # 处理取消设置总结
    rule_id = data.split(':')[1]
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if rule:
            # 清除状态
            state_manager.clear_state(event.sender_id, abs(event.chat_id))
            # 返回到 AI 设置页面
            await event.edit(await get_ai_settings_text(rule), buttons=await create_ai_settings_buttons(rule))
            await event.answer("已取消设置")
    finally:
        session.close()
    return

async def callback_summary_now(event, rule_id, session, message, data):
    # 处理立即执行总结的回调
    logger.info(f"处理立即执行总结回调 - rule_id: {rule_id}")
    
    try:
        rule = session.query(ForwardRule).get(int(rule_id))
        if not rule:
            await event.answer("规则不存在")
            return
        
        main = await get_main_module()
        user_client = main.user_client
        bot_client = main.bot_client

        scheduler = SummaryScheduler(user_client, bot_client)
        await event.answer("开始执行总结，请稍候...")
        
        await message.edit(
            f"正在为规则 {rule_id}（{rule.source_chat.name} -> {rule.target_chat.name}）生成总结...\n"
            f"处理需要一定时间，请耐心等待。",
            buttons=[[Button.inline("返回", f"ai_settings:{rule_id}")]]
        )
        
        try:
            # 执行总结任务
            await asyncio.create_task(scheduler._execute_summary(rule.id,is_now=True))
            logger.info(f"已启动规则 {rule_id} 的立即总结任务")
        except Exception as e:
            logger.error(f"执行总结任务失败: {str(e)}")
            logger.error(traceback.format_exc())
            await message.edit(
                f"总结生成失败: {str(e)}",
                buttons=[[Button.inline("返回", f"ai_settings:{rule_id}")]]
            )
    except Exception as e:
        logger.error(f"处理总结时出错: {str(e)}")
        logger.error(traceback.format_exc())
        await event.answer(f"处理时出错: {str(e)}")
    finally:
        session.close()
    
    return
