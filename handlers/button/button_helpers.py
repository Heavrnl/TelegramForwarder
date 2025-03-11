from telethon import Button
from utils.constants import *
from utils.settings import load_summary_times, load_ai_models, load_delay_times, load_max_media_size, load_media_extensions
from handlers.button.settings_manager import AI_SETTINGS, AI_MODELS, MEDIA_SETTINGS
from utils.common import get_db_ops
from models.models import get_session
from sqlalchemy import text

SUMMARY_TIMES = load_summary_times()
AI_MODELS= load_ai_models()
DELAY_TIMES = load_delay_times()
MEDIA_SIZE = load_max_media_size()
MEDIA_EXTENSIONS = load_media_extensions()
async def create_ai_settings_buttons(rule):
    """创建 AI 设置按钮"""
    buttons = []

    # 添加 AI 设置按钮
    for field, config in AI_SETTINGS.items():
        # 非属性的项
        if field == 'summary_now':
            display_value = config['display_name']
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(display_value, callback_data)])
            continue
            
        # 特殊处理提示词设置    
        if field == 'ai_prompt' or field == 'summary_prompt':
            display_value = config['display_name']
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(display_value, callback_data)])
            continue

        elif field == 'ai_model':
            current_value = getattr(rule, field)
            display_value = current_value or os.getenv('DEFAULT_AI_MODEL')
        else:
            current_value = getattr(rule, field)
            display_value = config['values'].get(current_value, str(current_value))
        button_text = f"{config['display_name']}: {display_value}"
        callback_data = f"{config['toggle_action']}:{rule.id}"
        buttons.append([Button.inline(button_text, callback_data)])

    # 添加返回按钮
    buttons.append([
        Button.inline('👈 返回', f"rule_settings:{rule.id}"),
        Button.inline('关闭', "close_settings")
    ])
    
    return buttons

async def create_media_settings_buttons(rule):
    """创建媒体设置按钮"""
    buttons = []

    for field, config in MEDIA_SETTINGS.items():
        # 特殊处理selected_media_types字段，因为它已经移动到单独的表中
        if field == 'selected_media_types':
            display_value = f"{config['display_name']}"
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(display_value, callback_data)])
            continue
        elif field == 'max_media_size':
            display_value = f"{config['display_name']}: {rule.max_media_size} MB"
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(display_value, callback_data)])
            continue
        elif field == 'media_extensions':
            display_value = f"{config['display_name']}"
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(display_value, callback_data)])
            continue
        else:
            current_value = getattr(rule, field)
            display_value = config['values'].get(current_value, str(current_value))
        button_text = f"{config['display_name']}: {display_value}"
        callback_data = f"{config['toggle_action']}:{rule.id}"
        buttons.append([Button.inline(button_text, callback_data)])
    
    # 添加返回按钮
    buttons.append([
        Button.inline('👈 返回', f"rule_settings:{rule.id}"),
        Button.inline('关闭', "close_settings")
    ])

    return buttons



async def create_list_buttons(total_pages, current_page, command):
    """创建分页按钮"""
    buttons = []
    row = []

    # 上一页按钮
    if current_page > 1:
        row.append(Button.inline(
            '⬅️ 上一页',
            f'page:{current_page-1}:{command}'
        ))

    # 页码显示
    row.append(Button.inline(
        f'{current_page}/{total_pages}',
        'noop:0'  # 空操作
    ))

    # 下一页按钮
    if current_page < total_pages:
        row.append(Button.inline(
            '下一页 ➡️',
            f'page:{current_page+1}:{command}'
        ))

    buttons.append(row)
    return buttons




