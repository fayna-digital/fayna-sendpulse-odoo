import json
import logging

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class ChannelBridgeController(http.Controller):
    """
    Webhook-рути провайдерів власного транспорту.

    Кожен провайдер приводить payload до загальної структури і викликає
    channel.conversation._process_incoming_event (обробник власного транспорту).
    """

    def _json(self, data, status=200):
        return Response(
            json.dumps(data), content_type="application/json", status=status
        )

    def _find_backend_by_token(self, token):
        """Знаходить активний channel.backend за Telegram bot token."""
        Backend = request.env["channel.backend"].sudo()
        # Токен може бути в полі bot_token або в credentials JSON
        backend = Backend.search(
            [
                ("service", "=", "telegram"),
                ("provider", "=", "direct"),
                ("active", "=", True),
            ]
        )
        for rec in backend:
            if rec._get_telegram_token() == token:
                return rec
        return None

    @http.route(
        "/bridge/telegram/webhook/<token>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def telegram_webhook(self, token):
        """
        Telegram webhook. Токен у URL — аутентифікація (capable).
        Payload: {"update_id": ..., "message": {"message_id": ..., "chat": {...}, "text": ...}}
        """
        backend = self._find_backend_by_token(token)
        if not backend:
            _logger.warning(
                "Channel Bridge: unknown Telegram token from %s",
                request.httprequest.remote_addr,
            )
            return self._json(
                {"status": "error", "message": "Unauthorized"}, status=401
            )

        raw = request.httprequest.data
        if not raw:
            return self._json({"status": "error", "message": "Empty payload"})
        try:
            data = json.loads(raw)
        except ValueError:
            return self._json(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        update = data.get("update") or data
        message = update.get("message") or {}
        if not message:
            # Не-повідомлення (напр. edited_message) — ігноруємо, але 200 щоб Telegram не ретраїв
            return self._json({"status": "ok"})

        provider_message_id = str(message.get("message_id", ""))
        chat = message.get("chat") or {}
        provider_user_id = str(chat.get("id", ""))
        text = message.get("text") or ""
        user = message.get("from") or {}
        user_name = user.get("first_name", "") or ""
        if user.get("last_name"):
            user_name = f"{user_name} {user['last_name']}".strip()
        username = user.get("username", "") or ""

        # ── Ідемпотентність: дедуплікація за (provider_message_id, service) ──
        Message = request.env["channel.message"].sudo()
        existing = Message.search(
            [
                ("provider_message_id", "=", provider_message_id),
                ("service", "=", "telegram"),
                ("direction", "=", "incoming"),
            ],
            limit=1,
        )
        if existing:
            _logger.info(
                "Channel Bridge: duplicate Telegram update %s, skipping",
                provider_message_id,
            )
            return self._json({"status": "ok"})

        # ── Нормалізуємо payload до загальної структури (див. ТЗ §8) ──
        # Формат own:telegram:{bot_id}:{user_id} — bot_id дозволяє розрізняти
        # кілька Telegram-ботів при виборі backend-а для відправки.
        bot_id = backend.bot_id or ""
        own_contact_id = (
            f"own:telegram:{bot_id}:{provider_user_id}"
            if bot_id
            else f"own:telegram:{provider_user_id}"
        )
        normalized = {
            "service": "telegram",
            "contact": {
                "id": own_contact_id,
                "name": user_name or username or f"TG:{provider_user_id}",
                "email": "",
                "phone": "",
                "last_message": text,
                "last_message_data": {"message": {"type": "text"}},
                "variables": {
                    "username": username,
                    "profile_url": f"https://t.me/{username}" if username else "",
                },
            },
            "bot": {"id": bot_id, "name": backend.name},
            "title": "incoming_message",
            "date": int(message.get("date", 0)) * 1000,
        }

        # ── Записуємо в журнал власного транспорту (до обробки, для audit) ──
        Message.create(
            {
                "backend_id": backend.id,
                "service": "telegram",
                "direction": "incoming",
                "state": "received",
                "provider_message_id": provider_message_id,
                "provider_user_id": provider_user_id,
                "text_message": text,
                "raw_json": json.dumps(data, ensure_ascii=False),
            }
        )

        # ── Обробник вхідних подій власного транспорту ──
        try:
            with request.env.cr.savepoint():
                request.env["channel.conversation"].sudo()._process_incoming_event(
                    data=normalized,
                    contact=normalized["contact"],
                    bot=normalized["bot"],
                    service="telegram",
                    event_type="incoming_message",
                    timestamp_ms=normalized["date"],
                )
        except Exception as e:
            _logger.error(
                "Channel Bridge: telegram processing failed — %s", e, exc_info=True
            )
            return self._json(
                {"status": "error", "message": "Processing failed"}, status=500
            )

        return self._json({"status": "ok"})

    def _find_backend_by_service(self, service):
        """Знаходить активний channel.backend за service (для Meta)."""
        Backend = request.env["channel.backend"].sudo()
        return Backend.search(
            [
                ("service", "=", service),
                ("provider", "=", "direct"),
                ("active", "=", True),
            ],
            limit=1,
        )

    @http.route(
        "/bridge/messenger/webhook",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def messenger_webhook_verify(self):
        """
        Meta webhook verify (hub.challenge). Повертає hub.challenge якщо
        hub.verify_token збігається з webhook_secret backend-а (messenger або instagram).
        """
        verify_token = request.params.get("hub.verify_token", "")
        challenge = request.params.get("hub.challenge", "")
        for service in ("messenger", "instagram"):
            backend = self._find_backend_by_service(service)
            if (
                backend
                and backend.webhook_secret
                and verify_token == backend.webhook_secret
            ):
                return Response(challenge, content_type="text/plain")
        _logger.warning(
            "Channel Bridge: Meta verify token mismatch from %s",
            request.httprequest.remote_addr,
        )
        return self._json({"status": "error", "message": "Unauthorized"}, status=401)

    @http.route(
        "/bridge/messenger/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def messenger_webhook(self):
        """
        Meta Messenger/Instagram webhook POST. Payload:
        {"object": "page", "entry": [{"id": ..., "messaging": [{"sender": {...}, "message": {...}}]}]}
        Для Instagram Meta надсилає той самий webhook з object="instagram".
        Визначаємо канал за полем object і маршрутизуємо на відповідний backend.
        """
        raw = request.httprequest.data
        if not raw:
            return self._json({"status": "error", "message": "Empty payload"})
        try:
            data = json.loads(raw)
        except ValueError:
            return self._json(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        # Instagram → object="instagram", Messenger → object="page"
        obj = data.get("object", "")
        service = "instagram" if obj == "instagram" else "messenger"
        backend = self._find_backend_by_service(service)
        if not backend:
            return self._json(
                {"status": "error", "message": "Not configured"}, status=404
            )

        # Meta надсилає масив entry; кожен entry має messaging[]
        entries = data.get("entry") or []
        for entry in entries:
            for messaging in entry.get("messaging") or []:
                sender = messaging.get("sender") or {}
                message = messaging.get("message") or {}
                if not message:
                    continue
                provider_user_id = str(sender.get("id", ""))
                provider_message_id = str(message.get("mid", ""))
                text = message.get("text") or ""

                # Ідемпотентність
                Message = request.env["channel.message"].sudo()
                existing = Message.search(
                    [
                        ("provider_message_id", "=", provider_message_id),
                        ("service", "=", service),
                        ("direction", "=", "incoming"),
                    ],
                    limit=1,
                )
                if existing:
                    continue

                own_contact_id = f"own:{service}:{provider_user_id}"
                normalized = {
                    "service": service,
                    "contact": {
                        "id": own_contact_id,
                        "name": f"{service.upper()}:{provider_user_id}",
                        "email": "",
                        "phone": "",
                        "last_message": text,
                        "last_message_data": {"message": {"type": "text"}},
                        "variables": {},
                    },
                    "bot": {"id": backend.bot_id or "", "name": backend.name},
                    "title": "incoming_message",
                    "date": int(message.get("timestamp", 0)),
                }

                Message.create(
                    {
                        "backend_id": backend.id,
                        "service": service,
                        "direction": "incoming",
                        "state": "received",
                        "provider_message_id": provider_message_id,
                        "provider_user_id": provider_user_id,
                        "text_message": text,
                        "raw_json": json.dumps(data, ensure_ascii=False),
                    }
                )

                try:
                    with request.env.cr.savepoint():
                        request.env[
                            "channel.conversation"
                        ].sudo()._process_incoming_event(
                            data=normalized,
                            contact=normalized["contact"],
                            bot=normalized["bot"],
                            service=service,
                            event_type="incoming_message",
                            timestamp_ms=normalized["date"],
                        )
                except Exception as e:
                    _logger.error(
                        "Channel Bridge: %s processing failed — %s",
                        service,
                        e,
                        exc_info=True,
                    )
                    return self._json(
                        {"status": "error", "message": "Processing failed"}, status=500
                    )

        return self._json({"status": "ok"})

    def _process_incoming(
        self,
        backend,
        service,
        provider_message_id,
        provider_user_id,
        text,
        raw_data,
        timestamp_ms=0,
    ):
        """
        Спільний helper: ідемпотентність + журнал + виклик _process_incoming_event.
        Повертає (ok: bool, error: str|None).
        """
        Message = request.env["channel.message"].sudo()
        existing = Message.search(
            [
                ("provider_message_id", "=", provider_message_id),
                ("service", "=", service),
                ("direction", "=", "incoming"),
            ],
            limit=1,
        )
        if existing:
            _logger.info(
                "Channel Bridge: duplicate %s update %s, skipping",
                service,
                provider_message_id,
            )
            return True, None

        own_contact_id = f"own:{service}:{provider_user_id}"
        normalized = {
            "service": service,
            "contact": {
                "id": own_contact_id,
                "name": f"{service.upper()}:{provider_user_id}",
                "email": "",
                "phone": "",
                "last_message": text,
                "last_message_data": {"message": {"type": "text"}},
                "variables": {},
            },
            "bot": {"id": backend.bot_id or "", "name": backend.name},
            "title": "incoming_message",
            "date": timestamp_ms,
        }

        Message.create(
            {
                "backend_id": backend.id,
                "service": service,
                "direction": "incoming",
                "state": "received",
                "provider_message_id": provider_message_id,
                "provider_user_id": provider_user_id,
                "text_message": text,
                "raw_json": json.dumps(raw_data, ensure_ascii=False),
            }
        )

        try:
            with request.env.cr.savepoint():
                request.env["channel.conversation"].sudo()._process_incoming_event(
                    data=normalized,
                    contact=normalized["contact"],
                    bot=normalized["bot"],
                    service=service,
                    event_type="incoming_message",
                    timestamp_ms=timestamp_ms,
                )
        except Exception as e:
            _logger.error(
                "Channel Bridge: %s processing failed — %s", service, e, exc_info=True
            )
            return False, str(e)
        return True, None

    @http.route(
        "/bridge/viber/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def viber_webhook(self):
        """Viber webhook. Payload: {"event": "message", "sender": {...}, "message": {...}}"""
        backend = self._find_backend_by_service("viber")
        if not backend:
            return self._json(
                {"status": "error", "message": "Not configured"}, status=404
            )
        raw = request.httprequest.data
        if not raw:
            return self._json({"status": "error", "message": "Empty payload"})
        try:
            data = json.loads(raw)
        except ValueError:
            return self._json(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        event = data.get("event", "")
        if event != "message":
            # subscribed/unsubscribed/delivered/seen — ігноруємо, але 200
            return self._json({"status": "ok"})

        sender = data.get("sender") or {}
        message = data.get("message") or {}
        provider_user_id = str(sender.get("id", ""))
        provider_message_id = str(message.get("token", ""))
        text = message.get("text", "") or ""
        timestamp_ms = int(data.get("timestamp", 0)) * 1000

        ok, err = self._process_incoming(
            backend,
            "viber",
            provider_message_id,
            provider_user_id,
            text,
            data,
            timestamp_ms,
        )
        if not ok:
            return self._json({"status": "error", "message": err}, status=500)
        return self._json({"status": "ok"})

    @http.route(
        "/bridge/whatsapp/webhook",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def whatsapp_webhook(self):
        """WhatsApp Cloud API webhook. GET = verify (hub.challenge), POST = події."""
        if request.httprequest.method == "GET":
            verify_token = request.params.get("hub.verify_token", "")
            challenge = request.params.get("hub.challenge", "")
            backend = self._find_backend_by_service("whatsapp")
            if not backend or not backend.webhook_secret:
                return self._json(
                    {"status": "error", "message": "Not configured"}, status=404
                )
            if verify_token != backend.webhook_secret:
                return self._json(
                    {"status": "error", "message": "Unauthorized"}, status=401
                )
            return Response(challenge, content_type="text/plain")

        backend = self._find_backend_by_service("whatsapp")
        if not backend:
            return self._json(
                {"status": "error", "message": "Not configured"}, status=404
            )
        raw = request.httprequest.data
        if not raw:
            return self._json({"status": "error", "message": "Empty payload"})
        try:
            data = json.loads(raw)
        except ValueError:
            return self._json(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        for entry in data.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                for contact_msg in value.get("messages") or []:
                    provider_user_id = str(contact_msg.get("from", ""))
                    provider_message_id = str(contact_msg.get("id", ""))
                    text = ""
                    if contact_msg.get("type") == "text":
                        text = (contact_msg.get("text") or {}).get("body", "") or ""
                    ok, err = self._process_incoming(
                        backend,
                        "whatsapp",
                        provider_message_id,
                        provider_user_id,
                        text,
                        data,
                    )
                    if not ok:
                        return self._json(
                            {"status": "error", "message": err}, status=500
                        )
        return self._json({"status": "ok"})

    @http.route(
        "/bridge/tiktok/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def tiktok_webhook(self):
        """TikTok webhook. Payload: {"event": "im.message.receive", "sender": {...}, "content": {...}}"""
        backend = self._find_backend_by_service("tiktok")
        if not backend:
            return self._json(
                {"status": "error", "message": "Not configured"}, status=404
            )
        raw = request.httprequest.data
        if not raw:
            return self._json({"status": "error", "message": "Empty payload"})
        try:
            data = json.loads(raw)
        except ValueError:
            return self._json(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        event = data.get("event", "")
        if event != "im.message.receive":
            return self._json({"status": "ok"})
        sender = data.get("sender") or {}
        content = data.get("content") or {}
        provider_user_id = str(sender.get("open_id", ""))
        provider_message_id = str(data.get("msg_id", ""))
        text = content.get("text", "") or ""
        ok, err = self._process_incoming(
            backend, "tiktok", provider_message_id, provider_user_id, text, data
        )
        if not ok:
            return self._json({"status": "error", "message": err}, status=500)
        return self._json({"status": "ok"})

    @http.route(
        "/bridge/livechat/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def livechat_webhook(self):
        """LiveChat webhook. Payload: {"event": "incoming_event", "chat": {...}, "event": {...}}"""
        backend = self._find_backend_by_service("livechat")
        if not backend:
            return self._json(
                {"status": "error", "message": "Not configured"}, status=404
            )
        raw = request.httprequest.data
        if not raw:
            return self._json({"status": "error", "message": "Empty payload"})
        try:
            data = json.loads(raw)
        except ValueError:
            return self._json(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        event = data.get("event", "")
        if event != "incoming_event":
            return self._json({"status": "ok"})
        chat = data.get("chat") or {}
        evt = data.get("event") or {}
        provider_user_id = str(chat.get("id", ""))
        provider_message_id = str(evt.get("id", ""))
        text = (evt.get("text") or {}).get("value", "") or ""
        ok, err = self._process_incoming(
            backend, "livechat", provider_message_id, provider_user_id, text, data
        )
        if not ok:
            return self._json({"status": "error", "message": err}, status=500)
        return self._json({"status": "ok"})
