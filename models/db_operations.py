from sqlalchemy.exc import IntegrityError
from models.models import Keyword, ReplaceRule, ForwardRule, MediaTypes, MediaExtensions, RSSConfig, RSSPattern, User, ApplyRuleChat, Chat
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy.orm import joinedload
import logging
import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from ufb.ufb_client import UFBClient
from models.models import get_session
from sqlalchemy import text

logger = logging.getLogger(__name__)
load_dotenv()



class DBOperations:
    def __init__(self):
        self.ufb_client = None

    @classmethod
    async def create(cls):
        """创建DBOperations实例"""
        instance = cls()
        await instance.init_ufb()
        return instance

    async def init_ufb(self):
        """初始化UFB客户端"""
        try:
            # 从环境变量获取UFB配置
            logger.info("初始化UFB客户端")
            is_ufb = os.getenv('UFB_ENABLED', 'false').lower() == 'true'
            if is_ufb:
                server_url = os.getenv('UFB_SERVER_URL', '')
                token = os.getenv('UFB_TOKEN')
                logger.info(f"UFB配置: server_url={server_url}, token={token and '***'}")
                
                if server_url and token:
                    # 处理URL
                    if not server_url.startswith(('ws://', 'wss://')):
                        if server_url.startswith('http://'):
                            server_url = f"ws://{server_url[7:]}"
                        elif server_url.startswith('https://'):
                            server_url = f"wss://{server_url[8:]}"
                        else:
                            server_url = f"wss://{server_url}"
                    
                    logger.info(f"处理后的URL: {server_url}")
                    self.ufb_client = UFBClient()
                    logger.info("UFB客户端已创建")
                    
                    try:
                        await self.ufb_client.start(server_url=server_url, token=token)
                        logger.info("UFB客户端已启动")
                    except Exception as e:
                        logger.error(f"UFB客户端启动失败: {str(e)}")
                        self.ufb_client = None
                else:
                    logger.warning("UFB配置不完整，未启用UFB功能")
                    self.ufb_client = None
            else:
                logger.info("UFB未启用")
        except Exception as e:
            logger.error(f"初始化UFB时出错: {str(e)}")
            self.ufb_client = None
    
    
    async def sync_to_server(self,session,rule_id):
        """同步UFB配置"""
        if self.ufb_client and os.getenv('UFB_ENABLED').lower() == 'true':
            # 通过rule_id获取规则ufb是否开启
            rule = session.query(ForwardRule).filter(ForwardRule.id == rule_id).first()
            ufb_domain = rule.ufb_domain
            if rule.is_ufb and ufb_domain:
                item = rule.ufb_item
                # 获取规则的所有非正则表达关键字
                normal_keywords = session.query(Keyword).filter(
                    Keyword.rule_id == rule_id,
                    Keyword.is_regex == False
                ).all()
                
                # 获取规则的所有正则表达关键字
                regex_keywords = session.query(Keyword).filter(
                    Keyword.rule_id == rule_id,
                    Keyword.is_regex == True
                ).all()

                # 获取../ufb/config/config.json文件
                config_file = Path(__file__).parent.parent / 'ufb' / 'config' / 'config.json'
                # 读取文件
                with open(config_file, 'r', encoding='utf-8') as file:
                    config = json.load(file)

                # 在userConfig中找到对应domain的配置
                for user_config in config.get('userConfig', []):
                    if user_config.get('domain') == ufb_domain:
                        # 根据item类型更新关键字
                        if item == 'main':
                            keywords_config = user_config.get('mainAndSubPageKeywords', {})
                        elif item == 'content':
                            keywords_config = user_config.get('contentPageKeywords', {})
                        elif item == 'main_username':
                            keywords_config = user_config.get('mainAndSubPageUserKeywords', {})
                        elif item == 'content_username':
                            keywords_config = user_config.get('contentPageUserKeywords', {})

                        # 更新关键字列表
                        keywords_config['keywords'] = [k.keyword for k in normal_keywords]
                        keywords_config['regexPatterns'] = [k.keyword for k in regex_keywords]

                        # 保存回对应的位置
                        if item == 'main':  
                            user_config['mainAndSubPageKeywords'] = keywords_config
                        elif item == 'content':
                            user_config['contentPageKeywords'] = keywords_config
                        elif item == 'main_username':
                            user_config['mainAndSubPageUserKeywords'] = keywords_config
                        elif item == 'content_username':
                            user_config['contentPageUserKeywords'] = keywords_config
                        else:
                            logger.error(f"未设置UFB_ITEM环境变量")
                            return
                        break
                
                # 更新时间戳
                config['globalConfig']['SYNC_CONFIG']['lastSyncTime'] = int(time.time() * 1000)
                # 保存到本地文件
                with open(config_file, 'w', encoding='utf-8') as file:
                    json.dump(config, file, ensure_ascii=False, indent=2)

                # 更新配置到服务器
                if self.ufb_client.is_connected:
                    await self.ufb_client.websocket.send(json.dumps({
                        "additional_info": "to_server",
                        "type": "update",
                        **config
                    }))
                    logger.info("UFB配置已同步")
                else:
                    logger.warning("UFB客户端未连接，无法同步配置")
            else:
                logger.warning("UFB未开启，无法同步配置")
        else:
            logger.warning("UFB客户端未初始化，无法同步配置")

    async def sync_from_json(self, config):
        """从收到的JSON配置同步关键字到数据库
        
        Args:
            config: 收到的配置数据
        """
        logger.info(f"从JSON同步关键字到数据库")
        session = get_session()
        try:
            # 获取所有启用了UFB的规则
            ufb_rules = session.query(ForwardRule).filter(
                ForwardRule.is_ufb == True,
                ForwardRule.ufb_domain != None
            ).all()
            
            if not ufb_rules:
                logger.info("没有找到启用UFB的规则")
                return
            logger.info(f"ufb_rules: {ufb_rules}")
            
            # 遍历所有启用UFB的规则
            for rule in ufb_rules:
                # 获取item类型
                item = rule.ufb_item
                logger.info(f"item: {item}")
                if not item:
                    logger.error("未设置UFB_ITEM环境变量")
                    continue  # 跳过没有设置 item 的规则
                
                # 在收到的配置中查找对应domain的配置
                for user_config in config.get('userConfig', []):
                    if user_config.get('domain') == rule.ufb_domain:
                        logger.info(f"找到匹配的domain配置: {rule.ufb_domain}")
                        
                        # 根据item类型获取关键字配置
                        if item == 'main':
                            keywords_config = user_config.get('mainAndSubPageKeywords', {})
                        elif item == 'content':
                            keywords_config = user_config.get('contentPageKeywords', {})
                        elif item == 'main_username':
                            keywords_config = user_config.get('mainAndSubPageUserKeywords', {})
                        elif item == 'content_username':
                            keywords_config = user_config.get('contentPageUserKeywords', {})
                        else:
                            logger.error(f"未设置UFB_ITEM环境变量")
                            continue
                        
                        # 清空现有关键字
                        session.query(Keyword).filter(
                            Keyword.rule_id == rule.id
                        ).delete()
                        
                        # 添加普通关键字
                        for keyword in keywords_config.get('keywords', []):
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=False
                            )
                            session.add(new_keyword)
                            
                        # 添加正则关键字
                        for pattern in keywords_config.get('regexPatterns', []):
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=pattern,
                                is_regex=True
                            )
                            session.add(new_keyword)
                        
                        session.commit()
                        logger.info(f"已从JSON同步关键字到规则 {rule.id} (domain: {rule.ufb_domain})")
                        break  # 找到匹配的domain后跳出内层循环
        finally:
            session.close()

    async def add_keywords(self, session, rule_id, keywords, is_regex=False, is_blacklist=False):
        """添加关键字到规则

        Args:
            session: 数据库会话
            rule_id: 规则ID
            keywords: 关键字列表
            is_regex: 是否是正则表达式
            is_blacklist: 是否为黑名单关键字

        Returns:
            tuple: (成功数量, 重复数量)
        """
        success_count = 0
        duplicate_count = 0

        for keyword in keywords:
            try:
                # 检查是否存在相同的关键字（考虑黑白名单）
                existing_keyword = session.query(Keyword).filter(
                    Keyword.rule_id == rule_id,
                    Keyword.keyword == keyword,
                    Keyword.is_blacklist == is_blacklist
                ).first()

                if existing_keyword:
                    duplicate_count += 1
                    continue

                new_keyword = Keyword(
                    rule_id=rule_id,
                    keyword=keyword,
                    is_regex=is_regex,
                    is_blacklist=is_blacklist
                )
                session.add(new_keyword)
                session.flush()
                success_count += 1
            except Exception as e:
                logger.error(f"添加关键字时出错: {str(e)}")
                session.rollback()
                duplicate_count += 1
                continue

        await self.sync_to_server(session, rule_id)
        return success_count, duplicate_count

    async def get_keywords(self, session, rule_id, add_mode):
        """获取规则的所有关键字
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            
        Returns:
            list: 关键字列表
        """
        return session.query(Keyword).filter(
            Keyword.rule_id == rule_id,
            Keyword.is_blacklist == (add_mode == 'blacklist')
        ).all()

    async def delete_keywords(self, session, rule_id, indices):
        """删除指定索引的关键字
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            indices: 要删除的索引列表（1-based）
            
        Returns:
            tuple: (删除数量, 剩余关键字列表)
        """
        keywords = await self.get_keywords(session, rule_id)
        if not keywords:
            return 0, []
            
        deleted_count = 0
        max_id = len(keywords)
        
        for idx in indices:
            if 1 <= idx <= max_id:
                keyword = keywords[idx - 1]
                session.delete(keyword)
                deleted_count += 1

        await self.sync_to_server(session, rule_id)
        return deleted_count, await self.get_keywords(session, rule_id)

    async def add_replace_rules(self, session, rule_id, patterns, contents=None):
        """添加替换规则
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            patterns: 匹配模式列表
            contents: 替换内容列表（可选）
            
        Returns:
            tuple: (成功数量, 重复数量)
        """
        success_count = 0
        duplicate_count = 0
        
        if contents is None:
            contents = [''] * len(patterns)
        
        for pattern, content in zip(patterns, contents):
            try:
                new_rule = ReplaceRule(
                    rule_id=rule_id,
                    pattern=pattern,
                    content=content
                )
                session.add(new_rule)
                session.flush()
                success_count += 1
            except IntegrityError:
                session.rollback()
                duplicate_count += 1
                continue
                
        return success_count, duplicate_count

    async def get_replace_rules(self, session, rule_id):
        """获取规则的所有替换规则
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            
        Returns:
            list: 替换规则列表
        """
        return session.query(ReplaceRule).filter(
            ReplaceRule.rule_id == rule_id
        ).all()

    async def delete_replace_rules(self, session, rule_id, indices):
        """删除指定索引的替换规则
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            indices: 要删除的索引列表（1-based）
            
        Returns:
            tuple: (删除数量, 剩余替换规则列表)
        """
        rules = await self.get_replace_rules(session, rule_id)
        if not rules:
            return 0, []
            
        deleted_count = 0
        max_id = len(rules)
        
        for idx in indices:
            if 1 <= idx <= max_id:
                rule = rules[idx - 1]
                session.delete(rule)
                deleted_count += 1
                
        return deleted_count, await self.get_replace_rules(session, rule_id) 

    async def get_media_types(self, session, rule_id):
        """获取媒体类型设置"""
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, "规则不存在", None
            
            media_types = session.query(MediaTypes).filter_by(rule_id=rule_id).first()
            if not media_types:
                # 如果不存在则创建默认设置
                media_types = MediaTypes(
                    rule_id=rule_id,
                    photo=False,
                    document=False,
                    video=False,
                    audio=False,
                    voice=False
                )
                session.add(media_types)
                session.commit()
            
            return True, "获取媒体类型设置成功", media_types
        except Exception as e:
            logger.error(f"获取媒体类型设置时出错: {str(e)}")
            session.rollback()
            return False, f"获取媒体类型设置时出错: {str(e)}", None

    async def update_media_types(self, session, rule_id, media_types_dict):
        """更新媒体类型设置"""
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, "规则不存在"
            
            media_types = session.query(MediaTypes).filter_by(rule_id=rule_id).first()
            if not media_types:
                media_types = MediaTypes(rule_id=rule_id)
                session.add(media_types)
            
            # 更新媒体类型设置
            for field in ['photo', 'document', 'video', 'audio', 'voice']:
                if field in media_types_dict:
                    setattr(media_types, field, media_types_dict[field])
            
            session.commit()
            return True, "更新媒体类型设置成功"
        except Exception as e:
            logger.error(f"更新媒体类型设置时出错: {str(e)}")
            session.rollback()
            return False, f"更新媒体类型设置时出错: {str(e)}"

    async def toggle_media_type(self, session, rule_id, media_type):
        """切换特定媒体类型的启用状态"""
        try:
            if media_type not in ['photo', 'document', 'video', 'audio', 'voice']:
                return False, f"无效的媒体类型: {media_type}"
                
            success, msg, media_types = await self.get_media_types(session, rule_id)
            if not success:
                return False, msg
            
            # 切换状态
            current_value = getattr(media_types, media_type)
            setattr(media_types, media_type, not current_value)
            
            session.commit()
            return True, f"媒体类型 {media_type} 切换为 {not current_value}"
        except Exception as e:
            logger.error(f"切换媒体类型时出错: {str(e)}")
            session.rollback()
            return False, f"切换媒体类型时出错: {str(e)}"

    async def add_media_extensions(self, session, rule_id, extensions):
        """添加媒体扩展名
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            extensions: 扩展名列表，比如 ['jpg', 'png', 'pdf']
        
        Returns:
            (bool, str): 成功状态和消息
        """
        try:
            added_count = 0
            for ext in extensions:
                # 确保扩展名不带点，去除可能存在的点
                ext = ext.lstrip('.')
                
                # 检查是否已存在相同的扩展名
                existing = session.execute(
                    text("SELECT id FROM media_extensions WHERE rule_id = :rule_id AND extension = :extension"),
                    {"rule_id": rule_id, "extension": ext}
                )
                
                if existing.first() is None:
                    # 添加新的扩展名
                    new_extension = MediaExtensions(rule_id=rule_id, extension=ext)
                    session.add(new_extension)
                    added_count += 1
            
            if added_count > 0:
                session.commit()
                return True, f"成功添加 {added_count} 个媒体扩展名"
            else:
                return False, "所有扩展名已存在，未添加任何新扩展名"
        
        except Exception as e:
            session.rollback()
            logger.error(f"添加媒体扩展名失败: {str(e)}")
            return False, f"添加媒体扩展名失败: {str(e)}"

    async def get_media_extensions(self, session, rule_id):
        """获取规则的媒体扩展名列表
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
        
        Returns:
            list: 媒体扩展名对象列表
        """
        try:
            # 使用SQLAlchemy文本SQL查询，不需要await
            result = session.execute(
                text("SELECT id, extension FROM media_extensions WHERE rule_id = :rule_id ORDER BY id"),
                {"rule_id": rule_id}
            )
            
            # 构建返回结果
            extensions = []
            for row in result:
                extensions.append({
                    "id": row[0],
                    "extension": row[1]
                })
            
            # 返回扩展名列表
            return extensions
        
        except Exception as e:
            # 记录错误并返回空列表
            logger.error(f"获取媒体扩展名失败: {str(e)}")
            return []

    async def delete_media_extensions(self, session, rule_id, indices):
        """删除媒体扩展名
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            indices: 要删除的扩展名ID列表
        
        Returns:
            (bool, str): 成功状态和消息
        """
        try:
            if not indices:
                return False, "未指定要删除的扩展名"
            
            for index in indices:
                # 查找并删除扩展名
                result = session.execute(
                    text("SELECT id FROM media_extensions WHERE id = :id AND rule_id = :rule_id"),
                    {"id": index, "rule_id": rule_id}
                )
                
                extension = result.first()
                if extension:
                    session.execute(
                        text("DELETE FROM media_extensions WHERE id = :id"),
                        {"id": extension[0]}
                    )
            
            session.commit()
            return True, f"成功删除 {len(indices)} 个媒体扩展名"
        except Exception as e:
            session.rollback()
            logger.error(f"删除媒体扩展名失败: {str(e)}")
            return False, f"删除媒体扩展名失败: {str(e)}"

    # RSS配置相关操作
    async def get_rss_config(self, session, rule_id):
        """获取指定规则的RSS配置"""
        return session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()

    async def create_rss_config(self, session, rule_id, **kwargs):
        """创建RSS配置"""
        rss_config = RSSConfig(rule_id=rule_id, **kwargs)
        session.add(rss_config)
        session.commit()
        return rss_config

    async def update_rss_config(self, session, rule_id, **kwargs):
        """更新RSS配置"""
        rss_config = await self.get_rss_config(session, rule_id)
        if rss_config:
            for key, value in kwargs.items():
                setattr(rss_config, key, value)
            session.commit()
        return rss_config

    async def delete_rss_config(self, session, rule_id):
        """删除RSS配置"""
        rss_config = await self.get_rss_config(session, rule_id)
        if rss_config:
            session.delete(rss_config)
            session.commit()
            return True
        return False

    # RSS模式相关操作
    async def get_rss_patterns(self, session, rss_config_id):
        """获取指定RSS配置的所有模式"""
        return session.query(RSSPattern).filter(RSSPattern.rss_config_id == rss_config_id).order_by(RSSPattern.priority).all()

    async def get_rss_pattern(self, session, pattern_id):
        """获取指定的RSS模式"""
        return session.query(RSSPattern).filter(RSSPattern.id == pattern_id).first()

    async def create_rss_pattern(self, session, rss_config_id, pattern, pattern_type, priority=0):
        """创建RSS模式"""
        logger.info(f"创建RSS模式：config_id={rss_config_id}, pattern={pattern}, type={pattern_type}, priority={priority}")
        try:
            pattern_obj = RSSPattern(
                rss_config_id=rss_config_id,
                pattern=pattern,
                pattern_type=pattern_type,
                priority=priority
            )
            session.add(pattern_obj)
            session.commit()
            logger.info(f"RSS模式创建成功：{pattern_obj.id}")
            return pattern_obj
        except Exception as e:
            logger.error(f"创建RSS模式失败：{str(e)}")
            session.rollback()
            raise

    async def update_rss_pattern(self, session, pattern_id, **kwargs):
        """更新RSS模式"""
        logger.info(f"更新RSS模式：pattern_id={pattern_id}, kwargs={kwargs}")
        try:
            pattern = session.query(RSSPattern).filter(RSSPattern.id == pattern_id).first()
            if not pattern:
                logger.error(f"RSS模式不存在：pattern_id={pattern_id}")
                raise ValueError("RSS模式不存在")
            
            for key, value in kwargs.items():
                setattr(pattern, key, value)
            
            session.commit()
            logger.info(f"RSS模式更新成功：{pattern.id}")
            return pattern
        except Exception as e:
            logger.error(f"更新RSS模式失败：{str(e)}")
            session.rollback()
            raise

    async def delete_rss_pattern(self, session, pattern_id):
        """删除RSS模式"""
        rss_pattern = await self.get_rss_pattern(session, pattern_id)
        if rss_pattern:
            session.delete(rss_pattern)
            session.commit()
            return True
        return False

    async def reorder_rss_patterns(self, session, rss_config_id, pattern_ids):
        """重新排序RSS模式"""
        patterns = await self.get_rss_patterns(session, rss_config_id)
        pattern_dict = {p.id: p for p in patterns}
        
        for index, pattern_id in enumerate(pattern_ids):
            if pattern_id in pattern_dict:
                pattern_dict[pattern_id].priority = index
        
        session.commit()

    # 用户相关操作
    async def get_user(self, session, username):
        """通过用户名获取用户"""
        return session.query(User).filter(User.username == username).first()

    async def get_user_by_id(self, session, user_id):
        """通过ID获取用户"""
        return session.query(User).filter(User.id == user_id).first()

    async def create_user(self, session, username, password):
        """创建用户"""

        user = User(
            username=username,
            password=generate_password_hash(password)
        )
        session.add(user)
        session.commit()
        return user

    async def update_user_password(self, session, username, new_password):
        """更新用户密码"""

        user = await self.get_user(session, username)
        if user:
            user.password = generate_password_hash(new_password)
            session.commit()
        return user

    async def verify_user(self, session, username, password):
        """验证用户密码"""
        
        user = await self.get_user(session, username)
        if user and check_password_hash(user.password, password):
            return user
        return None

    # 批量操作
    async def get_all_enabled_rss_configs(self, session):
        """获取所有启用的RSS配置"""
        return session.query(RSSConfig).filter(RSSConfig.enable_rss == True).all()

    async def get_rss_config_with_patterns(self, session, rule_id):
        """获取RSS配置及其所有模式"""
        return session.query(RSSConfig).options(
            joinedload(RSSConfig.patterns)
        ).filter(RSSConfig.rule_id == rule_id).first()

    # ApplyRuleChat相关操作
    async def create_apply_rule_chat(self, session, telegram_chat_id, current_rule_id=None):
        """创建应用规则聊天记录
        
        Args:
            session: 数据库会话
            telegram_chat_id: Telegram聊天ID
            current_rule_id: 当前应用的规则ID，可为空
            
        Returns:
            (bool, str, ApplyRuleChat): 成功状态、消息和创建的记录
        """
        try:
            # 检查是否已存在相同的telegram_chat_id
            existing = session.query(ApplyRuleChat).filter_by(telegram_chat_id=telegram_chat_id).first()
            if existing:
                return False, "此聊天已存在应用规则记录", existing
                
            # 创建新记录
            apply_rule_chat = ApplyRuleChat(
                telegram_chat_id=telegram_chat_id,
                current_rule_id=current_rule_id
            )
            session.add(apply_rule_chat)
            session.commit()
            
            return True, "创建应用规则聊天记录成功", apply_rule_chat
            
        except Exception as e:
            session.rollback()
            logger.error(f"创建应用规则聊天记录失败: {str(e)}")
            return False, f"创建应用规则聊天记录失败: {str(e)}", None
            
    async def get_apply_rule_chat(self, session, telegram_chat_id):
        """获取应用规则聊天记录
        
        Args:
            session: 数据库会话
            telegram_chat_id: Telegram聊天ID
            
        Returns:
            (bool, str, ApplyRuleChat): 成功状态、消息和查询到的记录
        """
        try:
            apply_rule_chat = session.query(ApplyRuleChat).filter_by(telegram_chat_id=telegram_chat_id).first()
            if not apply_rule_chat:
                return False, "未找到该聊天的应用规则记录", None
                
            return True, "获取应用规则聊天记录成功", apply_rule_chat
            
        except Exception as e:
            logger.error(f"获取应用规则聊天记录失败: {str(e)}")
            return False, f"获取应用规则聊天记录失败: {str(e)}", None
            
    async def get_apply_rule_chat_by_id(self, session, chat_id):
        """通过ID获取应用规则聊天记录
        
        Args:
            session: 数据库会话
            chat_id: 应用规则聊天记录ID
            
        Returns:
            (bool, str, ApplyRuleChat): 成功状态、消息和查询到的记录
        """
        try:
            apply_rule_chat = session.query(ApplyRuleChat).get(chat_id)
            if not apply_rule_chat:
                return False, "未找到该ID的应用规则聊天记录", None
                
            return True, "获取应用规则聊天记录成功", apply_rule_chat
            
        except Exception as e:
            logger.error(f"获取应用规则聊天记录失败: {str(e)}")
            return False, f"获取应用规则聊天记录失败: {str(e)}", None
            
    async def update_apply_rule_chat(self, session, telegram_chat_id, current_rule_id=None):
        """更新应用规则聊天记录
        
        Args:
            session: 数据库会话
            telegram_chat_id: Telegram聊天ID
            current_rule_id: 新的当前规则ID
            
        Returns:
            (bool, str, ApplyRuleChat): 成功状态、消息和更新后的记录
        """
        try:
            apply_rule_chat = session.query(ApplyRuleChat).filter_by(telegram_chat_id=telegram_chat_id).first()
            if not apply_rule_chat:
                # 如果记录不存在，则创建新记录
                return await self.create_apply_rule_chat(session, telegram_chat_id, current_rule_id)
                
            # 更新记录
            apply_rule_chat.current_rule_id = current_rule_id
            session.commit()
            
            return True, "更新应用规则聊天记录成功", apply_rule_chat
            
        except Exception as e:
            session.rollback()
            logger.error(f"更新应用规则聊天记录失败: {str(e)}")
            return False, f"更新应用规则聊天记录失败: {str(e)}", None
            
    async def delete_apply_rule_chat(self, session, telegram_chat_id):
        """删除应用规则聊天记录
        
        Args:
            session: 数据库会话
            telegram_chat_id: Telegram聊天ID
            
        Returns:
            (bool, str): 成功状态和消息
        """
        try:
            result = session.query(ApplyRuleChat).filter_by(telegram_chat_id=telegram_chat_id).delete()
            if result == 0:
                return False, "未找到该聊天的应用规则记录"
                
            session.commit()
            return True, "删除应用规则聊天记录成功"
            
        except Exception as e:
            session.rollback()
            logger.error(f"删除应用规则聊天记录失败: {str(e)}")
            return False, f"删除应用规则聊天记录失败: {str(e)}"
            
    async def get_all_apply_rule_chats(self, session):
        """获取所有应用规则聊天记录
        
        Args:
            session: 数据库会话
            
        Returns:
            list: 应用规则聊天记录列表
        """
        try:
            return session.query(ApplyRuleChat).all()
        except Exception as e:
            logger.error(f"获取所有应用规则聊天记录失败: {str(e)}")
            return []
            
    # ForwardRule相关操作
    async def check_forward_rule_exists(self, session, source_chat_id, target_chat_id):
        """检查是否已存在相同的转发规则
        
        Args:
            session: 数据库会话
            source_chat_id: 源聊天ID
            target_chat_id: 目标聊天ID
            
        Returns:
            (bool, str, ForwardRule): 是否存在, 消息, 现有规则(如果存在)
        """
        try:
            # 查询是否已存在相同source_chat_id和target_chat_id的规则
            existing_rule = session.query(ForwardRule).filter(
                ForwardRule.source_chat_id == source_chat_id,
                ForwardRule.target_chat_id == target_chat_id
            ).first()
            
            if existing_rule:
                return True, "已存在相同的转发规则", existing_rule
            
            return False, "不存在相同的转发规则", None
            
        except Exception as e:
            logger.error(f"检查转发规则是否存在时出错: {str(e)}")
            return False, f"检查转发规则是否存在时出错: {str(e)}", None
            
    async def create_forward_rule(self, session, source_chat_id, target_chat_id, source_name=None, target_name=None, **kwargs):
        """创建转发规则，同时确保Chat记录存在
        
        Args:
            session: 数据库会话
            source_chat_id: 源聊天ID（字符串ID）
            target_chat_id: 目标聊天ID（字符串ID）
            source_name: 源聊天名称
            target_name: 目标聊天名称
            **kwargs: 其他转发规则参数
            
        Returns:
            (bool, str, ForwardRule): 成功状态, 消息, 创建的规则
        """
        try:
            # 先检查是否已存在相同的规则
            exists, msg, existing_rule = await self.check_forward_rule_exists(session, source_chat_id, target_chat_id)
            if exists:
                return False, msg, existing_rule
                
            # 创建新规则
            rule = ForwardRule(
                source_chat_id=source_chat_id,
                target_chat_id=target_chat_id,
                **kwargs
            )
            
            session.add(rule)
            session.flush()  # 获取ID但不提交

            # 查看是否存在source_chat_id再创建
            success, msg, chat = await self.get_chat_by_source_id(session, source_chat_id)
            if not success:
                await self.create_chat(session, source_chat_id, source_name)
            
            return True, "创建转发规则成功", rule
            
        except Exception as e:
            session.rollback()
            logger.error(f"创建转发规则失败: {str(e)}")
            return False, f"创建转发规则失败: {str(e)}", None
            
    async def delete_forward_rule(self, session, rule_id):
        """删除转发规则，同时检查是否需要删除关联的Chat记录
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            
        Returns:
            (bool, str): 成功状态, 消息
        """
        try:
            # 获取规则
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, "规则不存在"
                
            # 获取目标聊天
            source_chat_id = rule.source_chat_id
            
            # 删除规则
            session.delete(rule)
            session.flush()

            # ApplyRuleChat对应rule_id的全部记录
            apply_rule_chats = session.query(ApplyRuleChat).filter_by(current_rule_id=rule_id).all()
            if apply_rule_chats:
                for apply_rule_chat in apply_rule_chats:
                    session.delete(apply_rule_chat)
                session.flush()
            
            # 检查是否还有其他使用该源聊天的规则
            rules_count = session.query(ForwardRule).filter_by(source_chat_id=source_chat_id).count()
            logger.info(f"rules_count: {rules_count}")
            if rules_count == 0:
                # 如果没有其他规则使用该源聊天，则删除聊天记录
                chat = session.query(Chat).filter_by(source_chat_id=source_chat_id).first()
                logger.info(f"chat: {chat}")
                if chat:
                    session.delete(chat)
                    session.flush()
                    logger.info(f"已删除不再使用的Chat记录: ID={source_chat_id}")
            
            return True, "删除转发规则成功"
            
        except Exception as e:
            session.rollback()
            logger.error(f"删除转发规则失败: {str(e)}")
            return False, f"删除转发规则失败: {str(e)}"

    # Chat表操作方法
    async def get_chat_by_source_id(self, session, source_chat_id):
        """通过source_chat_id获取Chat记录
        
        Args:
            session: 数据库会话
            source_chat_id: 源聊天ID
            
        Returns:
            (bool, str, Chat): 成功状态, 消息, Chat记录
        """
        try:
            chat = session.query(Chat).filter_by(source_chat_id=source_chat_id).first()
            if not chat:
                return False, "未找到Chat记录", None
            return True, "成功获取Chat记录", chat
        except Exception as e:
            logger.error(f"获取Chat记录出错: {str(e)}")
            return False, f"获取Chat记录出错: {str(e)}", None
            
    async def create_chat(self, session, source_chat_id, name=None):
        """创建Chat记录
        
        Args:
            session: 数据库会话
            source_chat_id: 源聊天ID
            name: 聊天名称
            
        Returns:
            (bool, str, Chat): 成功状态, 消息, 创建的Chat记录
        """
        try:
            # 检查是否已存在
            success, _, chat = await self.get_chat_by_source_id(session, source_chat_id)
            if success:
                return False, "Chat记录已存在", chat
                
            # 创建新记录
            new_chat = Chat(
                source_chat_id=source_chat_id,
                name=name
            )
            session.add(new_chat)
            session.flush()  # 获取ID而不提交
            
            return True, "成功创建Chat记录", new_chat
        except Exception as e:
            session.rollback()
            logger.error(f"创建Chat记录出错: {str(e)}")
            return False, f"创建Chat记录出错: {str(e)}", None

    async def delete_chat(self, session, source_chat_id):
        """删除Chat记录，但仅当没有关联的ForwardRule时
        
        Args:
            session: 数据库会话
            source_chat_id: 源聊天ID
            
        Returns:
            (bool, str): 成功状态, 消息
        """
        try:
            success, msg, chat = await self.get_chat_by_source_id(session, source_chat_id)
            if not success:
                return False, msg
                
            # 检查是否有关联的ForwardRule
            rules_count = session.query(ForwardRule).filter_by(source_chat_id=source_chat_id).count()
            if rules_count > 0:
                return False, f"不能删除Chat记录，仍有{rules_count}个关联的转发规则"
                
            # 执行删除
            session.delete(chat)
            session.flush()
            
            return True, "成功删除Chat记录"
        except Exception as e:
            session.rollback()
            logger.error(f"删除Chat记录出错: {str(e)}")
            return False, f"删除Chat记录出错: {str(e)}" 