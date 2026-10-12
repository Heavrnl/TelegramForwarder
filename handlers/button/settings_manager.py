import os
from utils.settings import load_ai_models
from enums.enums import ForwardMode, MessageMode, PreviewMode, AddMode, HandleMode
from models.models import get_session
from telethon import Button
from utils.constants import RSS_ENABLED, UFB_ENABLED

AI_MODELS = load_ai_models()

# Rule configuration field definitions
RULE_SETTINGS = {
    'enable_rule': {
        'display_name': 'Rule enabled',
        'values': {
            True: 'Yes',
            False: 'No'
        },
        'toggle_action': 'toggle_enable_rule',
        'toggle_func': lambda current: not current
    },
    'add_mode': {
        'display_name': 'Keyword add mode',
        'values': {
            AddMode.WHITELIST: 'Whitelist',
            AddMode.BLACKLIST: 'Blacklist'
        },
        'toggle_action': 'toggle_add_mode',
        'toggle_func': lambda current: AddMode.BLACKLIST if current == AddMode.WHITELIST else AddMode.WHITELIST
    },
    'is_filter_user_info': {
        'display_name': 'Include sender name/ID in keyword filter',
        'values': {
            True: 'Yes',
            False: 'No'
        },
        'toggle_action': 'toggle_filter_user_info',
        'toggle_func': lambda current: not current
    },
    'forward_mode': {
        'display_name': 'Filter mode',
        'values': {
            ForwardMode.BLACKLIST: 'Blacklist only',
            ForwardMode.WHITELIST: 'Whitelist only',
            ForwardMode.BLACKLIST_THEN_WHITELIST: 'Blacklist then whitelist',
            ForwardMode.WHITELIST_THEN_BLACKLIST: 'Whitelist then blacklist'
        },
        'toggle_action': 'toggle_forward_mode',
        'toggle_func': lambda current: {
            ForwardMode.BLACKLIST: ForwardMode.WHITELIST,
            ForwardMode.WHITELIST: ForwardMode.BLACKLIST_THEN_WHITELIST,
            ForwardMode.BLACKLIST_THEN_WHITELIST: ForwardMode.WHITELIST_THEN_BLACKLIST,
            ForwardMode.WHITELIST_THEN_BLACKLIST: ForwardMode.BLACKLIST
        }[current]
    },
    'use_bot': {
        'display_name': 'Forward via',
        'values': {
            True: 'Bot account',
            False: 'User account'
        },
        'toggle_action': 'toggle_bot',
        'toggle_func': lambda current: not current
    },
    'is_replace': {
        'display_name': 'Replace mode',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_replace',
        'toggle_func': lambda current: not current
    },
    'message_mode': {
        'display_name': 'Message format',
        'values': {
            MessageMode.MARKDOWN: 'Markdown',
            MessageMode.HTML: 'HTML'
        },
        'toggle_action': 'toggle_message_mode',
        'toggle_func': lambda current: MessageMode.HTML if current == MessageMode.MARKDOWN else MessageMode.MARKDOWN
    },
    'is_preview': {
        'display_name': 'Link preview',
        'values': {
            PreviewMode.ON: 'On',
            PreviewMode.OFF: 'Off',
            PreviewMode.FOLLOW: 'Follow original'
        },
        'toggle_action': 'toggle_preview',
        'toggle_func': lambda current: {
            PreviewMode.ON: PreviewMode.OFF,
            PreviewMode.OFF: PreviewMode.FOLLOW,
            PreviewMode.FOLLOW: PreviewMode.ON
        }[current]
    },
    'is_original_link': {
        'display_name': 'Original link',
        'values': {
            True: 'Include',
            False: 'Exclude'
        },
        'toggle_action': 'toggle_original_link',
        'toggle_func': lambda current: not current
    },
    'is_delete_original': {
        'display_name': 'Delete original message',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_delete_original',
        'toggle_func': lambda current: not current
    },
    'is_ufb': {
        'display_name': 'UFB sync',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_ufb',
        'toggle_func': lambda current: not current
    },
    'is_original_sender': {
        'display_name': 'Original sender',
        'values': {
            True: 'Show',
            False: 'Hide'
        },
        'toggle_action': 'toggle_original_sender',
        'toggle_func': lambda current: not current
    },
    'is_original_time': {
        'display_name': 'Send time',
        'values': {
            True: 'Show',
            False: 'Hide'
        },
        'toggle_action': 'toggle_original_time',
        'toggle_func': lambda current: not current
    },
    'enable_delay': {
        'display_name': 'Delayed processing',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_enable_delay',
        'toggle_func': lambda current: not current
    },
    'delay_seconds': {
        'values': {
            None: 5,
            '': 5
        },
        'toggle_action': 'set_delay_time',
        'toggle_func': None
    },
    'handle_mode': {
        'display_name': 'Processing mode',
        'values': {
            HandleMode.FORWARD: 'Forward mode',
            HandleMode.EDIT: 'Edit mode'
        },
        'toggle_action': 'toggle_handle_mode',
        'toggle_func': lambda current: HandleMode.EDIT if current == HandleMode.FORWARD else HandleMode.FORWARD
    },
    'enable_comment_button': {
        'display_name': 'Comment button',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_enable_comment_button',
        'toggle_func': lambda current: not current
    },
    'only_rss': {
        'display_name': 'Forward to RSS only',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_only_rss',
        'toggle_func': lambda current: not current
    },
    'close_settings': {
        'display_name': 'Close',
        'toggle_action': 'close_settings',
        'toggle_func': None
    },
    'enable_sync': {
        'display_name': 'Enable sync',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_enable_sync',
        'toggle_func': lambda current: not current
    }
}


