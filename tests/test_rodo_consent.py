# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Фаза 1 — characterization-тести `SendpulseConnect._check_and_record_unsubscribe`
(RODO consent / unsubscribe detection). Пріоритет №3 з ТЗ рефакторингу.

Метод сканує вхідний текст на unsubscribe-фрази (STOP, відпис-, nie chcę,
...) і, якщо збіг є, пише withdrawal-записи у `sendpulse.privacy.consent.log`
для трьох purposes: lead_magnet_email (якщо є email), lead_magnet_sms
(якщо є телефон) і marketing_email/messenger (якщо є партнер АБО
sendpulse_contact_id).

✅ ВИПРАВЛЕНО у Фазі 3, крок 3 (`models/sendpulse_rodo.py`). Історія: під
час написання цих тестів (Фаза 1) був знайдений реальний баг —
перевірено живим Odoo shell, не здогадка: у messenger-гілці
umsubscribe-методу була умова, що звертались до поля з невірним
префіксом («sp_» замість «sendpulse_»), якого в моделі
`sendpulse.connect` НЕ ІСНУЄ (є тільки `sendpulse_contact_id`). Odoo
кидав AttributeError на звернення до неоголошеного поля. Через
`or`-коротке замикання це спрацьовувало ТІЛЬКИ коли `self.partner_id`
порожній (неідентифікований контакт) — тобто НЕІДЕНТИФІКОВАНИЙ клієнт,
який пише "STOP" (чи інший unsubscribe-патерн), крашив
`_check_and_record_unsubscribe`, а разом з нею — ВЕСЬ
`_process_incoming_event` (виклик там нічим не обгорнутий). При
переносі методу в `models/sendpulse_rodo.py` умову виправлено на
звернення до правильного поля `sendpulse_contact_id` — тести нижче
(`test_unidentified_...`) переписані під новий, ВИПРАВЛЕНИЙ контракт.
"""
from .common import SendpulseWebhookTestCase


class TestRodoUnsubscribe(SendpulseWebhookTestCase):
    def _connect(self, **kw):
        vals = {'name': 'RODO Тест', 'service': 'telegram', 'sendpulse_contact_id': 'rodo-1'}
        vals.update(kw)
        return self.env['sendpulse.connect'].create(vals)

    def _msg(self, connect, text):
        return self.env['sendpulse.message'].create(
            {
                'connect_id': connect.id,
                'sendpulse_contact_id': connect.sendpulse_contact_id,
                'direction': 'incoming',
                'message_type': 'text',
                'text_message': text,
            }
        )

    def test_no_unsubscribe_pattern_returns_false_no_records(self):
        connect = self._connect()
        msg = self._msg(connect, 'Дякую, все чудово!')
        result = connect._check_and_record_unsubscribe('Дякую, все чудово!', msg)
        self.assertFalse(result)
        self.assertFalse(
            self.env['sendpulse.privacy.consent.log'].sudo().search([('connect_id', '=', connect.id)])
        )

    def test_empty_text_returns_false(self):
        connect = self._connect()
        msg = self._msg(connect, '')
        self.assertFalse(connect._check_and_record_unsubscribe('', msg))

    def test_stop_with_partner_email_and_phone_records_three_withdrawals(self):
        partner = self.env['res.partner'].create(
            {'name': 'RODO Партнер', 'email': 'rodo@example.com', 'mobile': '+48700111222'}
        )
        connect = self._connect(partner_id=partner.id)
        msg = self._msg(connect, 'STOP будь ласка')
        result = connect._check_and_record_unsubscribe('STOP будь ласка', msg)
        self.assertTrue(result)

        logs = self.env['sendpulse.privacy.consent.log'].sudo().search([('connect_id', '=', connect.id)])
        self.assertEqual(len(logs), 3, 'email + sms + messenger withdrawal')
        purposes = set(logs.mapped('purpose'))
        self.assertEqual(purposes, {'lead_magnet_email', 'lead_magnet_sms', 'marketing_email'})
        self.assertTrue(all(not log.consent_given for log in logs), 'усі три — withdrawal (consent_given=False)')
        email_log = logs.filtered(lambda log: log.purpose == 'lead_magnet_email')
        self.assertEqual(email_log.email, 'rodo@example.com')
        sms_log = logs.filtered(lambda log: log.purpose == 'lead_magnet_sms')
        self.assertEqual(sms_log.phone, '+48700111222')

    def test_stop_with_partner_no_phone_records_two_withdrawals(self):
        partner = self.env['res.partner'].create({'name': 'Без телефону', 'email': 'nophone@example.com'})
        connect = self._connect(partner_id=partner.id)
        msg = self._msg(connect, 'unsubscribe')
        connect._check_and_record_unsubscribe('unsubscribe', msg)
        logs = self.env['sendpulse.privacy.consent.log'].sudo().search([('connect_id', '=', connect.id)])
        self.assertEqual(len(logs), 2, 'email + messenger, без sms (немає телефону)')
        self.assertEqual(set(logs.mapped('purpose')), {'lead_magnet_email', 'marketing_email'})

    def test_polish_pattern_nie_chce_detected(self):
        partner = self.env['res.partner'].create({'name': 'PL', 'email': 'pl@example.com'})
        connect = self._connect(partner_id=partner.id)
        msg = self._msg(connect, 'Dziękuję, ale nie chcę więcej wiadomości')
        result = connect._check_and_record_unsubscribe(
            'Dziękuję, ale nie chcę więcej wiadomości', msg
        )
        self.assertTrue(result, 'польський патерн nie chcę теж детектиться')

    def test_ukrainian_pattern_vidpys_detected(self):
        partner = self.env['res.partner'].create({'name': 'UA', 'email': 'ua@example.com'})
        connect = self._connect(partner_id=partner.id)
        text = 'хочу відписатися від розсилки'
        msg = self._msg(connect, text)
        self.assertTrue(connect._check_and_record_unsubscribe(text, msg))

    def test_unidentified_contact_records_messenger_withdrawal_after_fix(self):
        """Історична примітка: цей тест раніше характеризував баг, де
        неідентифікований контакт (partner_id=False), що пише
        unsubscribe-фразу, крашив `_check_and_record_unsubscribe` з
        AttributeError через посилання на неіснуюче поле з невірним
        префіксом (див. докстрінг модуля). Баг виправлено у Фазі 3, крок 3
        (`models/sendpulse_rodo.py`): рядок тепер звертається до
        реального поля `sendpulse_contact_id`.

        Новий, ВИПРАВЛЕНИЙ контракт: неідентифікований контакт
        (partner_id=False) без sp_booking_email, який пише
        unsubscribe-фразу — email/sms-гілки нічого не пишуть (немає ні
        email, ні phone), а messenger-гілка ТЕПЕР спрацьовує, бо
        `self.sendpulse_contact_id` ('rodo-1' з фікстури `_connect`)
        truthy — записується один withdrawal-лог, крашу немає.
        """
        connect = self._connect()  # без partner_id, без sp_booking_email
        msg = self._msg(connect, 'STOP')
        result = connect._check_and_record_unsubscribe('STOP', msg)
        self.assertTrue(result)
        logs = self.env['sendpulse.privacy.consent.log'].sudo().search([('connect_id', '=', connect.id)])
        self.assertEqual(len(logs), 1, 'лише messenger withdrawal (немає email, немає phone)')
        self.assertEqual(logs.purpose, 'marketing_email')
        self.assertFalse(logs.partner_id, 'немає partner_id у неідентифікованого контакту')

    def test_unidentified_contact_with_booking_email_records_two_withdrawals_after_fix(self):
        """Той самий, вже виправлений контракт, але з sp_booking_email:
        email-withdrawal пишеться (sp_booking_email є), sms-withdrawal
        не пишеться (немає partner_id → немає телефону), а
        messenger-withdrawal ТЕПЕР теж пишеться (sendpulse_contact_id
        truthy) — усього 2 логи, без крашу.
        """
        connect = self._connect(sp_booking_email='booking-only@example.com')
        msg = self._msg(connect, 'STOP')
        result = connect._check_and_record_unsubscribe('STOP', msg)
        self.assertTrue(result)
        # .sudo() тут ОБОВ'ЯЗКОВИЙ, не стилістичний — security/ir.model.access.csv
        # дає доступ до sendpulse.privacy.consent.log лише
        # group_sendpulse_officer/admin.
        logs = self.env['sendpulse.privacy.consent.log'].sudo().search([('connect_id', '=', connect.id)])
        self.assertEqual(len(logs), 2, 'email + messenger withdrawal, без sms (немає partner_id)')
        self.assertEqual(set(logs.mapped('purpose')), {'lead_magnet_email', 'marketing_email'})
        email_log = logs.filtered(lambda log: log.purpose == 'lead_magnet_email')
        self.assertEqual(email_log.email, 'booking-only@example.com')
