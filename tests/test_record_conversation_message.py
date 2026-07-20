# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести на `SendpulseConnect._record_conversation_message()` — спільний
helper, що замінив 3 незалежно продубльовані копії патерну
"sendpulse.message → message_post(discuss.channel) → partner.sendpulse.message"
(знахідка Odoo/OCA-аудиту 19.07.2026, п.7.2.5 `docs/INCIDENT_MESSAGE_LOSS_2026-07-19.md`).

Call-sites (звірено з поточним кодом, не зі старим аудитом):
  1. `_send_autoreply_greeting`   — helper лише для create() (post_to_channel=False)
  2. `_process_incoming_event`    — helper лише для create() (post_to_channel=False)
  3. `_process_outgoing_event`    — helper робить create+post+partner-create одним викликом

Сайти 1 і 2 свідомо НЕ віддають helper-у channel-post/partner-create —
там між create() і рештою кроків є side-effecting виклики
(send_message_to_sendpulse, _check_and_record_unsubscribe), чий порядок
відносно posting — частина поточної поведінки (див. коментарі в самому
sendpulse_connect.py біля кожного call-site).
"""
from odoo import fields
from markupsafe import Markup

from .common import SendpulseWebhookTestCase


class TestRecordConversationMessage(SendpulseWebhookTestCase):
    def _connect_with_channel_and_partner(self):
        partner = self.env['res.partner'].create({'name': 'Хелпер Партнер', 'email': 'helper@example.com'})
        connect = self.env['sendpulse.connect'].create(
            {
                'name': 'Хелпер Розмова',
                'service': 'telegram',
                'sendpulse_contact_id': 'helper-1',
                'partner_id': partner.id,
            }
        )
        channel = connect._create_discuss_channel()
        return connect, partner, channel

    def test_create_only_mode_used_by_greeting_and_incoming_sites(self):
        """post_to_channel=False, record_partner_message=False — лише
        sendpulse.message.create(), нічого іншого. Це режим, у якому
        helper викликається з _send_autoreply_greeting і
        _process_incoming_event."""
        connect = self.env['sendpulse.connect'].create(
            {'name': 'Create-only', 'service': 'telegram', 'sendpulse_contact_id': 'helper-2'}
        )
        msg = connect._record_conversation_message(
            connect,
            direction='outgoing',
            sendpulse_contact_id='helper-2',
            message_type='text',
            text_message='Доброго дня!',
            raw_json={'text': 'Доброго дня!', 'source': 'auto_greeting'},
            post_to_channel=False,
            record_partner_message=False,
        )
        self.assertEqual(msg.connect_id, connect)
        self.assertEqual(msg.direction, 'outgoing')
        self.assertEqual(msg.text_message, 'Доброго дня!')
        self.assertIn("'source': 'auto_greeting'", msg.raw_json)
        self.assertFalse(
            self.env['partner.sendpulse.message'].search([]),
            'record_partner_message=False — нічого не пишеться у вкладку партнера',
        )

    def test_full_mode_creates_message_posts_channel_and_partner_message(self):
        """Режим, яким користується _process_outgoing_event (backfill):
        одним викликом helper робить усі 3 кроки — рівно як было в
        оригінальному коді до екстракції (create → post → partner-create,
        без side-effecting викликів між ними)."""
        connect, partner, channel = self._connect_with_channel_and_partner()
        author = self.env.ref('base.partner_root')

        msg = connect._record_conversation_message(
            connect,
            direction='incoming',
            sendpulse_contact_id='helper-1',
            message_type='text',
            text_message='Пропущене повідомлення',
            raw_json={'text': 'Пропущене повідомлення', 'source': 'backfill_from_outgoing_event'},
            channel_body=Markup('<p><em>(backfill)</em><br/>Пропущене повідомлення</p>'),
            channel_author_id=author.id,
            partner_body='<p>👤 Пропущене повідомлення</p>',
        )

        self.assertEqual(msg.text_message, 'Пропущене повідомлення')

        channel_msg = self.env['mail.message'].search(
            [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id), ('author_id', '=', author.id)],
            order='id desc',
            limit=1,
        )
        self.assertIn('Пропущене повідомлення', channel_msg.body or '')

        partner_msg = self.env['partner.sendpulse.message'].search(
            [('partner_id', '=', partner.id), ('direction', '=', 'incoming')]
        )
        self.assertTrue(partner_msg)
        self.assertIn('Пропущене повідомлення', partner_msg.text_message or '')
        self.assertEqual(partner_msg.service, 'telegram')

    def test_no_channel_skips_post_even_if_body_given(self):
        connect = self.env['sendpulse.connect'].create(
            {'name': 'Без каналу', 'service': 'telegram', 'sendpulse_contact_id': 'helper-3'}
        )
        self.assertFalse(connect.channel_id)
        before = self.env['mail.message'].search_count([('model', '=', 'discuss.channel')])
        connect._record_conversation_message(
            connect,
            direction='incoming',
            sendpulse_contact_id='helper-3',
            text_message='Текст',
            channel_body=Markup('<p>Текст</p>'),
            channel_author_id=self.env.ref('base.partner_root').id,
        )
        after = self.env['mail.message'].search_count([('model', '=', 'discuss.channel')])
        self.assertEqual(before, after, 'немає channel_id — message_post не викликається')

    def test_no_partner_skips_partner_message_even_if_body_given(self):
        connect = self.env['sendpulse.connect'].create(
            {'name': 'Без партнера', 'service': 'telegram', 'sendpulse_contact_id': 'helper-4'}
        )
        self.assertFalse(connect.partner_id)
        connect._record_conversation_message(
            connect,
            direction='incoming',
            sendpulse_contact_id='helper-4',
            text_message='Текст',
            partner_body='<p>Текст</p>',
        )
        self.assertFalse(
            self.env['partner.sendpulse.message'].search([('service', '=', 'telegram')]),
            'немає partner_id — partner.sendpulse.message не створюється, навіть якщо задано partner_body',
        )

    def test_raw_json_none_stores_empty_string(self):
        connect = self.env['sendpulse.connect'].create(
            {'name': 'raw_json None', 'service': 'telegram', 'sendpulse_contact_id': 'helper-5'}
        )
        msg = connect._record_conversation_message(
            connect,
            direction='incoming',
            sendpulse_contact_id='helper-5',
            text_message='X',
            raw_json=None,
        )
        self.assertEqual(msg.raw_json, '')

    def test_date_defaults_to_now_when_not_given(self):
        connect = self.env['sendpulse.connect'].create(
            {'name': 'default date', 'service': 'telegram', 'sendpulse_contact_id': 'helper-6'}
        )
        before = fields.Datetime.now()
        msg = connect._record_conversation_message(
            connect, direction='incoming', sendpulse_contact_id='helper-6', text_message='X'
        )
        self.assertGreaterEqual(msg.date, before)
