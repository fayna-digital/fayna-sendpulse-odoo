# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести моделі-каталогу `channel.provider` (Пакет 3, В-2).

Покриває:
  - рівно 7 записів каталогу після установки;
  - T-127: новий канал додається рядком даних без змін у Python;
  - `service` бере значення зі спільної константи SERVICE_SELECTION.
"""

from odoo.tests import TransactionCase, tagged

from ..models.channel_backend import SERVICE_SELECTION


@tagged("post_install", "-at_install")
class TestProviderCatalog(TransactionCase):
    def test_seven_providers_after_install(self):
        """Після установки в каталозі рівно 7 записів channel.provider."""
        providers = self.env["channel.provider"].search([])
        self.assertEqual(len(providers), 7, "У каталозі має бути рівно 7 каналів")

    def test_provider_services_use_shared_constant(self):
        """`service` кожного провайдера належить спільній константі."""
        providers = self.env["channel.provider"].search([])
        valid_services = {value for value, _label in SERVICE_SELECTION}
        for provider in providers:
            self.assertIn(
                provider.service,
                valid_services,
                "service має брати значення зі спільної константи SERVICE_SELECTION",
            )

    def test_t127_new_provider_as_data_row(self):
        """T-127: новий канал додається рядком даних без змін у Python."""
        provider = self.env["channel.provider"].create(
            {
                "name": "Signal",
                "service": "telegram",  # значення зі спільної константи
                "sequence": 80,
                "connect_method": "token",
            }
        )
        self.assertTrue(provider.id, "Новий провайдер має створитись")
        # Запис з'являється в каталозі (галерея читає channel.provider)
        found = self.env["channel.provider"].search([("id", "=", provider.id)])
        self.assertEqual(len(found), 1, "Новий канал має з'явитись у каталозі")
        self.assertEqual(found.name, "Signal")
