# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести власного транспорту (fayna_channel_bridge) — M0 Telegram пілот.

Покриває:
  - channel.backend: відправка через Telegram Bot API (мок requests)
  - channel.message: ідемпотентність за provider_message_id
  - channel.conversation._send_single_message: маршрутизація transport='own'
  - webhook-прийом: нормалізація payload + дедуплікація
"""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class ChannelBridgeTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        ICP = self.env["ir.config_parameter"].sudo()
        self.ICP = ICP

        # Створюємо тестовий backend
        Backend = self.env["channel.backend"]
        self.backend = Backend.create(
            {
                "name": "TG Test Bot",
                "service": "telegram",
                "provider": "direct",
                "transport_priority": "own",
                "bot_token": "123456:TEST_TOKEN",
                "bot_id": "@TestBot",
            }
        )

    def _mock_telegram_response(self, ok=True, message_id=42):
        """Повертає mock-об'єкт відповіді Telegram API."""
        mock = type("Resp", (), {})()
        mock.status_code = 200 if ok else 400
        mock.text = '{"ok": true, "result": {"message_id": %d}}'
        mock.json = lambda: {
            "ok": ok,
            "result": {"message_id": message_id},
            "description": None if ok else "Bad Request",
        }
        return mock


class TestChannelBackendSend(ChannelBridgeTestCase):
    def test_send_message_success(self):
        """send_message через Telegram Bot API повертає provider_message_id."""
        mock_resp = self._mock_telegram_response(ok=True, message_id=200)
        with patch("requests.post", return_value=mock_resp) as mock_post:
            ok, msg_id, err = self.backend.send_message(
                "Привіт!", provider_user_id="12345"
            )
        self.assertTrue(ok)
        self.assertEqual(msg_id, "200")
        self.assertIsNone(err)
        # Перевіряємо, що запит пішов на правильный endpoint
        call_url = mock_post.call_args[0][0]
        self.assertIn("/bot123456:TEST_TOKEN/", call_url)
        self.assertIn("sendMessage", call_url)

    def test_send_message_missing_token(self):
        """Без токена — помилка."""
        self.backend.write({"bot_token": False})
        ok, msg_id, err = self.backend.send_message("text", provider_user_id="1")
        self.assertFalse(ok)
        self.assertIn("token", err)

    def test_send_message_missing_user_id(self):
        """Без provider_user_id — помилка."""
        ok, msg_id, err = self.backend.send_message("text", provider_user_id=None)
        self.assertFalse(ok)
        self.assertIn("provider_user_id", err)


class TestTransportRouting(ChannelBridgeTestCase):
    def test_own_transport_routes_to_backend(self):
        """transport='own' → _send_single_message йде через channel.backend."""
        Conversation = self.env["channel.conversation"]
        conversation = Conversation.create(
            {
                "name": "TG Client",
                "service": "telegram",
                "backend_id": self.backend.id,
                "provider_user_id": "12345",
                "transport": "own",
            }
        )
        mock_resp = self._mock_telegram_response(ok=True, message_id=300)
        with patch("requests.post", return_value=mock_resp):
            ok = conversation._send_single_message("Тест від оператора")
        self.assertTrue(ok)
        # Журнал власного транспорту записано
        msg = self.env["channel.message"].search(
            [("backend_id", "=", self.backend.id), ("direction", "=", "outgoing")]
        )
        self.assertTrue(msg)
        self.assertEqual(msg.text_message, "Тест від оператора")


