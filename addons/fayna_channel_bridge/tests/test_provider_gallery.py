# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести галереї «Підключити канали» (Пакет 3, В-3).

Покриває:
  - T-114: галерея показує 7 карток, у кожній видно статус;
  - T-115: на формі провайдера рівно одна primary-кнопка;
  - T-116: для token-каналу help_url непорожній;
  - T-119: у нових view немає полів токена/секрету/URL вебхука.
"""

import os

from odoo.tests import TransactionCase, tagged

_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Поля, яких НЕ має бути в жодному новому view галереї (UX-14, T-119).
_FORBIDDEN_FIELDS = (
    'bot_token',
    'credentials',
    'webhook_secret',
    'webhook_path_id',
    'heal_url',
)


@tagged('post_install', '-at_install')
class TestProviderGallery(TransactionCase):
    def test_t114_gallery_shows_seven_cards_with_status(self):
        """T-114: галерея показує 7 карток, у кожній видно статус."""
        providers = self.env['channel.provider'].search([])
        self.assertEqual(len(providers), 7, 'Галерея має показувати 7 карток')
        for provider in providers:
            self.assertTrue(
                provider.status_label,
                'У картці має бути видно статус (підключено / ні)',
            )

    def test_t115_form_has_exactly_one_primary_button(self):
        """T-115: на формі провайдера рівно одна primary-кнопка."""
        view = self.env.ref('fayna_channel_bridge.view_channel_provider_form')
        arch = view.arch
        # Рахуємо кнопки з класом btn-primary (головна дія).
        primary_buttons = arch.count('btn-primary')
        self.assertEqual(
            primary_buttons,
            1,
            'На формі провайдера має бути рівно одна primary-кнопка',
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
        """T-119: у нових view галереї немає полів токена/секрету/URL вебхука."""
        view_file = os.path.join(_MODULE_DIR, 'views', 'channel_provider_views.xml')
        with open(view_file, encoding='utf-8') as handle:
            content = handle.read()
        for field in _FORBIDDEN_FIELDS:
            self.assertNotIn(
                field,
                content,
                f'У view галереї не має бути поля/посилання на {field} (UX-14)',
            )
