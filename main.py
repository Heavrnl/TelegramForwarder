from telethon import TelegramClient, types
from telethon.tl.types import BotCommand
from telethon.tl.functions.bots import SetBotCommandsRequest
from models.models import init_db
from dotenv import load_dotenv
from message_listener import setup_listeners
import os
import asyncio
import logging
import uvicorn
import multiprocessing
from models.db_operations import DBOperations
from scheduler.summary_scheduler import SummaryScheduler
from scheduler.chat_updater import ChatUpdater
from handlers.bot_handler import send_welcome_message
from rss.main import app as rss_app
from utils.log_config import setup_logging

# 设置Docker日志的默认配置，如果docker-compose.yml中没有配置日志选项将使用这些值
os.environ.setdefault('DOCKER_LOG_MAX_SIZE', '10m')
os.environ.setdefault('DOCKER_LOG_MAX_FILE', '3')

# 设置日志配置
setup_logging()

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 从环境变量获取配置
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')
phone_number = os.getenv('PHONE_NUMBER')

# 创建 DBOperations 实例
db_ops = None

scheduler = None
chat_updater = None


async def init_db_ops():
    """初始化 DBOperations 实例"""
    global db_ops
    if db_ops is None:
        db_ops = await DBOperations.create()
    return db_ops


# 创建文件夹
os.makedirs('./sessions', exist_ok=True)
os.makedirs('./temp', exist_ok=True)


# 清空./temp文件夹
def clear_temp_dir():
    for file in os.listdir('./temp'):
        os.remove(os.path.join('./temp', file))

proxy = None
proxy_type = os.getenv('PROXY_TYPE')
if proxy_type and proxy_type.lower() != 'none':
    proxy_host = os.getenv('PROXY_HOST')
    proxy_port = os.getenv('PROXY_PORT')
    if not proxy_host or not proxy_port:
        logger.error("代理配置不完整，缺少 PROXY_HOST 或 PROXY_PORT")
        raise ValueError("代理配置不完整，缺少 PROXY_HOST 或 PROXY_PORT")
    proxy_username = os.getenv('PROXY_USERNAME', '')
    proxy_password = os.getenv('PROXY_PASSWORD', '')
    proxy = (proxy_type, proxy_host, int(proxy_port), True, proxy_username, proxy_password)

# 创建客户端
user_client = TelegramClient('./sessions/user', api_id, api_hash, proxy=proxy)
bot_client = TelegramClient('./sessions/bot', api_id, api_hash, proxy=proxy)

# 初始化数据库
engine = init_db()


def run_rss_server(host: str, port: int):
    """在新进程中运行 RSS 服务器"""
    uvicorn.run(
        rss_app,
        host=host,
        port=port
    )


async def start_clients():
    # 初始化 DBOperations
    global db_ops, scheduler, chat_updater
    db_ops = await DBOperations.create()

    try:
        # 启动用户客户端
        await user_client.start(phone=phone_number)
        me_user = await user_client.get_me()
        print(f'用户客户端已启动: {me_user.first_name} (@{me_user.username})')

        # 启动机器人客户端
        await bot_client.start(bot_token=bot_token)
        me_bot = await bot_client.get_me()
        print(f'机器人客户端已启动: {me_bot.first_name} (@{me_bot.username})')

        # 设置消息监听器
        await setup_listeners(user_client, bot_client)

        # 注册命令
        await register_bot_commands(bot_client)

        # 创建并启动调度器
        scheduler = SummaryScheduler(user_client, bot_client)
        await scheduler.start()
        
        # 创建并启动聊天信息更新器
        chat_updater = ChatUpdater(user_client)
        await chat_updater.start()

        # 如果启用了 RSS 服务
        if os.getenv('RSS_ENABLED', '').lower() == 'true':
            try:
                rss_host = os.getenv('RSS_HOST', '0.0.0.0')
                rss_port = int(os.getenv('RSS_PORT', '8000'))
                logger.info(f"正在启动 RSS 服务 (host={rss_host}, port={rss_port})")
                
                # 在新进程中启动 RSS 服务
                rss_process = multiprocessing.Process(
                    target=run_rss_server,
                    args=(rss_host, rss_port)
                )
                rss_process.start()
                logger.info("RSS 服务启动成功")
            except Exception as e:
                logger.error(f"启动 RSS 服务失败: {str(e)}")
                logger.exception(e)
        else:
            logger.info("RSS 服务未启用")

        # 发送欢迎消息
        await send_welcome_message(bot_client)

        # 等待两个客户端都断开连接
        await asyncio.gather(
            user_client.run_until_disconnected(),
            bot_client.run_until_disconnected()
        )
    finally:
        # 关闭 DBOperations
        if db_ops and hasattr(db_ops, 'close'):
            await db_ops.close()
        # 停止调度器
        if scheduler:
            scheduler.stop()
        # 停止聊天信息更新器
        if chat_updater:
            chat_updater.stop()
        # 如果 RSS 服务在运行，停止它
        if 'rss_process' in locals() and rss_process.is_alive():
            rss_process.terminate()
            rss_process.join()


