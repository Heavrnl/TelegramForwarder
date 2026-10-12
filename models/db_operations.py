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
        """Create a DBOperations instance"""
        instance = cls()
        await instance.init_ufb()
        return instance

    async def init_ufb(self):
        """Initialize the UFB client"""
        try:
            # Retrieve UFB configuration from environment variables
            logger.info("Initializing UFB client")
            is_ufb = os.getenv('UFB_ENABLED', 'false').lower() == 'true'
            if is_ufb:
                server_url = os.getenv('UFB_SERVER_URL', '')
                token = os.getenv('UFB_TOKEN')
                logger.info(f"UFB config: server_url={server_url}, token={token and '***'}")

                if server_url and token:
                    # Normalize URL scheme
                    if not server_url.startswith(('ws://', 'wss://')):
                        if server_url.startswith('http://'):
                            server_url = f"ws://{server_url[7:]}"
                        elif server_url.startswith('https://'):
                            server_url = f"wss://{server_url[8:]}"
                        else:
                            server_url = f"wss://{server_url}"

                    logger.info(f"Normalized URL: {server_url}")
                    self.ufb_client = UFBClient()
                    logger.info("UFB client created")

                    try:
                        await self.ufb_client.start(server_url=server_url, token=token)
                        logger.info("UFB client started")
                    except Exception as e:
                        logger.error(f"UFB client failed to start: {str(e)}")
                        self.ufb_client = None
                else:
                    logger.warning("UFB configuration incomplete, UFB feature not enabled")
                    self.ufb_client = None
            else:
                logger.info("UFB not enabled")
        except Exception as e:
            logger.error(f"Error initializing UFB: {str(e)}")
            self.ufb_client = None


    async def sync_to_server(self,session,rule_id):
        """Sync UFB configuration to server"""
        if self.ufb_client and os.getenv('UFB_ENABLED').lower() == 'true':
            # Check whether UFB is enabled for this rule
            rule = session.query(ForwardRule).filter(ForwardRule.id == rule_id).first()
            ufb_domain = rule.ufb_domain
            if rule.is_ufb and ufb_domain:
                item = rule.ufb_item
                # Retrieve all non-regex keywords for this rule
                normal_keywords = session.query(Keyword).filter(
                    Keyword.rule_id == rule_id,
                    Keyword.is_regex == False
                ).all()

                # Retrieve all regex keywords for this rule
                regex_keywords = session.query(Keyword).filter(
                    Keyword.rule_id == rule_id,
                    Keyword.is_regex == True
                ).all()

                # Load the UFB config file
                config_file = Path(__file__).parent.parent / 'ufb' / 'config' / 'config.json'
                # Read the file
                with open(config_file, 'r', encoding='utf-8') as file:
                    config = json.load(file)

                # Find the matching domain config in userConfig
                for user_config in config.get('userConfig', []):
                    if user_config.get('domain') == ufb_domain:
                        # Select keyword config based on item type
                        if item == 'main':
                            keywords_config = user_config.get('mainAndSubPageKeywords', {})
                        elif item == 'content':
                            keywords_config = user_config.get('contentPageKeywords', {})
                        elif item == 'main_username':
                            keywords_config = user_config.get('mainAndSubPageUserKeywords', {})
                        elif item == 'content_username':
                            keywords_config = user_config.get('contentPageUserKeywords', {})

                        # Update keyword lists
                        keywords_config['keywords'] = [k.keyword for k in normal_keywords]
                        keywords_config['regexPatterns'] = [k.keyword for k in regex_keywords]

                        # Write back to the corresponding section
                        if item == 'main':
                            user_config['mainAndSubPageKeywords'] = keywords_config
                        elif item == 'content':
                            user_config['contentPageKeywords'] = keywords_config
                        elif item == 'main_username':
                            user_config['mainAndSubPageUserKeywords'] = keywords_config
                        elif item == 'content_username':
                            user_config['contentPageUserKeywords'] = keywords_config
                        else:
                            logger.error(f"UFB_ITEM environment variable not set")
                            return
                        break

                # Update timestamp
                config['globalConfig']['SYNC_CONFIG']['lastSyncTime'] = int(time.time() * 1000)
                # Save to local file
                with open(config_file, 'w', encoding='utf-8') as file:
                    json.dump(config, file, ensure_ascii=False, indent=2)

                # Push updated config to server
                if self.ufb_client.is_connected:
                    await self.ufb_client.websocket.send(json.dumps({
                        "additional_info": "to_server",
                        "type": "update",
                        **config
                    }))
                    logger.info("UFB configuration synced")
                else:
                    logger.warning("UFB client not connected, cannot sync configuration")
            else:
                logger.warning("UFB not enabled, cannot sync configuration")
        else:
            logger.warning("UFB client not initialized, cannot sync configuration")

    async def sync_from_json(self, config):
        """Sync keywords from received JSON configuration to the database

        Args:
            config: Received configuration data
        """
        logger.info(f"Syncing keywords from JSON to database")
        session = get_session()
        try:
            # Retrieve all rules with UFB enabled
            ufb_rules = session.query(ForwardRule).filter(
                ForwardRule.is_ufb == True,
                ForwardRule.ufb_domain != None
            ).all()

            if not ufb_rules:
                logger.info("No UFB-enabled rules found")
                return
            logger.info(f"ufb_rules: {ufb_rules}")

            # Iterate over all UFB-enabled rules
            for rule in ufb_rules:
                # Get item type
                item = rule.ufb_item
                logger.info(f"item: {item}")
                if not item:
                    logger.error("UFB_ITEM environment variable not set")
                    continue  # Skip rules without item set

                # Find the matching domain config in the received config
                for user_config in config.get('userConfig', []):
                    if user_config.get('domain') == rule.ufb_domain:
                        logger.info(f"Found matching domain config: {rule.ufb_domain}")

                        # Select keyword config based on item type
                        if item == 'main':
                            keywords_config = user_config.get('mainAndSubPageKeywords', {})
                        elif item == 'content':
                            keywords_config = user_config.get('contentPageKeywords', {})
                        elif item == 'main_username':
                            keywords_config = user_config.get('mainAndSubPageUserKeywords', {})
                        elif item == 'content_username':
                            keywords_config = user_config.get('contentPageUserKeywords', {})
                        else:
                            logger.error(f"UFB_ITEM environment variable not set")
                            continue

                        # Clear existing keywords
                        session.query(Keyword).filter(
                            Keyword.rule_id == rule.id
                        ).delete()

                        # Add plain keywords
                        for keyword in keywords_config.get('keywords', []):
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=keyword,
                                is_regex=False
                            )
                            session.add(new_keyword)

                        # Add regex keywords
                        for pattern in keywords_config.get('regexPatterns', []):
                            new_keyword = Keyword(
                                rule_id=rule.id,
                                keyword=pattern,
                                is_regex=True
                            )
                            session.add(new_keyword)

                        session.commit()
                        logger.info(f"Synced keywords from JSON to rule {rule.id} (domain: {rule.ufb_domain})")
                        break  # Stop inner loop after matching domain
        finally:
            session.close()

    async def add_keywords(self, session, rule_id, keywords, is_regex=False, is_blacklist=False):
        """Add keywords to a rule

        Args:
            session: Database session
            rule_id: Rule ID
            keywords: List of keywords
            is_regex: Whether the keywords are regular expressions
            is_blacklist: Whether the keywords belong to the blacklist

        Returns:
            tuple: (success count, duplicate count)
        """
        success_count = 0
        duplicate_count = 0

        # Fetch the target rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"Rule ID {rule_id} does not exist")
            return 0, 0

        # Add keywords for this rule
        for keyword in keywords:
            try:
                # Check for an existing keyword with the same blacklist/whitelist flag
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
                logger.error(f"Error adding keyword: {str(e)}")
                session.rollback()
                duplicate_count += 1
                continue

        # Check whether sync is enabled for this rule
        if rule.enable_sync:
            logger.info(f"Rule {rule_id} has sync enabled, syncing keywords to linked rules")
            # Get the list of rules to sync to
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()

            # Add the same keywords to each sync target rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing keywords to rule {sync_rule_id}")

                # Fetch the sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                    continue

                # Add keywords to the sync target rule
                sync_success = 0
                sync_duplicate = 0
                for keyword in keywords:
                    try:
                        # Check whether the sync rule already has this keyword
                        existing_keyword = session.query(Keyword).filter(
                            Keyword.rule_id == sync_rule_id,
                            Keyword.keyword == keyword,
                            Keyword.is_blacklist == is_blacklist
                        ).first()

                        if existing_keyword:
                            sync_duplicate += 1
                            continue

                        # Add new keyword to sync rule
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
                        logger.error(f"Error syncing keyword to rule {sync_rule_id}: {str(e)}")
                        continue

                logger.info(f"Sync result for rule {sync_rule_id}: success={sync_success}, duplicates={sync_duplicate}")

        await self.sync_to_server(session, rule_id)
        return success_count, duplicate_count

    async def get_keywords(self, session, rule_id, add_mode):
        """Retrieve all keywords for a rule

        Args:
            session: Database session
            rule_id: Rule ID

        Returns:
            list: List of keywords
        """
        return session.query(Keyword).filter(
            Keyword.rule_id == rule_id,
            Keyword.is_blacklist == (add_mode == 'blacklist')
        ).all()

    async def delete_keywords(self, session, rule_id, indices):
        """Delete keywords at the specified indices

        Args:
            session: Database session
            rule_id: Rule ID
            indices: List of indices to delete (1-based)

        Returns:
            tuple: (deleted count, remaining keyword list)
        """
        # Fetch the target rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"Rule ID {rule_id} does not exist")
            return 0, []

        # Fetch current keywords for this rule
        keywords = await self.get_keywords(session, rule_id, 'blacklist' if rule.add_mode == AddMode.BLACKLIST else 'whitelist')
        if not keywords:
            return 0, []

        deleted_count = 0
        max_id = len(keywords)

        # Save info about keywords to delete for later sync
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

        # Check whether sync is enabled for this rule
        if rule.enable_sync and keywords_to_delete:
            logger.info(f"Rule {rule_id} has sync enabled, syncing keyword deletions to linked rules")
            # Get the list of rules to sync to
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()

            # Delete the same keywords from each sync target rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing keyword deletions to rule {sync_rule_id}")

                # Fetch the sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                    continue

                # Delete matching keywords from the sync target rule
                sync_deleted = 0
                for kw_info in keywords_to_delete:
                    try:
                        # Find matching keywords in the target rule
                        target_keywords = session.query(Keyword).filter(
                            Keyword.rule_id == sync_rule_id,
                            Keyword.keyword == kw_info['keyword'],
                            Keyword.is_regex == kw_info['is_regex'],
                            Keyword.is_blacklist == kw_info['is_blacklist']
                        ).all()

                        # Delete matching keywords
                        for target_kw in target_keywords:
                            session.delete(target_kw)
                            sync_deleted += 1
                    except Exception as e:
                        logger.error(f"Error syncing keyword deletion for rule {sync_rule_id}: {str(e)}")
                        continue

                logger.info(f"Synced keyword deletions for rule {sync_rule_id}: deleted {sync_deleted}")

        await self.sync_to_server(session, rule_id)
        return deleted_count, await self.get_keywords(session, rule_id, 'blacklist' if rule.add_mode == AddMode.BLACKLIST else 'whitelist')

    async def add_replace_rules(self, session, rule_id, patterns, contents=None):
        """Add replacement rules

        Args:
            session: Database session
            rule_id: Rule ID
            patterns: List of match patterns
            contents: List of replacement content (optional)

        Returns:
            tuple: (success count, duplicate count)
        """
        # Fetch the target rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"Rule ID {rule_id} does not exist")
            return 0, 0

        success_count = 0
        duplicate_count = 0

        if contents is None:
            contents = [''] * len(patterns)

        # Add replacement rules to the main rule
        added_rules = []  # Track successfully added rules for later sync
        for pattern, content in zip(patterns, contents):
            try:
                # Check for an existing identical replacement rule
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

        # Check whether sync is enabled for this rule
        if rule.enable_sync and added_rules:
            logger.info(f"Rule {rule_id} has sync enabled, syncing replacement rules to linked rules")
            # Get the list of rules to sync to
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()

            # Add the same replacement rules to each sync target rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing replacement rules to rule {sync_rule_id}")

                # Fetch the sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                    continue

                # Add replacement rules to the sync target rule
                sync_success = 0
                sync_duplicate = 0
                for rule_info in added_rules:
                    try:
                        # Check whether the sync rule already has this replacement rule
                        existing_rule = session.query(ReplaceRule).filter(
                            ReplaceRule.rule_id == sync_rule_id,
                            ReplaceRule.pattern == rule_info['pattern'],
                            ReplaceRule.content == rule_info['content']
                        ).first()

                        if existing_rule:
                            sync_duplicate += 1
                            continue

                        # Add new replacement rule to sync rule
                        new_rule = ReplaceRule(
                            rule_id=sync_rule_id,
                            pattern=rule_info['pattern'],
                            content=rule_info['content']
                        )
                        session.add(new_rule)
                        session.flush()
                        sync_success += 1
                    except Exception as e:
                        logger.error(f"Error syncing replacement rule to rule {sync_rule_id}: {str(e)}")
                        continue

                logger.info(f"Replacement rule sync result for rule {sync_rule_id}: success={sync_success}, duplicates={sync_duplicate}")

        return success_count, duplicate_count

    async def get_replace_rules(self, session, rule_id):
        """Retrieve all replacement rules for a rule

        Args:
            session: Database session
            rule_id: Rule ID

        Returns:
            list: List of replacement rules
        """
        return session.query(ReplaceRule).filter(
            ReplaceRule.rule_id == rule_id
        ).all()

    async def delete_replace_rules(self, session, rule_id, indices):
        """Delete replacement rules at the specified indices

        Args:
            session: Database session
            rule_id: Rule ID
            indices: List of indices to delete (1-based)

        Returns:
            tuple: (deleted count, remaining replacement rule list)
        """
        # Fetch the target rule
        rule = session.query(ForwardRule).get(rule_id)
        if not rule:
            logger.error(f"Rule ID {rule_id} does not exist")
            return 0, []

        rules = await self.get_replace_rules(session, rule_id)
        if not rules:
            return 0, []

        deleted_count = 0
        max_id = len(rules)

        # Save info about rules to delete for later sync
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

        # Check whether sync is enabled for this rule
        if rule.enable_sync and rules_to_delete:
            logger.info(f"Rule {rule_id} has sync enabled, syncing replacement rule deletions to linked rules")
            # Get the list of rules to sync to
            sync_rules = session.query(RuleSync).filter(RuleSync.rule_id == rule_id).all()

            # Delete the same replacement rules from each sync target rule
            for sync_rule in sync_rules:
                sync_rule_id = sync_rule.sync_rule_id
                logger.info(f"Syncing replacement rule deletions to rule {sync_rule_id}")

                # Fetch the sync target rule
                target_rule = session.query(ForwardRule).get(sync_rule_id)
                if not target_rule:
                    logger.warning(f"Sync target rule {sync_rule_id} does not exist, skipping")
                    continue

                # Delete matching replacement rules from the sync target rule
                sync_deleted = 0
                for rule_info in rules_to_delete:
                    try:
                        # Find matching replacement rules in the target rule
                        target_rules = session.query(ReplaceRule).filter(
                            ReplaceRule.rule_id == sync_rule_id,
                            ReplaceRule.pattern == rule_info['pattern'],
                            ReplaceRule.content == rule_info['content']
                        ).all()

                        # Delete matching replacement rules
                        for target_rule in target_rules:
                            session.delete(target_rule)
                            sync_deleted += 1
                    except Exception as e:
                        logger.error(f"Error syncing replacement rule deletion for rule {sync_rule_id}: {str(e)}")
                        continue

                logger.info(f"Synced replacement rule deletions for rule {sync_rule_id}: deleted {sync_deleted}")

        return deleted_count, await self.get_replace_rules(session, rule_id)

    async def get_media_types(self, session, rule_id):
        """Retrieve media type settings"""
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, "Rule does not exist", None

            media_types = session.query(MediaTypes).filter_by(rule_id=rule_id).first()
            if not media_types:
                # Create default settings if none exist
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

            return True, "Media type settings retrieved successfully", media_types
        except Exception as e:
            logger.error(f"Error retrieving media type settings: {str(e)}")
            session.rollback()
            return False, f"Error retrieving media type settings: {str(e)}", None

    async def update_media_types(self, session, rule_id, media_types_dict):
        """Update media type settings"""
        try:
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, "Rule does not exist"

            media_types = session.query(MediaTypes).filter_by(rule_id=rule_id).first()
            if not media_types:
                media_types = MediaTypes(rule_id=rule_id)
                session.add(media_types)

            # Update media type settings
            for field in ['photo', 'document', 'video', 'audio', 'voice']:
                if field in media_types_dict:
                    setattr(media_types, field, media_types_dict[field])

            session.commit()
            return True, "Media type settings updated successfully"
        except Exception as e:
            logger.error(f"Error updating media type settings: {str(e)}")
            session.rollback()
            return False, f"Error updating media type settings: {str(e)}"

    async def toggle_media_type(self, session, rule_id, media_type):
        """Toggle the enabled state of a specific media type"""
        try:
            if media_type not in ['photo', 'document', 'video', 'audio', 'voice']:
                return False, f"Invalid media type: {media_type}"

            success, msg, media_types = await self.get_media_types(session, rule_id)
            if not success:
                return False, msg

            # Toggle state
            current_value = getattr(media_types, media_type)
            setattr(media_types, media_type, not current_value)

            session.commit()
            return True, f"Media type {media_type} toggled to {not current_value}"
        except Exception as e:
            logger.error(f"Error toggling media type: {str(e)}")
            session.rollback()
            return False, f"Error toggling media type: {str(e)}"

    async def add_media_extensions(self, session, rule_id, extensions):
        """Add media file extensions

        Args:
            session: Database session
            rule_id: Rule ID
            extensions: List of extensions, e.g. ['jpg', 'png', 'pdf']

        Returns:
            (bool, str): Success status and message
        """
        try:
            added_count = 0
            for ext in extensions:
                # Ensure extension has no leading dot
                ext = ext.lstrip('.')

                # Check whether the same extension already exists
                existing = session.execute(
                    text("SELECT id FROM media_extensions WHERE rule_id = :rule_id AND extension = :extension"),
                    {"rule_id": rule_id, "extension": ext}
                )

                if existing.first() is None:
                    # Add new extension
                    new_extension = MediaExtensions(rule_id=rule_id, extension=ext)
                    session.add(new_extension)
                    added_count += 1

            if added_count > 0:
                session.commit()
                return True, f"Successfully added {added_count} media extension(s)"
            else:
                return False, "All extensions already exist, no new extensions added"

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add media extensions: {str(e)}")
            return False, f"Failed to add media extensions: {str(e)}"

    async def get_media_extensions(self, session, rule_id):
        """Retrieve the media extension list for a rule

        Args:
            session: Database session
            rule_id: Rule ID

        Returns:
            list: List of media extension objects
        """
        try:
            # Use SQLAlchemy text SQL query (no await needed)
            result = session.execute(
                text("SELECT id, extension FROM media_extensions WHERE rule_id = :rule_id ORDER BY id"),
                {"rule_id": rule_id}
            )

            # Build return result
            extensions = []
            for row in result:
                extensions.append({
                    "id": row[0],
                    "extension": row[1]
                })

            # Return extension list
            return extensions

        except Exception as e:
            # Log error and return empty list
            logger.error(f"Failed to retrieve media extensions: {str(e)}")
            return []

    async def delete_media_extensions(self, session, rule_id, indices):
        """Delete media file extensions

        Args:
            session: Database session
            rule_id: Rule ID
            indices: List of extension IDs to delete

        Returns:
            (bool, str): Success status and message
        """
        try:
            if not indices:
                return False, "No extensions specified for deletion"

            for index in indices:
                # Find and delete the extension
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
            return True, f"Successfully deleted {len(indices)} media extension(s)"
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete media extensions: {str(e)}")
            return False, f"Failed to delete media extensions: {str(e)}"

    # RSS configuration operations
    async def get_rss_config(self, session, rule_id):
        """Retrieve the RSS configuration for the specified rule"""
        return session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()

    async def create_rss_config(self, session, rule_id, **kwargs):
        """Create an RSS configuration"""
        rss_config = RSSConfig(rule_id=rule_id, **kwargs)
        session.add(rss_config)
        session.commit()
        return rss_config

    async def update_rss_config(self, session, rule_id, **kwargs):
        """Update an RSS configuration"""
        rss_config = await self.get_rss_config(session, rule_id)
        if rss_config:
            for key, value in kwargs.items():
                setattr(rss_config, key, value)
            session.commit()
        return rss_config

    async def delete_rss_config(self, session, rule_id):
        """Delete an RSS configuration"""
        rss_config = await self.get_rss_config(session, rule_id)
        if rss_config:
            session.delete(rss_config)
            session.commit()
            return True
        return False

    # RSS pattern operations
    async def get_rss_patterns(self, session, rss_config_id):
        """Retrieve all patterns for the specified RSS configuration"""
        return session.query(RSSPattern).filter(RSSPattern.rss_config_id == rss_config_id).order_by(RSSPattern.priority).all()

    async def get_rss_pattern(self, session, pattern_id):
        """Retrieve a specific RSS pattern"""
        return session.query(RSSPattern).filter(RSSPattern.id == pattern_id).first()

    async def create_rss_pattern(self, session, rss_config_id, pattern, pattern_type, priority=0):
        """Create an RSS pattern"""
        logger.info(f"Creating RSS pattern: config_id={rss_config_id}, pattern={pattern}, type={pattern_type}, priority={priority}")
        try:
            pattern_obj = RSSPattern(
                rss_config_id=rss_config_id,
                pattern=pattern,
                pattern_type=pattern_type,
                priority=priority
            )
            session.add(pattern_obj)
            session.commit()
            logger.info(f"RSS pattern created successfully: {pattern_obj.id}")
            return pattern_obj
        except Exception as e:
            logger.error(f"Failed to create RSS pattern: {str(e)}")
            session.rollback()
            raise

    async def update_rss_pattern(self, session, pattern_id, **kwargs):
        """Update an RSS pattern"""
        logger.info(f"Updating RSS pattern: pattern_id={pattern_id}, kwargs={kwargs}")
        try:
            pattern = session.query(RSSPattern).filter(RSSPattern.id == pattern_id).first()
            if not pattern:
                logger.error(f"RSS pattern does not exist: pattern_id={pattern_id}")
                raise ValueError("RSS pattern does not exist")

            for key, value in kwargs.items():
                setattr(pattern, key, value)

            session.commit()
            logger.info(f"RSS pattern updated successfully: {pattern.id}")
            return pattern
        except Exception as e:
            logger.error(f"Failed to update RSS pattern: {str(e)}")
            session.rollback()
            raise

    async def delete_rss_pattern(self, session, pattern_id):
        """Delete an RSS pattern"""
        rss_pattern = await self.get_rss_pattern(session, pattern_id)
        if rss_pattern:
            session.delete(rss_pattern)
            session.commit()
            return True
        return False

    async def reorder_rss_patterns(self, session, rss_config_id, pattern_ids):
        """Reorder RSS patterns"""
        patterns = await self.get_rss_patterns(session, rss_config_id)
        pattern_dict = {p.id: p for p in patterns}

        for index, pattern_id in enumerate(pattern_ids):
            if pattern_id in pattern_dict:
                pattern_dict[pattern_id].priority = index

        session.commit()

    # User operations
    async def get_user(self, session, username):
        """Retrieve a user by username"""
        return session.query(User).filter(User.username == username).first()

    async def get_user_by_id(self, session, user_id):
        """Retrieve a user by ID"""
        return session.query(User).filter(User.id == user_id).first()

    async def create_user(self, session, username, password):
        """Create a user"""

        user = User(
            username=username,
            password=generate_password_hash(password)
        )
        session.add(user)
        session.commit()
        return user

    async def update_user_password(self, session, username, new_password):
        """Update a user's password"""

        user = await self.get_user(session, username)
        if user:
            user.password = generate_password_hash(new_password)
            session.commit()
        return user

    async def verify_user(self, session, username, password):
        """Verify a user's password"""

        user = await self.get_user(session, username)
        if user and check_password_hash(user.password, password):
            return user
        return None

    # Bulk operations
    async def get_all_enabled_rss_configs(self, session):
        """Retrieve all enabled RSS configurations"""
        return session.query(RSSConfig).filter(RSSConfig.enable_rss == True).all()

    async def get_rss_config_with_patterns(self, session, rule_id):
        """Retrieve an RSS configuration along with all its patterns"""
        return session.query(RSSConfig).options(
            joinedload(RSSConfig.patterns)
        ).filter(RSSConfig.rule_id == rule_id).first()

    # Rule sync operations
    async def add_rule_sync(self, session, rule_id, sync_rule_id):
        """Add a rule sync relationship

        Args:
            session: Database session
            rule_id: Source rule ID
            sync_rule_id: Target rule ID (the rule to sync to)

        Returns:
            tuple: (bool, str) - (success status, message)
        """
        try:
            # Check whether the source rule exists
            source_rule = session.query(ForwardRule).get(rule_id)
            if not source_rule:
                return False, f"Source rule ID {rule_id} does not exist"

            # Check whether the target rule exists
            target_rule = session.query(ForwardRule).get(sync_rule_id)
            if not target_rule:
                return False, f"Target rule ID {sync_rule_id} does not exist"

            # Check whether the same sync relationship already exists
            existing_sync = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id,
                RuleSync.sync_rule_id == sync_rule_id
            ).first()

            if existing_sync:
                return False, f"Sync relationship already exists"

            # Create new sync relationship
            new_sync = RuleSync(
                rule_id=rule_id,
                sync_rule_id=sync_rule_id
            )

            # Enable sync for the source rule
            source_rule.enable_sync = True

            session.add(new_sync)
            session.commit()

            logger.info(f"Added rule sync: from rule {rule_id} to rule {sync_rule_id}")
            return True, f"Sync relationship added successfully"

        except Exception as e:
            session.rollback()
            logger.error(f"Error adding rule sync relationship: {str(e)}")
            return False, f"Failed to add sync relationship: {str(e)}"

    async def get_rule_syncs(self, session, rule_id):
        """Retrieve the list of sync relationships for a rule

        Args:
            session: Database session
            rule_id: Rule ID

        Returns:
            list: List of sync relationships
        """
        try:
            # Get all sync targets for this rule
            syncs = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id
            ).all()

            return syncs

        except Exception as e:
            logger.error(f"Error retrieving rule sync relationships: {str(e)}")
            return []

    async def delete_rule_sync(self, session, rule_id, sync_rule_id):
        """Delete a rule sync relationship

        Args:
            session: Database session
            rule_id: Source rule ID
            sync_rule_id: Target rule ID

        Returns:
            tuple: (bool, str) - (success status, message)
        """
        try:
            # Find the sync relationship
            sync = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id,
                RuleSync.sync_rule_id == sync_rule_id
            ).first()

            if not sync:
                return False, "Specified sync relationship does not exist"

            # Delete the sync relationship
            session.delete(sync)

            # Check whether the rule has any other sync relationships
            remaining_syncs = session.query(RuleSync).filter(
                RuleSync.rule_id == rule_id
            ).count()

            # If no other sync relationships remain, disable sync for this rule
            if remaining_syncs == 0:
                rule = session.query(ForwardRule).get(rule_id)
                if rule:
                    rule.enable_sync = False

            session.commit()

            logger.info(f"Deleted rule sync: from rule {rule_id} to rule {sync_rule_id}")
            return True, "Sync relationship deleted successfully"

        except Exception as e:
            session.rollback()
            logger.error(f"Error deleting rule sync relationship: {str(e)}")
            return False, f"Failed to delete sync relationship: {str(e)}"

    async def get_push_configs(self, session, rule_id):
        """Retrieve all push configurations for the specified rule

        Args:
            session: Database session
            rule_id: Rule ID

        Returns:
            list: List of push configurations
        """
        try:
            return session.query(PushConfig).filter(
                PushConfig.rule_id == rule_id
            ).all()
        except Exception as e:
            logger.error(f"Error retrieving push configurations: {str(e)}")
            return []

    async def add_push_config(self, session, rule_id, push_channel, enable_push_channel=True):
        """Add a push configuration

        Args:
            session: Database session
            rule_id: Rule ID
            push_channel: Push channel
            enable_push_channel: Whether to enable the push channel

        Returns:
            tuple: (bool, str, obj) - (success status, message, created object)
        """
        try:
            # Check whether the rule exists
            rule = session.query(ForwardRule).get(rule_id)
            if not rule:
                return False, f"Rule ID {rule_id} does not exist", None

            # Create new push configuration
            push_config = PushConfig(
                rule_id=rule_id,
                push_channel=push_channel,
                enable_push_channel=enable_push_channel
            )

            session.add(push_config)
            session.commit()

            # Enable push for the rule
            rule.enable_push = True
            session.commit()

            return True, "Push configuration added successfully", push_config
        except Exception as e:
            session.rollback()
            logger.error(f"Error adding push configuration: {str(e)}")
            return False, f"Failed to add push configuration: {str(e)}", None

    async def toggle_push_config(self, session, config_id):
        """Toggle the enabled state of a push configuration

        Args:
            session: Database session
            config_id: Configuration ID

        Returns:
            tuple: (bool, str) - (success status, message)
        """
        try:
            push_config = session.query(PushConfig).get(config_id)
            if not push_config:
                return False, "Push configuration does not exist"

            # Toggle enabled state
            push_config.enable_push_channel = not push_config.enable_push_channel
            session.commit()

            return True, f"Push configuration {'enabled' if push_config.enable_push_channel else 'disabled'}"
        except Exception as e:
            session.rollback()
            logger.error(f"Error toggling push configuration state: {str(e)}")
            return False, f"Failed to toggle push configuration state: {str(e)}"

    async def delete_push_config(self, session, config_id):
        """Delete a push configuration

        Args:
            session: Database session
            config_id: Configuration ID

        Returns:
            tuple: (bool, str) - (success status, message)
        """
        try:
            push_config = session.query(PushConfig).get(config_id)
            if not push_config:
                return False, "Push configuration does not exist"

            rule_id = push_config.rule_id

            # Delete the configuration
            session.delete(push_config)

            # Check whether any other push configurations remain
            remaining_configs = session.query(PushConfig).filter(
                PushConfig.rule_id == rule_id
            ).count()

            # If no other push configurations remain, disable push for the rule
            if remaining_configs == 0:
                rule = session.query(ForwardRule).get(rule_id)
                if rule:
                    rule.enable_push = False

            session.commit()

            return True, "Push configuration deleted successfully"
        except Exception as e:
            session.rollback()
            logger.error(f"Error deleting push configuration: {str(e)}")
            return False, f"Failed to delete push configuration: {str(e)}"
