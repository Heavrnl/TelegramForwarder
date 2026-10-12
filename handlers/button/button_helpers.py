from telethon import Button
from utils.constants import *
from utils.settings import load_summary_times, load_ai_models, load_delay_times, load_max_media_size, load_media_extensions
from handlers.button.settings_manager import AI_SETTINGS, AI_MODELS, MEDIA_SETTINGS,OTHER_SETTINGS, PUSH_SETTINGS
from utils.common import get_db_ops
from models.models import get_session
from sqlalchemy import text
from models.models import ForwardRule

SUMMARY_TIMES = load_summary_times()
AI_MODELS= load_ai_models()
DELAY_TIMES = load_delay_times()
MEDIA_SIZE = load_max_media_size()
MEDIA_EXTENSIONS = load_media_extensions()
async def create_ai_settings_buttons(rule=None,rule_id=None):
    """Create AI settings buttons"""
    buttons = []

    # Add AI settings buttons
    for field, config in AI_SETTINGS.items():
        # Non-attribute items
        if field == 'summary_now':
            display_value = config['display_name']
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(display_value, callback_data)])
            continue
            
        # Special handling for prompt settings    
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

    # Add back button
    buttons.append([
        Button.inline('👈 Back', f"rule_settings:{rule.id}"),
        Button.inline('❌ Close', "close_settings")
    ])
    
    return buttons

async def create_media_settings_buttons(rule=None,rule_id=None):
    """Create media settings buttons"""
    buttons = []

    for field, config in MEDIA_SETTINGS.items():
        # Special handling for selected_media_types field (moved to separate table)
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
        elif field == 'media_allow_text':
            current_value = getattr(rule, field)
            display_value = config['values'].get(current_value, str(current_value))
            button_text = f"{config['display_name']}: {display_value}"
            callback_data = f"{config['toggle_action']}:{rule.id}"
            buttons.append([Button.inline(button_text, callback_data)])
            continue
        else:
            current_value = getattr(rule, field)
            display_value = config['values'].get(current_value, str(current_value))
        button_text = f"{config['display_name']}: {display_value}"
        callback_data = f"{config['toggle_action']}:{rule.id}"
        buttons.append([Button.inline(button_text, callback_data)])
    
    # Add back button
    buttons.append([
        Button.inline('👈 Back', f"rule_settings:{rule.id}"),
        Button.inline('❌ Close', "close_settings")
    ])

    return buttons

async def create_other_settings_buttons(rule=None,rule_id=None):
    """Create other settings buttons"""
    buttons = []
    
    if rule_id is None:
        rule_id = rule.id
    else:
        session = get_session()
        try:
            rule = session.query(ForwardRule).get(int(rule_id))
        finally:
            session.close()

    current_row = []
    for field, config in OTHER_SETTINGS.items():
        if field in ['reverse_blacklist', 'reverse_whitelist']:
            is_enabled = getattr(rule, f'enable_{field}', False)
            display_value = f"{'✅ ' if is_enabled else ''}{config['display_name']}"
            callback_data = f"{config['toggle_action']}:{rule_id}"

            current_row.append(Button.inline(display_value, callback_data))
            

            if field == 'reverse_whitelist':
                buttons.append(current_row)
                current_row = []
        else:
            # Other buttons get their own row
            display_value = f"{config['display_name']}"
            callback_data = f"{config['toggle_action']}:{rule_id}"
            buttons.append([Button.inline(display_value, callback_data)])

    # Add back button
    buttons.append([
        Button.inline('👈 Back', f"rule_settings:{rule_id}"),
        Button.inline('❌ Close', "close_settings")
    ])

    return buttons


async def create_list_buttons(total_pages, current_page, command):
    """Create pagination buttons"""
    buttons = []
    row = []

    # Previous page button
    if current_page > 1:
        row.append(Button.inline(
            '⬅️ Prev',
            f'page:{current_page-1}:{command}'
        ))

    # Page number display
    row.append(Button.inline(
        f'{current_page}/{total_pages}',
        'noop:0'  # no-op
    ))

    # Next page button
    if current_page < total_pages:
        row.append(Button.inline(
            'Next ➡️',
            f'page:{current_page+1}:{command}'
        ))

    buttons.append(row)
    return buttons




