# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class ChatwootWebhook(http.Controller):

    @http.route('/chatwoot/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def handle_webhook(self, **post):
        """
        Endpoint to receive events from Chatwoot.
        URL: /chatwoot/webhook
        """
        try:
            data = request.jsonrequest
            event_type = data.get('event')

            _logger.info(f"⚡ Chatwoot Event Received: {event_type}")

            if event_type == 'conversation_created':
                _logger.info(f"New Conversation: ID {data.get('id')}")
            
            elif event_type == 'message_created':
                 content = data.get('content', '')
                 _logger.info(f"Message content: {content}")

            return {'status': 'success'}
            
        except Exception as e:
            _logger.error(f"Chatwoot Webhook Error: {str(e)}")
            return {'status': 'error', 'message': str(e)}