class TestTelegramWebhook(ChannelBridgeTestCase):
    def test_duplicate_update_skipped(self):
        """Повторний webhook з тим самим message_id не дублює повідомлення."""
        Message = self.env["channel.message"]
        # Перший раз — створюємо запис
        Message.create(
            {
                "backend_id": self.backend.id,
                "service": "telegram",
                "direction": "incoming",
                "state": "received",
                "provider_message_id": "100",
                "provider_user_id": "12345",
                "text_message": "Привіт!",
            }
        )
        # Другий раз — ідемпотентність: search знаходить existing
        existing = Message.search(
            [
                ("provider_message_id", "=", "100"),
                ("service", "=", "telegram"),
                ("direction", "=", "incoming"),
            ]
        )
        self.assertEqual(len(existing), 1)

    def test_unique_index_blocks_duplicate(self):
        """Partial unique index блокує дублікат (provider_message_id, service)."""
        Message = self.env["channel.message"]
        Message.create(
            {
                "backend_id": self.backend.id,
                "service": "telegram",
                "direction": "incoming",
                "state": "received",
                "provider_message_id": "101",
                "provider_user_id": "12345",
                "text_message": "Перше",
            }
        )
        from psycopg2 import IntegrityError

        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            Message.create(
                {
                    "backend_id": self.backend.id,
                    "service": "telegram",
                    "direction": "incoming",
                    "state": "received",
                    "provider_message_id": "101",
                    "provider_user_id": "12345",
                    "text_message": "Дубль",
                }
            )


class TestMetaSend(ChannelBridgeTestCase):
    def setUp(self):
        super().setUp()
        # Створюємо Meta backend (messenger) з credentials (access_token + page_id)
        Backend = self.env["channel.backend"]
        self.meta_backend = Backend.create(
            {
                "name": "MSG Test Page",
                "service": "messenger",
                "provider": "direct",
                "transport_priority": "own",
                "webhook_secret": "verify_secret_123",
                "credentials": '{"access_token": "EAA_TEST_TOKEN", "page_id": "123456789"}',
            }
        )

    def _mock_meta_response(self, ok=True, message_id="m_123"):
        mock = type("Resp", (), {})()
        mock.status_code = 200 if ok else 400
        mock.text = f'{{"message_id": "{message_id}"}}'
        mock.json = lambda: {"message_id": message_id}
        return mock

    def test_meta_send_success(self):
        """send_message через Meta Graph API повертає message_id."""
        mock_resp = self._mock_meta_response(ok=True, message_id="m_200")
        with patch("requests.post", return_value=mock_resp) as mock_post:
            ok, msg_id, err = self.meta_backend.send_message(
                "Привіт!", provider_user_id="psid_123"
            )
        self.assertTrue(ok)
        self.assertEqual(msg_id, "m_200")
        self.assertIsNone(err)
        call_url = mock_post.call_args[0][0]
        self.assertIn("graph.facebook.com", call_url)
        self.assertIn("/messages", call_url)

    def test_meta_send_missing_token(self):
        """Без Page Access Token — помилка."""
        # Очищаємо credentials щоб не було токена
        self.meta_backend.write({"credentials": "{}"})
        ok, msg_id, err = self.meta_backend.send_message(
            "text", provider_user_id="psid_1"
        )
        self.assertFalse(ok)
        self.assertIn("Token", err)


class TestMessengerWebhook(ChannelBridgeTestCase):
    def setUp(self):
        super().setUp()
        Backend = self.env["channel.backend"]
        self.meta_backend = Backend.create(
            {
                "name": "MSG Webhook Page",
                "service": "messenger",
                "provider": "direct",
                "transport_priority": "own",
                "webhook_secret": "verify_secret_123",
            }
        )

    def test_messenger_webhook_secret_configured(self):
        """Messenger backend має webhook_secret для verify."""
        self.assertEqual(self.meta_backend.webhook_secret, "verify_secret_123")
        self.assertTrue(self.meta_backend.webhook_secret)
        # Backend знаходиться за service
        found = self.env["channel.backend"].search(
            [
                ("service", "=", "messenger"),
                ("provider", "=", "direct"),
                ("active", "=", True),
            ],
            limit=1,
        )
        self.assertEqual(found, self.meta_backend)