# Model selection button creation function
async def create_model_buttons(rule_id, page=0):
    """Create model selection buttons with pagination.

    Args:
        rule_id: Rule ID
        page: Current page (0-indexed)
    """
    buttons = []
    total_models = len(AI_MODELS)
    total_pages = (total_models + MODELS_PER_PAGE - 1) // MODELS_PER_PAGE

    # Calculate model range for current page
    start_idx = page * MODELS_PER_PAGE
    end_idx = min(start_idx + MODELS_PER_PAGE, total_models)

    # Add model buttons
    for model in AI_MODELS[start_idx:end_idx]:
        buttons.append([Button.inline(f"{model}", f"select_model:{rule_id}:{model}")])

    # Add navigation buttons
    nav_buttons = []
    if page > 0:  # Not first page, show Prev
        nav_buttons.append(Button.inline("⬅️ Prev", f"model_page:{rule_id}:{page - 1}"))
    # Show page number in center
    nav_buttons.append(Button.inline(f"{page + 1}/{total_pages}", f"noop:{rule_id}"))
    if page < total_pages - 1:  # Not last page, show Next
        nav_buttons.append(Button.inline("Next ➡️", f"model_page:{rule_id}:{page + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    # Add back button
    buttons.append([Button.inline("Back", f"rule_settings:{rule_id}")])

    return buttons


async def create_summary_time_buttons(rule_id, page=0):
    """Create time selection buttons"""
    # Get layout settings from environment variables
    rows = SUMMARY_TIME_ROWS
    cols = SUMMARY_TIME_COLS
    times_per_page = rows * cols

    buttons = []
    total_times = len(SUMMARY_TIMES)
    start_idx = page * times_per_page
    end_idx = min(start_idx + times_per_page, total_times)

    # Check if channel message
    buttons = []
    total_times = len(SUMMARY_TIMES)

    # Add time buttons
    current_row = []
    for i, time in enumerate(SUMMARY_TIMES[start_idx:end_idx], start=1):
        current_row.append(Button.inline(
            time,
            f"select_time:{rule_id}:{time}"
        ))

        # When row is full, append and reset
        if i % cols == 0:
            buttons.append(current_row)
            current_row = []

    # Append any remaining partial row
    if current_row:
        buttons.append(current_row)

    # Add navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline(
            "⬅️ Prev",
            f"time_page:{rule_id}:{page - 1}"
        ))

    nav_buttons.append(Button.inline(
        f"{page + 1}/{(total_times + times_per_page - 1) // times_per_page}",
        "noop:0"
    ))

    if end_idx < total_times:
        nav_buttons.append(Button.inline(
            "Next ➡️",
            f"time_page:{rule_id}:{page + 1}"
        ))

    buttons.append(nav_buttons)
    buttons.append([
            Button.inline('👈 Back', f"ai_settings:{rule_id}"),
            Button.inline('❌ Close', "close_settings")
        ])

    return buttons


async def create_media_size_buttons(rule_id, page=0):
    """Create media size selection buttons"""
    # Get layout settings from environment variables
    rows = MEDIA_SIZE_ROWS
    cols = MEDIA_SIZE_COLS
    size_select_per_page = rows * cols

    buttons = []
    total_size = len(MEDIA_SIZE)
    start_idx = page * size_select_per_page
    end_idx = min(start_idx + size_select_per_page, total_size)

    # Check if channel message
    buttons = []
    total_size = len(MEDIA_SIZE)

    # Add media size buttons
    current_row = []
    for i, size in enumerate(MEDIA_SIZE[start_idx:end_idx], start=1):
        current_row.append(Button.inline(
            str(size),
            f"select_max_media_size:{rule_id}:{size}"
        ))

        # When row is full, append and reset
        if i % cols == 0:
            buttons.append(current_row)
            current_row = []

    # Append any remaining partial row
    if current_row:
        buttons.append(current_row)

    # Add navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline(
            "⬅️ Prev",
            f"media_size_page:{rule_id}:{page - 1}"
        ))

    nav_buttons.append(Button.inline(
        f"{page + 1}/{(total_size + size_select_per_page - 1) // size_select_per_page}",
        "noop:0"
    ))

    if end_idx < total_size:
        nav_buttons.append(Button.inline(
            "Next ➡️",
            f"media_size_page:{rule_id}:{page + 1}"
        ))

    buttons.append(nav_buttons)

    buttons.append([
            Button.inline('👈 Back', f"rule_settings:{rule_id}"),
            Button.inline('❌ Close', "close_settings")
        ])

    return buttons

