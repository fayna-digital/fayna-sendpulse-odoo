# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести Пакету 5 — Д-1 (галерея) та Д-2 (UX-дрібне), перенесені під OWL-SPA.

Пакет 9 (штатні kanban/form вигляди галереї) скасовано ТЗ_OMNI_DASHBOARD_OWL.md:
екран «Підключити канали» — client action на OWL-компонент (Master-Detail).
Тому тести, що перевіряли `view_channel_provider_kanban`, перенесені на нову
реальність: client action, OWL-шаблон, методи моделі `channel.provider`.

Покриває:
  - Д-1: галерея відкривається як client action; на картці є кнопка дії
    («Підключити»/«Відкрити канал»), видно `description`, є іконка каналу;
  - Д-2: `create="false"` на розмовах і журналі, людський label
    `provider_user_id`, `help` у `action_channel_backend`, обрізані заголовки;
  - UX-аудит (Пакет 7): Н9 (last_error / retry), Ш6/Т8 (disconnect архівує),
    Н5 (попередження на екрані), Н1 (confirm у wizard).
"""

import os

from odoo.tests import TransactionCase, tagged

_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_file(rel_path):
    """Читає вміст файлу модуля."""
    with open(os.path.join(_MODULE_DIR, rel_path), encoding='utf-8') as handle:
        return handle.read()


def _owl_template():
    """Вміст OWL-шаблону галереї."""
    return _read_file(os.path.join('static', 'src', 'channel_dashboard', 'channel_dashboard.xml'))


@tagged('post_install', '-at_install')
class TestPackage5Gallery(TransactionCase):
    """Д-1: галерея «Підключити канали» (OWL-SPA)."""

    def test_d1_gallery_is_client_action(self):
        """Д-1: екран відкривається як client action на OWL-компонент."""
        action = self.env.ref('fayna_channel_bridge.action_channel_provider')
        self.assertEqual(action.type, 'ir.actions.client')
        self.assertEqual(
            action.tag,
            'fayna_channel_bridge.channel_dashboard',
            'client action має вказувати на OWL-компонент ChannelDashboard',
        )

    def test_d1_gallery_has_connect_action(self):
        """Д-1: на картці є кнопка дії (Підключити / Відкрити канал)."""
        template = _owl_template()
        # Головна кнопка підключення (ТЗ §2.2) — одна primary-кнопка.
        self.assertIn('btn-primary', template, 'головна кнопка має бути primary')
        self.assertIn('onClickConnect', template, 'має бути обробник підключення')
        provider = self.env['channel.provider']
        self.assertTrue(
            hasattr(provider, 'action_connect'),
            'у channel.provider має бути метод action_connect',
        )
        self.assertTrue(
            hasattr(provider, 'action_open_backend'),
            'у channel.provider має бути метод action_open_backend',
        )

    def test_d1_gallery_shows_description(self):
        """Д-1: на картці видно `description`."""
        template = _owl_template()
        self.assertIn('activeProvider.description', template, 'у шаблоні має бути description')
        provider = self.env['channel.provider'].search([], limit=1)
        self.assertTrue(
            hasattr(provider, 'description'),
            'у channel.provider має бути поле description',
        )

    def test_d1_gallery_has_channel_icon(self):
        """Д-1: на картці є іконка каналу (нейтральний placeholder)."""
        template = _owl_template()
        self.assertIn('channel_placeholder.svg', template, 'у шаблоні має бути іконка каналу')
        # Файл іконки реально існує в модулі.
        icon_path = os.path.join(_MODULE_DIR, 'static', 'img', 'channel_placeholder.svg')
        self.assertTrue(
            os.path.isfile(icon_path),
            'файл іконки channel_placeholder.svg має існувати',
        )


@tagged('post_install', '-at_install')
class TestPackage5Ux(TransactionCase):
    """Д-2: UX-дрібне."""

    def test_d2_create_false_on_lists(self):
        """Д-2: `create="false"` на розмовах і журналі (канбан скасовано)."""
        conv = self.env.ref('fayna_channel_bridge.view_channel_conversation_list')
        msg = self.env.ref('fayna_channel_bridge.view_channel_message_list')
        for view in (conv, msg):
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
      - Ш6/Т8: у галереї є дія «Disconnect» (`action_disconnect`), яка
        архівує підключений backend;
      - Н5: на екрані видно попередження (cost/side effect) перед дією;
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
        """Ш6/Т8: у галереї є дія «Disconnect» і метод action_disconnect."""
        template = _owl_template()
        self.assertIn('onClickDisconnect', template, 'у галереї має бути дія Disconnect')
        provider = self.env['channel.provider']
        self.assertTrue(
            hasattr(provider, 'action_disconnect'),
            'у channel.provider має бути метод action_disconnect',
        )

    def test_s6_t8_disconnect_archives_backend(self):
        """Ш6/Т8: action_disconnect архівує підключений backend."""
        # Беремо token-канал (connect_method у _BACKEND_METHODS), щоб
        # `backend_id` коректно обчислився за service.
        provider = self.env['channel.provider'].search([('service', '=', 'telegram')], limit=1)
        self.assertTrue(provider, 'має бути token-канал Telegram')
        backend = self.env['channel.backend'].create(
            {
                'name': 'Telegram Test',
                'service': 'telegram',
                'provider': 'direct',
                'transport_priority': 'own',
                'bot_token': '123:TESTTOKEN',
            }
        )
        # Переконатись, що backend_id підхопив створений backend.
        self.assertEqual(provider.backend_id.id, backend.id, 'backend_id має вказувати на backend')
        provider.action_disconnect()
        self.assertFalse(backend.active, 'після disconnect backend має бути архівований')

    def test_n5_connect_has_warnings_on_screen(self):
        """Н5: на екрані видно попередження (cost/side effect) перед дією."""
        template = _owl_template()
        self.assertIn('activeProvider.cost_warning', template, 'має бути блок cost_warning')
        self.assertIn(
            'activeProvider.side_effect_warning',
            template,
            'має бути блок side_effect_warning',
        )

    def test_n1_wizard_connect_has_confirm(self):
        """Н1/Ш3/Нор2: кнопка «Connect» у wizard має confirm."""
        view = self.env.ref('fayna_channel_bridge.view_channel_connect_wizard_form')
        self.assertIn(
            'confirm="Connect this channel now?',
            view.arch,
            'кнопка Connect у wizard має мати confirm перед мережевим викликом',
        )
