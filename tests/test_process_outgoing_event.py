# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Фаза 1 — characterization-тести `SendpulseConnect._process_outgoing_event`
(backfill missed incoming). Частина пріоритету №1 (webhook processing) —
це третій call-site патерну "sendpulse.message → message_post →
partner.sendpulse.message", який винесено у спільний
`_record_conversation_message()` helper (див. test_record_conversation_message.py).
"""

from .common import SendpulseWebhookTestCase


class TestProcessOutgoingEvent(SendpulseWebhookTestCase):
    def test_backfill_creates_missed_incoming_message(self):
        """SendPulse іноді не шле окремий incoming_message webhook —
        outbound_message payload завжди несе останнє КЛІЄНТСЬКЕ
        повідомлення в contact.last_message, і код підхоплює його як
        backfill, якщо такого incoming ще немає в базі."""
        Connect = self.env['sendpulse.connect']
        contact_in = self._contact(id='backfill-1', last_message='Перше')
        connect = Connect._process_incoming_event(
            {}, contact_in, self._bot(), 'telegram', 'incoming_message', 0
        )

        contact_out = self._contact(
            id='backfill-1', last_message='Пропущене SendPulse повідомлення'
        )
        Connect._process_outgoing_event(contact_out, 'telegram', 0)

        msgs = self.env['sendpulse.message'].search([('connect_id', '=', connect.id)], order='id')
        self.assertEqual(len(msgs), 2)
        backfilled = msgs.filtered(
            lambda m: 'Пропущене SendPulse повідомлення' in (m.raw_json or '')
        )
        self.assertTrue(backfilled, 'backfill-повідомлення записано як окремий sendpulse.message')
        self.assertEqual(backfilled.direction, 'incoming')

    def test_no_backfill_when_text_already_recorded_as_incoming(self):
        """Guard: якщо цей самий текст УЖЕ є як incoming — outbound_event
        не повинен створювати дубль."""
        Connect = self.env['sendpulse.connect']
        contact_in = self._contact(id='backfill-2', last_message='Вже записане')
        connect = Connect._process_incoming_event(
            {}, contact_in, self._bot(), 'telegram', 'incoming_message', 0
        )
        before = self.env['sendpulse.message'].search_count([('connect_id', '=', connect.id)])

        contact_out = self._contact(id='backfill-2', last_message='Вже записане')
        Connect._process_outgoing_event(contact_out, 'telegram', 0)

        after = self.env['sendpulse.message'].search_count([('connect_id', '=', connect.id)])
        self.assertEqual(before, after, 'текст що вже є як incoming — не дублюється')

    def test_no_op_when_no_active_connect(self):
        """Немає активної розмови для цього contact_id+service — outbound
        event тихо ігнорується (немає куди робити backfill)."""
        Connect = self.env['sendpulse.connect']
        contact_out = self._contact(id='no-such-contact', last_message='Хтозна')
        result = Connect._process_outgoing_event(contact_out, 'telegram', 0)
        self.assertIsNone(result)
        self.assertFalse(
            self.env['sendpulse.message'].search([('sendpulse_contact_id', '=', 'no-such-contact')])
        )

    def test_no_op_when_no_last_message(self):
        Connect = self.env['sendpulse.connect']
        contact_in = self._contact(id='backfill-3', last_message='Є повідомлення')
        connect = Connect._process_incoming_event(
            {}, contact_in, self._bot(), 'telegram', 'incoming_message', 0
        )
        before = self.env['sendpulse.message'].search_count([('connect_id', '=', connect.id)])
        contact_out = self._contact(id='backfill-3', last_message='')
        Connect._process_outgoing_event(contact_out, 'telegram', 0)
        after = self.env['sendpulse.message'].search_count([('connect_id', '=', connect.id)])
        self.assertEqual(before, after)

    def test_backfill_records_partner_message_when_partner_linked(self):
        partner = self.env['res.partner'].create(
            {'name': 'Backfill Партнер', 'email': 'backfill-partner@example.com'}
        )
        Connect = self.env['sendpulse.connect']
        contact_in = self._contact(
            id='backfill-4', email='backfill-partner@example.com', last_message='Перше'
        )
        connect = Connect._process_incoming_event(
            {}, contact_in, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertEqual(connect.partner_id, partner)

        contact_out = self._contact(
            id='backfill-4', email='backfill-partner@example.com', last_message='Пропущене'
        )
        Connect._process_outgoing_event(contact_out, 'telegram', 0)

        partner_msgs = self.env['partner.sendpulse.message'].search(
            [('partner_id', '=', partner.id), ('direction', '=', 'incoming')]
        )
        self.assertTrue(
            any('Пропущене' in (pm.text_message or '') for pm in partner_msgs),
            'backfill теж записується у вкладку Messaging партнера',
        )
