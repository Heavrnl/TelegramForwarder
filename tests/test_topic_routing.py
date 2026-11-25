"""Offline routing/upgrade regression tests. Run: python -m unittest discover -s tests -v."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from telethon.tl import types

from enums.enums import MessageMode, PreviewMode
from filters.context import MessageContext
from filters.sender_filter import SenderFilter
from models.models import Base, Chat, ForwardRule, Keyword, migrate_db
from models.topic_migration import migrate_topic_routing
from utils.rule_selection import selected_rule, select_rule
from utils.topics import (creates_route_cycle, forward_to_topic, matches_topic,
                          message_topic_id, parse_bind_args, topic_reply_id, validate_topic)


def message(topic=0, reply=None, **kwargs):
    header = None
    if topic:
        header = types.MessageReplyHeader(
            forum_topic=True, reply_to_msg_id=reply or topic,
            reply_to_top_id=topic if reply else None)
    elif reply:
        header = types.MessageReplyHeader(reply_to_msg_id=reply)
    return NS(reply_to=header, text='hello', grouped_id=None, media=None, id=5, **kwargs)


class TopicTests(unittest.TestCase):
    def test_direct_posts_and_nested_replies_match_the_same_topic(self):
        self.assertEqual(message_topic_id(message(17)), 17)
        self.assertEqual(message_topic_id(message(17, reply=99)), 17)
        self.assertTrue(matches_topic(message(17, reply=99), 17, True))
        self.assertFalse(matches_topic(message(18), 17, True))

    def test_general_is_distinct_from_wildcard_and_ordinary_replies(self):
        self.assertEqual(message_topic_id(message(), True), 1)
        self.assertEqual(message_topic_id(message(reply=99), True), 1)
        self.assertEqual(message_topic_id(message(reply=99)), 0)
        self.assertFalse(matches_topic(message(17), 1, True))
        self.assertFalse(matches_topic(message(reply=17), 17, True))
        self.assertTrue(matches_topic(message(17), 0, True))
        self.assertIsNone(topic_reply_id(1))

    def test_bind_flags_and_legacy_syntax(self):
        self.assertEqual(parse_bind_args('/bind "源 群" "目标 群" --source-topic 17 --target-topic 12'),
                         ('源 群', '目标 群', 17, 12))
        self.assertEqual(parse_bind_args('/b@bot --target-topic 12 "源 群"'), ('源 群', None, 0, 12))
        self.assertEqual(parse_bind_args('/bind https://t.me/source'), ('https://t.me/source', None, 0, None))
        self.assertEqual(parse_bind_args('/bind Source --target-topic 0'), ('Source', None, 0, 0))
        for bad in ('/bind', '/bind a b c', '/bind a --source-topic', '/bind a --source-topic -1',
                    '/bind a --target-topic x', '/bind a --topic 2', '/bind a --source-topic 2 --source-topic 3',
                    '/bind a --source-topic 2147483648', '/bind "unclosed'):
            with self.subTest(command=bad), self.assertRaises(ValueError):
                parse_bind_args(bad)

    def test_cycles_include_wildcards_and_indirect_routes(self):
        self.assertFalse(creates_route_cycle([], 1, 17, 1, 12))
        self.assertTrue(creates_route_cycle([], 1, 17, 1, 17))
        self.assertTrue(creates_route_cycle([], 1, 0, 1, 12))
        rules = [NS(source_chat_id=2, source_topic_id=0, target_chat_id=3, target_topic_id=21),
                 NS(source_chat_id=3, source_topic_id=21, target_chat_id=1, target_topic_id=17)]
        self.assertTrue(creates_route_cycle(rules, 1, 17, 2, 12))
        self.assertFalse(creates_route_cycle(rules, 1, 18, 2, 12))


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'forward.db'
        self.engine = create_engine('sqlite:///' + str(self.path))
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, 'connect')
        def enable_foreign_keys(connection, record):
            connection.execute('PRAGMA foreign_keys=ON')

    def legacy_database(self):
        Base.metadata.create_all(self.engine)
        # Build the actual old schema, keeping every pre-topic rule column.
        rule_sql = str(CreateTable(ForwardRule.__table__).compile(self.engine))
        rule_sql = '\n'.join(line for line in rule_sql.splitlines()
                             if not line.strip().startswith(('source_topic_id ', 'target_topic_id ', 'is_ai ')))
        rule_sql = rule_sql.replace('unique_source_target_topic UNIQUE (source_chat_id, source_topic_id, target_chat_id, target_topic_id)',
                                    'unique_source_target UNIQUE (source_chat_id, target_chat_id)')
        chat_sql = '\n'.join(line for line in str(CreateTable(Chat.__table__).compile(self.engine)).splitlines()
                             if not line.strip().startswith('current_rule_id '))
        with self.engine.begin() as conn:
            conn.exec_driver_sql('DROP TABLE forward_rules')
            conn.exec_driver_sql('DROP TABLE chats')
            conn.exec_driver_sql(chat_sql)
            conn.exec_driver_sql(rule_sql)
            conn.exec_driver_sql('ALTER TABLE forward_rules ADD COLUMN custom_setting TEXT')
            conn.exec_driver_sql("INSERT INTO chats(id, telegram_chat_id, name, current_add_id) VALUES (1, '111', '源群', NULL), (2, '222', '目标群', '111')")
            conn.exec_driver_sql("INSERT INTO forward_rules(id, source_chat_id, target_chat_id, forward_mode, message_mode, is_preview, add_mode, handle_mode, extension_filter_mode, custom_setting) VALUES (42, 1, 2, 'BLACKLIST', 'MARKDOWN', 'FOLLOW', 'BLACKLIST', 'FORWARD', 'BLACKLIST', 'keep me')")
            conn.exec_driver_sql("INSERT INTO keywords(id, rule_id, keyword, is_regex, is_blacklist) VALUES (77, 42, '保留关键字', 0, 1)")
            conn.exec_driver_sql('CREATE TABLE migration_child (id INTEGER PRIMARY KEY, rule_id INTEGER REFERENCES forward_rules(id) ON DELETE CASCADE)')
            conn.exec_driver_sql('INSERT INTO migration_child VALUES (1, 42)')
            conn.exec_driver_sql('CREATE INDEX custom_rule_index ON forward_rules(custom_setting)')

    def test_upgrade_preserves_ids_children_selection_and_unknown_columns(self):
        self.legacy_database()
        migrate_db(self.engine)
        migrate_db(self.engine)
        with Session(self.engine) as session:
            rule = session.get(ForwardRule, 42)
            self.assertEqual((rule.source_topic_id, rule.target_topic_id), (0, 0))
            self.assertFalse(rule.is_ai)
            self.assertEqual(session.get(Keyword, 77).keyword, '保留关键字')
            self.assertEqual(selected_rule(session, session.get(Chat, 2)).id, 42)
            second = ForwardRule(source_chat_id=1, target_chat_id=2, source_topic_id=17, target_topic_id=12)
            session.add(second)
            session.commit()
            select_rule(session.get(Chat, 2), second)
            session.commit()
            self.assertEqual(selected_rule(session, session.get(Chat, 2)).id, second.id)
            session.add(ForwardRule(source_chat_id=1, target_chat_id=2, source_topic_id=17, target_topic_id=12))
            with self.assertRaises(IntegrityError):
                session.commit()
        with self.engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql('SELECT custom_setting FROM forward_rules WHERE id=42').scalar(), 'keep me')
            self.assertEqual(conn.exec_driver_sql('SELECT rule_id FROM migration_child').scalar(), 42)
            self.assertEqual(conn.exec_driver_sql('PRAGMA foreign_keys').scalar(), 1)
            self.assertEqual(conn.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
        self.assertIn('custom_rule_index', [i['name'] for i in inspect(self.engine).get_indexes('forward_rules')])
        backups = list(Path(self.temp.name).glob('*.bak'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as conn:
            self.assertNotIn('source_topic_id', [r[1] for r in conn.execute('PRAGMA table_info(forward_rules)')])

    def test_failed_rebuild_rolls_back_schema_and_data(self):
        self.legacy_database()
        with self.engine.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE forward_rules_topic_migration (sentinel INTEGER)')
        with self.assertRaises(OperationalError):
            migrate_topic_routing(self.engine)
        self.assertNotIn('source_topic_id', [c['name'] for c in inspect(self.engine).get_columns('forward_rules')])
        self.assertNotIn('current_rule_id', [c['name'] for c in inspect(self.engine).get_columns('chats')])
        with self.engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql('SELECT rule_id FROM migration_child').scalar(), 42)
            self.assertEqual(conn.exec_driver_sql('PRAGMA foreign_keys').scalar(), 1)

    def test_fresh_database_allows_multiple_topics_and_rejects_duplicates(self):
        Base.metadata.create_all(self.engine)
        migrate_db(self.engine)
        with Session(self.engine) as session:
            source, target = Chat(telegram_chat_id='1'), Chat(telegram_chat_id='2')
            session.add_all([source, target])
            session.flush()
            for topic in (0, 17, 18):
                session.add(ForwardRule(source_chat_id=source.id, target_chat_id=target.id,
                                        source_topic_id=topic, target_topic_id=12))
            session.commit()
            self.assertEqual(session.query(ForwardRule).count(), 3)
            session.add(ForwardRule(source_chat_id=source.id, target_chat_id=target.id, source_topic_id=0, target_topic_id=12))
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_deleted_selection_does_not_fall_back_to_another_topic(self):
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            source, target = Chat(telegram_chat_id='1'), Chat(telegram_chat_id='2')
            session.add_all([source, target])
            session.flush()
            first = ForwardRule(source_chat_id=source.id, target_chat_id=target.id, source_topic_id=17)
            second = ForwardRule(source_chat_id=source.id, target_chat_id=target.id, source_topic_id=18)
            session.add_all([first, second])
            session.flush()
            select_rule(target, second)
            session.delete(second)
            session.commit()
            self.assertIsNone(selected_rule(session, target))


class SendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_forward_routes_single_and_album_with_top_msg_id(self):
        class Client:
            forward_messages = AsyncMock()
            get_input_entity = AsyncMock(side_effect=lambda peer: types.InputPeerChannel(peer.channel_id, 123)
                                         if isinstance(peer, types.PeerChannel) else types.InputPeerChannel(555, 456))

            def __init__(self):
                self.requests = []

            async def __call__(self, request):
                self.requests.append(request)
                bytes(request)  # Validate against the pinned Telethon TL schema.

        client = Client()
        await forward_to_topic(client, 999, 5, -100555, 12)
        await forward_to_topic(client, -100999, [5, 6], -100555, 12)
        await forward_to_topic(client, 999, 7, -100555, 1)
        self.assertEqual([r.id for r in client.requests], [[5], [5, 6], [7]])
        self.assertEqual([r.top_msg_id for r in client.requests], [12, 12, None])
        self.assertTrue(all(r.to_peer.channel_id == 999 for r in client.requests))
        self.assertEqual(len(client.requests[1].random_id), 2)
        await forward_to_topic(client, 999, 8, -100555, 0)
        client.forward_messages.assert_awaited_once_with(999, 8, -100555)

    async def test_validation_rejects_deleted_closed_or_nonforum_topics(self):
        client = AsyncMock(return_value=NS(topics=[NS(id=17, title='topic', closed=False, hidden=False)]))
        await validate_topic(client, NS(id=999, forum=True), 17, destination=True)
        for chat, topic, destination in ((NS(id=999, forum=False), 17, False), (NS(id=999, forum=True), 18, False)):
            with self.assertRaises(ValueError):
                await validate_topic(client, chat, topic, destination)
        client.return_value.topics[0].closed = True
        with self.assertRaises(ValueError):
            await validate_topic(client, NS(id=999, forum=True), 17, destination=True)
        await validate_topic(client, NS(id=999, forum=True), 17, destination=False)

    async def test_current_target_is_resolved_with_user_session_access_hash(self):
        class Client:
            get_input_entity = AsyncMock(side_effect=[ValueError('not cached'), types.InputPeerChannel(999, 123)])

            async def iter_dialogs(self):
                yield NS()

            async def __call__(self, request):
                # Resolve just as Telethon does, then serialize the real request.
                request.channel = types.InputChannel(request.channel.channel_id, request.channel.access_hash)
                bytes(request)
                return NS(topics=[NS(id=17, title='topic', closed=False, hidden=False)])

        client = Client()
        await validate_topic(client, NS(id=999, forum=True), 17, destination=True)
        self.assertEqual(client.get_input_entity.await_count, 2)

    async def test_bot_text_media_album_and_size_notice_use_destination_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            for topic in (0, 1, 12):
                with self.subTest(topic=topic):
                    client = NS(get_entity=AsyncMock(), send_message=AsyncMock(), send_file=AsyncMock(return_value=[NS(id=101)]))
                    rule = NS(target_chat=NS(telegram_chat_id='999', name='target'), target_topic_id=topic,
                              enable_only_push=False, enable_push=False, message_mode=MessageMode.MARKDOWN,
                              is_preview=PreviewMode.OFF)
                    event = NS(message=message(), chat_id=-100555)
                    context = MessageContext(client, event, 555, rule)
                    sender = SenderFilter()
                    self.assertTrue(await sender._process(context))
                    file = Path(tmp) / 'file.jpg'
                    file.write_bytes(b'fake media')
                    context.media_files = [str(file)]
                    self.assertTrue(await sender._process(context))
                    context.media_files = []
                    context.skipped_media = [(message(), 99, 'big.mp4')]
                    self.assertTrue(await sender._process(context))
                    context.skipped_media = []
                    context.is_media_group = True
                    file.write_bytes(b'fake media')
                    context.media_group_messages = [NS(media=True, download_media=AsyncMock(return_value=str(file)))]
                    self.assertTrue(await sender._process(context))
                    for call in client.send_message.await_args_list + client.send_file.await_args_list:
                        self.assertEqual(call.kwargs['reply_to'], topic_reply_id(topic))


if __name__ == '__main__':
    unittest.main()
