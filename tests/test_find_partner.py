# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Фаза 1 — characterization-тести `SendpulseConnect._find_partner`.

Пріоритет №2 з ТЗ рефакторингу. Метод шукає партнера в такому порядку
(з docstring коду, звірено з реалізацією `models/sendpulse_connect.py`):
  1. sendpulse_contact_id
  2. email (контакту з SendPulse)
  3. user_email з bot-змінних
  4. booking_email з bot-змінних
  5. phone / mobile
  6. None, якщо нічого не збіглось

Побічний ефект, який теж пінується тестами: збіг по email/phone дописує
`sendpulse_contact_id` партнеру, якщо він там ще не заповнений (щоб
наступний виклик уже потрапив у гілку 1 — найдешевшу).
"""
from .common import SendpulseWebhookTestCase


class TestFindPartner(SendpulseWebhookTestCase):
    def _find(self, contact_id, email='', phone='', variables=None):
        return self.env['sendpulse.connect']._find_partner(
            contact_id, email, phone, variables=variables
        )

    def test_priority1_by_contact_id(self):
        partner = self.env['res.partner'].create(
            {'name': 'Знайдений по contact_id', 'sendpulse_contact_id': 'cid-1'}
        )
        # email/phone нижче навмисно вказують на ІНШОГО (неіснуючого)
        # партнера — доводимо що contact_id виграє пріоритет.
        found = self._find('cid-1', email='nobody@example.com', phone='+48000000000')
        self.assertEqual(found, partner)

    def test_priority2_by_email(self):
        partner = self.env['res.partner'].create(
            {'name': 'Знайдений по email', 'email': 'byemail@example.com'}
        )
        found = self._find('cid-new', email='ByEmail@Example.com')
        self.assertEqual(found, partner, 'пошук email через =ilike — регістр не важливий')

    def test_email_match_writes_back_contact_id(self):
        partner = self.env['res.partner'].create(
            {'name': 'Без contact_id', 'email': 'writeback@example.com'}
        )
        self.assertFalse(partner.sendpulse_contact_id)
        self._find('cid-writeback', email='writeback@example.com')
        self.assertEqual(partner.sendpulse_contact_id, 'cid-writeback')

    def test_email_match_does_not_overwrite_existing_contact_id(self):
        partner = self.env['res.partner'].create(
            {
                'name': 'Вже має contact_id',
                'email': 'keep@example.com',
                'sendpulse_contact_id': 'original-cid',
            }
        )
        self._find('new-cid-should-not-overwrite', email='keep@example.com')
        self.assertEqual(
            partner.sendpulse_contact_id,
            'original-cid',
            'існуючий sendpulse_contact_id не перезаписується новим контактом з іншого каналу',
        )

    def test_priority3_by_variables_user_email(self):
        partner = self.env['res.partner'].create(
            {'name': 'Через user_email бота', 'email': 'bot-collected@example.com'}
        )
        found = self._find('cid-uv', variables={'user_email': 'bot-collected@example.com'})
        self.assertEqual(found, partner)

    def test_priority4_by_variables_booking_email(self):
        partner = self.env['res.partner'].create(
            {'name': 'Через booking_email', 'email': 'booking@example.com'}
        )
        found = self._find('cid-bv', variables={'booking_email': 'booking@example.com'})
        self.assertEqual(found, partner)

    def test_variables_user_email_takes_priority_over_booking_email(self):
        user_email_partner = self.env['res.partner'].create(
            {'name': 'user_email партнер', 'email': 'uev@example.com'}
        )
        self.env['res.partner'].create(
            {'name': 'booking_email партнер', 'email': 'bev@example.com'}
        )
        found = self._find(
            'cid-priority', variables={'user_email': 'uev@example.com', 'booking_email': 'bev@example.com'}
        )
        self.assertEqual(found, user_email_partner)

    def test_priority5_by_phone(self):
        partner = self.env['res.partner'].create(
            {'name': 'Через телефон', 'phone': '+48123456789'}
        )
        found = self._find('cid-ph', phone='+48123456789')
        self.assertEqual(found, partner)

    def test_priority5_by_mobile(self):
        partner = self.env['res.partner'].create(
            {'name': 'Через mobile', 'mobile': '+48987654321'}
        )
        found = self._find('cid-mob', phone='+48987654321')
        self.assertEqual(found, partner)

    def test_phone_match_strips_spaces(self):
        partner = self.env['res.partner'].create(
            {'name': 'Телефон без пробілів', 'phone': '+48111222333'}
        )
        found = self._find('cid-sp', phone='+48 111 222 333')
        self.assertEqual(found, partner)

    def test_no_match_returns_none(self):
        found = self._find('cid-none', email='nobody@example.com', phone='+48000000000')
        self.assertIsNone(found)

    def test_empty_contact_id_skips_priority1_lookup(self):
        """contact_id='' — гілка `if contact_id:` не виконується, одразу
        йде пошук по email (сам факт що метод не падає на порожньому
        contact_id — теж частина контракту)."""
        partner = self.env['res.partner'].create(
            {'name': 'Порожній contact_id', 'email': 'empty-cid@example.com'}
        )
        found = self._find('', email='empty-cid@example.com')
        self.assertEqual(found, partner)