# AI settings
AI_SETTINGS = {
    'is_ai': {
        'display_name': 'AI processing',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_ai',
        'toggle_func': lambda current: not current
    },
    'ai_model': {
        'display_name': 'AI model',
        'values': {
            None: 'Default',
            '': 'Default',
            **{model: model for model in AI_MODELS}
        },
        'toggle_action': 'change_model',
        'toggle_func': None
    },
    'ai_prompt': {
        'display_name': 'Set AI processing prompt',
        'toggle_action': 'set_ai_prompt',
        'toggle_func': None
    },
    'enable_ai_upload_image': {
        'display_name': 'Upload images to AI',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_ai_upload_image',
        'toggle_func': lambda current: not current
    },
    'is_keyword_after_ai': {
        'display_name': 'Re-run keyword filter after AI',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_keyword_after_ai',
        'toggle_func': lambda current: not current
    },
    'is_summary': {
        'display_name': 'AI summary',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_summary',
        'toggle_func': lambda current: not current
    },
    'summary_time': {
        'display_name': 'Summary time',
        'values': {
            None: '00:00',
            '': '00:00'
        },
        'toggle_action': 'set_summary_time',
        'toggle_func': None
    },
    'summary_prompt': {
        'display_name': 'Set AI summary prompt',
        'toggle_action': 'set_summary_prompt',
        'toggle_func': None
    },
    'is_top_summary': {
        'display_name': 'Pin summary message',
        'values': {
            True: 'Yes',
            False: 'No'
        },
        'toggle_action': 'toggle_top_summary',
        'toggle_func': lambda current: not current
    },
    'summary_now': {
        'display_name': 'Run summary now',
        'toggle_action': 'summary_now',
        'toggle_func': None
    }
}

MEDIA_SETTINGS = {
    'enable_media_type_filter': {
        'display_name': 'Media type filter',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_enable_media_type_filter',
        'toggle_func': lambda current: not current
    },
    'selected_media_types': {
        'display_name': 'Select media types',
        'toggle_action': 'set_media_types',
        'toggle_func': None
    },
    'enable_media_size_filter': {
        'display_name': 'Media size filter',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_enable_media_size_filter',
        'toggle_func': lambda current: not current
    },
    'max_media_size': {
        'display_name': 'Max media size',
        'values': {
            None: '5MB',
            '': '5MB'
        },
        'toggle_action': 'set_max_media_size',
        'toggle_func': None
    },
    'is_send_over_media_size_message': {
        'display_name': 'Notify when media exceeds size limit',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_send_over_media_size_message',
        'toggle_func': lambda current: not current
    },
    'enable_extension_filter': {
        'display_name': 'File extension filter',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_enable_media_extension_filter',
        'toggle_func': lambda current: not current
    },
    'extension_filter_mode': {
        'display_name': 'Extension filter mode',
        'values': {
            AddMode.BLACKLIST: 'Blacklist',
            AddMode.WHITELIST: 'Whitelist'
        },
        'toggle_action': 'toggle_media_extension_filter_mode',
        'toggle_func': lambda current: AddMode.WHITELIST if current == AddMode.BLACKLIST else AddMode.BLACKLIST
    },
    'media_extensions': {
        'display_name': 'Set file extensions',
        'toggle_action': 'set_media_extensions',
        'toggle_func': None,
        'values': {}
    },
    'media_allow_text': {
        'display_name': 'Allow text-only messages',
        'values': {
            True: 'On',
            False: 'Off'
        },
        'toggle_action': 'toggle_media_allow_text',
        'toggle_func': lambda current: not current
    }
}


