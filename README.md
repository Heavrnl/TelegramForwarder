![img](images/logo/png/logo-title.png)

<h3><div align="center">Telegram Forwarder — English Edition</div>

---

<div align="center">

[![Docker](https://img.shields.io/badge/-Docker-2496ED?style=flat-square&logo=docker&logoColor=white)][docker-url] [![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-4CAF50?style=flat-square)](https://github.com/Heavrnl/TelegramForwarder/blob/main/LICENSE)

[docker-url]: https://hub.docker.com/r/heavrnl/telegramforwarder

</div>

## 📖 Introduction
Telegram Forwarder is a powerful message forwarding tool. As long as your account has joined a channel or group, it can forward messages from specified chats to other chats — no need for a bot to be in the source channel/group to monitor it. It can be used for information aggregation and filtering, message alerts, content bookmarking, and many other scenarios, with no restriction on forwarding or copy-protection. In addition, by leveraging Apprise's powerful push notification capabilities, you can easily distribute messages to chat apps, email, SMS, Webhooks, APIs, and many other platforms.

## ✨ Features

- 🔄 **Multi-source forwarding**: Forward from multiple sources to a specified target
- 🔍 **Keyword filtering**: Supports both whitelist and blacklist modes
- 📝 **Regex matching**: Supports regular expression matching on target text
- 📋 **Content modification**: Supports multiple ways to modify message content
- 🤖 **AI processing**: Supports AI APIs from major providers
- 📹 **Media filtering**: Supports filtering by specific media file types
- 📰 **RSS feed**: Supports RSS feed generation
- 📢 **Multi-platform push notifications**: Supports pushing to multiple platforms via Apprise

## 📋 Table of Contents

- [📖 Introduction](#-introduction)
- [✨ Features](#-features)
- [🚀 Quick Start (Docker)](#-quick-start)
  - [1️⃣ Prerequisites](#1️⃣-prerequisites)
  - [2️⃣ Configure Environment](#2️⃣-configure-environment)
  - [3️⃣ Start the Service](#3️⃣-start-the-service)
  - [4️⃣ Updates](#4️⃣-updates)
- [🖥️ Native Install (No Docker)](#️-native-install-no-docker)
  - [Prerequisites](#prerequisites-1)
  - [Install & Configure](#install--configure)
  - [First Run (Phone Verification)](#first-run-phone-verification)
  - [Run as a System Service](#run-as-a-system-service)
  - [Multiple Instances](#multiple-instances)
- [📚 Usage Guide](#-usage-guide)
  - [🌟 Basic Usage Examples](#-basic-usage-examples)
  - [🔧 Special Use Case Examples](#-special-use-case-examples)
- [🛠️ Feature Details](#️-feature-details)
  - [⚡ Filter Flow](#-filter-flow)
  - [⚙️ Settings Reference](#️-settings-reference)
    - [Main Settings Reference](#main-settings-reference)
    - [Media Settings Reference](#media-settings-reference)
  - [🤖 AI Features](#-ai-features)
    - [Configuration](#configuration)
    - [Custom Model](#custom-model)
    - [AI Processing](#ai-processing)
    - [Scheduled Summary](#scheduled-summary)
  - [📢 Push Notifications](#-push-notifications)
    - [Settings Reference](#settings-reference)
  - [📰 RSS Feed](#-rss-feed)
    - [Enable RSS](#enable-rss)
    - [Access the RSS Dashboard](#access-the-rss-dashboard)
    - [Nginx Configuration](#nginx-configuration)
    - [RSS Config Management](#rss-config-management)
    - [Special Settings](#special-settings)
    - [Notes](#notes)

- [🎯 Special Features](#-special-features)
  - [🔗 Link Forwarding](#-link-forwarding)
- [📝 Command List](#-command-list)
- [💐 Credits](#-credits)
- [☕ Donate](#-donate)
- [📄 License](#-license)



## 🚀 Quick Start (Docker)

### 1️⃣ Prerequisites

1. Get your Telegram API credentials:
   - Visit https://my.telegram.org/apps
   - Create an app to get your `API_ID` and `API_HASH`

2. Get a bot token:
   - Talk to @BotFather to create a bot
   - Obtain the bot's `BOT_TOKEN`

3. Get your user ID:
   - Talk to @userinfobot to get your `USER_ID`

### 2️⃣ Configure Environment

Create a new folder:
```bash
mkdir ./TelegramForwarder && cd ./TelegramForwarder
```
Download the repository's [**docker-compose.yml**](https://github.com/Heavrnl/TelegramForwarder/blob/main/docker-compose.yml) into that folder.

Then download or copy the repository's **[.env.example](./.env.example)** file, fill in the required fields, and rename it to `.env`:
```bash
wget https://raw.githubusercontent.com/Heavrnl/TelegramForwarder/refs/heads/main/.env.example -O .env
```



### 3️⃣ Start the Service

First run (verification required):

```bash
docker-compose run -it telegram-forwarder
```
Press CTRL+C to exit the container.

Edit `docker-compose.yml` and set `stdin_open: false` and `tty: false`.

Run in the background:
```bash
docker-compose up -d
```

### 4️⃣ Updates
Note: When running via docker-compose you do not need to pull the repository source code. Unless you plan to build it yourself, just run the following commands in the project directory to update:
```bash
docker-compose down
```
```bash
docker-compose pull
```
```bash
docker-compose up -d
```
---

## 🖥️ Native Install (No Docker)

Run directly on any Linux server with Python 3.10+. No Docker required. This is ideal if you're already running other services on the same machine or want to run multiple instances for different users.

### Prerequisites

- Python 3.10 or higher
- `pip3`
- A Linux server (Ubuntu 20.04+ recommended)
- Your Telegram API credentials (see [Prerequisites](#1️⃣-prerequisites) above)

### Install & Configure

```bash
# Clone the repo
git clone https://github.com/Heavrnl/TelegramForwarder.git
cd TelegramForwarder

# Install dependencies
pip3 install -r requirements.txt --break-system-packages

# Create your config
cp .env.example .env
nano .env  # Fill in your credentials (see below)

# Create required directories
mkdir -p sessions db
```

**Minimum `.env` values to fill in:**

```ini
API_ID=your_api_id
API_HASH=your_api_hash
PHONE_NUMBER=+1xxxxxxxxxx   # The account that will do the forwarding
BOT_TOKEN=xxxxxxxxxx:xxxxx  # From @BotFather
USER_ID=your_telegram_id    # From @userinfobot — only this account can control the bot
```

**If you want the RSS dashboard:**
```ini
RSS_ENABLED=true
RSS_HOST=0.0.0.0
RSS_PORT=8100
RSS_BASE_URL=http://YOUR_SERVER_IP:8100
```

### First Run (Phone Verification)

The first run requires interactive login to authorize the user account:

```bash
python3 main.py
```

Telegram will send a verification code to your phone. Enter it when prompted. Once logged in, press `Ctrl+C` — the session is saved and you won't need to do this again.

### Run as a System Service

Create a systemd service so the bot starts automatically and restarts on crash:

```bash
sudo tee /etc/systemd/system/tg-forwarder.service > /dev/null << 'EOF'
[Unit]
Description=Telegram Message Forwarder Bot
After=network.target
StartLimitBurst=50
StartLimitIntervalSec=300

[Service]
Type=simple
User=YOUR_LINUX_USERNAME
WorkingDirectory=/path/to/TelegramForwarder
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable tg-forwarder
sudo systemctl start tg-forwarder
```

Replace `YOUR_LINUX_USERNAME` and `/path/to/TelegramForwarder` with your actual values.

Check it's running:
```bash
sudo systemctl status tg-forwarder
journalctl -u tg-forwarder -f   # Live logs
```

### Multiple Instances

To run separate instances for different users (each with their own credentials, database, and rules):

```bash
# Copy the whole directory
cp -r TelegramForwarder TelegramForwarder-alice

# Give alice her own config
cd TelegramForwarder-alice
cp .env .env.bak
nano .env  # Alice's API_ID, API_HASH, BOT_TOKEN, USER_ID
           # Change RSS_PORT to something unused (e.g. 8101)

# First run for alice (phone verification)
python3 main.py
# Enter alice's verification code, then Ctrl+C

# Create a second service (copy the service file, change the name and path)
sudo cp /etc/systemd/system/tg-forwarder.service /etc/systemd/system/tg-forwarder-alice.service
sudo nano /etc/systemd/system/tg-forwarder-alice.service
# Update WorkingDirectory to point to TelegramForwarder-alice

sudo systemctl daemon-reload
sudo systemctl enable tg-forwarder-alice
sudo systemctl start tg-forwarder-alice
```

Each instance is completely isolated — separate database, separate sessions, separate bot, separate rules. Users cannot see or affect each other's data.

---

## 📚 Usage Guide

### 🌟 Basic Usage Examples

Say you've subscribed to the channels "TG News" (https://t.me/tgnews) and "TG Read" (https://t.me/tgread), but you want to filter out content you're not interested in:

1. Create a Telegram group/channel (e.g. "My TG Filter")
2. Add the bot to the group/channel and set it as an admin
3. In the **newly created** group/channel, send the following commands:
   ```bash
   /bind https://t.me/tgnews  or  /bind "TG News"
   /bind https://t.me/tgread  or  /bind "TG Read"
   ```
4. Configure message processing mode:
   ```bash
   /settings
   ```
   Select the forwarding rule for the corresponding channel and configure it to your preference.

   For detailed settings, see [🛠️ Feature Details](#️-feature-details).

5. Add blocked keywords:
   ```bash
   /add ad promotion 'this is an ad'
   ```

6. If the forwarded messages have formatting issues (e.g. extra symbols), use regex to fix them:
   ```bash
   /replace \*\*
   ```
   This will remove all `**` symbols from messages.

>Note: All add/remove/edit/list operations only affect the first bound rule — in this example, that's "TG News". To operate on "TG Read", first use `/settings` (`/s`), select TG Read, then click "Apply Current Rule" — after that all operations will target that rule. You can also use `/add_all` (`/aa`), `/replace_all` (`/ra`), and similar commands to apply changes to both rules simultaneously.

This way you'll receive channel messages that have been filtered and formatted to your liking.

### 🔧 Special Use Case Examples

#### 1. Some TG channel messages use embedded links that show a redirect confirmation when clicked — for example, the official NodeSeek notification channel

Original message format:
```markdown
[**Post Title**](https://www.nodeseek.com/post-xxxx-1)
```
You can apply the following commands **in order** to the notification channel's forwarding rule:
```plaintext
/replace \*\*
/replace \[(?:\[([^\]]+)\])?([^\]]+)\]\(([^)]+)\) [\1]\2\n(\3)
/replace \[\]\s*
```
All forwarded messages will then be converted to the following format, so clicking the link no longer requires a redirect confirmation:
```plaintext
Post Title
(https://www.nodeseek.com/post-xxxx-1)
```

---

#### 2. Monitored user messages that look messy can be formatted for better display

Apply the following commands **in order**:
```plaintext
/r ^(?=.) <blockquote>
/r (?<=.)(?=$) </blockquote>
```
Then set the message format to **HTML** — monitored user messages will then display much more cleanly:

![Example image](./images/user_spy.png)

---

#### 3. Rule sync operation

Enable **"Sync Rules"** in the **settings menu** and select a **target rule** — all operations on the current rule will be synced to the selected rule.

This is useful when:
- You don't want to manage rules in the current window
- You need to operate on multiple rules at once

If the current rule is only used for syncing and doesn't need to be active itself, set **"Enable Rule"** to **"No"**.

---

#### 4. How to forward to Saved Messages

> Not recommended — the setup is somewhat cumbersome.
1. In any group or channel managed by your bot, send the following command:
   ```bash
   /bind https://t.me/tgnews YourDisplayName
   ```

2. Create any new rule and configure it as follows:
   - **Enable sync**, syncing to the **rule that forwards to Saved Messages**
   - Set **forwarding mode** to **"User Mode"**
   - **Disable the rule** (set "Enable Rule" to off)

This way you can manage the Saved Messages forwarding rule from other rules, and all operations will be synced to the **Forward to Saved Messages** rule.


## 🛠️ Feature Details

### ⚡ Filter Flow
First, understand the message filter order. The options in parentheses correspond to settings:

![img](./images/flow_chart.png)



### ⚙️ Settings Reference
| Main Settings | AI Settings | Media Settings |
|---------|------|------|
| ![img](./images/settings_main.png) | ![img](./images/settings_ai.png) | ![img](./images/settings_media.png) |

#### Main Settings Reference
The following explains each setting option:
| Setting | Description |
|---------|------|
| Apply Current Rule | Once selected, keyword commands (/add, /remove_keyword, /list_keyword, etc.) and replace commands (/replace, /list_replace, etc.) — including add, remove, edit, list, import, and export — will apply to the current rule |
| Enable Rule | When selected, the current rule is enabled; otherwise it is disabled |
| Current Keyword Mode | Click to toggle between blacklist/whitelist mode. Because the blacklist and whitelist are stored separately, you must switch manually. Note: all keyword add/remove/edit/list operations are tied to the mode selected here. If you want to operate on the whitelist for the current rule, make sure this is set to whitelist mode |
| Include Sender Name and ID in Keyword Filtering | When enabled, keyword filtering will also consider the sender's name and ID (not added to the actual message), which can be used to filter messages from specific users |
| Processing Mode | Toggle between Edit/Forward mode. In Edit mode the original message is modified directly; in Forward mode the processed message is forwarded to the target chat. Note: Edit mode only works if you are an admin and the original message is a channel post or a message you sent in a group |
| Filter Mode | Toggle between Blacklist Only / Whitelist Only / Blacklist then Whitelist / Whitelist then Blacklist. Since blacklist and whitelist are stored separately, choose the filtering method that suits your needs |
| Forwarding Mode | Toggle between User/Bot mode. In User mode, messages are forwarded using the user account; in Bot mode, messages are sent using the bot account |
| Replace Mode | When enabled, messages will be processed according to the configured replacement rules |
| Message Format | Toggle between Markdown/HTML format — takes effect at the final send stage. Markdown is generally fine as the default |
| Preview Mode | Toggle between On / Off / Follow Original. When on, the first link in the message is previewed. Default follows the preview state of the original message |
| Original Sender / Original Link / Send Time | When enabled, these pieces of information are appended to the message at send time. Off by default. Custom templates can be set in the "Other Settings" menu |
| Delayed Processing | When enabled, the bot waits for a configured delay before re-fetching the original message content and starting the processing pipeline. Useful for channels/groups that frequently edit messages. Custom delay times can be added in `config/delay_time.txt` |
| Delete Original Message | When enabled, the original message is deleted. Confirm you have delete permissions before enabling |
| Direct Comments Button | When enabled, a button linking directly to the comments section is added below the forwarded message, provided the original message has a comments section |
| Sync to Other Rules | When enabled, all operations on the current rule are synced to other rules. Everything except "Enable Rule" and "Enable Sync" is synced |

#### Media Settings Reference
| Setting | Description |
|---------|------|
| Media Type Filter | When enabled, media types that are not selected will be filtered out |
| Selected Media Types | Choose the media types to **block**. Note: Telegram's media classification is fixed and consists mainly of: photo, document, video, audio, voice. Any file that is not a photo, video, audio, or voice message is classified as "document" — this includes executable files (.exe), archives (.zip), text files (.txt), etc. |
| Media Size Filter | When enabled, media exceeding the configured size limit will be filtered out |
| Media Size Limit | Set the media size limit in MB. Custom sizes can be added in `config/media_size.txt` |
| Notify When Media Exceeds Limit | When enabled, a notification message is sent when media exceeds the size limit |
| Media Extension Filter | When enabled, media with selected file extensions will be filtered out |
| Media Extension Filter Mode | Toggle between blacklist/whitelist mode |
| Selected Media Extensions | Choose the file extensions to filter. Custom extensions can be added in `config/media_extensions.txt` |
| Pass Text Through | When enabled, filtering media will not block the entire message — text will be forwarded separately |

#### Other Settings Reference

The Other Settings menu consolidates several commonly used commands into an interactive UI, including:
- Copy rule
- Copy keywords
- Copy replacement rules
- Clear keywords
- Clear replacement rules
- Delete rule

Clear keywords, clear replacement rules, and delete rule can be applied to other rules as well.

You can also configure custom templates here, including: sender info template, time template, and original link template.
| Setting | Description |
|---------|------|
| Invert Blacklist | When enabled, the blacklist is treated as a whitelist. In "Whitelist then Blacklist" mode, the blacklist acts as a second-tier whitelist |
| Invert Whitelist | When enabled, the whitelist is treated as a blacklist. In "Whitelist then Blacklist" mode, the whitelist acts as a second-tier blacklist |

Combined with "X then X" modes, this enables a double-layer blacklist/whitelist mechanism. For example, after inverting the blacklist, the blacklist in "Whitelist then Blacklist" mode becomes a second-level whitelist — useful for monitoring specific users and filtering their messages by special keywords, among many other scenarios.



### 🤖 AI Features

The project has built-in AI API integrations from major providers, which can help you:
- Automatically translate foreign language content
- Generate scheduled summaries of group messages
- Intelligently filter out advertisements
- Automatically tag content
...

#### Configuration

1. Configure your AI API in the `.env` file:
```ini
# OpenAI API
OPENAI_API_KEY=your_key
OPENAI_API_BASE=  # Optional, defaults to the official endpoint

# Claude API
CLAUDE_API_KEY=your_key

# Other supported APIs...
```

#### Custom Model

Can't find the model you want? Add it in `config/ai_models.json`.

#### AI Processing

The following placeholders can be used in AI processing prompts:
- `{source_message_context:N}` - Fetch the latest N messages from the source chat
- `{target_message_context:N}` - Fetch the latest N messages from the target chat
- `{source_message_time:N}` - Fetch messages from the source chat in the last N minutes
- `{target_message_time:N}` - Fetch messages from the target chat in the last N minutes

Example prompt:

Pre-requisite: after enabling AI processing, run keyword filtering again and add `#skip` to the filter keywords.
```
This is a news aggregation channel that collects messages from multiple sources. Your job is to determine whether the new article duplicates any historical article. If it does, reply only with "#skip". Otherwise, return the full original text of the new article and preserve its formatting.
Remember: you may only return "#skip" or the original text of the new article.
Here is the history: {target_message_context:10}
Here is the new article:
```

#### Scheduled Summary

When scheduled summary is enabled, the bot will automatically summarize the past 24 hours of messages at a configured time (default: 7:00 AM every day).

- Multiple summary times can be added in `config/summary_time.txt`
- Set the default timezone in `.env`
- Customize the summary prompt

> Note: The summary feature consumes a significant amount of API quota — enable it only as needed.

### 📢 Push Notifications

In addition to forwarding messages within Telegram, the project integrates Apprise. Leveraging its powerful push notification capabilities, you can easily distribute messages to chat apps, email, SMS, Webhooks, APIs, and many other platforms.

| Push Settings Main | Push Settings Sub |
|---------|------|
| ![img](./images/settings_push.png) | ![img](./images/settings_push_sub1.png) |

#### Settings Reference

| Setting | Description |
|---------|------|
| Forward to Push Config Only | When enabled, skips the forwarding filter and goes directly to the push filter |
| Media Send Mode | Supports two modes:<br>- Single: each media file is pushed as a separate message<br>- All: all media files are combined into a single message<br>Which mode to use depends on whether the target platform supports multiple attachments in a single push |

### How to add a push configuration?
For the full list of supported platforms and configuration formats, refer to the [Apprise Wiki](https://github.com/caronc/apprise/wiki).

**Example: push via ntfy.sh**

*   Say you want to push to a topic named `my_topic` on ntfy.sh.
*   According to the Apprise Wiki, the format is `ntfy://ntfy.sh/your_topic_name`.
*   The configuration URL you need to add is:
    ```
    ntfy://ntfy.sh/my_topic
    ```



## 📰 RSS Feed

The project integrates a feature to convert Telegram messages into an RSS feed, making it easy to expose Telegram channel/group content in standard RSS format so it can be tracked by any RSS reader.

### Enable RSS

1. Configure RSS-related parameters in your `.env` file:
   ```ini
   # RSS configuration
   # Whether to enable RSS (true/false)
   RSS_ENABLED=true
   # Base URL for RSS access — leave blank to use the default access URL (e.g. https://rss.example.com)
   RSS_BASE_URL=
   # Base URL for RSS media files — leave blank to use the default access URL (e.g. https://media.example.com)
   RSS_MEDIA_BASE_URL=
   ```
2. Uncomment the relevant section in `docker-compose.yml`:
   ```
    # Uncomment the following if you want to use the RSS feature
     ports:
       - 9804:8000
   ```
3. Restart the service to enable RSS:
   ```bash
   docker-compose restart
   ```
> Note: Users on older versions will need to redeploy using the new docker-compose.yml file: [docker-compose.yml](./docker-compose.yml)

### Access the RSS Dashboard

**Option 1 — Telegram Mini App (recommended when using HTTPS)**

Send `/rss` to your bot. If `RSS_BASE_URL` starts with `https://`, the bot sends a button that opens the dashboard directly inside Telegram as a Mini App. Authentication is handled automatically via Telegram's signed `initData` — no separate login needed.

**Option 2 — Browser**

Open a browser and go to `http://your-server-address:9804/` and log in with the credentials you set on first use.

### Nginx Configuration

> **Mini App requirement**: Telegram Mini Apps require an HTTPS URL. Set `RSS_BASE_URL` to your `https://` domain in `.env` to get the in-app button from `/rss`. HTTP deployments fall back to a plain link button.

```nginx
location / {
    proxy_pass http://127.0.0.1:9804;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
}
```

### RSS Config Management

Related screens:

| Login | Dashboard | Create/Edit Config |
|---------|------|------|
| ![img](./images/rss_login.png) | ![img](./images/rss_dashboard.png) | ![img](./images/rss_create_config.png) |


### Create/Edit Config Screen Reference
| Setting | Description |
|---------|------|
| Rule ID | Select an existing forwarding rule to use for generating the RSS feed |
| Copy Existing Config | Select an existing RSS config to copy its settings into the current form |
| Feed Title | Set the feed title |
| Auto-fill | Click to automatically generate the feed title from the source chat name of the selected rule |
| Feed Description | Set the feed description |
| Language | Placeholder — no special function yet |
| Max Items | Set the maximum number of items in the RSS feed. Default is 50. For sources with a lot of media, set this according to your available disk space |
| Use AI to Extract Title and Content | When enabled, an AI service will automatically analyze messages to extract the title and content and clean up the formatting. The AI model is configured in the bot settings and is not affected by the bot's "Enable AI Processing" toggle. Enabling this option is mutually exclusive with all settings below it |
| AI Extraction Prompt | Set the prompt for AI title and content extraction. If customizing, make sure the AI returns content in the following JSON format: `{ "title": "title", "content": "body content" }` |
| Auto-extract Title | When enabled, a preset regex automatically extracts the title |
| Auto-extract Content | When enabled, a preset regex automatically extracts the content |
| Auto-convert Markdown to HTML | When enabled, a library automatically converts Telegram's Markdown format to standard HTML. If you prefer to handle this yourself, use `/replace` in the bot |
| Enable Custom Title Extraction Regex | When enabled, a custom regex is used to extract the title |
| Enable Custom Content Extraction Regex | When enabled, a custom regex is used to extract the content |
| Priority | Sets the execution order of regex expressions — lower numbers have higher priority. The system runs them from highest to lowest priority, and **the output of each regex is fed as input to the next**, until all extractions are complete |
| Regex Test | Can be used to test whether the current regex matches the target text |

### Special Notes
- If only auto-extract title is enabled (not auto-extract content), the content will be the full Telegram message including the extracted title
- If no content processing options or regex are configured, the first 20 characters are automatically used as the title, and the content is the raw message


### Special Settings
If `RSS_ENABLED=true` is set in `.env`, a new **"Forward to RSS Only"** option will appear in the bot's settings. When enabled, messages go through all processing steps but are stopped at the RSS filter — no forwarding or editing is performed.


### Notes

- There is no password recovery feature — keep your account credentials safe.

## 🎯 Special Features

### 🔗 Link Forwarding

Send a message link to the bot to forward that message to the current chat window, bypassing any forwarding or copy restrictions. (The project itself already ignores forwarding and copy restrictions by design.)

### 🔄 Integration with Universal Forum Block Plugin
> https://github.com/heavrnl/universalforumblock

Make sure the relevant parameters are configured in your `.env` file, then use `/ufb_bind <forum_domain>` in a chat window that already has a binding. This enables three-way synchronized blocking. Use `/ufb_item_change` to switch which type of data is synced for the current domain: homepage keywords / homepage usernames / content page keywords / content page usernames.

## 📝 Command List

```bash
Command List

Basic Commands
/start - Start using the bot
/help(/h) - Show this help message

Binding and Settings
/bind(/b) <source chat link or name> [target chat link or name] - Bind a source chat
/settings(/s) [rule ID] - Manage forwarding rules
/changelog(/cl) - View the changelog

Forwarding Rule Management
/copy_rule(/cr) <source rule ID> [target rule ID] - Copy all settings from the specified rule to the current rule or target rule ID
/delete_rule(/dr) <rule ID> [rule ID] [rule ID] ... - Delete the specified rule(s)
/list_rule(/lr) - List all forwarding rules

Keyword Management
/add(/a) <keyword> [keyword] ["key word"] ['key word'] ... - Add plain keywords
/add_regex(/ar) <regex> [regex] [regex] ... - Add regex keywords
/add_all(/aa) <keyword> [keyword] [keyword] ... - Add plain keywords to all rules bound to the current channel
/add_regex_all(/ara) <regex> [regex] [regex] ... - Add regex keywords to all rules
/list_keyword(/lk) - List all keywords
/remove_keyword(/rk) <keyword> ["key word"] ['key word'] ... - Remove a keyword
/remove_keyword_by_id(/rkbi) <ID> [ID] [ID] ... - Remove keywords by ID
/remove_all_keyword(/rak) <keyword> ["key word"] ['key word'] ... - Remove the specified keyword from all rules bound to the current channel
/clear_all_keywords(/cak) - Clear all keywords from the current rule
/clear_all_keywords_regex(/cakr) - Clear all regex keywords from the current rule
/copy_keywords(/ck) <rule ID> - Copy keywords from the specified rule to the current rule
/copy_keywords_regex(/ckr) <rule ID> - Copy regex keywords from the specified rule to the current rule
/copy_replace(/crp) <rule ID> - Copy replacement rules from the specified rule to the current rule
/copy_rule(/cr) <rule ID> - Copy all settings from the specified rule to the current rule (includes keywords, regex, replacement rules, media settings, etc.)

Replacement Rule Management
/replace(/r) <regex> [replacement] - Add a replacement rule
/replace_all(/ra) <regex> [replacement] - Add a replacement rule to all rules
/list_replace(/lrp) - List all replacement rules
/remove_replace(/rr) <index> - Remove a replacement rule
/clear_all_replace(/car) - Clear all replacement rules from the current rule
/copy_replace(/crp) <rule ID> - Copy replacement rules from the specified rule to the current rule

Import / Export
/export_keyword(/ek) - Export keywords from the current rule
/export_replace(/er) - Export replacement rules from the current rule
/import_keyword(/ik) <attach file simultaneously> - Import plain keywords
/import_regex_keyword(/irk) <attach file simultaneously> - Import regex keywords
/import_replace(/ir) <attach file simultaneously> - Import replacement rules

RSS
/rss - Open the RSS feed dashboard (Mini App button or direct link)
/delete_rss_user(/dru) [username] - Delete an RSS user

UFB
/ufb_bind(/ub) <domain> - Bind a UFB domain
/ufb_unbind(/uu) - Unbind a UFB domain
/ufb_item_change(/uic) - Switch UFB sync config type

Tips
• Text in parentheses is the shorthand form of the command
• Angle brackets <> indicate required parameters
• Square brackets [] indicate optional parameters
• Import commands require a file to be attached at the same time
```

## 💐 Credits

- [Apprise](https://github.com/caronc/apprise)
- [Telethon](https://github.com/LonamiWebs/Telethon)

## ☕ Donate

If you find this project useful, feel free to buy me a coffee:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/0heavrnl)


## 📄 License

This project is licensed under the [GPL-3.0](LICENSE) license. See the [LICENSE](LICENSE) file for details.

