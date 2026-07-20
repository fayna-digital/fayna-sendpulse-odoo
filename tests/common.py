# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Спільна база для Фаза-1 characterization-тестів (God Object safety net).

Вимикає всі мережеві/AI side-effects, які інакше спрацьовують за
замовчуванням усередині `_process_incoming_event` (авто-привітання шле
реальний HTTP-запит у SendPulse, бот-ідентифікація теж) — без цього тести
або гальмують на мережевому таймауті, або залежать від зовнішнього сервісу.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class SendpulseWebhookTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        self.ICP = ICP
        # greeting_enabled за замовчуванням 'True' → без цього перший
        # inbound від нового контакту реально стукається у SendPulse API.
        ICP.set_param('odoo_chatwoot_connector.greeting_enabled', 'False')
        # bot_identification_enabled / rag_auto_answer_enabled за
        # замовчуванням вже 'False' в коді — фіксуємо явно, щоб тест не
        # залежав від дефолту, який може змінитись.
        ICP.set_param('odoo_chatwoot_connector.bot_identification_enabled', 'False')
        ICP.set_param('odoo_chatwoot_connector.rag_auto_answer_enabled', 'False')
        ICP.set_param('odoo_chatwoot_connector.auto_create_lead_enabled', 'False')

    def _contact(self, **kw):
        vals = {
            'id': 'sp-contact-1',
            'name': 'Тест Контакт',
            'email': '',
            'phone': '',
            'last_message': '',
            'variables': {},
        }
        vals.update(kw)
        return vals

    def _bot(self, **kw):
        vals = {'id': 1, 'name': 'CampScout Bot'}
        vals.update(kw)
        return vals