# 添加模型选择按钮创建函数
async def create_model_buttons(rule_id, page=0):
    """创建模型选择按钮，支持分页

    Args:
        rule_id: 规则ID
        page: 当前页码（从0开始）
    """
    buttons = []
    total_models = len(AI_MODELS)
    total_pages = (total_models + MODELS_PER_PAGE - 1) // MODELS_PER_PAGE

    # 计算当前页的模型范围
    start_idx = page * MODELS_PER_PAGE
    end_idx = min(start_idx + MODELS_PER_PAGE, total_models)

    # 添加模型按钮
    for model in AI_MODELS[start_idx:end_idx]:
        buttons.append([Button.inline(f"{model}", f"select_model:{rule_id}:{model}")])

    # 添加导航按钮
    nav_buttons = []
    if page > 0:  # 不是第一页，显示"上一页"
        nav_buttons.append(Button.inline("⬅️ 上一页", f"model_page:{rule_id}:{page - 1}"))
    # 添加页码显示在中间
    nav_buttons.append(Button.inline(f"{page + 1}/{total_pages}", f"noop:{rule_id}"))
    if page < total_pages - 1:  # 不是最后一页，显示"下一页"
        nav_buttons.append(Button.inline("下一页 ➡️", f"model_page:{rule_id}:{page + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    # 添加返回按钮
    buttons.append([Button.inline("返回", f"rule_settings:{rule_id}")])

    return buttons


async def create_summary_time_buttons(rule_id, page=0):
    """创建时间选择按钮"""
    # 从环境变量获取布局设置
    rows = SUMMARY_TIME_ROWS
    cols = SUMMARY_TIME_COLS
    times_per_page = rows * cols

    buttons = []
    total_times = len(SUMMARY_TIMES)
    start_idx = page * times_per_page
    end_idx = min(start_idx + times_per_page, total_times)

    # 检查是否是频道消息
    buttons = []
    total_times = len(SUMMARY_TIMES)

    # 添加时间按钮
    current_row = []
    for i, time in enumerate(SUMMARY_TIMES[start_idx:end_idx], start=1):
        current_row.append(Button.inline(
            time,
            f"select_time:{rule_id}:{time}"
        ))

        # 当达到每行的列数时，添加当前行并重置
        if i % cols == 0:
            buttons.append(current_row)
            current_row = []

    # 添加最后一个不完整的行
    if current_row:
        buttons.append(current_row)

    # 添加导航按钮
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline(
            "⬅️ 上一页",
            f"time_page:{rule_id}:{page - 1}"
        ))

    nav_buttons.append(Button.inline(
        f"{page + 1}/{(total_times + times_per_page - 1) // times_per_page}",
        "noop:0"
    ))

    if end_idx < total_times:
        nav_buttons.append(Button.inline(
            "下一页 ➡️",
            f"time_page:{rule_id}:{page + 1}"
        ))

    buttons.append(nav_buttons)
    buttons.append([
            Button.inline('👈 返回', f"ai_settings:{rule_id}"),
            Button.inline('关闭', "close_settings")
        ])

    return buttons


async def create_media_size_buttons(rule_id, page=0):
    """创建媒体大小选择按钮"""
    # 从环境变量获取布局设置
    rows = MEDIA_SIZE_ROWS
    cols = MEDIA_SIZE_COLS
    size_select_per_page = rows * cols

    buttons = []
    total_size = len(MEDIA_SIZE)
    start_idx = page * size_select_per_page
    end_idx = min(start_idx + size_select_per_page, total_size)

    # 检查是否是频道消息
    buttons = []
    total_size = len(MEDIA_SIZE)

    # 添加媒体大小按钮
    current_row = []
    for i, size in enumerate(MEDIA_SIZE[start_idx:end_idx], start=1):
        current_row.append(Button.inline(
            str(size),
            f"select_max_media_size:{rule_id}:{size}"
        ))

        # 当达到每行的列数时，添加当前行并重置
        if i % cols == 0:
            buttons.append(current_row)
            current_row = []

    # 添加最后一个不完整的行
    if current_row:
        buttons.append(current_row)

    # 添加导航按钮
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline(
            "⬅️ 上一页",
            f"media_size_page:{rule_id}:{page - 1}"
        ))

    nav_buttons.append(Button.inline(
        f"{page + 1}/{(total_size + size_select_per_page - 1) // size_select_per_page}",
        "noop:0"
    ))

    if end_idx < total_size:
        nav_buttons.append(Button.inline(
            "下一页 ➡️",
            f"media_size_page:{rule_id}:{page + 1}"
        ))

    buttons.append(nav_buttons)

    buttons.append([
            Button.inline('👈 返回', f"rule_settings:{rule_id}"),
            Button.inline('关闭', "close_settings")
        ])

    return buttons

