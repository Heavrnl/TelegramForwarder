"""Exercise the real command and listener entry points without Telegram access."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from telethon.tl import types

from filters.ai_filter import _get_chat_messages
from handlers import command_handlers as commands
from handlers.button.callback import callback_handlers as callbacks
from handlers.button.settings_manager import create_settings_text
from models.models import Base, Chat, ForwardRule, Keyword
from scheduler import summary_scheduler
from utils.common import get_current_rule
from test_topic_routing import message
import message_listener as listener


class RuleFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
        self.source = NS(id=111, title='Source', forum=True)
        self.target = NS(id=222, title='Target', forum=True)
        self.responses = AsyncMock()
        self.event = NS(message=NS(text='', chat_id=-100222, id=99),
                        get_chat=AsyncMock(return_value=self.target), client=NS(), answer=AsyncMock())
        for target, value in (
            ('handlers.command_handlers.get_session', self.sessions),
            ('handlers.command_handlers.reply_and_delete', self.responses),
            ('handlers.command_handlers.async_delete_user_message', AsyncMock()),
            ('handlers.button.callback.callback_handlers.reply_and_delete', AsyncMock()),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def bind(self, source_topic, target_topic):
        await self.bind_command(f'/bind Source Target --source-topic {source_topic} --target-topic {target_topic}')

    async def bind_command(self, text):
        source, target = self.source, self.target

        class Client:
            async def get_input_entity(self, peer):
                return types.InputPeerChannel(peer.channel_id, 123)

            async def iter_dialogs(self):
                for entity in (source, target, NS(id=333, title='Other', forum=True)):
                    yield NS(name=entity.title, entity=entity)

            async def __call__(self, request):
                return NS(topics=[NS(id=i, title=f'Topic {i}', closed=False, hidden=False)
                                  for i in (1, 12, 13, 17, 18)])

        self.event.message.text = text
        with patch.object(commands, 'get_main_module', AsyncMock(return_value=NS(user_client=Client()))):
            await commands.handle_bind_command(self.event, None, [])

    async def test_bind_uses_current_topic_when_destination_is_omitted(self):
        self.event.message.reply_to = message(12).reply_to
        await self.bind_command('/bind Source --source-topic 17')
        with self.sessions() as session:
            rule = session.query(ForwardRule).one()
            self.assertEqual((rule.source_topic_id, rule.target_topic_id), (17, 12))

    async def test_bind_explicit_current_group_uses_topic_of_nested_reply(self):
        self.event.message.reply_to = message(13, reply=99).reply_to
        await self.bind_command('/bind Source Target --source-topic 17')
        with self.sessions() as session:
            self.assertEqual(session.query(ForwardRule).one().target_topic_id, 13)

    async def test_bind_explicit_topic_including_zero_overrides_current_topic(self):
        self.event.message.reply_to = message(12).reply_to
        for source_topic, target_topic in ((17, 0), (18, 13), (0, 1)):
            with self.subTest(target_topic=target_topic):
                await self.bind(source_topic, target_topic)
                with self.sessions() as session:
                    rule = session.query(ForwardRule).filter_by(source_topic_id=source_topic).one()
                    self.assertEqual(rule.target_topic_id, target_topic)

    async def test_bind_other_group_does_not_inherit_current_topic(self):
        self.event.message.reply_to = message(12).reply_to
        await self.bind_command('/bind Source Other --source-topic 17')
        with self.sessions() as session:
            rule = session.query(ForwardRule).one()
            self.assertEqual((rule.target_chat.telegram_chat_id, rule.target_topic_id), ('333', 0))

    async def test_bind_general_uses_general_without_treating_ordinary_reply_as_topic(self):
        self.event.message.reply_to = message(reply=99).reply_to
        await self.bind_command('/bind Source')
        with self.sessions() as session:
            rule = session.query(ForwardRule).one()
            self.assertEqual((rule.source_topic_id, rule.target_topic_id), (0, 1))

    async def test_bind_nonforum_chat_uses_default_destination(self):
        self.target.forum = False
        self.event.message.reply_to = message(reply=99).reply_to
        await self.bind_command('/bind Source')
        with self.sessions() as session:
            self.assertEqual(session.query(ForwardRule).one().target_topic_id, 0)

    async def test_bind_inferred_topic_is_validated_before_saving(self):
        self.event.message.reply_to = message(99).reply_to
        await self.bind_command('/bind Source')
        with self.sessions() as session:
            self.assertEqual(session.query(ForwardRule).count(), 0)
        self.assertIn('话题 99 不存在', self.responses.await_args.args[1])

    async def test_bind_inferred_topic_cannot_create_forwarding_cycle(self):
        self.event.message.reply_to = message(12).reply_to
        await self.bind_command('/bind Target --source-topic 12')
        with self.sessions() as session:
            self.assertEqual(session.query(ForwardRule).count(), 0)
        self.assertIn('转发循环', self.responses.await_args.args[1])

    async def test_bind_multiple_topics_duplicate_and_switch_are_unambiguous(self):
        await self.bind(17, 12)
        await self.bind(18, 13)
        await self.bind(17, 12)
        with self.sessions() as session:
            rules = session.query(ForwardRule).order_by(ForwardRule.id).all()
            self.assertEqual([(r.source_topic_id, r.target_topic_id) for r in rules], [(17, 12), (18, 13)])
            current, _ = await get_current_rule(session, self.event)
            self.assertEqual(current.id, rules[0].id)
            screen = NS(edit=AsyncMock())
            await callbacks.callback_switch_rule(self.event, str(rules[1].id), session, screen, '')
            current, _ = await get_current_rule(session, self.event)
            self.assertEqual(current.id, rules[1].id)
            self.assertIn('Topic 18', await create_settings_text(current))
            button_data = [row[0].data.decode() for row in screen.edit.await_args.kwargs['buttons']]
            self.assertEqual(button_data, [f'switch_rule:{r.id}' for r in rules])
        self.assertIn('已存在相同', self.responses.await_args.args[1])

    async def test_old_switch_button_cannot_silently_choose_a_topic(self):
        await self.bind(17, 12)
        await self.bind(18, 13)
        with self.sessions() as session:
            await callbacks.callback_switch(self.event, '111', session, NS(edit=AsyncMock()), '')
            self.assertIn('重新选择', self.event.answer.await_args.args[0])

    async def test_copy_settings_preserves_both_route_endpoints(self):
        await self.bind(17, 12)
        await self.bind(18, 13)
        with self.sessions() as session:
            first, second = session.query(ForwardRule).order_by(ForwardRule.id).all()
            first.is_replace = True
            session.add(Keyword(rule_id=first.id, keyword='copy me', is_regex=False, is_blacklist=True))
            session.commit()
            first_id, second_id = first.id, second.id
        self.event.message.text = f'/copy_rule {first_id} {second_id}'
        await commands.handle_copy_rule_command(self.event, 'copy_rule')
        with self.sessions() as session:
            second = session.get(ForwardRule, second_id)
            self.assertEqual((second.source_chat.telegram_chat_id, second.target_chat.telegram_chat_id), ('111', '222'))
            self.assertEqual((second.source_topic_id, second.target_topic_id), (18, 13))
            self.assertTrue(second.is_replace)
            self.assertEqual([k.keyword for k in second.keywords], ['copy me'])

    async def test_listener_routes_only_matching_topics_and_keeps_wildcard(self):
        with self.sessions() as session:
            source, target = Chat(telegram_chat_id='111'), Chat(telegram_chat_id='222')
            session.add_all([source, target])
            session.flush()
            for topic in (17, 18, 0):
                session.add(ForwardRule(source_chat_id=source.id, target_chat_id=target.id,
                                        source_topic_id=topic, target_topic_id=12, use_bot=topic != 18))
            session.commit()
        bot_process, user_process = AsyncMock(), AsyncMock()
        event = NS(get_chat=AsyncMock(return_value=self.source), chat=self.source, sender_id=55,
                   message=message(17, reply=99))
        with patch.object(listener, 'get_session', self.sessions), \
                patch.object(listener, 'process_forward_rule', bot_process), \
                patch.object(listener.user_handler, 'process_forward_rule', user_process), \
                patch.object(listener.state_manager, 'get_state', return_value=(None, None, None)):
            await listener.handle_user_message(event, NS(), NS())
            self.assertCountEqual([call.args[3].source_topic_id for call in bot_process.await_args_list], [17, 0])
            user_process.assert_not_awaited()
            event.message = message(18)
            await listener.handle_user_message(event, NS(), NS())
            self.assertEqual(user_process.await_args.args[3].source_topic_id, 18)

    async def test_general_history_excludes_other_topics_and_ordinary_replies_stay_general(self):
        history = [message(17), message(reply=99), message(18), message()]
        for index, item in enumerate(history):
            item.text = str(index)
            item.date = datetime.now(timezone.utc)

        class Client:
            async def iter_messages(self, peer, **kwargs):
                for item in history:
                    yield item

        result = await _get_chat_messages(Client(), 111, count=2, topic_id=1)
        self.assertEqual(result, '1\n---\n3')

    async def test_summary_reads_and_sends_only_configured_topics(self):
        for source_topic, target_topic in ((17, 12), (1, 1)):
            with self.subTest(source_topic=source_topic):
                await self.bind(source_topic, target_topic)
                with self.sessions() as session:
                    rule = session.query(ForwardRule).filter_by(source_topic_id=source_topic).one()
                    rule.is_summary = True
                    rule.is_top_summary = False
                    rule_id = rule.id
                    session.commit()
                history = [message(source_topic), message(18)]
                for item, body in zip(history, ('keep this', 'exclude this')):
                    item.text = body
                    item.date = datetime.now(timezone.utc)
                user_client = NS(get_messages=AsyncMock(side_effect=[history, []]))
                bot_client = NS(send_message=AsyncMock(return_value=NS(id=100)))
                provider = NS(process_message=AsyncMock(return_value='summary text'))
                scheduler = summary_scheduler.SummaryScheduler(user_client, bot_client)
                scheduler.batch_delay = 0
                with patch.object(summary_scheduler, 'get_session', self.sessions), \
                        patch.object(summary_scheduler, 'get_ai_provider', AsyncMock(return_value=provider)):
                    await scheduler._execute_summary(rule_id)
                self.assertEqual(provider.process_message.await_args.args[0], 'keep this')
                expected_reply = 12 if target_topic == 12 else None
                self.assertEqual(bot_client.send_message.await_args.kwargs['reply_to'], expected_reply)


if __name__ == '__main__':
    unittest.main()
