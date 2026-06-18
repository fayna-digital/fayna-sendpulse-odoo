# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести F4 — auto-create crm.lead з SendPulse-розмови (lead-трек).

Закриває ДІРУ #1: у модулі було 0 тестів. Покриває критичний шлях
`SendpulseConnect._auto_create_crm_lead` + модель пулу (claim).
"""

from odoo.tests import TransactionCase, tagged

ENABLED = 'odoo_chatwoot_connector.auto_create_lead_enabled'


@tagged('post_install', '-at_install')
class TestAutoCreateLead(TransactionCase):
    def setUp(self):
        super().setUp()
        self.ICP = self.env['ir.config_parameter'].sudo()
        self.ICP.set_param(ENABLED, 'True')

    def _connect(self, **kw):
        vals = {
            'name': 'Тест Клієнт',
            'service': 'telegram',
            'unidentified_email': 'test.lead@example.com',
        }
        vals.update(kw)
        return self.env['sendpulse.connect'].create(vals)

    def test_creates_lead_in_pool(self):
        c = self._connect()
        lead = c._auto_create_crm_lead()
        self.assertTrue(lead, 'має створитись crm.lead')
        self.assertEqual(c.sp_lead_id, lead, 'sp_lead_id має вказувати на лід')
        self.assertFalse(lead.user_id, 'пул + claim: лід падає БЕЗ відповідального')
        self.assertTrue(lead.team_id, 'лід має бути в лійці (team)')
        self.assertEqual(lead.type, 'lead')

    def test_idempotent(self):
        c = self._connect()
        l1 = c._auto_create_crm_lead()
        l2 = c._auto_create_crm_lead()
        self.assertEqual(l1, l2, 'повторний виклик не дублює лід')

    def test_no_contact_skips(self):
        c = self.env['sendpulse.connect'].create({'name': 'Аноним', 'service': 'telegram'})
        lead = c._auto_create_crm_lead()
        self.assertFalse(lead, 'без жодного контакту — лід не створюємо')

    def test_disabled_is_noop(self):
        self.ICP.set_param(ENABLED, 'False')
        c = self._connect()
        lead = c._auto_create_crm_lead()
        self.assertFalse(lead, 'auto_create_lead_enabled=False → no-op')
        self.assertFalse(c.sp_lead_id)

    def test_partner_linked(self):
        partner = self.env['res.partner'].create(
            {'name': 'Іван Тест', 'email': 'ivan@example.com', 'phone': '+48700000000'}
        )
        c = self._connect(partner_id=partner.id, unidentified_email=False)
        lead = c._auto_create_crm_lead()
        self.assertEqual(lead.partner_id, partner)
        self.assertEqual(lead.email_from, 'ivan@example.com')
        self.assertEqual(lead.phone, '+48700000000')

    def test_unidentified_contact_used(self):
        c = self._connect(unidentified_email='lead2@example.com')
        lead = c._auto_create_crm_lead()
        self.assertEqual(lead.email_from, 'lead2@example.com')
