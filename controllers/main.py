# -*- coding: utf-8 -*-
import logging
import json

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Типи подій SendPulse webhook
EVENT_NEW_SUBSCRIBER = 'new_subscriber'
EVENT_INCOMING_MSG = 'incoming_message'
EVENT_OUTGOING_MSG = 'outbound_message'
EVENT_LIVE_CHAT = 'opened_live_chat'
EVENT_UNSUBSCRIBE = 'bot_unsubscribe'
EVENT_BLOCKED = 'bot_blocked'


class SendpulseWebhookController(http.Controller):

    @http.route(
        '/sendpulse/webhook',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def handle_webhook(self):
        """
        Головний webhook ендпоінт для SendPulse.

        SendPulse надсилає події:
        - new_subscriber        → перший контакт з ботом
        - incoming_message      → клієнт написав повідомлення
        - outbound_message      → бот відправив повідомлення
        - opened_live_chat      → клієнт ініціював live-чат
        - bot_unsubscribe       → клієнт відписався
        - bot_blocked           → клієнт заблокував бота

        Payload:
        {
          "service": "telegram"|"instagram"|"facebook"|"messenger"|"viber"|"whatsapp"|"livechat"|"tiktok",
          "title": "incoming_message",
          "bot": {"id": "uuid", "name": "BotName", "external_id": "..."},
          "contact": {
            "id": "uuid",
            "name": "Ім'я Клієнта",
            "email": "email@example.com",
            "phone": "+380...",
            "last_message": "Текст повідомлення",
            "photo": "url",
            "tags": [],
            "variables": {"username": "...", "profile_url": "..."}
          },
          "date": 1617401679000
        }
        """
        try:
            raw = request.httprequest.data
            if not raw:
                return {'status': 'error', 'message': 'Empty payload'}
            data = json.loads(raw)
            if not data:
                return {'status': 'error', 'message': 'Empty payload'}

            event_type = data.get('title', '')
            service = data.get('service', '')
            contact = data.get('contact', {}) or {}
            bot = data.get('bot', {}) or {}
            timestamp_ms = data.get('date', 0)

            _logger.info(
                'SendPulse Odo webhook: event=%s service=%s contact_id=%s',
                event_type, service, contact.get('id'),
            )

            # Зберігаємо сирі дані для відлагодження
            request.env['sendpulse.webhook.data'].sudo().create({
                'name': contact.get('name', 'Unknown'),
                'sendpulse_contact_id': contact.get('id', ''),
                'service': service,
                'event_type': event_type,
                'raw_data': json.dumps(data, ensure_ascii=False),
                'bot_id': bot.get('id', ''),
                'bot_name': bot.get('name', ''),
            })

            # Обробляємо події
            if event_type in (EVENT_NEW_SUBSCRIBER, EVENT_INCOMING_MSG, EVENT_LIVE_CHAT):
                request.env['sendpulse.connect'].sudo()._process_incoming_event(
                    data=data,
                    contact=contact,
                    bot=bot,
                    service=service,
                    event_type=event_type,
                    timestamp_ms=timestamp_ms,
                )

            elif event_type == EVENT_OUTGOING_MSG:
                # Вихідне повідомлення з SendPulse (може бути з мобільного додатку менеджера)
                # Зберігаємо з дедуплікацією — якщо вже є в Odoo (надіслано з Discuss) — пропускаємо
                request.env['sendpulse.connect'].sudo()._process_outgoing_event(
                    contact=contact,
                    service=service,
                    timestamp_ms=timestamp_ms,
                )

            elif event_type == EVENT_UNSUBSCRIBE:
                request.env['sendpulse.connect'].sudo()._process_unsubscribe(
                    contact_id=contact.get('id', ''),
                    service=service,
                )

            return {'status': 'ok'}

        except Exception as e:
            _logger.error('SendPulse Odo webhook error: %s', e, exc_info=True)
            return {'status': 'error', 'message': str(e)}