async def register_bot_commands(bot):
    """注册机器人命令"""
    # # 先清空现有命令
    # try:
    #     await bot(SetBotCommandsRequest(
    #         scope=types.BotCommandScopeDefault(),
    #         lang_code='',
    #         commands=[]  # 空列表清空所有命令
    #     ))
    #     logger.info('已清空现有机器人命令')
    # except Exception as e:
    #     logger.error(f'清空机器人命令时出错: {str(e)}')

    commands = [
        # 基础命令
        BotCommand(
            command='start',
            description='开始使用'
        ),
        BotCommand(
            command='help',
            description='查看帮助'
        ),
        # 绑定和设置
        BotCommand(
            command='bind',
            description='绑定源聊天'
        ),
        BotCommand(
            command='settings',
            description='管理转发规则'
        ),
        BotCommand(
            command='switch',
            description='切换当前需要设置的聊天规则'
        ),
        # 关键字管理
        BotCommand(
            command='add',
            description='添加关键字'
        ),
        BotCommand(
            command='add_regex',
            description='添加正则关键字'
        ),
        BotCommand(
            command='add_all',
            description='添加普通关键字到所有规则'
        ),
        BotCommand(
            command='add_regex_all',
            description='添加正则表达式到所有规则'
        ),
        BotCommand(
            command='list_keyword',
            description='列出所有关键字'
        ),
        BotCommand(
            command='remove_keyword',
            description='删除关键字'
        ),
        BotCommand(
            command='remove_keyword_by_id',
            description='按ID删除关键字'
        ),
        BotCommand(
            command='remove_all_keyword',
            description='删除当前频道绑定的所有规则的指定关键字'
        ),
        # 替换规则管理
        BotCommand(
            command='replace',
            description='添加替换规则'
        ),
        BotCommand(
            command='replace_all',
            description='添加替换规则到所有规则'
        ),
        BotCommand(
            command='list_replace',
            description='列出所有替换规则'
        ),
        BotCommand(
            command='remove_replace',
            description='删除替换规则'
        ),
        # 导入导出功能
        BotCommand(
            command='export_keyword',
            description='导出当前规则的关键字'
        ),
        BotCommand(
            command='export_replace',
            description='导出当前规则的替换规则'
        ),
        BotCommand(
            command='import_keyword',
            description='导入普通关键字'
        ),
        BotCommand(
            command='import_regex_keyword',
            description='导入正则表达式关键字'
        ),
        BotCommand(
            command='import_replace',
            description='导入替换规则'
        ),
        # UFB相关功能
        BotCommand(
            command='ufb_bind',
            description='绑定ufb域名'
        ),
        BotCommand(
            command='ufb_unbind',
            description='解绑ufb域名'
        ),
        BotCommand(
            command='ufb_item_change',
            description='切换ufb同步配置类型'
        ),
        BotCommand(
            command='clear_all_keywords',
            description='清除当前规则的所有关键字'
        ),
        BotCommand(
            command='clear_all_keywords_regex',
            description='清除当前规则的所有正则关键字'
        ),
        BotCommand(
            command='clear_all_replace',
            description='清除当前规则的所有替换规则'
        ),
        BotCommand(
            command='copy_keywords',
            description='复制参数规则的关键字到当前规则'
        ),
        BotCommand(
            command='copy_keywords_regex',
            description='复制参数规则的正则关键字到当前规则'
        ),
        BotCommand(
            command='copy_replace',
            description='复制参数规则的替换规则到当前规则'
        ),
        BotCommand(
            command='copy_rule',
            description='复制参数规则到当前规则'
        ),
        BotCommand(
            command='changelog',
            description='查看更新日志'
        ),
        BotCommand(
            command='list_rule',
            description='列出所有转发规则'
        ),
        BotCommand(
            command='delete_rule',
            description='删除转发规则'
        ),
        BotCommand(
            command='delete_rss_user',
            description='删除RSS用户'
        ),


        # BotCommand(
        #     command='clear_all',
        #     description='慎用！清空所有数据'
        # ),
    ]

    try:
        result = await bot(SetBotCommandsRequest(
            scope=types.BotCommandScopeDefault(),
            lang_code='',  # 空字符串表示默认语言
            commands=commands
        ))
        if result:
            logger.info('已成功注册机器人命令')
        else:
            logger.error('注册机器人命令失败')
    except Exception as e:
        logger.error(f'注册机器人命令时出错: {str(e)}')


if __name__ == '__main__':
    # 运行事件循环
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_clients())
    except KeyboardInterrupt:
        print("正在关闭客户端...")
    finally:
        loop.close()