OTHER_SETTINGS = {
    'copy_rule': {
        'display_name': 'Copy rule',
        'toggle_action': 'copy_rule',
        'toggle_func': None
    },
    'copy_keyword': {
        'display_name': 'Copy keywords',
        'toggle_action': 'copy_keyword',
        'toggle_func': None
    },
    'copy_replace': {
        'display_name': 'Copy replacements',
        'toggle_action': 'copy_replace',
        'toggle_func': None
    },
    'clear_keyword': {
        'display_name': 'Clear all keywords',
        'toggle_action': 'clear_keyword',
        'toggle_func': None
    },
    'clear_replace': {
        'display_name': 'Clear all replace rules',
        'toggle_action': 'clear_replace',
        'toggle_func': None
    },
    'delete_rule': {
        'display_name': 'Delete rule',
        'toggle_action': 'delete_rule',
        'toggle_func': None
    },
    'null': {
        'display_name': '-----------',
        'toggle_action': 'null',
        'toggle_func': None
    },
    'set_userinfo_template': {
        'display_name': 'Set sender info template',
        'toggle_action': 'set_userinfo_template',
        'toggle_func': None
    },
    'set_time_template': {
        'display_name': 'Set time template',
        'toggle_action': 'set_time_template',
        'toggle_func': None
    },
    'set_original_link_template': {
        'display_name': 'Set original link template',
        'toggle_action': 'set_original_link_template',
        'toggle_func': None
    },
    'reverse_blacklist': {
        'display_name': 'Invert blacklist',
        'toggle_action': 'toggle_reverse_blacklist',
        'toggle_func': None
    },
    'reverse_whitelist': {
        'display_name': 'Invert whitelist',
        'toggle_action': 'toggle_reverse_whitelist',
        'toggle_func': None
    }
}

PUSH_SETTINGS = {
    'enable_push_channel': {
        'display_name': 'Enable push notifications',
        'toggle_action': 'toggle_enable_push',
        'toggle_func': None
    },
    'add_push_channel': {
        'display_name': '➕ Add push configuration',
        'toggle_action': 'add_push_channel',
        'toggle_func': None
    },
    'enable_only_push': {
        'display_name': 'Forward to push only',
        'toggle_action': 'toggle_enable_only_push',
        'toggle_func': None
    }
}

async def create_settings_text(rule):
    """Create settings info text"""
    text = (
        "📋 Manage forwarding rule\n\n"
        f"Rule ID: `{rule.id}`\n"
        f"{rule.source_chat.name} --> {rule.target_chat.name}"
    )
    return text

