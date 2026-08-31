# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести Пакету 5 — Д-1 (галерея) та Д-2 (UX-дрібне).

Покриває:
  - Д-1: на картці галереї є кнопка дії («Підключити»/«Відкрити канал»),
    видно `description`, є іконка каналу (нейтральний placeholder);
  - Д-2: `create="false"` на трьох списках/канбані (розмови, журнал, галерея),
    людський label `provider_user_id` («Контакт у каналі»),
    `help` у `action_channel_backend`, обрізані заголовки списку каналів.
"""

import os

from odoo.tests import TransactionCase, tagged

_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_view(rel_path):
    """Читає вміст view-файлу модуля."""
    with open(os.path.join(_MODULE_DIR, rel_path), encoding='utf-8') as handle:
        return handle.read()


@tagged('post_install', '-at_install')
class TestPackage5Gallery(TransactionCase):
    """Д-1: галерея «Підключити канали»."""

    def test_d1_kanban_has_action_button(self):
        """Д-1: на картці галереї є кнопка дії (Підключити / Відкрити канал)."""
        view = self.env.ref('fayna_channel_bridge.view_channel_provider_kanban')
        arch = view.arch
        self.assertIn('name="action_connect"', arch, 'має бути кнопка «Підключити»')
        self.assertIn('name="action_open_backend"', arch, 'має бути кнопка «Відкрити канал»')
        # Кнопка дії — primary (головна дія на картці).
        self.assertIn('btn-primary', arch, 'кнопка дії має бути primary')

    def test_d1_kanban_shows_description(self):
        """Д-1: на картці галереї видно `description`."""
        view = self.env.ref('fayna_channel_bridge.view_channel_provider_kanban')
        arch = view.arch
        # Odoo нормалізує self-closing теги до `<field name="description"/>`.
        self.assertIn('name="description"', arch, 'у канбані має бути description')
        self.assertIn('o_kanban_description', arch, 'description має бути в блоці опису')

    def test_d1_kanban_has_channel_icon(self):
        """Д-1: на картці галереї є іконка каналу (нейтральний placeholder)."""
        view = self.env.ref('fayna_channel_bridge.view_channel_provider_kanban')
        arch = view.arch
        self.assertIn('channel_placeholder.svg', arch, 'має бути іконка каналу')
        # Файл іконки реально існує в модулі.
        icon_path = os.path.join(_MODULE_DIR, 'static', 'img', 'channel_placeholder.svg')
        self.assertTrue(
            os.path.isfile(icon_path),
            'файл іконки channel_placeholder.svg має існувати',
        )

    def test_d1_open_backend_action_exists(self):
        """Д-1: метод `action_open_backend` існує на моделі провайдера."""
        provider = self.env['channel.provider'].search([], limit=1)
        self.assertTrue(
            hasattr(provider, 'action_open_backend'),
            'у channel.provider має бути метод action_open_backend',
        )


@tagged('post_install', '-at_install')
class TestPackage5Ux(TransactionCase):
    """Д-2: UX-дрібне."""

    def test_d2_create_false_on_three_lists(self):
        """Д-2: `create="false"` на розмовах, журналі та канбані галереї."""
        conv = self.env.ref('fayna_channel_bridge.view_channel_conversation_list')
        msg = self.env.ref('fayna_channel_bridge.view_channel_message_list')
        kanban = self.env.ref('fayna_channel_bridge.view_channel_provider_kanban')
        for view in (conv, msg, kanban):
            self.assertIn(
                'create="false"',
                view.arch,
                f'view {view.name} має мати create="false"',
            )

    def test_d2_provider_user_id_human_label(self):
        """Д-2: `provider_user_id` має людський label «Контакт у каналі»."""
        view = self.env.ref('fayna_channel_bridge.view_channel_message_list')
        self.assertIn(
            'string="Contact in channel"',
            view.arch,
            'provider_user_id має мати людський label «Contact in channel»',
        )

    def test_d2_backend_action_has_help(self):
        """Д-2: `action_channel_backend` має непорожній `help`."""
        action = self.env.ref('fayna_channel_bridge.action_channel_backend')
        self.assertTrue(action.help, 'help у action_channel_backend не має бути порожнім')

    def test_d2_backend_list_headers_not_truncated(self):
        """Е-1: у списку каналів одна текстова колонка «Стан», булевих немає."""
        view = self.env.ref('fayna_channel_bridge.view_channel_backend_list')
        arch = view.arch
        # Е-1: замість двох булевих колонок — одна текстова колонка стану.
        self.assertIn('string="Status"', arch, 'колонка «Status»')
        # Булевих колонок у списку не має бути (вони лишились лише у формі).
        self.assertNotIn('name="active"', arch, 'булеву колонку active прибрано зі списку')
        self.assertNotIn(
            'name="last_healthcheck_ok"',
            arch,
            'булеву колонку last_healthcheck_ok прибрано зі списку',
        )
        # Старого довгого заголовка не має бути.
        self.assertNotIn('string="Healthcheck OK"', arch, 'довгий заголовок прибрано')


@tagged('post_install', '-at_install')
class TestUxAuditFixes(TransactionCase):
    """UX-аудит (Пакет 7): виправлення 🟡-знахідок аналітичних лінз.

    Покриває:
      - Н9: у списку каналів видно `last_error` (причину помилки);
      - Н9: у формі каналу є кнопка «Retry check» (`action_retry_check`);
      - Ш6/Т8: у галереї є кнопка «Disconnect» (`action_disconnect`), яка
        архівує підключений backend;
      - Н5: кнопка «Connect» має `confirm` при наявності попереджень;
      - Н1/Ш3/Нор2: кнопка «Connect» у wizard має `confirm` перед мережевим
        викликом.
    """

    def test_n9_backend_list_shows_last_error(self):
        """Н9: у списку каналів видно `last_error` (причину помилки)."""
        view = self.env.ref('fayna_channel_bridge.view_channel_backend_list')
        self.assertIn('name="last_error"', view.arch, 'у списку каналів має бути last_error')

    def test_n9_backend_form_has_retry_check(self):
        """Н9: у формі каналу є кнопка «Retry check»."""
        view = self.env.ref('fayna_channel_bridge.view_channel_backend_form')
        self.assertIn(
            'name="action_retry_check"',
            view.arch,
            'у формі каналу має бути кнопка «Retry check»',
        )
        backend = self.env['channel.backend']
        self.assertTrue(
            hasattr(backend, 'action_retry_check'),
            'у channel.backend має бути метод action_retry_check',
        )

    def test_s6_t8_gallery_has_disconnect(self):
        """Ш6/Т8: у галереї є кнопка «Disconnect» і метод action_disconnect."""
        view = self.env.ref('fayna_channel_bridge.view_channel_provider_kanban')
        self.assertIn(
            'name="action_disconnect"',
            view.arch,
            'у галереї має бути кнопка «Disconnect»',
        )
        provider = self.env['channel.provider']
        self.assertTrue(
            hasattr(provider, 'action_disconnect'),
            'у channel.provider має бути метод action_disconnect',
        )

    def test_s6_t8_disconnect_archives_backend(self):
        """Ш6/Т8: action_disconnect архівує підключений backend."""
        # Використовуємо service, якого ще немає в базі, щоб уникнути
        # конфлікту з partial-unique індексом (service, provider, bot_id).
        provider = self.env['channel.provider'].search([('service', '=', 'livechat')], limit=1)
        backend = self.env['channel.backend'].create(
            {
                'name': 'LiveChat Test',
                'service': 'livechat',
                'provider': 'direct',
                'transport_priority': 'own',
            }
        )
        # Прив'язуємо backend до провайдера через пошук за service.
        provider.action_disconnect()
        self.assertFalse(backend.active, 'після disconnect backend має бути архівований')

    def test_n5_connect_has_confirm_when_warnings(self):
        """Н5: кнопка «Connect» має confirm при наявності попереджень."""
        view = self.env.ref('fayna_channel_bridge.view_channel_provider_kanban')
        self.assertIn(
            'cost_warning.raw_value or record.side_effect_warning.raw_value',
            view.arch,
            'кнопка Connect має враховувати попередження (cost/side effect)',
        )

    def test_n1_wizard_connect_has_confirm(self):
        """Н1/Ш3/Нор2: кнопка «Connect» у wizard має confirm."""
        view = self.env.ref('fayna_channel_bridge.view_channel_connect_wizard_form')
        self.assertIn(
            'confirm="Connect this channel now?',
            view.arch,
            'кнопка Connect у wizard має мати confirm перед мережевим викликом',
        )
