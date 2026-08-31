# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести автоматичної прив'язки груп Channel Bridge до адміністраторів.

Покриває:
  - post_init_hook: кожен адміністратор (base.group_system) отримує групи
    Officer та Administrator автоматично
  - ідемпотентність: повторний виклик не дублює членство
  - не-адміністратори НЕ отримують групи автоматично
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..hooks import post_init_hook


@tagged('post_install', '-at_install')
class SecurityGroupsTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.officer = self.env.ref('fayna_channel_bridge.group_channel_bridge_officer')
        self.admin_group = self.env.ref('fayna_channel_bridge.group_channel_bridge_admin')
        self.system_group = self.env.ref('base.group_system')

    def _run_hook(self):
        """Викликає post_init_hook на поточному реєстрі."""
        post_init_hook(self.env)

    def test_admins_get_both_groups(self):
        """Кожен адміністратор автоматично отримує Officer та Administrator."""
        self._run_hook()
        for admin in self.system_group.users:
            self.assertIn(self.officer, admin.groups_id)
            self.assertIn(self.admin_group, admin.groups_id)

    def test_hook_is_idempotent(self):
        """Повторний виклик хука не створює дублікатів членства."""
        self._run_hook()
        first_count = len(self.officer.users)
        self._run_hook()
        self.assertEqual(len(self.officer.users), first_count)

    def test_non_admin_does_not_get_groups(self):
        """Звичайний користувач (не адмін) не отримує групи автоматично."""
        user = self.env['res.users'].create(
            {
                'name': 'Test Non Admin',
                'login': 'test_non_admin_channel_bridge',
                'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
            }
        )
        self._run_hook()
        self.assertNotIn(self.officer, user.groups_id)
        self.assertNotIn(self.admin_group, user.groups_id)

    def test_officer_cannot_read_secret_fields(self):
        """Б-5: Officer не читає bot_token/credentials/webhook_secret/webhook_path_id."""
        backend = self.env['channel.backend'].create(
            {
                'name': 'TG Secret',
                'service': 'telegram',
                'provider': 'direct',
                'transport_priority': 'own',
                'bot_token': '123:SECRET',
                'webhook_secret': 'wh_secret_xyz',
                'webhook_path_id': 'path_secret_xyz',
                'credentials': '{"access_token": "meta_secret"}',
            }
        )
        # Користувач лише з групою Officer (не адмін).
        officer_user = self.env['res.users'].create(
            {
                'name': 'Officer Only',
                'login': 'test_officer_only_channel_bridge',
                'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.officer.id])],
            }
        )
        # Odoo 17: читання поля з groups=, до якого немає доступу, кидає AccessError.
        with self.assertRaises(AccessError):
            backend.with_user(officer_user).read(['bot_token'])
        # Адміністратор читає секрети нормально.
        admin = self.env.ref('base.user_admin')
        vals = backend.with_user(admin).read(
            ['bot_token', 'credentials', 'webhook_secret', 'webhook_path_id']
        )[0]
        self.assertEqual(vals['bot_token'], '123:SECRET')
        self.assertEqual(vals['webhook_secret'], 'wh_secret_xyz')
        self.assertEqual(vals['webhook_path_id'], 'path_secret_xyz')
        self.assertEqual(vals['credentials'], '{"access_token": "meta_secret"}')
