from handlers.button.button_helpers import *
from utils.auto_delete import reply_and_delete

async def show_list(event, command, items, formatter, title, page=1):
    """Show a paginated list"""

    # KEYWORDS_PER_PAGE
    PAGE_SIZE = KEYWORDS_PER_PAGE
    total_items = len(items)
    total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE

    if not items:
        try:
            return await event.edit(f'No {title} found')
        except:
            return await reply_and_delete(event,f'No {title} found')

    # Get items for the current page
    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total_items)
    current_items = items[start:end]

    # Format list items
    item_list = []
    for i, item in enumerate(current_items):
        formatted_item = formatter(i + start + 1, item)
        # Add backticks to keywords if this is a keyword list
        if command == 'keyword':
            # Split index number and keyword content
            parts = formatted_item.split('. ', 1)
            if len(parts) == 2:
                number = parts[0]
                content = parts[1]
                # If it's a regex, add backticks around the keyword part
                if ' (regex)' in content:
                    keyword, regex_mark = content.split(' (regex)')
                    formatted_item = f'{number}. `{keyword}` (regex)'
                else:
                    formatted_item = f'{number}. `{content}`'
        item_list.append(formatted_item)

    # Create pagination buttons
    buttons = await create_list_buttons(total_pages, page, command)

    # Build message text
    text = f'{title}\n{chr(10).join(item_list)}'
    if len(text) > 4096:  # Telegram message length limit
        text = text[:4093] + '...'

    try:
        return await event.edit(text, buttons=buttons, parse_mode='markdown')
    except:
        return await reply_and_delete(event,text, buttons=buttons, parse_mode='markdown')

