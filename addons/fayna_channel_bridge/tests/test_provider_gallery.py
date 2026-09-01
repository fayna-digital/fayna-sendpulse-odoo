# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести галереї «Підключити канали» (OWL-SPA, ТЗ_OMNI_DASHBOARD_OWL.md).

Покриває (перенесено з Пакета 3, В-3, під новий client action):
  - T-114: галерея показує всі картки, згруповані за категорією
    (main = 8, marketplace = 3), у кожній видно стан;
  - T-115: екран відкривається як client action на OWL-компонент
    (замість form view провайдера);
  - T-116: для token-каналу help_url непорожній;
  - T-119: у view і в OWL-шаблоні немає полів токена/секрету/URL вебхука;
  - T-120: get_dashboard_data() повертає категорію, connect_method і жодного
    секрету; для native/external стану підключення немає (ТЗ §2.3-bis).
"""

import os

from odoo.tests import TransactionCase, tagged

_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Поля, яких НЕ має бути в жодному view/шаблоні галереї (UX-14, T-119).
_FORBIDDEN_FIELDS = (
    'bot_token',
    'credentials',
    'webhook_secret',
    'webhook_path_id',
)

# Очікуваний склад категорій (ТЗ §2.2, §2.3-bis).
_MAIN_SERVICES = {
    'telegram',
    'messenger',
    'whatsapp',
    'instagram',
    'tiktok',
    'viber',
    'email',
    'sms',
}
_MARKETPLACE_SERVICES = {'telegram_personal', 'viber_personal', 'linkedin'}


@tagged('post_install', '-at_install')
class TestProviderGallery(TransactionCase):
    def test_t114_gallery_shows_all_cards_grouped_by_category(self):
        """T-114: галерея показує всі картки, згруповані за категорією."""
        providers = self.env['channel.provider'].search([])
        # 8 основних + 3 маркетплейс = 11 карток.
        self.assertEqual(len(providers), 11, 'Галерея має показувати 11 карток')

        main = providers.filtered(lambda p: p.category == 'main')
        marketplace = providers.filtered(lambda p: p.category == 'marketplace')
        self.assertEqual(
            set(main.mapped('service')),
            _MAIN_SERVICES,
            'Категорія «Основні» має містити рівно 8 каналів',
        )
        self.assertEqual(
            set(marketplace.mapped('service')),
            _MARKETPLACE_SERVICES,
            'Категорія «Маркетплейс» має містити рівно 3 канали',
        )

        # У кожного каналу з власним бекендом (oauth/token) видно стан.
        for provider in providers.filtered(lambda p: p.connect_method in ('oauth', 'token')):
            self.assertTrue(
                provider.state_label,
                f'Канал {provider.name} має мати видимий стан (ТЗ §0.1)',
            )

    def test_t115_screen_is_client_action(self):
        """T-115: екран відкривається як client action на OWL-компонент."""
        action = self.env.ref('fayna_channel_bridge.action_channel_provider')
        self.assertEqual(action.type, 'ir.actions.client')
        self.assertEqual(
            action.tag,
            'fayna_channel_bridge.channel_dashboard',
            'Client action має вказувати на OWL-компонент ChannelDashboard',
        )

    def test_t116_token_channel_has_help_url(self):
        """T-116: для token-каналу help_url непорожній."""
        token_providers = self.env['channel.provider'].search([('connect_method', '=', 'token')])
        self.assertTrue(token_providers, 'Мають бути token-канали (Telegram, Viber)')
        for provider in token_providers:
            self.assertTrue(
                provider.help_url,
                f'Token-канал {provider.name} має мати непорожній help_url',
            )

    def test_t119_no_secret_fields_in_gallery_views(self):
        """T-119: у view і OWL-шаблоні немає полів токена/секрету/URL вебхука."""
        files = [
            os.path.join(_MODULE_DIR, 'views', 'channel_provider_views.xml'),
            os.path.join(
                _MODULE_DIR,
                'static',
                'src',
                'channel_dashboard',
                'channel_dashboard.xml',
            ),
            os.path.join(
                _MODULE_DIR,
                'static',
                'src',
                'channel_dashboard',
                'channel_dashboard.js',
            ),
        ]
        for path in files:
            with open(path, encoding='utf-8') as handle:
                content = handle.read()
            for field in _FORBIDDEN_FIELDS:
                self.assertNotIn(
                    field,
                    content,
                    f'У {os.path.basename(path)} не має бути {field} (UX-14)',
                )

    def test_t120_dashboard_data_has_no_secrets_and_honest_states(self):
        """T-120: get_dashboard_data() без секретів; native/external без стану."""
        data = self.env['channel.provider'].get_dashboard_data()
        self.assertEqual(len(data), 11, 'RPC має повернути всі 11 карток')

        for item in data:
            # Жодного секрету в payload (UX-14).
            for secret in (
                'bot_token',
                'credentials',
                'webhook_secret',
                'webhook_path_id',
            ):
                self.assertNotIn(secret, item, f'У payload не має бути {secret}')
            # Кожен пункт має категорію і метод підключення.
            self.assertIn(item['category'], ('main', 'marketplace'))
            self.assertIn(
                item['connect_method'],
                ('oauth', 'token', 'widget', 'settings', 'native', 'external'),
            )
            # native/external — статусу підключення немає взагалі (§2.3-bis).
            if item['connect_method'] in ('native', 'external'):
                self.assertFalse(item['state'], f"{item['name']} не має стану")
                self.assertFalse(item['is_connected'], f"{item['name']} не підключено")
