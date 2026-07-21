# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Regression-тест на баг, знайдений sudo()-аудитом 21.07.2026 («345»,
довершення аудит-пунктів #2/#8): `mail_channel.py.message_post` перевіряв
slash-команду `/lead` ДО перевірки контексту `sendpulse_incoming` — клієнтське
inbound-повідомлення, що випадково починається з "/lead", тихо
проковтувалось (ніколи не потрапляло в chat) і замінювалось авто-створеним
CRM-лідом, розрахованим лише на ручну команду оператора.
"""

from .common import SendpulseWebhookTestCase


class TestMailChannelLeadCommand(SendpulseWebhookTestCase):
    def test_customer_message_starting_with_lead_is_not_swallowed(self):
        """Клієнтське inbound-повідомлення "/lead ..." має потрапити в чат
        як звичайний sendpulse.message — НЕ бути проковтнутим і НЕ
        створювати crm.lead."""
        Connect = self.env['sendpulse.connect']
        Lead = self.env['crm.lead']
        leads_before = Lead.search_count([])

        contact = self._contact(
            id='lead-cmd-1', name='Клієнт Тест', last_message='/lead мене цікавить табір'
        )
        connect = Connect._process_incoming_event(
            {}, contact, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertTrue(connect)

        msg = self.env['sendpulse.message'].search([('connect_id', '=', connect.id)])
        self.assertEqual(len(msg), 1, 'клієнтське повідомлення має бути збережено, не проковтнуто')
        self.assertIn('/lead мене цікавить табір', msg.text_message)

        self.assertEqual(
            Lead.search_count([]),
            leads_before,
            "клієнтське '/lead ...' не повинно автоматично створювати CRM-лід",
        )

    def test_operator_lead_command_still_creates_lead(self):
        """Ручна команда оператора /lead (без sendpulse_incoming контексту)
        і далі створює CRM-лід — стара поведінка не зламана."""
        Connect = self.env['sendpulse.connect']
        contact = self._contact(id='lead-cmd-2', name='Клієнт Два', last_message='Привіт')
        connect = Connect._process_incoming_event(
            {}, contact, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertTrue(connect)
        leads_before = self.env['crm.lead'].search_count([])

        connect.channel_id.message_post(body='/lead', message_type='comment')

        self.assertEqual(
            self.env['crm.lead'].search_count([]),
            leads_before + 1,
            'оператор, що вручну пише /lead, має отримати створений лід як і раніше',
        )