async def create_delay_time_buttons(rule_id, page=0):
    """Create delay time selection buttons"""
    # Get layout settings from environment variables
    rows = DELAY_TIME_ROWS
    cols = DELAY_TIME_COLS

    times_per_page = rows * cols

    buttons = []
    total_times = len(DELAY_TIMES)
    start_idx = page * times_per_page
    end_idx = min(start_idx + times_per_page, total_times)

    # Check if channel message
    buttons = []
    total_times = len(DELAY_TIMES)

    # Add time buttons
    current_row = []
    for i, time in enumerate(DELAY_TIMES[start_idx:end_idx], start=1):
        current_row.append(Button.inline(
            str(time),
            f"select_delay_time:{rule_id}:{time}"
        ))

        # When row is full, append and reset
        if i % cols == 0:
            buttons.append(current_row)
            current_row = []

    # Append any remaining partial row
    if current_row:
        buttons.append(current_row)

    # Add navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline(
            "⬅️ Prev",
            f"delay_time_page:{rule_id}:{page - 1}"
        ))

    nav_buttons.append(Button.inline(
        f"{page + 1}/{(total_times + times_per_page - 1) // times_per_page}",
        "noop:0"
    ))

    if end_idx < total_times:
        nav_buttons.append(Button.inline(
            "Next ➡️",
            f"delay_time_page:{rule_id}:{page + 1}"
        ))

    buttons.append(nav_buttons)

    buttons.append([
            Button.inline('👈 Back', f"rule_settings:{rule_id}"),
            Button.inline('❌ Close', "close_settings")
        ])

    return buttons

async def create_media_types_buttons(rule_id, media_types):
    """Create media type selection buttons
    
    Args:
        rule_id: Rule ID
        media_types: MediaTypes object

    Returns:
        Button list
    """
    buttons = []
    
    # Media type buttons
    media_type_names = {
        'photo': '📷 Photo',
        'document': '📄 Document',
        'video': '🎬 Video',
        'audio': '🎵 Audio',
        'voice': '🎤 Voice'
    }
    
    for field, display_name in media_type_names.items():
        # Get current value
        current_value = getattr(media_types, field, False)
        # If True, add checkmark
        button_text = f"{'✅ ' if current_value else ''}{display_name}"
        callback_data = f"toggle_media_type:{rule_id}:{field}"
        buttons.append([Button.inline(button_text, callback_data)])
    
    buttons.append([
            Button.inline('👈 Back', f"media_settings:{rule_id}"),
            Button.inline('❌ Close', "close_settings")
        ])
    
    return buttons



async def create_media_extensions_buttons(rule_id, page=0):
    """Create media extension selection buttons
    
    Args:
        rule_id: Rule ID
        page: Current page

    Returns:
        Button list
    """
    # Get layout settings from environment variables
    rows = MEDIA_EXTENSIONS_ROWS
    cols = MEDIA_EXTENSIONS_COLS
    
    extensions_per_page = rows * cols
    
    buttons = []
    total_extensions = len(MEDIA_EXTENSIONS)
    start_idx = page * extensions_per_page
    end_idx = min(start_idx + extensions_per_page, total_extensions)
    
    # Get currently selected extensions for this rule
    db_ops = await get_db_ops()
    session = get_session()
    selected_extensions = []
    try:
        # Fetch selected extensions via db_ops
        selected_extensions = await db_ops.get_media_extensions(session, rule_id)
        selected_extension_list = [ext["extension"] for ext in selected_extensions]
    
        # Create extension buttons
        current_row = []
        for i in range(start_idx, end_idx):
            ext = MEDIA_EXTENSIONS[i]
            # Check if already selected
            is_selected = ext in selected_extension_list
            button_text = f"{'✅ ' if is_selected else ''}{ext}"
            # Include page number in callback data
            callback_data = f"toggle_media_extension:{rule_id}:{ext}:{page}"
            
            current_row.append(Button.inline(button_text, callback_data))
            
            # Place cols buttons per row
            if len(current_row) == cols:
                buttons.append(current_row)
                current_row = []
        
        # Append remaining buttons
        if current_row:
            buttons.append(current_row)
        
        # Add pagination buttons
        page_buttons = []
        total_pages = (total_extensions + extensions_per_page - 1) // extensions_per_page
        
        if total_pages > 1:
            # Previous page button
            if page > 0:
                page_buttons.append(Button.inline("⬅️", f"media_extensions_page:{rule_id}:{page-1}"))
            else:
                page_buttons.append(Button.inline("⬅️", f"noop"))
            
            # Page indicator
            page_buttons.append(Button.inline(f"{page+1}/{total_pages}", f"noop"))
            
            # Next page button
            if page < total_pages - 1:
                page_buttons.append(Button.inline("➡️", f"media_extensions_page:{rule_id}:{page+1}"))
            else:
                page_buttons.append(Button.inline("➡️", f"noop"))
        
        if page_buttons:
            buttons.append(page_buttons)
        

        buttons.append([
            Button.inline('👈 Back', f"media_settings:{rule_id}"),
            Button.inline('❌ Close', "close_settings")
        ])
    finally:
        session.close()
    
    return buttons


