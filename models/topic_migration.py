"""Transactional SQLite migration preserving rule IDs, extra columns and child rows."""
import logging
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect


def migrate_topic_routing(engine):
    inspector = inspect(engine)
    rule_column_info = {c['name']: c for c in inspector.get_columns('forward_rules')}
    rule_columns = set(rule_column_info)
    chat_columns = {c['name'] for c in inspector.get_columns('chats')}
    unique_constraints = inspector.get_unique_constraints('forward_rules')
    legacy_unique = any(c['column_names'] == ['source_chat_id', 'target_chat_id']
                        for c in unique_constraints)
    topic_unique = any(c['column_names'] == ['source_chat_id', 'source_topic_id', 'target_chat_id', 'target_topic_id']
                       for c in unique_constraints)
    nullable_topics = {name for name in ('source_topic_id', 'target_topic_id')
                       if name in rule_columns and rule_column_info[name]['nullable']}
    if {'source_topic_id', 'target_topic_id'} <= rule_columns and 'current_rule_id' in chat_columns and not legacy_unique and topic_unique and not nullable_topics:
        return

    database = engine.url.database
    if database and database != ':memory:':
        backup = Path(str(database) + '.before-topics-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.bak')
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
        logging.info('话题迁移前已备份数据库: %s', backup)

    with engine.connect() as connection:
        foreign_keys = connection.exec_driver_sql('PRAGMA foreign_keys').scalar()
        connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        try:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            before_violations = set(connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall())
            for name in ('source_topic_id', 'target_topic_id'):
                if name not in rule_columns:
                    connection.exec_driver_sql(f'ALTER TABLE forward_rules ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
            if 'current_rule_id' not in chat_columns:
                connection.exec_driver_sql('ALTER TABLE chats ADD COLUMN current_rule_id INTEGER')

            if legacy_unique or not topic_unique or nullable_topics:
                original_sql = connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='forward_rules'").scalar_one()
                # Keep the original DDL, including fields not known by this application version.
                new_sql = original_sql
                if legacy_unique:
                    new_sql, count = re.subn(
                        r'UNIQUE\s*\(\s*["`\[]?source_chat_id["`\]]?\s*,\s*["`\[]?target_chat_id["`\]]?\s*\)',
                        'UNIQUE (source_chat_id, source_topic_id, target_chat_id, target_topic_id)',
                        new_sql, flags=re.IGNORECASE)
                    if count != 1:
                        raise RuntimeError('无法识别旧规则唯一约束，已取消话题迁移')
                elif not topic_unique:
                    position = new_sql.rfind(')')
                    new_sql = (new_sql[:position] + ', UNIQUE (source_chat_id, source_topic_id, target_chat_id, target_topic_id)'
                               + new_sql[position:])
                for name in nullable_topics:
                    # Older releases already stored nullable target_topic_id values.
                    # Retain non-null destinations and enforce the new 0 sentinel.
                    pattern = (r'((?:^|[,(])\s*["`\[]?' + name
                               + r'["`\]]?\s+INTEGER\b)([^,\n]*)')

                    def required_topic(match):
                        options = re.sub(r'\bDEFAULT\s+(?:NULL|\(?0\)?|\x270\x27|"0")', '',
                                         match[2], flags=re.IGNORECASE)
                        if re.search(r'\bDEFAULT\b', options, flags=re.IGNORECASE):
                            raise RuntimeError('无法识别旧话题字段默认值，已取消话题迁移')
                        options = re.sub(r'\b(?:NOT\s+)?NULL\b', '', options, flags=re.IGNORECASE)
                        return match[1] + ' NOT NULL DEFAULT 0' + options

                    new_sql, count = re.subn(pattern, required_topic, new_sql, flags=re.IGNORECASE)
                    if count != 1:
                        raise RuntimeError('无法识别旧话题字段，已取消话题迁移')
                new_sql = new_sql.replace('unique_source_target', 'unique_source_target_topic')
                new_sql, count = re.subn(
                    r'^(CREATE\s+TABLE\s+)(?:"forward_rules"|`forward_rules`|\[forward_rules\]|forward_rules)',
                    r'\1forward_rules_topic_migration', new_sql, count=1, flags=re.IGNORECASE)
                if count != 1:
                    raise RuntimeError('无法识别旧规则建表语句，已取消话题迁移')
                objects = connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE tbl_name='forward_rules' AND type IN ('index', 'trigger') AND sql IS NOT NULL"
                ).scalars().all()
                connection.exec_driver_sql(new_sql)
                columns = connection.exec_driver_sql('PRAGMA table_info(forward_rules)').fetchall()
                names = ', '.join('"' + c[1].replace('"', '""') + '"' for c in columns)
                values = ', '.join(f'COALESCE("{c[1]}", 0)' if c[1] in nullable_topics
                                   else '"' + c[1].replace('"', '""') + '"' for c in columns)
                connection.exec_driver_sql(f'INSERT INTO forward_rules_topic_migration ({names}) SELECT {values} FROM forward_rules')
                connection.exec_driver_sql('DROP TABLE forward_rules')
                connection.exec_driver_sql('ALTER TABLE forward_rules_topic_migration RENAME TO forward_rules')
                for sql in objects:
                    connection.exec_driver_sql(sql)

            connection.exec_driver_sql('''
                UPDATE chats SET current_rule_id = (
                    SELECT MIN(r.id) FROM forward_rules r JOIN chats source ON source.id = r.source_chat_id
                    WHERE r.target_chat_id = chats.id AND source.telegram_chat_id = chats.current_add_id
                ) WHERE current_rule_id IS NULL AND current_add_id IS NOT NULL
            ''')
            violations = set(connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall())
            if violations - before_violations:
                raise RuntimeError('话题迁移产生了无效关联，已取消迁移')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql(f'PRAGMA foreign_keys={int(foreign_keys)}')
            connection.commit()
