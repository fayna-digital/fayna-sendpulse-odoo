# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести моделі-каталогу `channel.provider` (Пакет 3, В-2; ТЗ §2.3-bis).

Покриває:
  - рівно 11 записів каталогу після установки (8 основних + 3 маркетплейс);
  - T-127: новий канал додається рядком даних без змін у Python;
  - `service` кожного провайдера належить власній константі
    PROVIDER_CATALOG_SELECTION (ТЗ §2.3-bis: розчеплено з channel.backend).
"""

from odoo.tests import TransactionCase, tagged

from ..models.channel_provider import PROVIDER_CATALOG_SELECTION


@tagged('post_install', '-at_install')
class TestProviderCatalog(TransactionCase):
    def test_eleven_providers_after_install(self):
        """Після установки в каталозі рівно 11 записів channel.provider."""
        providers = self.env['channel.provider'].search([])
        self.assertEqual(len(providers), 11, 'У каталозі має бути рівно 11 каналів')

    def test_provider_services_use_catalog_constant(self):
        """`service` кожного провайдера належить PROVIDER_CATALOG_SELECTION."""
        providers = self.env['channel.provider'].search([])
        valid_services = {value for value, _label in PROVIDER_CATALOG_SELECTION}
        for provider in providers:
            self.assertIn(
                provider.service,
                valid_services,
                'service має брати значення з PROVIDER_CATALOG_SELECTION',
            )

    def test_t127_new_provider_as_data_row(self):
        """T-127: новий канал додається рядком даних без змін у Python."""
        provider = self.env['channel.provider'].create(
            {
                'name': 'Signal',
                'service': 'telegram',  # значення зі спільної константи
                'sequence': 80,
                'connect_method': 'token',
            }
        )
        self.assertTrue(provider.id, 'Новий провайдер має створитись')
        # Запис з'являється в каталозі (галерея читає channel.provider)
        found = self.env['channel.provider'].search([('id', '=', provider.id)])
        self.assertEqual(len(found), 1, "Новий канал має з'явитись у каталозі")
        self.assertEqual(found.name, 'Signal')