async def create_delay_time_buttons(rule_id, page=0):
    """创建延迟时间选择按钮"""
    # 从环境变量获取布局设置
    rows = DELAY_TIME_ROWS
    cols = DELAY_TIME_COLS

    times_per_page = rows * cols

    buttons = []
    total_times = len(DELAY_TIMES)
    start_idx = page * times_per_page
    end_idx = min(start_idx + times_per_page, total_times)

    # 检查是否是频道消息
    buttons = []
    total_times = len(DELAY_TIMES)

    # 添加时间按钮
    current_row = []
    for i, time in enumerate(DELAY_TIMES[start_idx:end_idx], start=1):
        current_row.append(Button.inline(
            str(time),
            f"select_delay_time:{rule_id}:{time}"
        ))

        # 当达到每行的列数时，添加当前行并重置
        if i % cols == 0:
            buttons.append(current_row)
            current_row = []

    # 添加最后一个不完整的行
    if current_row:
        buttons.append(current_row)

    # 添加导航按钮
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline(
            "⬅️ 上一页",
            f"delay_time_page:{rule_id}:{page - 1}"
        ))

    nav_buttons.append(Button.inline(
        f"{page + 1}/{(total_times + times_per_page - 1) // times_per_page}",
        "noop:0"
    ))

    if end_idx < total_times:
        nav_buttons.append(Button.inline(
            "下一页 ➡️",
            f"delay_time_page:{rule_id}:{page + 1}"
        ))

    buttons.append(nav_buttons)

    buttons.append([
            Button.inline('👈 返回', f"rule_settings:{rule_id}"),
            Button.inline('关闭', "close_settings")
        ])

    return buttons

async def create_media_types_buttons(rule_id, media_types):
    """创建媒体类型选择按钮
    
    Args:
        rule_id: 规则ID
        media_types: MediaTypes对象
    
    Returns:
        按钮列表
    """
    buttons = []
    
    # 媒体类型按钮
    media_type_names = {
        'photo': '📷 图片',
        'document': '📄 文档',
        'video': '🎬 视频',
        'audio': '🎵 音频',
        'voice': '🎤 语音'
    }
    
    for field, display_name in media_type_names.items():
        # 获取当前值
        current_value = getattr(media_types, field, False)
        # 如果为True，添加勾选标记
        button_text = f"{'✅ ' if current_value else ''}{display_name}"
        callback_data = f"toggle_media_type:{rule_id}:{field}"
        buttons.append([Button.inline(button_text, callback_data)])
    
    buttons.append([
            Button.inline('👈 返回', f"media_settings:{rule_id}"),
            Button.inline('关闭', "close_settings")
        ])
    
    return buttons



async def create_media_extensions_buttons(rule_id, page=0):
    """创建媒体扩展名选择按钮
    
    Args:
        rule_id: 规则ID
        page: 当前页码
    
    Returns:
        按钮列表
    """
    # 从环境变量获取布局设置
    rows = MEDIA_EXTENSIONS_ROWS
    cols = MEDIA_EXTENSIONS_COLS
    
    extensions_per_page = rows * cols
    
    buttons = []
    total_extensions = len(MEDIA_EXTENSIONS)
    start_idx = page * extensions_per_page
    end_idx = min(start_idx + extensions_per_page, total_extensions)
    
    # 获取当前规则已选择的扩展名
    db_ops = await get_db_ops()
    session = get_session()
    selected_extensions = []
    try:
        # 使用db_ops.get_media_extensions方法获取已选择的扩展名
        selected_extensions = await db_ops.get_media_extensions(session, rule_id)
        selected_extension_list = [ext["extension"] for ext in selected_extensions]
    
        # 创建扩展名按钮
        current_row = []
        for i in range(start_idx, end_idx):
            ext = MEDIA_EXTENSIONS[i]
            # 检查是否已选择
            is_selected = ext in selected_extension_list
            button_text = f"{'✅ ' if is_selected else ''}{ext}"
            # 在回调数据中包含页码信息
            callback_data = f"toggle_media_extension:{rule_id}:{ext}:{page}"
            
            current_row.append(Button.inline(button_text, callback_data))
            
            # 每行放置cols个按钮
            if len(current_row) == cols:
                buttons.append(current_row)
                current_row = []
        
        # 添加剩余的按钮
        if current_row:
            buttons.append(current_row)
        
        # 添加分页按钮
        page_buttons = []
        total_pages = (total_extensions + extensions_per_page - 1) // extensions_per_page
        
        if total_pages > 1:
            # 上一页按钮
            if page > 0:
                page_buttons.append(Button.inline("⬅️", f"media_extensions_page:{rule_id}:{page-1}"))
            else:
                page_buttons.append(Button.inline("⬅️", f"noop"))
            
            # 页码指示
            page_buttons.append(Button.inline(f"{page+1}/{total_pages}", f"noop"))
            
            # 下一页按钮
            if page < total_pages - 1:
                page_buttons.append(Button.inline("➡️", f"media_extensions_page:{rule_id}:{page+1}"))
            else:
                page_buttons.append(Button.inline("➡️", f"noop"))
        
        if page_buttons:
            buttons.append(page_buttons)
        

        buttons.append([
            Button.inline('👈 返回', f"media_settings:{rule_id}"),
            Button.inline('关闭', "close_settings")
        ])
    finally:
        session.close()
    
    return buttons


