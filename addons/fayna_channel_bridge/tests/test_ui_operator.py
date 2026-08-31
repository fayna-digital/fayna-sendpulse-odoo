# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести UI оператора (Пакет 3, В-1).

Покриває:
  - T-92: користувач лише з групою Officer бачить пункти «Розмови» і «Журнал»
    і НЕ бачить «Канали» (той доступний лише Administrator);
  - T-93: ir.actions.act_window для розмов має непорожній help.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestUIOperator(TransactionCase):
    def setUp(self):
        super().setUp()
        self.officer_group = self.env.ref('fayna_channel_bridge.group_channel_bridge_officer')
        self.admin_group = self.env.ref('fayna_channel_bridge.group_channel_bridge_admin')
        self.officer = self.env['res.users'].create(
            {
                'name': 'Officer UI',
                'login': 'test_officer_ui_channel_bridge',
                'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.officer_group.id])],
            }
        )

    def _menu_ids(self, user):
        """Повертає множину id видимих меню для користувача.

        `_visible_menu_ids` — це @api.model-метод, що використовує
        `self.env.user.groups_id`, тому для перевірки конкретного
        користувача обов'язково застосовуємо `with_user(user)`.
        """
        return self.env['ir.ui.menu'].with_user(user)._visible_menu_ids()

    def test_t92_officer_sees_conversations_and_journal_not_channels(self):
        """T-92: Officer бачить «Розмови» і «Журнал», але не «Канали»."""
        conv_menu = self.env.ref('fayna_channel_bridge.menu_channel_bridge_conversations')
        msg_menu = self.env.ref('fayna_channel_bridge.menu_channel_bridge_messages')
        backends_menu = self.env.ref('fayna_channel_bridge.menu_channel_bridge_backends')

        visible = self._menu_ids(self.officer)
        self.assertIn(conv_menu.id, visible)
        self.assertIn(msg_menu.id, visible)
        self.assertNotIn(backends_menu.id, visible)

    def test_t92_admin_sees_channels(self):
        """T-92: Administrator бачить пункт «Канали»."""
        admin = self.env['res.users'].create(
            {
                'name': 'Admin UI',
                'login': 'test_admin_ui_channel_bridge',
                'groups_id': [
                    (
                        6,
                        0,
                        [
                            self.env.ref('base.group_user').id,
                            self.officer_group.id,
                            self.admin_group.id,
                        ],
                    )
                ],
            }
        )
        backends_menu = self.env.ref('fayna_channel_bridge.menu_channel_bridge_backends')
        visible = self._menu_ids(admin)
        self.assertIn(backends_menu.id, visible)

    def test_t93_conversation_action_has_help(self):
        """T-93: act_window для розмов має непорожній help."""
        action = self.env.ref('fayna_channel_bridge.action_channel_conversation')
        self.assertTrue(action.help, 'help для розмов не має бути порожнім')
