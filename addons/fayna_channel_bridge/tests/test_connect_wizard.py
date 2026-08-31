# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести wizard підключення token-каналів (Пакет 3, В-4).

Покриває:
  - Telegram із валідним ключем створює `channel.backend` і викликає реєстрацію
    вебхука (реєстрацію мокаємо, мережу не смикаємо);
  - UX-12: невалідний ключ → повідомлення без сирого коду провайдера;
  - T-119: у результаті роботи wizard користувачеві не повертається ні секрет,
    ні URL вебхука.
"""

from unittest.mock import Mock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestConnectWizard(TransactionCase):
    """Тести wizard `channel.connect.wizard`."""

    def setUp(self):
        super().setUp()
        self.telegram = self.env.ref("fayna_channel_bridge.provider_telegram")
        self.viber = self.env.ref("fayna_channel_bridge.provider_viber")

    @staticmethod
    def _tg_webhook_ok():
        """Мок успішної відповіді Telegram setWebhook."""
        resp = Mock()
        resp.status_code = 200
        resp.text = '{"ok": true}'
        resp.json.return_value = {"ok": True}
        return resp

    @staticmethod
    def _tg_webhook_error():
        """Мок відповіді Telegram setWebhook з помилкою авторизації."""
        resp = Mock()
        resp.status_code = 401
        resp.text = '{"ok": false, "description": "Unauthorized"}'
        resp.json.return_value = {"ok": False, "description": "Unauthorized"}
        return resp

    def _make_wizard(self, provider, token):
        return self.env["channel.connect.wizard"].create(
            {"provider_id": provider.id, "token": token}
        )

    def test_telegram_valid_key_creates_backend_and_registers_webhook(self):
        """Валідний ключ Telegram → створюється backend і реєструється вебхук."""
        wizard = self._make_wizard(self.telegram, "123456:TESTTOKEN")
        with patch("requests.post", return_value=self._tg_webhook_ok()) as mock:
            result = wizard.action_connect()
        # Backend створено
        backend = self.env["channel.backend"].search(
            [("service", "=", "telegram"), ("active", "=", True)], limit=1
        )
        self.assertTrue(backend, "має створитись channel.backend для Telegram")
        self.assertEqual(backend.bot_token, "123456:TESTTOKEN")
        # Реєстрацію вебхука викликано (setWebhook)
        self.assertTrue(mock.called, "має викликатись реєстрація вебхука")
        # Результат — закриття wizard
        self.assertEqual(result["type"], "ir.actions.act_window_close")

    def test_viber_valid_key_creates_backend_without_webhook_call(self):
        """Валідний ключ Viber → backend створено, мережу не смикаємо."""
        wizard = self._make_wizard(self.viber, "viber_token_123")
        with patch("requests.post") as mock:
            result = wizard.action_connect()
        backend = self.env["channel.backend"].search(
            [("service", "=", "viber"), ("active", "=", True)], limit=1
        )
        self.assertTrue(backend, "має створитись channel.backend для Viber")
        creds = backend._get_credentials()
        self.assertEqual(creds.get("auth_token"), "viber_token_123")
        # Для Viber окремого методу реєстрації немає — мережу не чіпаємо.
        self.assertFalse(mock.called, "для Viber не має бути виклику мережі")
        self.assertEqual(result["type"], "ir.actions.act_window_close")

    def test_invalid_key_human_message_without_raw_provider_code(self):
        """UX-12: невалідний ключ → людське повідомлення без сирого коду."""
        wizard = self._make_wizard(self.telegram, "bad_token")
        with (
            patch("requests.post", return_value=self._tg_webhook_error()),
            self.assertRaises(UserError) as ctx,
        ):
            wizard.action_connect()
        message = str(ctx.exception)
        # Людське пояснення, а не сирий код провайдера
        self.assertIn("Invalid token", message)
        self.assertNotIn("Unauthorized", message)
        self.assertNotIn("401", message)

    def test_t119_no_secret_or_webhook_url_returned(self):
        """T-119: у результаті wizard немає секрету чи URL вебхука."""
        wizard = self._make_wizard(self.telegram, "123456:TESTTOKEN")
        with patch("requests.post", return_value=self._tg_webhook_ok()):
            result = wizard.action_connect()
        # Результат — це dict action; серіалізуємо його для перевірки.
        serialized = str(result)
        self.assertNotIn("webhook_secret", serialized)
        self.assertNotIn("webhook_path_id", serialized)
        self.assertNotIn("/bridge/telegram/webhook/", serialized)
        self.assertNotIn("123456:TESTTOKEN", serialized)
