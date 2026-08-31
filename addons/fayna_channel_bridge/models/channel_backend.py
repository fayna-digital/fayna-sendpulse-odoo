import json
import logging
import random
import re
import secrets
from datetime import timedelta

import requests
from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Список каналів власного прямого транспорту.
SERVICE_SELECTION = [
    ('telegram', 'Telegram'),
    ('instagram', 'Instagram'),
    ('facebook', 'Facebook'),
    ('messenger', 'Messenger'),
    ('viber', 'Viber'),
    ('whatsapp', 'WhatsApp'),
    ('tiktok', 'TikTok'),
    ('livechat', 'LiveChat'),
]

PROVIDER_SELECTION = [
    ('direct', 'Direct (own transport)'),
]

TRANSPORT_PRIORITY_SELECTION = [
    ('own', 'Own'),
    ('auto', 'Auto (fallback)'),
]


class ChannelBackend(models.Model):
    """
    Модель "підключений канал" — одна на канал + провайдер.

    Аналог whatsapp.backend з референсу. Зберігає credentials провайдера,
    webhook secret, операторів каналу і транспортний пріоритет.
    """

    _name = 'channel.backend'
    _description = 'Channel Backend (own transport)'
    _order = 'name asc'

    def init(self):
        """
        Partial unique index: (service, provider, bot_id) мають бути унікальними
        у межах активних записів. Дозволяє кілька backend-ів одного каналу
        (напр. два Telegram-боти), але не дублює однаковий (service, provider, bot_id).
        """
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS channel_backend_active_service_provider_uniq
            ON channel_backend (service, provider, COALESCE(bot_id, ''))
            WHERE active = true
        """)

    _sql_constraints = [
        (
            'channel_backend_webhook_path_id_uniq',
            'UNIQUE (webhook_path_id)',
            'Webhook Path ID must be unique.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """Заповнює webhook_path_id для нових записів, якщо його не передали."""
        for vals in vals_list:
            if not vals.get('webhook_path_id'):
                vals['webhook_path_id'] = secrets.token_urlsafe(24)
        return super().create(vals_list)

    # ── Основні поля ────────────────────────────────────────────────────
    name = fields.Char(string='Name', required=True, index=True)
    service = fields.Selection(
        SERVICE_SELECTION,
        string='Channel',
        required=True,
        index=True,
        help='Channel of the direct own transport',
    )
    provider = fields.Selection(
        PROVIDER_SELECTION,
        string='Provider',
        default='direct',
        required=True,
        help='direct = own transport',
    )
    transport_priority = fields.Selection(
        TRANSPORT_PRIORITY_SELECTION,
        string='Transport priority',
        default='auto',
        required=True,
        help='own = own transport, auto = fallback',
    )
    active = fields.Boolean(string='Enabled', default=True, index=True)

    # ── Безпека ─────────────────────────────────────────────────────────
    webhook_secret = fields.Char(
        string='Webhook Secret',
        groups='fayna_channel_bridge.group_channel_bridge_admin',
        help='Webhook signing secret (for Meta X-Hub-Signature-256, Viber Auth-Token)',
    )
    credentials = fields.Text(
        string='Credentials (JSON)',
        groups='fayna_channel_bridge.group_channel_bridge_admin',
        help='JSON with provider tokens/keys. Stored in plain text (administrators only).',
    )

    # ── Telegram ────────────────────────────────────────────────────────
    bot_token = fields.Char(
        string='Bot Token',
        groups='fayna_channel_bridge.group_channel_bridge_admin',
        help='Telegram Bot Token (api.telegram.org/bot<TOKEN>). Stored in plain text '
        '(administrators only).',
    )
    bot_id = fields.Char(
        string='Bot ID',
        help='Telegram bot username (e.g. @CampScoutBot)',
    )
    heal_url = fields.Char(
        string='Webhook URL',
        help='URL for setWebhook (Telegram) / subscribe (Meta)',
    )
    webhook_path_id = fields.Char(
        string='Webhook Path ID',
        index=True,
        groups='fayna_channel_bridge.group_channel_bridge_admin',
        help='Unique identifier of the Telegram webhook path '
        '(generated automatically, does not contain the bot token).',
    )

    # ── Оператори ───────────────────────────────────────────────────────
    user_ids = fields.Many2many(
        'res.users',
        string='Operators',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Operators of this channel',
    )

    # ── Обмеження контактів (опц.) ──────────────────────────────────────
    partner_domain = fields.Char(
        string='Contact restriction (domain)',
        help='Optional restriction: accept messages only from contacts with this email domain.',
    )

    # ── Метрики ─────────────────────────────────────────────────────────
    last_healthcheck_at = fields.Datetime(string='Last check')
    last_healthcheck_ok = fields.Boolean(string='Last check OK')
    last_error = fields.Char(string='Last error')

    # ── Стан (Е-1) ─────────────────────────────────────────────────────
    # Обчислюване нестворене поле-індикатор. Зводить два булеві (active,
    # last_healthcheck_ok) в одне зрозуміле слово для list-view. store=False,
    # тому за ним не можна сортувати/шукати — це прийнятно для колонки-індикатора.
    STATE_SELECTION = [
        ('off', 'Disabled'),
        ('ok', 'Working'),
        ('not_implemented', 'Check not supported'),
        ('error', 'Error'),
    ]
    state = fields.Selection(
        STATE_SELECTION,
        string='Status',
        compute='_compute_state',
        store=False,
        help='Aggregated channel status: disabled / working / check not supported / error',
    )

    @api.depends('active', 'last_healthcheck_ok', 'last_error')
    def _compute_state(self):
        """Зводить active + last_healthcheck_ok + last_error в один стан."""
        for backend in self:
            if not backend.active:
                backend.state = 'off'
            elif backend.last_healthcheck_ok:
                backend.state = 'ok'
            elif backend.last_error == self._HEALTHCHECK_NOT_IMPLEMENTED:
                backend.state = 'not_implemented'
            else:
                backend.state = 'error'

    # ════════════════════════════════════════════════════════════════════
    # Credentials helpers
    # ════════════════════════════════════════════════════════════════════

    def _get_credentials(self):
        """Повертає dict з credentials (JSON)."""
        self.ensure_one()
        if not self.credentials:
            return {}
        try:
            return json.loads(self.credentials)
        except (ValueError, TypeError):
            _logger.warning('ChannelBackend %s: invalid credentials JSON', self.id)
            return {}

    def _set_credentials(self, data):
        """Зберігає dict у credentials (JSON)."""
        self.ensure_one()
        self.write({'credentials': json.dumps(data, ensure_ascii=False)})

    def _get_telegram_token(self):
        """Повертає Telegram bot token: з поля bot_token або з credentials."""
        self.ensure_one()
        if self.bot_token:
            return self.bot_token
        return self._get_credentials().get('bot_token', '')

    def _mask_secrets(self, text):
        """Маскує секрети в довільному рядку (логи, last_error, тексти винятків).

        Ховає значення bot_token, webhook_secret і будь-яку послідовність
        після '/bot' у URL. Порожні/відсутні значення обробляє без падіння.
        Секрети читає через sudo(), бо поля обмежені групою адміністраторів,
        а хелпер викликається з обробників винятків і не має права падати.
        """
        if not text:
            return text
        masked = str(text)
        # Секрети обмежені групою адміністраторів, а хелпер викликається
        # з обробників винятків і не має права падати через брак прав.
        safe = self.sudo()
        secrets = [safe.bot_token, safe.webhook_secret]
        for secret in secrets:
            if secret:
                masked = masked.replace(secret, '***')
        # Telegram URL: .../bot<TOKEN>/... — ховаємо все після '/bot'
        masked = re.sub(r'/bot[A-Za-z0-9:_-]+', '/bot***', masked)
        return masked

    # ════════════════════════════════════════════════════════════════════
    # Telegram — відправка (прямий транспорт)
    # ════════════════════════════════════════════════════════════════════

    _TELEGRAM_API = 'https://api.telegram.org'
    _TELEGRAM_API_TIMEOUT = 15
    _TELEGRAM_TEXT_LIMIT = 4096

    def send_message(self, text, attachment_url=None, provider_user_id=None):
        """
        Надсилає повідомлення через власний транспорт.
        Маршрутизує за service:
          telegram → Bot API, messenger/instagram/facebook → Meta Graph API,
          viber → Viber REST API, whatsapp → WhatsApp Cloud API,
          tiktok → TikTok API, livechat → LiveChat REST API.
        Повертає (success: bool, provider_message_id: str|None, error: str|None).
        """
        self.ensure_one()
        if not provider_user_id:
            return False, None, 'provider_user_id is missing'

        if self.service in ('messenger', 'instagram', 'facebook'):
            return self._meta_send_single(text, attachment_url, provider_user_id)
        if self.service == 'viber':
            return self._viber_send_single(text, attachment_url, provider_user_id)
        if self.service == 'whatsapp':
            return self._whatsapp_send_single(text, attachment_url, provider_user_id)
        if self.service == 'tiktok':
            return self._tiktok_send_single(text, attachment_url, provider_user_id)
        if self.service == 'livechat':
            return self._livechat_send_single(text, attachment_url, provider_user_id)

        # Telegram (за замовчуванням)
        token = self._get_telegram_token()
        if not token:
            return False, None, 'Telegram bot token is not configured'

        # Auto-split за лімитом 4096 (перевикористовуємо _split_text_by_limit)
        if text and len(text) > self._TELEGRAM_TEXT_LIMIT:
            chunks = self._split_text_by_limit(text, self._TELEGRAM_TEXT_LIMIT)
            total = len(chunks)
            all_ok = True
            last_msg_id = None
            for i, chunk in enumerate(chunks, 1):
                prefix = f'({i}/{total}) ' if total > 1 else ''
                piece = prefix + chunk
                att = attachment_url if i == 1 else None
                ok, msg_id, last_err = self._telegram_send_single(piece, att, provider_user_id)
                if not ok:
                    all_ok = False
                    _logger.warning(
                        'Channel Bridge: chunk %d/%d failed for %s — %s',
                        i,
                        total,
                        provider_user_id,
                        last_err,
                    )
                    break
                last_msg_id = msg_id
            return all_ok, last_msg_id, None if all_ok else 'chunk send failed'

        return self._telegram_send_single(text, attachment_url, provider_user_id)

    # ════════════════════════════════════════════════════════════════════
    # Meta (Messenger / Instagram) — відправка через Graph API
    # ════════════════════════════════════════════════════════════════════

    _META_API = 'https://graph.facebook.com/v25.0'
    _META_API_TIMEOUT = 15

    def _get_meta_token(self):
        """
        Повертає Page Access Token для Meta з credentials цього backend-а.
        """
        self.ensure_one()
        return self._get_credentials().get('access_token', '') or ''

    def _meta_send_single(self, text, attachment_url, provider_user_id):
        """
        Надсилає повідомлення через Meta Graph API.
        Messenger: POST /{page_id}/messages (recipient.id + message.text)
        Instagram: POST /{ig_id}/messages (recipient.id + message.text)
        """
        token = self._get_meta_token()
        if not token:
            return False, None, 'Meta Page Access Token is not configured'

        creds = self._get_credentials()
        # Для Instagram потрібен ig_business_id, для Messenger — page_id
        if self.service == 'instagram':
            ig_id = creds.get('ig_business_id', '') or ''
            if not ig_id:
                return False, None, 'Instagram Business Account ID is not configured'
            endpoint = f'{self._META_API}/{ig_id}/messages'
        else:
            page_id = creds.get('page_id', '') or ''
            if not page_id:
                return False, None, 'Facebook Page ID is not configured'
            endpoint = f'{self._META_API}/{page_id}/messages'

        payload = {
            'recipient': {'id': provider_user_id},
            'message': {'text': text},
            'access_token': token,
        }
        if attachment_url:
            payload['message'] = {
                'attachment': {'type': 'image', 'payload': {'url': attachment_url}}
            }

        try:
            resp = requests.post(endpoint, json=payload, timeout=self._META_API_TIMEOUT)
            _logger.info(
                'Channel Bridge: Meta send status=%s body=%s',
                resp.status_code,
                self._mask_secrets(resp.text[:200]),
            )
            if resp.status_code != 200:
                return False, None, self._mask_secrets(resp.text[:200])
            data = resp.json()
            msg_id = data.get('message_id')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: Meta send exception — %s', self._mask_secrets(e))
            return False, None, self._mask_secrets(str(e))

    # ════════════════════════════════════════════════════════════════════
    # Viber — відправка через Viber REST API
    # ════════════════════════════════════════════════════════════════════

    _VIBER_API = 'https://chatapi.viber.com'
    _VIBER_API_TIMEOUT = 15

    def _get_viber_token(self):
        """Повертає Viber Auth-Token (з credentials або поля)."""
        self.ensure_one()
        return self._get_credentials().get('auth_token', '') or ''

    def _viber_send_single(self, text, attachment_url, provider_user_id):
        """Надсилає повідомлення через Viber REST API (send_message)."""
        token = self._get_viber_token()
        if not token:
            return False, None, 'Viber Auth-Token is not configured'
        payload = {
            'auth_token': token,
            'receiver': provider_user_id,
            'type': 'text',
            'text': text,
        }
        if attachment_url:
            payload = {
                'auth_token': token,
                'receiver': provider_user_id,
                'type': 'picture',
                'text': text or '',
                'media': attachment_url,
            }
        try:
            resp = requests.post(
                f'{self._VIBER_API}/pa/send_message',
                json=payload,
                timeout=self._VIBER_API_TIMEOUT,
            )
            _logger.info(
                'Channel Bridge: Viber send status=%s body=%s',
                resp.status_code,
                self._mask_secrets(resp.text[:200]),
            )
            if resp.status_code != 200:
                return False, None, self._mask_secrets(resp.text[:200])
            data = resp.json()
            if data.get('status') != 0:
                return False, None, data.get('status_message', 'Viber API error')
            msg_id = data.get('message_token')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: Viber send exception — %s', self._mask_secrets(e))
            return False, None, self._mask_secrets(str(e))

    # ════════════════════════════════════════════════════════════════════
    # WhatsApp Cloud API — відправка через Meta Graph API
    # ════════════════════════════════════════════════════════════════════

    _WHATSAPP_API_TIMEOUT = 15

    def _get_whatsapp_credentials(self):
        """Повертає (phone_number_id, token) для WhatsApp Cloud API."""
        self.ensure_one()
        creds = self._get_credentials()
        phone_number_id = creds.get('phone_number_id', '')
        token = creds.get('token', '') or self._get_meta_token()
        return phone_number_id, token

    def _whatsapp_send_single(self, text, attachment_url, provider_user_id):
        """Надсилає повідомлення через WhatsApp Business Cloud API."""
        phone_number_id, token = self._get_whatsapp_credentials()
        if not phone_number_id:
            return False, None, 'WhatsApp phone_number_id is not configured'
        if not token:
            return False, None, 'WhatsApp token is not configured'
        endpoint = f'{self._META_API}/{phone_number_id}/messages'
        payload = {
            'messaging_product': 'whatsapp',
            'to': provider_user_id,
            'type': 'text',
            'text': {'body': text},
        }
        if attachment_url:
            payload = {
                'messaging_product': 'whatsapp',
                'to': provider_user_id,
                'type': 'image',
                'image': {'link': attachment_url},
            }
        headers = {'Authorization': f'Bearer {token}'}
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self._WHATSAPP_API_TIMEOUT,
            )
            _logger.info(
                'Channel Bridge: WhatsApp send status=%s body=%s',
                resp.status_code,
                self._mask_secrets(resp.text[:200]),
            )
            if resp.status_code != 200:
                return False, None, self._mask_secrets(resp.text[:200])
            data = resp.json()
            msg_id = (data.get('messages') or [{}])[0].get('id')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: WhatsApp send exception — %s', self._mask_secrets(e))
            return False, None, self._mask_secrets(str(e))

    # ════════════════════════════════════════════════════════════════════
    # TikTok — відправка (найнижчий пріоритет)
    # ════════════════════════════════════════════════════════════════════

    _TIKTOK_API = 'https://open.tiktokapis.com'
    _TIKTOK_API_TIMEOUT = 15

    def _get_tiktok_credentials(self):
        """Повертає (access_token, open_api) для TikTok."""
        self.ensure_one()
        creds = self._get_credentials()
        return creds.get('access_token', ''), creds.get('open_api', '')

    def _tiktok_send_single(self, text, attachment_url, provider_user_id):
        """Надсилає повідомлення через TikTok Business API (v1.3)."""
        access_token, open_api = self._get_tiktok_credentials()
        if not access_token:
            return False, None, 'TikTok access_token is not configured'
        endpoint = f'{self._TIKTOK_API}/v1.3/im/message/send/'
        payload = {
            'open_id': provider_user_id,
            'content': {'text': text},
        }
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self._TIKTOK_API_TIMEOUT,
            )
            _logger.info(
                'Channel Bridge: TikTok send status=%s body=%s',
                resp.status_code,
                self._mask_secrets(resp.text[:200]),
            )
            if resp.status_code != 200:
                return False, None, self._mask_secrets(resp.text[:200])
            data = resp.json()
            msg_id = data.get('data', {}).get('message_id')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: TikTok send exception — %s', self._mask_secrets(e))
            return False, None, self._mask_secrets(str(e))

    # ════════════════════════════════════════════════════════════════════
    # LiveChat — відправка через LiveChat REST API
    # ════════════════════════════════════════════════════════════════════

    _LIVECHAT_API = 'https://api.livechatinc.com/v3.3'
    _LIVECHAT_API_TIMEOUT = 15

    def _get_livechat_credentials(self):
        """Повертає (token, chat_id) для LiveChat."""
        self.ensure_one()
        creds = self._get_credentials()
        return creds.get('token', ''), creds.get('chat_id', '')

    def _livechat_send_single(self, text, attachment_url, provider_user_id):
        """Надсилає повідомлення через LiveChat REST API (send_event)."""
        token, chat_id = self._get_livechat_credentials()
        if not token:
            return False, None, 'LiveChat token is not configured'
        if not chat_id:
            return False, None, 'LiveChat chat_id is not configured'
        endpoint = f'{self._LIVECHAT_API}/agent/action/send_event'
        payload = {
            'chat_id': chat_id,
            'event': {'type': 'message', 'text': {'type': 'text', 'value': text}},
        }
        headers = {'Authorization': f'Bearer {token}'}
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self._LIVECHAT_API_TIMEOUT,
            )
            _logger.info(
                'Channel Bridge: LiveChat send status=%s body=%s',
                resp.status_code,
                self._mask_secrets(resp.text[:200]),
            )
            if resp.status_code != 200:
                return False, None, self._mask_secrets(resp.text[:200])
            data = resp.json()
            event_id = data.get('event_id')
            return True, str(event_id) if event_id else None, None
        except Exception as e:
            _logger.error(
                'Channel Bridge: LiveChat send exception — %s',
                self._mask_secrets(e),
            )
            return False, None, self._mask_secrets(str(e))

    def _telegram_send_single(self, text, attachment_url, provider_user_id):
        """Low-level Telegram sendMessage/sendPhoto/sendDocument."""
        token = self._get_telegram_token()
        base = f'{self._TELEGRAM_API}/bot{token}'
        try:
            if attachment_url:
                # Фото/документ: надсилаємо як photo (або document для не-зображень)
                if self._looks_like_image(attachment_url):
                    endpoint = f'{base}/sendPhoto'
                    payload = {'chat_id': provider_user_id, 'photo': attachment_url}
                else:
                    endpoint = f'{base}/sendDocument'
                    payload = {'chat_id': provider_user_id, 'document': attachment_url}
                if text:
                    payload['caption'] = text
            else:
                endpoint = f'{base}/sendMessage'
                payload = {'chat_id': provider_user_id, 'text': text}

            resp = requests.post(endpoint, json=payload, timeout=self._TELEGRAM_API_TIMEOUT)
            _logger.info(
                'Channel Bridge: TG send status=%s body=%s',
                resp.status_code,
                self._mask_secrets(resp.text[:200]),
            )
            if resp.status_code != 200:
                return False, None, self._mask_secrets(resp.text[:200])
            data = resp.json()
            ok = data.get('ok', False)
            if not ok:
                return (
                    False,
                    None,
                    self._mask_secrets(data.get('description', 'Telegram API error')),
                )
            msg = (data.get('result') or {}).get('message_id')
            return True, str(msg) if msg else None, None
        except Exception as e:
            _logger.error(
                'Channel Bridge: Telegram send exception — %s',
                self._mask_secrets(e),
            )
            return False, None, self._mask_secrets(str(e))

    @staticmethod
    def _looks_like_image(url):
        """Примитивна евристика: чи URL вказує на зображення."""
        if not url:
            return False
        lower = url.lower().split('?')[0]
        return lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))

    @staticmethod
    def _split_text_by_limit(text, max_chars):
        """Розбиває текст на частини не довші за max_chars."""
        if not text or len(text) <= max_chars:
            return [text] if text else []

        effective_max = max_chars - 20

        def flush(acc, chunks):
            if acc.strip():
                chunks.append(acc.strip())

        chunks = []
        current = ''
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if not para.strip():
                continue
            candidate = (current + '\n\n' + para) if current else para
            if len(candidate) <= effective_max:
                current = candidate
                continue
            flush(current, chunks)
            current = ''
            if len(para) <= effective_max:
                current = para
                continue
            import re as _re

            sentences = _re.split(r'(?<=[.!?…])\s+', para)
            buf = ''
            for sent in sentences:
                cand2 = (buf + ' ' + sent) if buf else sent
                if len(cand2) <= effective_max:
                    buf = cand2
                    continue
                flush(buf, chunks)
                buf = ''
                if len(sent) <= effective_max:
                    buf = sent
                    continue
                words = sent.split(' ')
                wbuf = ''
                for w in words:
                    cand3 = (wbuf + ' ' + w) if wbuf else w
                    if len(cand3) <= effective_max:
                        wbuf = cand3
                    else:
                        flush(wbuf, chunks)
                        while len(w) > effective_max:
                            chunks.append(w[:effective_max])
                            w = w[effective_max:]
                        wbuf = w
                if wbuf:
                    buf = wbuf
            if buf:
                current = buf

        flush(current, chunks)
        return chunks

    # ════════════════════════════════════════════════════════════════════
    # Telegram — webhook registration (setWebhook)
    # ════════════════════════════════════════════════════════════════════

    def register_telegram_webhook(self):
        """
        Реєструє webhook для Telegram бота:
        setWebhook(https://<odoo>/bridge/telegram/webhook/<webhook_path_id>).
        Повертає (ok, error).
        """
        self.ensure_one()
        token = self._get_telegram_token()
        if not token:
            return False, 'Telegram bot token is not configured'
        # Системний параметр web.base.url доступний лише з правами адміністратора.
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        if not base_url:
            return False, 'web.base.url is not configured'
        if not self.webhook_secret:
            self.webhook_secret = secrets.token_urlsafe(32)
        if not self.webhook_path_id:
            self.webhook_path_id = secrets.token_urlsafe(24)
        webhook_url = f'{base_url}/bridge/telegram/webhook/{self.webhook_path_id}'
        try:
            resp = requests.post(
                f'{self._TELEGRAM_API}/bot{token}/setWebhook',
                json={'url': webhook_url, 'secret_token': self.webhook_secret},
                timeout=self._TELEGRAM_API_TIMEOUT,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get('ok'):
                self.write({'heal_url': webhook_url, 'last_healthcheck_ok': True})
                _logger.info(
                    'Channel Bridge: Telegram webhook registered for backend %s',
                    self.id,
                )
                return webhook_url, None
            return False, self._mask_secrets(data.get('description', resp.text[:200]))
        except Exception as e:
            _logger.error(
                'Channel Bridge: setWebhook exception — %s',
                self._mask_secrets(e),
            )
            return False, self._mask_secrets(str(e))

    # ════════════════════════════════════════════════════════════════════
    # Cron
    # ════════════════════════════════════════════════════════════════════

    # Повідомлення для каналів, чия перевірка доступності ще не реалізована.
    # HC-02: не показуємо зелений статус, який не залежить від реальності.
    _HEALTHCHECK_NOT_IMPLEMENTED = 'Healthcheck for this channel is not implemented yet'

    # ── Політика повторів (RET-02, EB-01, EB-03) ────────────────────────
    # Постійні помилки провайдера — повторювати марно (клієнт заблокував бота,
    # чат не знайдено, невалідний токен). Декларативна мапа: ключ — підрядок
    # помилки (регістронезалежно), значення — людське пояснення. Додавання
    # нової причини = новий рядок, без правки логіки (як ERROR_REASON_MAP).
    PERMANENT_ERROR_MAP = [
        ('bot was blocked', 'The client blocked the bot'),
        ('forbidden: bot was blocked', 'The client blocked the bot'),
        ('chat not found', 'Chat not found'),
        ('user is deactivated', 'User is deactivated'),
        ('unauthorized', 'Invalid token'),
        ('invalid token', 'Invalid token'),
        ('not found', 'Chat or bot not found'),
    ]

    # Експоненційна затримка: база 15 хв (збігається з інтервалом крона),
    # множник 2^retry_count, кап 24 год, + випадковий jitter до 5 хв (EB-03).
    _RETRY_BASE_MINUTES = 15
    _RETRY_MAX_MINUTES = 24 * 60
    _RETRY_JITTER_MINUTES = 5
    _RETRY_MAX_ATTEMPTS = 5
    _RETRY_BATCH_LIMIT = 100

    @api.model
    def cron_bridge_healthcheck(self):
        """
        Кожні 60 хв. Перевіряє доступність власного транспорту.
        Для Telegram — пере-реєстрація setWebhook (ідемпотентно).
        Для решти каналів перевірки ще немає — пишемо нейтральний стан
        (не `ok`), щоб зелений індикатор не вводив в оману (HC-02).

        Ж-6: записи виконуємо батчами на recordset, а не на ітерацію.
        Мережеві виклики (setWebhook) лишаються по одному на backend —
        їх не можна батчити.
        """
        backends = self.search([('active', '=', True), ('provider', '=', 'direct')])
        now = fields.Datetime.now()

        # Не-Telegram канали: однаковий набір значень → один write на recordset.
        non_telegram = backends.filtered(lambda b: b.service != 'telegram')
        if non_telegram:
            non_telegram.write(
                {
                    'last_healthcheck_at': now,
                    'last_healthcheck_ok': False,
                    'last_error': self._HEALTHCHECK_NOT_IMPLEMENTED,
                }
            )

        # Telegram: setWebhook на кожен backend (мережа, не батчиться).
        # Результати збираємо й пишемо батчем після циклу.
        telegram = backends.filtered(lambda b: b.service == 'telegram')
        if telegram:
            ok_ids = []
            err_by_id = {}
            for backend in telegram:
                url, err = backend.register_telegram_webhook()
                if url:
                    ok_ids.append(backend.id)
                else:
                    err_by_id[backend.id] = err
            # Успішні: однакові значення → один write на recordset.
            if ok_ids:
                self.browse(ok_ids).write(
                    {
                        'last_healthcheck_at': now,
                        'last_healthcheck_ok': True,
                        'last_error': '',
                    }
                )
            # Невдалі: last_error різний на backend → пишемо по одному,
            # але поза циклом відправки.
            for bid, err in err_by_id.items():
                self.browse(bid).write(
                    {
                        'last_healthcheck_at': now,
                        'last_healthcheck_ok': False,
                        'last_error': err,
                    }
                )

    @staticmethod
    def _classify_error(error):
        """Повертає (is_permanent, reason) для помилки провайдера (RET-02).

        Постійні помилки (клієнт заблокував бота, чат не знайдено, невалідний
        токен) повторювати марно — їх позначаємо як постійні й не плануємо
        повтор. Мапа декларативна: додавання причини = новий рядок у
        `PERMANENT_ERROR_MAP`, без правки логіки.
        """
        if not error:
            return False, ''
        lowered = str(error).lower()
        for pattern, reason in ChannelBackend.PERMANENT_ERROR_MAP:
            if pattern in lowered:
                return True, reason
        return False, ''

    @staticmethod
    def _compute_next_retry_at(retry_count):
        """Обчислює час наступної спроби: експоненційна затримка + jitter.

        EB-01: затримка зростає як base * 2^retry_count (15, 30, 60, 120 хв…),
        з капом 24 год. EB-03: додаємо випадковий jitter до 5 хв, щоб уникнути
        thundering herd при масовому збої.
        """
        delay_min = ChannelBackend._RETRY_BASE_MINUTES * (2**retry_count)
        delay_min = min(delay_min, ChannelBackend._RETRY_MAX_MINUTES)
        jitter_min = random.uniform(0, ChannelBackend._RETRY_JITTER_MINUTES)
        return fields.Datetime.now() + timedelta(minutes=delay_min + jitter_min)

    @api.model
    def cron_bridge_retry(self):
        """
        Кожні 15 хви. Повтор відправки тих, що впали (channel.message state='failed').

        RET-02: постійні помилки (клієнт заблокував бота, чат не знайдено,
        невалідний токен) → `state='failed_permanent'`, повторів більше немає.
        Тимчасові (мережа, 5xx, 429) → плануємо наступну спробу з експоненційною
        затримкою + jitter (EB-01, EB-03) через `next_retry_at`.
        F-17: вибірку обмежуємо `limit`, щоб один прохід не тягнув усю чергу
        і крон не перекривався сам із собою.

        Ж-6: записи виконуємо батчами на recordset, а не на ітерацію.
        Мережеві виклики `send_message` лишаються по одному на повідомлення.
        Постійні помилки з однаковим набором значень пишемо одним write.
        """
        # Крон працює без контексту користувача; sudo() гарантує доступ
        # до журналу channel.message незалежно від прав.
        Message = self.env['channel.message'].sudo()
        now = fields.Datetime.now()
        failed = Message.search(
            [
                ('direction', '=', 'outgoing'),
                ('state', '=', 'failed'),
                ('retry_count', '<', self._RETRY_MAX_ATTEMPTS),
                '|',
                ('next_retry_at', '=', False),
                ('next_retry_at', '<=', now),
            ],
            limit=self._RETRY_BATCH_LIMIT,
        )

        # Збираємо результати відправки; write виконуємо батчами після циклу.
        sent = Message.browse()
        permanent = Message.browse()
        temporary = Message.browse()
        sent_provider = {}
        permanent_error = {}
        temporary_error = {}
        temporary_next = {}

        for msg in failed:
            backend = msg.backend_id
            if not backend or not backend.active:
                continue
            ok, provider_msg_id, err = backend.send_message(
                msg.text_message,
                attachment_url=msg.attachment_url,
                provider_user_id=msg.provider_user_id,
            )
            if ok:
                sent |= msg
                sent_provider[msg.id] = provider_msg_id
                continue
            is_permanent, reason = self._classify_error(err)
            if is_permanent:
                # Постійна помилка — повторювати марно (RET-02).
                permanent |= msg
                permanent_error[msg.id] = reason or err
            else:
                # Тимчасова помилка — плануємо наступну спробу з backoff.
                temporary |= msg
                temporary_error[msg.id] = err
                temporary_next[msg.id] = self._compute_next_retry_at(msg.retry_count)

        # Успішні: provider_message_id унікальний на повідомлення → пишемо
        # по одному, але поза циклом відправки.
        for msg in sent:
            msg.write(
                {
                    'state': 'sent',
                    'provider_message_id': sent_provider[msg.id],
                    'retry_count': msg.retry_count + 1,
                    'next_retry_at': False,
                    'last_error': '',
                }
            )

        # Постійні: групуємо за (retry_count+1, last_error) — однакові значення
        # пишемо одним write на recordset.
        permanent_groups = {}
        for msg in permanent:
            key = (msg.retry_count + 1, permanent_error[msg.id])
            permanent_groups.setdefault(key, Message.browse())
            permanent_groups[key] |= msg
        for (retry_count, reason), group in permanent_groups.items():
            group.write(
                {
                    'state': 'failed_permanent',
                    'retry_count': retry_count,
                    'last_error': reason,
                    'next_retry_at': False,
                }
            )

        # Тимчасові: next_retry_at унікальний (jitter) → пишемо по одному,
        # але поза циклом відправки.
        for msg in temporary:
            msg.write(
                {
                    'retry_count': msg.retry_count + 1,
                    'last_error': temporary_error[msg.id],
                    'next_retry_at': temporary_next[msg.id],
                }
            )

    @api.model
    def action_switch_all_to_own(self):
        """
        M4: примусово перемикає ВСІ активні канали на власний транспорт (own).
        Модуль повністю автономний — використовується лише власний транспорт.
        """
        switched = 0
        for backend in self.search([('active', '=', True)]):
            if backend.transport_priority != 'own':
                _logger.warning(
                    'Channel Bridge M4: перемикаємо backend=%s (service=%s) з %s на own',
                    backend.id,
                    backend.service,
                    backend.transport_priority,
                )
                backend.write({'transport_priority': 'own'})
                switched += 1
        _logger.info(
            'Channel Bridge M4: перемкнено %d backend-ів на own transport',
            switched,
        )
        return switched

    def action_retry_check(self):
        """
        UX-аудит (Н9): ручний повтор перевірки доступності каналу з форми.

        Викликає ту саму логіку, що й крон `cron_bridge_healthcheck`, але для
        одного backend-а, і одразу повертає користувачу зрозумілий результат.
        Для Telegram — пере-реєстрація setWebhook (ідемпотентно). Для решти
        каналів перевірки ще немає — пишемо нейтральний стан і пояснюємо.
        """
        self.ensure_one()
        now = fields.Datetime.now()
        if self.service == 'telegram':
            url, err = self.register_telegram_webhook()
            if url:
                self.write(
                    {
                        'last_healthcheck_at': now,
                        'last_healthcheck_ok': True,
                        'last_error': '',
                    }
                )
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Check passed'),
                        'message': _('The channel is working. The webhook was re-registered.'),
                        'type': 'success',
                        'sticky': False,
                    },
                }
            self.write(
                {
                    'last_healthcheck_at': now,
                    'last_healthcheck_ok': False,
                    'last_error': err,
                }
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Check failed'),
                    'message': err,
                    'type': 'danger',
                    'sticky': False,
                },
            }
        # Не-Telegram: перевірки ще немає — нейтральний стан (HC-02).
        self.write(
            {
                'last_healthcheck_at': now,
                'last_healthcheck_ok': False,
                'last_error': self._HEALTHCHECK_NOT_IMPLEMENTED,
            }
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Check not supported'),
                'message': _('Availability check for this channel is not implemented yet.'),
                'type': 'warning',
                'sticky': False,
            },
        }