async def create_sync_rule_buttons(rule_id, page=0):
    """Create sync rule selection buttons
    
    Args:
        rule_id: Current rule ID
        page: Current page

    Returns:
        Button list
    """
    # Set pagination parameters
    
    buttons = []
    session = get_session()
    
    try:
        # Get current rule
        current_rule = session.query(ForwardRule).get(rule_id)
        if not current_rule:
            buttons.append([Button.inline('❌ Rule not found', 'noop')])
            buttons.append([Button.inline('Close', 'close_settings')])
            return buttons
        
        # Get all rules (except current rule)
        all_rules = session.query(ForwardRule).filter(
            ForwardRule.id != rule_id
        ).all()
        
        # Calculate pagination
        total_rules = len(all_rules)
        total_pages = (total_rules + RULES_PER_PAGE - 1) // RULES_PER_PAGE
        
        if total_rules == 0:
            buttons.append([Button.inline('❌ No rules available', 'noop')])
            buttons.append([
                Button.inline('👈 Back', f"rule_settings:{rule_id}"),
                Button.inline('❌ Close', 'close_settings')
            ])
            return buttons
        
        # Get rules for current page
        start_idx = page * RULES_PER_PAGE
        end_idx = min(start_idx + RULES_PER_PAGE, total_rules)
        current_page_rules = all_rules[start_idx:end_idx]
        
        # Get sync targets for current rule
        db_ops = await get_db_ops()
        sync_targets = await db_ops.get_rule_syncs(session, rule_id)
        synced_rule_ids = [sync.sync_rule_id for sync in sync_targets]
        
        # Create rule buttons
        for rule in current_page_rules:
            # Get source and target chat names
            source_chat = rule.source_chat
            target_chat = rule.target_chat
            
            # Check if already synced
            is_synced = rule.id in synced_rule_ids
            
            # Build button text
            button_text = f"{'✅ ' if is_synced else ''}{rule.id} {source_chat.name}->{target_chat.name}"
            
            # Build callback data: toggle_rule_sync:current_rule_id:target_rule_id:page
            callback_data = f"toggle_rule_sync:{rule_id}:{rule.id}:{page}"
            
            buttons.append([Button.inline(button_text, callback_data)])
        
        # Add pagination buttons
        page_buttons = []
        
        if total_pages > 1:
            # Previous page button
            if page > 0:
                page_buttons.append(Button.inline("⬅️", f"sync_rule_page:{rule_id}:{page-1}"))
            else:
                page_buttons.append(Button.inline("⬅️", "noop"))
            
            # Page indicator
            page_buttons.append(Button.inline(f"{page+1}/{total_pages}", "noop"))
            
            # Next page button
            if page < total_pages - 1:
                page_buttons.append(Button.inline("➡️", f"sync_rule_page:{rule_id}:{page+1}"))
            else:
                page_buttons.append(Button.inline("➡️", "noop"))
        
        if page_buttons:
            buttons.append(page_buttons)
        
        # Add sync save and back buttons
        buttons.append([
            Button.inline('👈 Back', f"rule_settings:{rule_id}"),
            Button.inline('❌ Close', 'close_settings')
        ])
    
    finally:
        session.close()
    
    return buttons