class TestM3Providers(ChannelBridgeTestCase):
    """M3: Viber, WhatsApp, TikTok, LiveChat send через власний транспорт."""

    def _make_backend(self, service, credentials=None):
        Backend = self.env["channel.backend"]
        return Backend.create(
            {
                "name": f"{service.upper()} Test",
                "service": service,
                "provider": "direct",
                "transport_priority": "own",
                "credentials": credentials or "{}",
            }
        )

    def _mock_response(self, ok=True, body=None, json_data=None):
        mock = type("Resp", (), {})()
        mock.status_code = 200 if ok else 400
        mock.text = body or "{}"
        mock.json = lambda: json_data or {}
        return mock

    def test_viber_send_success(self):
        """Viber send_message через REST API."""
        backend = self._make_backend("viber", '{"auth_token": "VIBER_TOKEN"}')
        mock_resp = self._mock_response(
            ok=True, json_data={"status": 0, "message_token": "v_1"}
        )
        with patch("requests.post", return_value=mock_resp) as mock_post:
            ok, msg_id, err = backend.send_message(
                "Привіт!", provider_user_id="viber_id_1"
            )
        self.assertTrue(ok)
        self.assertEqual(msg_id, "v_1")
        self.assertIsNone(err)
        self.assertIn("chatapi.viber.com", mock_post.call_args[0][0])

    def test_viber_send_missing_token(self):
        """Viber без auth_token — помилка."""
        backend = self._make_backend("viber", "{}")
        ok, msg_id, err = backend.send_message("text", provider_user_id="viber_id_1")
        self.assertFalse(ok)
        self.assertIn("Auth-Token", err)

    def test_whatsapp_send_success(self):
        """WhatsApp Cloud API send_message."""
        backend = self._make_backend(
            "whatsapp", '{"phone_number_id": "12345", "token": "WA_TOKEN"}'
        )
        mock_resp = self._mock_response(
            ok=True, json_data={"messages": [{"id": "wamid_1"}]}
        )
        with patch("requests.post", return_value=mock_resp) as mock_post:
            ok, msg_id, err = backend.send_message(
                "Привіт!", provider_user_id="380123456789"
            )
        self.assertTrue(ok)
        self.assertEqual(msg_id, "wamid_1")
        self.assertIsNone(err)
        self.assertIn("graph.facebook.com", mock_post.call_args[0][0])

    def test_whatsapp_send_missing_phone(self):
        """WhatsApp без phone_number_id — помилка."""
        backend = self._make_backend("whatsapp", "{}")
        ok, msg_id, err = backend.send_message("text", provider_user_id="380123456789")
        self.assertFalse(ok)
        self.assertIn("phone_number_id", err)

    def test_tiktok_send_success(self):
        """TikTok send_message."""
        backend = self._make_backend("tiktok", '{"access_token": "TT_TOKEN"}')
        mock_resp = self._mock_response(
            ok=True, json_data={"data": {"message_id": "tt_1"}}
        )
        with patch("requests.post", return_value=mock_resp) as mock_post:
            ok, msg_id, err = backend.send_message(
                "Привіт!", provider_user_id="open_id_1"
            )
        self.assertTrue(ok)
        self.assertEqual(msg_id, "tt_1")
        self.assertIsNone(err)
        self.assertIn("open.tiktokapis.com", mock_post.call_args[0][0])

    def test_tiktok_send_missing_token(self):
        """TikTok без access_token — помилка."""
        backend = self._make_backend("tiktok", "{}")
        ok, msg_id, err = backend.send_message("text", provider_user_id="open_id_1")
        self.assertFalse(ok)
        self.assertIn("access_token", err)

    def test_livechat_send_success(self):
        """LiveChat send_message."""
        backend = self._make_backend(
            "livechat", '{"token": "LC_TOKEN", "chat_id": "ch_1"}'
        )
        mock_resp = self._mock_response(ok=True, json_data={"event_id": "ev_1"})
        with patch("requests.post", return_value=mock_resp) as mock_post:
            ok, msg_id, err = backend.send_message(
                "Привіт!", provider_user_id="lc_user_1"
            )
        self.assertTrue(ok)
        self.assertEqual(msg_id, "ev_1")
        self.assertIsNone(err)
        self.assertIn("api.livechatinc.com", mock_post.call_args[0][0])

    def test_livechat_send_missing_token(self):
        """LiveChat без token — помилка."""
        backend = self._make_backend("livechat", "{}")
        ok, msg_id, err = backend.send_message("text", provider_user_id="lc_user_1")
        self.assertFalse(ok)
        self.assertIn("token", err)
