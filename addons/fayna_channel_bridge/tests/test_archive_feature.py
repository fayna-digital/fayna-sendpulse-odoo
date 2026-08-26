# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести архівної фічі (fayna_channel_bridge) — 30-денне стиснення розмов.

Покриває:
  - cron_archive_old_conversations: архівація (active=False) неактивних розмов
  - soft-archive через нативний механізм Odoo (поле ``active``)
  - архівація пов'язаного discuss.channel (ховається з активного інбоксу)
  - конфігурація кількості днів через ir.config_parameter
  - збереження історії (запис не видаляється, лише ховається)
"""

from datetime import datetime, timedelta

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class ArchiveFeatureTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.ICP = self.env["ir.config_parameter"].sudo()
        # Скидаємо конфіг архівації до дефолту
        self.ICP.set_param("fayna_channel_bridge.archive_inactive_days", "30")

    def _create_conversation(self, name, last_message_date, with_channel=True):
        """Створює channel.conversation (і опційно пов'язаний discuss.channel)."""
        Conversation = self.env["channel.conversation"]
        conversation = Conversation.create(
            {
                "name": name,
                "service": "telegram",
                "provider_user_id": f"test_{name}",
                "last_message_date": last_message_date,
                "transport": "own",
            }
        )
        if with_channel:
            channel = self.env["discuss.channel"].create(
                {
                    "name": f"[Telegram] {name}",
                    "channel_type": "group",
                }
            )
            conversation.write({"channel_id": channel.id})
        return conversation

    def test_archives_old_inactive_conversations(self):
        """Розмови, неактивні понад 30 днів, архівуються (active=False)."""
        old = self._create_conversation("OldConv", datetime.now() - timedelta(days=60))
        recent = self._create_conversation(
            "RecentConv", datetime.now() - timedelta(days=5)
        )

        archived_count = self.env[
            "channel.conversation"
        ].cron_archive_old_conversations()

        self.assertEqual(archived_count, 1)
        self.assertFalse(old.active, "Стара розмова має бути заархівована")
        self.assertTrue(recent.active, "Свіжа розмова не має архівуватись")

    def test_archives_related_discuss_channel(self):
        """Пов'язаний discuss.channel теж архівується (ховається з інбоксу)."""
        old = self._create_conversation(
            "OldWithChannel", datetime.now() - timedelta(days=45)
        )
        self.assertTrue(old.channel_id.active)

        self.env["channel.conversation"].cron_archive_old_conversations()

        self.assertFalse(
            old.channel_id.active, "discuss.channel має бути заархівований"
        )

    def test_preserves_history(self):
        """Архівація не видаляє запис — лише ховає (soft-archive)."""
        old = self._create_conversation(
            "KeepHistory", datetime.now() - timedelta(days=90)
        )
        conversation_id = old.id

        self.env["channel.conversation"].cron_archive_old_conversations()

        # Запис існує в БД (з active=False)
        archived = (
            self.env["channel.conversation"]
            .with_context(active_test=False)
            .browse(conversation_id)
        )
        self.assertTrue(archived.exists(), "Запис має зберегтись у БД")
        self.assertFalse(archived.active)

    def test_respects_configured_days(self):
        """Кількість днів конфігурується через ir.config_parameter."""
        self.ICP.set_param("fayna_channel_bridge.archive_inactive_days", "10")
        # 15 днів — старше за 10, має архівуватись
        old = self._create_conversation("Old10d", datetime.now() - timedelta(days=15))
        # 5 днів — молодше за 10, не має архівуватись
        recent = self._create_conversation(
            "Recent10d", datetime.now() - timedelta(days=5)
        )

        archived_count = self.env[
            "channel.conversation"
        ].cron_archive_old_conversations()

        self.assertEqual(archived_count, 1)
        self.assertFalse(old.active)
        self.assertTrue(recent.active)

    def test_minimum_days_floor(self):
        """Мінімальний поріг — 7 днів (не можна встановити менше)."""
        self.ICP.set_param("fayna_channel_bridge.archive_inactive_days", "1")
        # 3 дні — менше за мінімум 7, але floor піднімає до 7 → не архівується
        recent = self._create_conversation(
            "FloorTest", datetime.now() - timedelta(days=3)
        )

        archived_count = self.env[
            "channel.conversation"
        ].cron_archive_old_conversations()

        self.assertEqual(archived_count, 0)
        self.assertTrue(recent.active)

    def test_invalid_days_falls_back_to_default(self):
        """Невалідне значення днів → fallback на дефолт 30."""
        self.ICP.set_param("fayna_channel_bridge.archive_inactive_days", "not-a-number")
        # 40 днів — старше за 30, має архівуватись
        old = self._create_conversation(
            "InvalidCfg", datetime.now() - timedelta(days=40)
        )

        archived_count = self.env[
            "channel.conversation"
        ].cron_archive_old_conversations()

        self.assertEqual(archived_count, 1)
        self.assertFalse(old.active)

    def test_no_old_conversations_returns_zero(self):
        """Якщо немає старих розмов — повертає 0 і нічого не архівує."""
        self._create_conversation("FreshOnly", datetime.now() - timedelta(days=1))

        archived_count = self.env[
            "channel.conversation"
        ].cron_archive_old_conversations()

        self.assertEqual(archived_count, 0)

    def test_skips_conversation_without_last_message_date(self):
        """Розмови без last_message_date не архівуються."""
        no_date = self._create_conversation("NoDate", False)

        archived_count = self.env[
            "channel.conversation"
        ].cron_archive_old_conversations()

        self.assertEqual(archived_count, 0)
        self.assertTrue(no_date.active)
