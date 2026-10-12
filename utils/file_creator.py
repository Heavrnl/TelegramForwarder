import os
import json
import logging

logger = logging.getLogger(__name__)

# Default AI model configuration (JSON format)
AI_MODELS_CONFIG = {
    "openai": [
        "gpt-4o",
        "chatgpt-4o-latest",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4",
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-instruct",
        "o1",
        "o1-mini",
        "o1-preview",
        "o3-mini"
    ],
    "gemini": [
        'gemini-2.5-pro-exp-03-25',
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite-preview-02-05",
        "gemini-2.0-pro-exp-02-05",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro"
    ],
    "grok": [
        "grok-3-beta",
        "grok-3-fast-beta",
        "grok-3-mini-beta",
        "grok-3-mini-fast-beta",
        "grok-2-vision-1212",
        "grok-2-image-1212",
        "grok-2-latest"
    ],
    "deepseek": [
        "deepseek-chat"
    ],
    "claude": [
        "claude-3-7-sonnet-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307"
    ],
    "qwen": [
        "qwq-plus",
        "qwq-plus-latest",
        "qwq-32b",
        'qvq-max',
        'qvq-max-latest',
        'qwen-vl-max',
        'qwen-vl-max-latest',
        'qwen-vl-plus',
        'qwen-vl-plus-latest',
        'qwen-vl-ocr',
        'qwen-vl-ocr-latest',
        'qwen-omni-turbo',
        'qwen-omni-turbo-latest',
        'qwen-max',
        'qwen-max-latest',
        'qwen-plus',
        'qwen-plus-latest',
        "qwen-turbo",
        "qwen-turbo-latest",
        "qwen-long"
    ]
}

# Summary times list
SUMMARY_TIMES_CONTENT = """00:00
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
23:50"""

# Delay times list
DELAY_TIMES_CONTENT = """1
2
3
4
5
6
7
8
9
10"""

# Maximum media size list
MAX_MEDIA_SIZE_CONTENT = """1
2
3
4
5
6
7
8
9
10
15
20
25
30
35
40
45
50
55
60
65
70
75
80
85
90
95
100
150
200
250
300
350
400
450
500
550
600
650
700
750
800
850
900
950
1024
2048
"""

MEDIA_EXTENSIONS_CONTENT = """no extension
jpg
jpeg
png
gif
bmp
webp
tiff
raw
heic
svg
mp4
avi
mkv
mov
wmv
flv
webm
m4v
mpeg
mpg
3gp
rmvb
mp3
wav
ogg
m4a
aac
flac
wma
opus
mid
midi
txt
doc
docx
pdf
xls
xlsx
ppt
pptx
csv
rtf
odt
zip
rar
7z
tar
gz
bz2
exe
apk
iso
bin
json
xml
html
css
js
py
"""


def create_default_configs():
    """Create default configuration files."""
    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
    os.makedirs(config_dir, exist_ok=True)

    # Define default config content
    default_configs = {
        'summary_times.txt': SUMMARY_TIMES_CONTENT,
        'delay_times.txt': DELAY_TIMES_CONTENT,
        'max_media_size.txt': MAX_MEDIA_SIZE_CONTENT,
        'media_extensions.txt': MEDIA_EXTENSIONS_CONTENT,
    }

    # Check and create each config file
    for filename, content in default_configs.items():
        file_path = os.path.join(config_dir, filename)
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content.strip())
            logger.info(f"Created {filename}")

    # Create the JSON AI model config file
    json_config_path = os.path.join(config_dir, 'ai_models.json')
    if not os.path.exists(json_config_path):
        try:
            with open(json_config_path, 'w', encoding='utf-8') as f:
                json.dump(AI_MODELS_CONFIG, f, ensure_ascii=False, indent=4)
            logger.info("Created ai_models.json")
        except Exception as e:
            logger.error(f"Failed to create ai_models.json: {e}")