async def create_buttons(rule):
    """Create rule settings buttons"""
    buttons = []

    session = get_session()
    try:
        target_chat = rule.target_chat
        current_add_id = target_chat.current_add_id
        source_chat = rule.source_chat

        # Rule toggle button
        is_current = current_add_id == source_chat.telegram_chat_id
        buttons.append([
            Button.inline(
                f"{'✅ ' if is_current else ''}Apply this rule",
                f"toggle_current:{rule.id}"
            )
        ])

        buttons.append([
            Button.inline(
                f"Rule enabled: {RULE_SETTINGS['enable_rule']['values'][rule.enable_rule]}",
                f"toggle_enable_rule:{rule.id}"
            )
        ])

        # Keyword add mode
        buttons.append([
            Button.inline(
                f"Keyword add mode: {RULE_SETTINGS['add_mode']['values'][rule.add_mode]}",
                f"toggle_add_mode:{rule.id}"
            )
        ])

        # Include sender info in keyword filter
        buttons.append([
            Button.inline(
                f"Include sender in filter: {RULE_SETTINGS['is_filter_user_info']['values'][rule.is_filter_user_info]}",
                f"toggle_filter_user_info:{rule.id}"
            )
        ])

        if RSS_ENABLED == 'false':
            buttons.append([
                Button.inline(
                    f"⚙️ Processing mode: {RULE_SETTINGS['handle_mode']['values'][rule.handle_mode]}",
                    f"toggle_handle_mode:{rule.id}"
                )
            ])
        else:
            buttons.append([
                Button.inline(
                    f"⚙️ Processing mode: {RULE_SETTINGS['handle_mode']['values'][rule.handle_mode]}",
                    f"toggle_handle_mode:{rule.id}"
                ),
                Button.inline(
                    f"⚠️ RSS only: {RULE_SETTINGS['only_rss']['values'][rule.only_rss]}",
                    f"toggle_only_rss:{rule.id}"
                )
            ])

        buttons.append([
            Button.inline(
                f"📥 Filter mode: {RULE_SETTINGS['forward_mode']['values'][rule.forward_mode]}",
                f"toggle_forward_mode:{rule.id}"
            ),
            Button.inline(
                f"🤖 Forward via: {RULE_SETTINGS['use_bot']['values'][rule.use_bot]}",
                f"toggle_bot:{rule.id}"
            )
        ])

        # These settings work regardless of which account sends the message —
        # replace/format/link-preview/original-info/delete/delay are all plain
        # text or account-agnostic operations, not bot-only API features.
        buttons.append([
            Button.inline(
                f"🔄 Replace mode: {RULE_SETTINGS['is_replace']['values'][rule.is_replace]}",
                f"toggle_replace:{rule.id}"
            ),
            Button.inline(
                f"📝 Message format: {RULE_SETTINGS['message_mode']['values'][rule.message_mode]}",
                f"toggle_message_mode:{rule.id}"
            )
        ])

        buttons.append([
            Button.inline(
                f"👁 Link preview: {RULE_SETTINGS['is_preview']['values'][rule.is_preview]}",
                f"toggle_preview:{rule.id}"
            ),
            Button.inline(
                f"🔗 Original link: {RULE_SETTINGS['is_original_link']['values'][rule.is_original_link]}",
                f"toggle_original_link:{rule.id}"
            )
        ])

        buttons.append([
            Button.inline(
                f"👤 Original sender: {RULE_SETTINGS['is_original_sender']['values'][rule.is_original_sender]}",
                f"toggle_original_sender:{rule.id}"
            ),
            Button.inline(
                f"⏰ Send time: {RULE_SETTINGS['is_original_time']['values'][rule.is_original_time]}",
                f"toggle_original_time:{rule.id}"
            )
        ])

        if rule.use_bot:
            # Comment button attaches an inline URL button to the sent message.
            # Telegram only allows bot accounts to attach reply_markup/inline
            # buttons to messages — a regular user account cannot send these,
            # so this option only makes sense (and only works) in bot mode.
            buttons.append([
                Button.inline(
                    f"🗑 Delete original: {RULE_SETTINGS['is_delete_original']['values'][rule.is_delete_original]}",
                    f"toggle_delete_original:{rule.id}"
                ),
                Button.inline(
                    f"💬 Comment button: {RULE_SETTINGS['enable_comment_button']['values'][rule.enable_comment_button]}",
                    f"toggle_enable_comment_button:{rule.id}"
                )
            ])
        else:
            buttons.append([
                Button.inline(
                    f"🗑 Delete original: {RULE_SETTINGS['is_delete_original']['values'][rule.is_delete_original]}",
                    f"toggle_delete_original:{rule.id}"
                )
            ])

        buttons.append([
            Button.inline(
                f"⏱️ Delayed processing: {RULE_SETTINGS['enable_delay']['values'][rule.enable_delay]}",
                f"toggle_enable_delay:{rule.id}"
            ),
            Button.inline(
                f"⌛ Delay seconds: {rule.delay_seconds or 5}s",
                f"set_delay_time:{rule.id}"
            )
        ])

        buttons.append([
            Button.inline(
                f"🔄 Sync rule: {RULE_SETTINGS['enable_sync']['values'][rule.enable_sync]}",
                f"toggle_enable_sync:{rule.id}"
            ),
            Button.inline(
                f"📡 Sync settings",
                f"set_sync_rule:{rule.id}"
            )
        ])

        if UFB_ENABLED == 'true':
            buttons.append([
                Button.inline(
                    f"☁️ UFB sync: {RULE_SETTINGS['is_ufb']['values'][rule.is_ufb]}",
                    f"toggle_ufb:{rule.id}"
                )
            ])

        buttons.append([
            Button.inline(
                "🤖 AI settings",
                f"ai_settings:{rule.id}"
            ),
            Button.inline(
                "🎬 Media settings",
                f"media_settings:{rule.id}"
            ),
            Button.inline(
                "➕ Other settings",
                f"other_settings:{rule.id}"
            )
        ])

        buttons.append([
            Button.inline(
                "🔔 Push settings",
                f"push_settings:{rule.id}"
            )
        ])

        buttons.append([
            Button.inline(
                "👈 Back",
                "settings"
            ),
            Button.inline(
                "❌ Close",
                "close_settings"
            )
        ])

    finally:
        session.close()

    return buttons
