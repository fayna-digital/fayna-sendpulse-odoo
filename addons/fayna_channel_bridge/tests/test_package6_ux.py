# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести Пакета 6, Е-2 — серверний гейт передумов (UX-16).

Покриває:
  - провайдер із непорожнім `region_blocklist` без підтвердження →
    `action_connect` кидає `UserError` з людським текстом, backend НЕ створено;
  - після підтвердження регіону той самий виклик проходить гейт;
  - провайдер із `consent_required` без підтвердження → `UserError`,
    backend НЕ створено.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPackage6PreconditionGate(TransactionCase):
    """Серверний захист `action_connect` від непідтверджених передумов."""

    def setUp(self):
        super().setUp()
        self.tiktok = self.env.ref("fayna_channel_bridge.provider_tiktok")
        self.whatsapp = self.env.ref("fayna_channel_bridge.provider_whatsapp")

    def _backend_exists(self, service):
        return bool(
            self.env["channel.backend"].search(
                [("service", "=", service), ("active", "=", True)], limit=1
            )
        )

    def test_region_blocklist_without_confirmation_is_blocked(self):
        """TikTok (region_blocklist) без підтвердження → UserError, backend не створено."""
        self.assertTrue(
            self.tiktok.region_blocklist, "TikTok має мати region_blocklist"
        )
        self.assertTrue(self.tiktok.has_unconfirmed_preconditions)
        with self.assertRaises(UserError) as ctx:
            self.tiktok.action_connect()
        message = str(ctx.exception)
        self.assertIn("regions", message, "помилка має бути людською мовою (UX-16)")
        self.assertFalse(
            self._backend_exists("tiktok"),
            "backend не має створюватись, поки передумови не підтверджені",
        )

    def test_region_blocklist_after_confirmation_passes_gate(self):
        """Після підтвердження регіону той самий виклик проходить гейт."""
        self.tiktok.region_confirmed = True
        self.assertFalse(self.tiktok.has_unconfirmed_preconditions)
        # TikTok — oauth: після гейта має впасти саме oauth-помилка «вручну»,
        # а не помилка передумов. Це доводить, що гейт пройдено.
        with self.assertRaises(UserError) as ctx:
            self.tiktok.action_connect()
        message = str(ctx.exception)
        self.assertIn(
            "manually", message, "має бути oauth-помилка, а не помилка передумов"
        )
        self.assertNotIn("regions", message)

    def test_consent_required_without_confirmation_is_blocked(self):
        """WhatsApp (consent_required) без підтвердження → UserError, backend не створено."""
        self.assertTrue(self.whatsapp.consent_required, "WhatsApp має вимагати згоду")
        self.assertTrue(self.whatsapp.has_unconfirmed_preconditions)
        with self.assertRaises(UserError) as ctx:
            self.whatsapp.action_connect()
        message = str(ctx.exception)
        self.assertIn("consent", message, "помилка має бути людською мовою (UX-16)")
        self.assertFalse(
            self._backend_exists("whatsapp"),
            "backend не має створюватись, поки згоду не підтверджено",
        )