async def create_push_settings_buttons(rule_id, page=0):
    """Create push settings button menu with pagination
    
    Args:
        rule_id: Rule ID
        page: Page number (0-indexed)

    Returns:
        Button list
    """
    buttons = []
    configs_per_page = PUSH_CHANNEL_PER_PAGE
    
    # Fetch rule object and push configs from database
    db_ops = await get_db_ops()
    session = get_session()
    try:
        # Get rule object
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            buttons.append([Button.inline("❌ Rule not found", "noop")])
            buttons.append([Button.inline("Close", "close_settings")])
            return buttons
        
        
        # Add "Enable push" button
        buttons.append([
            Button.inline(
                f"{'✅ ' if rule.enable_push else ''}{PUSH_SETTINGS['enable_push_channel']['display_name']}", 
                f"{PUSH_SETTINGS['enable_push_channel']['toggle_action']}:{rule_id}"
            )
        ])
        
        # Add "Forward to push only" button
        buttons.append([
            Button.inline(
                f"{'✅ ' if rule.enable_only_push else ''}{PUSH_SETTINGS['enable_only_push']['display_name']}", 
                f"{PUSH_SETTINGS['enable_only_push']['toggle_action']}:{rule_id}"
            )
        ])
        
        # Add "Add push config" button
        buttons.append([
            Button.inline(
                PUSH_SETTINGS['add_push_channel']['display_name'],
                f"{PUSH_SETTINGS['add_push_channel']['toggle_action']}:{rule_id}"
            )
        ])
        
        # Get all push configs for current rule
        push_configs = await db_ops.get_push_configs(session, rule_id)
        
        # Calculate total pages
        total_configs = len(push_configs)
        total_pages = (total_configs + configs_per_page - 1) // configs_per_page
        
        # Calculate range for current page
        start_idx = page * configs_per_page
        end_idx = min(start_idx + configs_per_page, total_configs)
        
        # Create buttons for each push config (current page only)
        for config in push_configs[start_idx:end_idx]:
            # Truncate to 25 chars
            display_name = config.push_channel[:25] + ('...' if len(config.push_channel) > 25 else '')
            button_text = display_name
            # Create button
            buttons.append([Button.inline(button_text, f"toggle_push_config:{config.id}")])
        
        # Add pagination buttons if needed
        if total_pages > 1:
            nav_buttons = []
            
            # Previous page button
            if page > 0:
                nav_buttons.append(Button.inline("⬅️", f"push_page:{rule_id}:{page-1}"))
            else:
                nav_buttons.append(Button.inline("⬅️", "noop"))
            
            # Page indicator
            nav_buttons.append(Button.inline(f"{page+1}/{total_pages}", "noop"))
            
            # Next page button
            if page < total_pages - 1:
                nav_buttons.append(Button.inline("➡️", f"push_page:{rule_id}:{page+1}"))
            else:
                nav_buttons.append(Button.inline("➡️", "noop"))
            
            buttons.append(nav_buttons)
    
    finally:
        session.close()
    
    # Add back and close buttons
    buttons.append([
        Button.inline('👈 Back', f"rule_settings:{rule_id}"),
        Button.inline('❌ Close', "close_settings")
    ])
    
    return buttons

async def create_push_config_details_buttons(config_id):
    """Create push config detail buttons
    
    Args:
        config_id: Push config ID

    Returns:
        Button list
    """
    buttons = []
    
    # Fetch push config from database
    session = get_session()
    try:
        from models.models import PushConfig
        
        # Get push config
        config = session.query(PushConfig).get(config_id)
        if not config:
            buttons.append([Button.inline("❌ Push config not found", "noop")])
            buttons.append([Button.inline("Close", "close_settings")])
            return buttons
        
        # Add enable/disable button
        buttons.append([
            Button.inline(
                f"{'✅ ' if config.enable_push_channel else ''}Enable push", 
                f"toggle_push_config_status:{config_id}"
            )
        ])
        
        # Add media send mode toggle button
        mode_text = "Single" if config.media_send_mode == "Single" else "All"
        buttons.append([
            Button.inline(
                f"📁 Media send mode: {mode_text}", 
                f"toggle_media_send_mode:{config_id}"
            )
        ])
        
        # Add delete button
        buttons.append([
            Button.inline("🗑️ Delete push config", f"delete_push_config:{config_id}")
        ])
        
        # Add back button
        buttons.append([
            Button.inline("👈 Back", f"push_settings:{config.rule_id}"),
            Button.inline("❌ Close", "close_settings")
        ])
        
    finally:
        session.close()
    
    return buttons
