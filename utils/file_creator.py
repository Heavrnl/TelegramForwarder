import os
import logging

logger = logging.getLogger(__name__)

def create_default_configs():
    """创建默认配置文件"""
    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
    os.makedirs(config_dir, exist_ok=True)

    # 定义默认配置内容
    default_configs = {
        'ai_models.txt': """gpt-4o
chatgpt-4o-latest
gpt-4o-mini
gpt-4-turbo
gpt-4-turbo-preview
gpt-4
gpt-3.5-turbo
gpt-3.5-turbo-instruct
o1
o1-mini
o1-preview
o3-mini
gemini-2.0-flash
gemini-2.0-flash-lite-preview-02-05
gemini-2.0-pro-exp-02-05
gemini-1.5-flash
gemini-1.5-flash-8b
gemini-1.5-pro
grok-2-latest
deepseek-chat
claude-3-5-sonnet-latest
claude-3-5-haiku-latest
claude-3-opus-latest
claude-3-sonnet-20240229
claude-3-haiku-20240307
qwen-omni-turbo
qwen-omni-turbo-latest
qwen-max
qwen-max-latest
qwen-plus
qwen-plus-latest
qwen-turbo
qwen-turbo-latest
qwen-long""",
        'summary_times.txt': """00:00
00:30
01:00
01:30
02:00
02:30
03:00
03:30
04:00
04:30
05:00
05:30
06:00
06:30
07:00
07:30
08:00
08:30
09:00
09:30
10:00
10:30
11:00
11:30
12:00
12:30
13:00
13:30
14:00
14:30
15:00
15:30
16:00
16:30
17:00
17:30
18:00
18:30
19:00
19:30
20:00
20:30
21:00
21:30
22:00
22:30
23:00
23:30
23:50""",
        'delay_times.txt': """1
2
3
4
5
6
7
8
9
10"""
    }

    # 检查并创建每个配置文件
    for filename, content in default_configs.items():
        file_path = os.path.join(config_dir, filename)
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content.strip())
            logger.info(f"Created {filename}") 