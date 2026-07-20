# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Фаза 1 — characterization-тести `SendpulseConnect._check_and_record_unsubscribe`
(RODO consent / unsubscribe detection). Пріоритет №3 з ТЗ рефакторингу.

Метод сканує вхідний текст на unsubscribe-фрази (STOP, відпис-, nie chcę,
...) і, якщо збіг є, пише withdrawal-записи у `sendpulse.privacy.consent.log`
для трьох purposes: lead_magnet_email (якщо є email), lead_magnet_sms
(якщо є телефон) і marketing_email/messenger (якщо є партнер АБО
sp_contact_id).

⚠️ ЗНАЙДЕНО РЕАЛЬНИЙ БАГ під час написання цих тестів (перевірено живим
Odoo shell, не здогадка): рядок `if self.partner_id or self.sp_contact_id:`
звертається до поля `sp_contact_id`, якого в моделі `sendpulse.connect`
НЕ ІСНУЄ (є тільки `sendpulse_contact_id`). Odoo кидає AttributeError на
звернення до неоголошеного поля. Через `or`-коротке замикання це
спрацьовує ТІЛЬКИ коли `self.partner_id` порожній (неідентифікований
контакт) — тобто НЕІДЕНТИФІКОВАНИЙ клієнт, який пише "STOP" (чи інший
unsubscribe-патерн), краше `_check_and_record_unsubscribe`, а разом з
нею — ВЕСЬ `_process_incoming_event` (виклик там нічим не обгорнутий,
`models/sendpulse_connect.py` рядок ~1339). Це поза межами дозволеного
для цієї сесії (тільки tests/ + one mechanical extraction) — НЕ
виправлено, лише зафіксовано тестом нижче (`test_unidentified_...`) і
винесено в звіт для Фази 3.
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

    def test_unidentified_contact_crashes_on_messenger_branch(self):
        """ХАРАКТЕРИЗАЦІЯ ПОТОЧНОГО (БАГОВАНОГО) стану — див. docstring
        модуля. Неідентифікований контакт (partner_id=False) без
        booking_email, який пише unsubscribe-фразу: email/sms-гілки
        нічого не пишуть (немає ні email, ні phone), а messenger-гілка
        падає з AttributeError через посилання на неіснуюче поле
        `sp_contact_id`. Якщо колись поле `sp_contact_id` зʼявиться в
        моделі АБО рядок виправлять на `sendpulse_contact_id` — цей тест
        свідомо почне падати і його треба буде переписати під новий,
        ВИПРАВЛЕНИЙ контракт (не просто підняти try/except навколо)."""
        connect = self._connect()  # без partner_id, без sp_booking_email
        msg = self._msg(connect, 'STOP')
        with self.assertRaises(AttributeError):
            connect._check_and_record_unsubscribe('STOP', msg)

    def test_unidentified_contact_with_booking_email_partial_write_before_crash(self):
        """Той самий баг, але показує ще неприємніший наслідок: email-
        withdrawal УСПІШНО записується (sp_booking_email є) ДО того як
        код доходить до messenger-гілки і падає. У реальному webhook-
        контролері (без savepoint навколо ЦЬОГО виклику) виняток
        піднімається аж до контролера, транзакція запиту котиться
        назад — і щойно записаний RODO-доказ withdrawal теж зникає
        разом з усім іншим у тому ж request (той самий клас бага, що і
        інцидент 2026-07-19, тільки для consent-логу, не sendpulse.message).
        """
        connect = self._connect(sp_booking_email='booking-only@example.com')
        msg = self._msg(connect, 'STOP')
        # Навмисно ЗВИЧАЙНИЙ try/except, НЕ `with self.assertRaises(...)`.
        # Перевірено живим прогоном: коли AttributeError ловиться через
        # `self.assertRaises` як контекст-менеджер, щойно створений
        # (реально закомічений у savepoint тесту, id присвоєно, залогован
        # record_consent-ом) sendpulse.privacy.consent.log стає
        # НЕВИДИМИМ для будь-якого наступного search() у ЦЬОМУ ж тесті —
        # `search([])` без жодного домену повертає [] замість запису, що
        # щойно створився. З простим try/except той самий сценарій працює
        # штатно, запис видно. Причина лишається не зʼясованою до кінця
        # (щось у тому як unittest.assertRaises тримає traceback і як це
        # взаємодіє з Odoo ORM cache/flush) — задокументовано як пастка
        # для майбутніх тестів у цьому репо: якщо після
        # `assertRaises`-блоку потрібно перевіряти БІЧНІ ЕФЕКТИ (не сам
        # факт винятку) — використовуйте try/except, не assertRaises.
        try:
            connect._check_and_record_unsubscribe('STOP', msg)
            self.fail('очікував AttributeError (sp_contact_id) — див. docstring модуля')
        except AttributeError:
            pass
        # .sudo() тут ОБОВ'ЯЗКОВИЙ, не стилістичний — security/ir.model.access.csv
        # дає доступ до sendpulse.privacy.consent.log лише
        # group_sendpulse_officer/admin.
        logs = self.env['sendpulse.privacy.consent.log'].sudo().search([('connect_id', '=', connect.id)])
        self.assertEqual(
            len(logs), 1, 'email-withdrawal УСПІВ записатись до того як код впав на messenger-гілці'
        )
        self.assertEqual(logs.purpose, 'lead_magnet_email')
        self.assertEqual(logs.email, 'booking-only@example.com')
