from sqlalchemy.exc import IntegrityError
from models.models import Keyword, ReplaceRule, ForwardRule, MediaTypes, MediaExtensions, RSSConfig, RSSPattern, User, RuleSync, PushConfig
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
from enums.enums import ForwardMode, PreviewMode, MessageMode, AddMode, HandleMode

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

        # 获取当前规则
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"规则ID {rule_id} 不存在")
            return 0, 0

        # 处理单个规则的关键字添加
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

        # 检查是否启用了同步功能
        if rule.enable_sync:
            logger.info(f"规则 {rule_id} 启用了同步功能，正在同步关键字到关联规则")
            # 获取需要同步的规则列表
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()
            
            # 为每个同步规则添加相同的关键字
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"正在同步关键字到规则 {sync_rule_id}")
                
                # 获取同步目标规则
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"同步目标规则 {sync_rule_id} 不存在，跳过")
                    continue
                
                # 为同步目标规则添加关键字
                sync_success = 0
                sync_duplicate = 0
                for keyword in keywords:
                    try:
                        # 检查同步规则是否已有此关键字
                        existing_keyword = session.query(Keyword).filter(
                            Keyword.rule_id == sync_rule_id,
                            Keyword.keyword == keyword,
                            Keyword.is_blacklist == is_blacklist
                        ).first()
                        
                        if existing_keyword:
                            sync_duplicate += 1
                            continue
                            
                        # 添加新关键字到同步规则
                        new_keyword = Keyword(
                            rule_id=sync_rule_id,
                            keyword=keyword,
                            is_regex=is_regex,
                            is_blacklist=is_blacklist
                        )
                        session.add(new_keyword)
                        session.flush()
                        sync_success += 1
                    except Exception as e:
                        logger.error(f"同步关键字到规则 {sync_rule_id} 时出错: {str(e)}")
                        continue
                
                logger.info(f"同步规则 {sync_rule_id} 的结果: 成功={sync_success}, 重复={sync_duplicate}")

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
        # 获取当前规则
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"规则ID {rule_id} 不存在")
            return 0, []
            
        # 获取当前规则的关键字
        keywords = await self.get_keywords(session, rule_id, 'blacklist' if rule.add_mode == AddMode.BLACKLIST else 'whitelist')
        if not keywords:
            return 0, []
            
        deleted_count = 0
        max_id = len(keywords)
        
        # 保存要删除的关键字信息，用于后续同步
        keywords_to_delete = []
        for idx in indices:
            if 1 <= idx <= max_id:
                keyword = keywords[idx - 1]
                keywords_to_delete.append({
                    'keyword': keyword.keyword,
                    'is_regex': keyword.is_regex,
                    'is_blacklist': keyword.is_blacklist
                })
                session.delete(keyword)
                deleted_count += 1
        
        # 检查是否启用了同步功能
        if rule.enable_sync and keywords_to_delete:
            logger.info(f"规则 {rule_id} 启用了同步功能，正在同步删除关联规则的关键字")
            # 获取需要同步的规则列表
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()
            
            # 为每个同步规则删除相同的关键字
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"正在同步删除规则 {sync_rule_id} 的关键字")
                
                # 获取同步目标规则
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"同步目标规则 {sync_rule_id} 不存在，跳过")
                    continue
                
                # 在同步目标规则中删除相同的关键字
                sync_deleted = 0
                for kw_info in keywords_to_delete:
                    try:
                        # 查找目标规则中匹配的关键字
                        target_keywords = session.query(Keyword).filter(
                            Keyword.rule_id == sync_rule_id,
                            Keyword.keyword == kw_info['keyword'],
                            Keyword.is_regex == kw_info['is_regex'],
                            Keyword.is_blacklist == kw_info['is_blacklist']
                        ).all()
                        
                        # 删除匹配的关键字
                        for target_kw in target_keywords:
                            session.delete(target_kw)
                            sync_deleted += 1
                    except Exception as e:
                        logger.error(f"同步删除规则 {sync_rule_id} 的关键字时出错: {str(e)}")
                        continue
                
                logger.info(f"同步删除规则 {sync_rule_id} 的关键字: 删除了 {sync_deleted} 个")

        await self.sync_to_server(session, rule_id)
        return deleted_count, await self.get_keywords(session, rule_id, 'blacklist' if rule.add_mode == AddMode.BLACKLIST else 'whitelist')

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
        # 获取当前规则
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"规则ID {rule_id} 不存在")
            return 0, 0
            
        success_count = 0
        duplicate_count = 0
        
        if contents is None:
            contents = [''] * len(patterns)
        
        # 添加替换规则到主规则
        added_rules = []  # 存储成功添加的规则，用于后续同步
        for pattern, content in zip(patterns, contents):
            try:
                # 检查是否已存在相同的替换规则
                existing_rule = session.query(ReplaceRule).filter(
                    ReplaceRule.rule_id == rule_id,
                    ReplaceRule.pattern == pattern,
                    ReplaceRule.content == content
                ).first()
                
                if existing_rule:
                    duplicate_count += 1
                    continue
                    
                new_rule = ReplaceRule(
                    rule_id=rule_id,
                    pattern=pattern,
                    content=content
                )
                session.add(new_rule)
                session.flush()
                success_count += 1
                added_rules.append({'pattern': pattern, 'content': content})
            except IntegrityError:
                session.rollback()
                duplicate_count += 1
                continue
        
        # 检查是否启用了同步功能
        if rule.enable_sync and added_rules:
            logger.info(f"规则 {rule_id} 启用了同步功能，正在同步添加替换规则到关联规则")
            # 获取需要同步的规则列表
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()
            
            # 为每个同步规则添加相同的替换规则
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"正在同步添加替换规则到规则 {sync_rule_id}")
                
                # 获取同步目标规则
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"同步目标规则 {sync_rule_id} 不存在，跳过")
                    continue
                
                # 为同步目标规则添加替换规则
                sync_success = 0
                sync_duplicate = 0
                for rule_info in added_rules:
                    try:
                        # 检查同步规则是否已有此替换规则
                        existing_rule = session.query(ReplaceRule).filter(
                            ReplaceRule.rule_id == sync_rule_id,
                            ReplaceRule.pattern == rule_info['pattern'],
                            ReplaceRule.content == rule_info['content']
                        ).first()
                        
                        if existing_rule:
                            sync_duplicate += 1
                            continue
                            
                        # 添加新替换规则到同步规则
                        new_rule = ReplaceRule(
                            rule_id=sync_rule_id,
                            pattern=rule_info['pattern'],
                            content=rule_info['content']
                        )
                        session.add(new_rule)
                        session.flush()
                        sync_success += 1
                    except Exception as e:
                        logger.error(f"同步添加替换规则到规则 {sync_rule_id} 时出错: {str(e)}")
                        continue
                
                logger.info(f"同步规则 {sync_rule_id} 的替换规则添加结果: 成功={sync_success}, 重复={sync_duplicate}")
        
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
        # 获取当前规则
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"规则ID {rule_id} 不存在")
            return 0, []
            
        rules = await self.get_replace_rules(session, rule_id)
        if not rules:
            return 0, []
            
        deleted_count = 0
        max_id = len(rules)
        
        # 保存要删除的替换规则信息，用于后续同步
        rules_to_delete = []
        for idx in indices:
            if 1 <= idx <= max_id:
                replace_rule = rules[idx - 1]
                rules_to_delete.append({
                    'pattern': replace_rule.pattern,
                    'content': replace_rule.content
                })
                session.delete(replace_rule)
                deleted_count += 1
        
        # 检查是否启用了同步功能
        if rule.enable_sync and rules_to_delete:
            logger.info(f"规则 {rule_id} 启用了同步功能，正在同步删除关联规则的替换规则")
            # 获取需要同步的规则列表
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()
            
            # 为每个同步规则删除相同的替换规则
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"正在同步删除规则 {sync_rule_id} 的替换规则")
                
                # 获取同步目标规则
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"同步目标规则 {sync_rule_id} 不存在，跳过")
                    continue
                
                # 在同步目标规则中删除相同的替换规则
                sync_deleted = 0
                for rule_info in rules_to_delete:
                    try:
                        # 查找目标规则中匹配的替换规则
                        target_rules = session.query(ReplaceRule).filter(
                            ReplaceRule.rule_id == sync_rule_id,
                            ReplaceRule.pattern == rule_info['pattern'],
                            ReplaceRule.content == rule_info['content']
                        ).all()
                        
                        # 删除匹配的替换规则
                        for target_rule in target_rules:
                            session.delete(target_rule)
                            sync_deleted += 1
                    except Exception as e:
                        logger.error(f"同步删除规则 {sync_rule_id} 的替换规则时出错: {str(e)}")
                        continue
                
                logger.info(f"同步删除规则 {sync_rule_id} 的替换规则: 删除了 {sync_deleted} 个")
                
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
                    voice=False,
                    sticker=False
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
            for field in ['photo', 'document', 'video', 'audio', 'voice', 'sticker']:
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
            if media_type not in ['photo', 'document', 'video', 'audio', 'voice', 'sticker']:
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

    # 规则同步相关操作
    async def add_rule_sync(self, session, rule_id, sync_rule_id):
        """添加规则同步关系
        
        Args:
            session: 数据库会话
            rule_id: 源规则ID
            sync_rule_id: 目标规则ID（要同步到的规则）
        
        Returns:
            tuple: (bool, str) - (成功状态, 消息)
        """
        try:
            # 检查源规则是否存在
            source_rule = session.query(ForwardRule).get(rule_id)
            if not source_rule:
                return False, f"源规则ID {rule_id} 不存在"
            
            # 检查目标规则是否存在
            target_rule = session.query(ForwardRule).get(sync_rule_id)
            if not target_rule:
                return False, f"目标规则ID {sync_rule_id} 不存在"
            
            # 检查是否已存在相同的同步关系
            existing_sync = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id,
                RuleSync.sync_rule_id == sync_rule_id
            ).first()
            
            if existing_sync:
                return False, f"同步关系已存在"
            
            # 创建新的同步关系
            new_sync = RuleSync(
                rule_id=rule_id,
                sync_rule_id=sync_rule_id
            )
            
            # 启用规则的同步功能
            source_rule.enable_sync = True
            
            session.add(new_sync)
            session.commit()
            
            logger.info(f"已添加规则同步: 从规则 {rule_id} 到规则 {sync_rule_id}")
            return True, f"成功添加同步关系"
        
        except Exception as e:
            session.rollback()
            logger.error(f"添加规则同步关系时出错: {str(e)}")
            return False, f"添加同步关系失败: {str(e)}"
    
    async def get_rule_syncs(self, session, rule_id):
        """获取指定规则的同步关系列表
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
        
        Returns:
            list: 同步关系列表
        """
        try:
            # 获取该规则的所有同步目标
            syncs = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id
            ).all()
            
            return syncs
        
        except Exception as e:
            logger.error(f"获取规则同步关系时出错: {str(e)}")
            return []
    
    async def delete_rule_sync(self, session, rule_id, sync_rule_id):
        """删除规则同步关系
        
        Args:
            session: 数据库会话
            rule_id: 源规则ID
            sync_rule_id: 目标规则ID
        
        Returns:
            tuple: (bool, str) - (成功状态, 消息)
        """
        try:
            # 查找同步关系
            sync = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id,
                RuleSync.sync_rule_id == sync_rule_id
            ).first()
            
            if not sync:
                return False, "指定的同步关系不存在"
            
            # 删除同步关系
            session.delete(sync)
            
            # 检查规则是否还有其他同步关系
            remaining_syncs = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id
            ).count()
            
            # 如果没有其他同步关系，关闭规则的同步功能
            if remaining_syncs == 0:
                rule = session.query(ForwardRule).get(rule_id)
                if rule:
                    rule.enable_sync = False
            
            session.commit()
            
            logger.info(f"已删除规则同步: 从规则 {rule_id} 到规则 {sync_rule_id}")
            return True, "成功删除同步关系"
        
        except Exception as e:
            session.rollback()
            logger.error(f"删除规则同步关系时出错: {str(e)}")
            return False, f"删除同步关系失败: {str(e)}"

    async def get_push_configs(self, session, rule_id):
        """获取指定规则的所有推送配置
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
        
        Returns:
            list: 推送配置列表
        """
        try:
            return session.query(PushConfig).filter(
                PushConfig.rule_id == rule_id
            ).all()
        except Exception as e:
            logger.error(f"获取推送配置时出错: {str(e)}")
            return []
    
    async def add_push_config(self, session, rule_id, push_channel, enable_push_channel=True):
        """添加推送配置
        
        Args:
            session: 数据库会话
            rule_id: 规则ID
            push_channel: 推送频道
            enable_push_channel: 是否启用推送频道
        
        Returns:
            tuple: (bool, str, obj) - (成功状态, 消息, 创建的对象)
        """
        try:
            # 检查规则是否存在
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, f"规则ID {rule_id} 不存在", None
            
            # 创建新的推送配置
            push_config = PushConfig(
                rule_id=rule_id,
                push_channel=push_channel,
                enable_push_channel=enable_push_channel
            )
            
            session.add(push_config)
            session.commit()
            
            # 启用规则的推送功能
            rule.enable_push = True
            session.commit()
            
            return True, "成功添加推送配置", push_config
        except Exception as e:
            session.rollback()
            logger.error(f"添加推送配置时出错: {str(e)}")
            return False, f"添加推送配置失败: {str(e)}", None
    
    async def toggle_push_config(self, session, config_id):
        """切换推送配置的启用状态
        
        Args:
            session: 数据库会话
            config_id: 配置ID
        
        Returns:
            tuple: (bool, str) - (成功状态, 消息)
        """
        try:
            push_config = session.query(PushConfig).get(config_id)
            if not push_config:
                return False, "推送配置不存在"
            
            # 切换启用状态
            push_config.enable_push_channel = not push_config.enable_push_channel
            session.commit()
            
            return True, f"推送配置已{'启用' if push_config.enable_push_channel else '禁用'}"
        except Exception as e:
            session.rollback()
            logger.error(f"切换推送配置状态时出错: {str(e)}")
            return False, f"切换推送配置状态失败: {str(e)}"
    
    async def delete_push_config(self, session, config_id):
        """删除推送配置
        
        Args:
            session: 数据库会话
            config_id: 配置ID
        
        Returns:
            tuple: (bool, str) - (成功状态, 消息)
        """
        try:
            push_config = session.query(PushConfig).get(config_id)
            if not push_config:
                return False, "推送配置不存在"
            
            rule_id = push_config.rule_id
            
            # 删除配置
            session.delete(push_config)
            
            # 检查是否还有其他推送配置
            remaining_configs = session.query(PushConfig).filter(
                PushConfig.rule_id == rule_id
            ).count()
            
            # 如果没有其他推送配置，关闭规则的推送功能
            if remaining_configs == 0:
                rule = session.query(ForwardRule).get(rule_id)
                if rule:
                    rule.enable_push = False
            
            session.commit()
            
            return True, "成功删除推送配置"
        except Exception as e:
            session.rollback()
            logger.error(f"删除推送配置时出错: {str(e)}")
            return False, f"删除推送配置失败: {str(e)}"
