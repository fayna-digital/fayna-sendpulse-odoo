import logging

import requests
from odoo import api, models

_logger = logging.getLogger(__name__)


class SendpulseConnectTelegramNotify(models.Model):
    _inherit = 'sendpulse.connect'

    # ── Magic-number константи (аудит 19.07.2026, issue #8) ───────────────
    _TELEGRAM_MESSAGE_MAX_LEN = 4000  # ліміт довжини тексту Telegram Bot API
    _TELEGRAM_SEND_TIMEOUT = 10  # requests timeout(s) для sendMessage
    _TELEGRAM_ERROR_PREVIEW_LEN = 200  # обрізка resp.text у _logger.warning

    @api.model
    def _notify_telegram(self, text, silent=False):
        """
        Надсилає повідомлення у Telegram-групу менеджерів через Bot API.
        Конфіг: telegram_bot_token + telegram_chat_id + telegram_alerts_enabled.
        `silent=True` — без звукового сповіщення (для менш критичних алертів).
        Повертає True якщо надіслано успішно.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.telegram_alerts_enabled', 'False') != 'True':
            return False
        token = ICP.get_param('odoo_chatwoot_connector.telegram_bot_token', '')
        chat_id = ICP.get_param('odoo_chatwoot_connector.telegram_chat_id', '')
        if not (token and chat_id and text):
            return False
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': text[: self._TELEGRAM_MESSAGE_MAX_LEN],
                    'parse_mode': 'HTML',
                    'disable_notification': silent,
                    'disable_web_page_preview': True,
                },
                timeout=self._TELEGRAM_SEND_TIMEOUT,
            )
            if resp.status_code == 200:
                return True
            _logger.warning(
                'SendPulse Odoo: Telegram alert failed HTTP %d — %s',
                resp.status_code,
                resp.text[: self._TELEGRAM_ERROR_PREVIEW_LEN],
            )
            return False
        except Exception as e:
            _logger.warning('SendPulse Odoo: Telegram alert exception — %s', e)
            return False
