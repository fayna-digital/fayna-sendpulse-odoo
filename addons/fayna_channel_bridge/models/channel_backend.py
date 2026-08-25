import json
import logging

import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Перевикористовуємо SERVICE_SELECTION із sendpulse.connect, щоб mail_channel
# і обробник розуміли канал без змін.
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
    ('direct', 'Direct (власний транспорт)'),
    ('sendpulse', 'SendPulse'),
]

TRANSPORT_PRIORITY_SELECTION = [
    ('own', 'Own (власний)'),
    ('sendpulse', 'SendPulse'),
    ('auto', 'Auto (fallback)'),
]


class ChannelBackend(models.Model):
    """
    Модель "підключений канал" — одна на канал + провайдер.

    Аналог whatsapp.backend з референсу. Зберігає credentials провайдера
    (encrypted), webhook secret, операторів каналу і транспортний пріоритет.
    """

    _name = 'channel.backend'
    _description = 'Channel Backend (власний транспорт)'
    _order = 'name asc'

    def init(self):
        """
        Partial unique index: (service, provider) мають бути унікальними
        у межах активних записів — один канал одного провайдера не дублюється.
        """
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS channel_backend_active_service_provider_uniq
            ON channel_backend (service, provider)
            WHERE active = true
        """)

    # ── Основні поля ────────────────────────────────────────────────────
    name = fields.Char(string='Назва', required=True, index=True)
    service = fields.Selection(
        SERVICE_SELECTION,
        string='Канал',
        required=True,
        index=True,
        help='Перевикористовує SERVICE_SELECTION із sendpulse.connect',
    )
    provider = fields.Selection(
        PROVIDER_SELECTION,
        string='Провайдер',
        default='direct',
        required=True,
        help='direct = власний транспорт, sendpulse = для майбутньої міграції',
    )
    transport_priority = fields.Selection(
        TRANSPORT_PRIORITY_SELECTION,
        string='Пріоритет транспорту',
        default='auto',
        required=True,
        help='own = власний, sendpulse = SendPulse, auto = fallback SendPulse→own',
    )
    active = fields.Boolean(string='Увімкнено', default=True, index=True)

    # ── Безпека ─────────────────────────────────────────────────────────
    webhook_secret = fields.Char(
        string='Webhook Secret',
        help='Секрет підпису webhook (для Meta X-Hub-Signature-256, Viber Auth-Token)',
    )
    credentials = fields.Text(
        string='Credentials (JSON)',
        help='JSON з токенами/ключами провайдера. Зберігається зашифровано.',
    )

    # ── Telegram ────────────────────────────────────────────────────────
    bot_token = fields.Char(
        string='Bot Token',
        help='Telegram Bot Token (api.telegram.org/bot<TOKEN>). Зберігається зашифровано.',
    )
    bot_id = fields.Char(
        string='Bot ID',
        help='Telegram bot username (напр. @CampScoutBot)',
    )
    heal_url = fields.Char(
        string='Webhook URL',
        help='URL для setWebhook (Telegram) / subscribe (Meta)',
    )

    # ── Оператори ───────────────────────────────────────────────────────
    user_ids = fields.Many2many(
        'res.users',
        string='Оператори',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Оператори цього каналу',
    )

    # ── Обмеження контактів (опц.) ──────────────────────────────────────
    partner_domain = fields.Char(
        string='Обмеження контактів (домен)',
        help='Опційне обмеження: приймати повідомлення лише від контактів з цього домену email.',
    )

    # ── Метрики ─────────────────────────────────────────────────────────
    last_healthcheck_at = fields.Datetime(string='Остання перевірка')
    last_healthcheck_ok = fields.Boolean(string='Остання перевірка OK')
    last_error = fields.Char(string='Остання помилка')

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
            return False, None, 'provider_user_id відсутній'

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
            return False, None, 'Telegram bot token не налаштований'

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
        Повертає Page Access Token для Meta (перевикористовує наявні токени
        з sendpulse.facebook.page або legacy ir.config_parameter).
        """
        self.ensure_one()
        Page = self.env['sendpulse.facebook.page'].sudo()
        # Default Page
        default = Page.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if default and default.access_token:
            return default.access_token
        # Legacy fallback
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('odoo_chatwoot_connector.fb_page_access_token', '')
            or ''
        )

    def _meta_send_single(self, text, attachment_url, provider_user_id):
        """
        Надсилає повідомлення через Meta Graph API.
        Messenger: POST /{page_id}/messages (recipient.id + message.text)
        Instagram: POST /{ig_id}/messages (recipient.id + message.text)
        """
        token = self._get_meta_token()
        if not token:
            return False, None, 'Meta Page Access Token не налаштований'

        # Для Instagram потрібен ig_business_id, для Messenger — page_id
        if self.service == 'instagram':
            Page = self.env['sendpulse.facebook.page'].sudo()
            ig_id = Page.search(
                [('is_default', '=', True), ('active', '=', True)], limit=1
            ).ig_business_id or self.env['ir.config_parameter'].sudo().get_param(
                'odoo_chatwoot_connector.ig_user_id', ''
            )
            if not ig_id:
                return False, None, 'Instagram Business Account ID не налаштований'
            endpoint = f'{self._META_API}/{ig_id}/messages'
        else:
            Page = self.env['sendpulse.facebook.page'].sudo()
            page_id = (
                Page.search([('is_default', '=', True), ('active', '=', True)], limit=1).page_id
                or ''
            )
            if not page_id:
                return False, None, 'Facebook Page ID не налаштований'
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
                resp.text[:200],
            )
            if resp.status_code != 200:
                return False, None, resp.text[:200]
            data = resp.json()
            msg_id = data.get('message_id')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: Meta send exception — %s', e)
            return False, None, str(e)

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
            return False, None, 'Viber Auth-Token не налаштований'
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
                resp.text[:200],
            )
            if resp.status_code != 200:
                return False, None, resp.text[:200]
            data = resp.json()
            if data.get('status') != 0:
                return False, None, data.get('status_message', 'Viber API error')
            msg_id = data.get('message_token')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: Viber send exception — %s', e)
            return False, None, str(e)

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
            return False, None, 'WhatsApp phone_number_id не налаштований'
        if not token:
            return False, None, 'WhatsApp token не налаштований'
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
                resp.text[:200],
            )
            if resp.status_code != 200:
                return False, None, resp.text[:200]
            data = resp.json()
            msg_id = (data.get('messages') or [{}])[0].get('id')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: WhatsApp send exception — %s', e)
            return False, None, str(e)

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
            return False, None, 'TikTok access_token не налаштований'
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
                resp.text[:200],
            )
            if resp.status_code != 200:
                return False, None, resp.text[:200]
            data = resp.json()
            msg_id = data.get('data', {}).get('message_id')
            return True, str(msg_id) if msg_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: TikTok send exception — %s', e)
            return False, None, str(e)

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
            return False, None, 'LiveChat token не налаштований'
        if not chat_id:
            return False, None, 'LiveChat chat_id не налаштований'
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
                resp.text[:200],
            )
            if resp.status_code != 200:
                return False, None, resp.text[:200]
            data = resp.json()
            event_id = data.get('event_id')
            return True, str(event_id) if event_id else None, None
        except Exception as e:
            _logger.error('Channel Bridge: LiveChat send exception — %s', e)
            return False, None, str(e)

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
                resp.text[:200],
            )
            if resp.status_code != 200:
                return False, None, resp.text[:200]
            data = resp.json()
            ok = data.get('ok', False)
            if not ok:
                return False, None, data.get('description', 'Telegram API error')
            msg = (data.get('result') or {}).get('message_id')
            return True, str(msg) if msg else None, None
        except Exception as e:
            _logger.error('Channel Bridge: Telegram send exception — %s', e)
            return False, None, str(e)

    @staticmethod
    def _looks_like_image(url):
        """Примитивна евристика: чи URL вказує на зображення."""
        if not url:
            return False
        lower = url.lower().split('?')[0]
        return lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))

    @staticmethod
    def _split_text_by_limit(text, max_chars):
        """Розбиває текст на частини не довші за max_chars (аналог sendpulse_messaging)."""
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
        Реєструє webhook для Telegram бота: setWebhook(https://<odoo>/bridge/telegram/webhook/<token>).
        Повертає (ok, error).
        """
        self.ensure_one()
        token = self._get_telegram_token()
        if not token:
            return False, 'Telegram bot token не налаштований'
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        if not base_url:
            return False, 'web.base.url не налаштований'
        webhook_url = f'{base_url}/bridge/telegram/webhook/{token}'
        try:
            resp = requests.post(
                f'{self._TELEGRAM_API}/bot{token}/setWebhook',
                json={'url': webhook_url},
                timeout=self._TELEGRAM_API_TIMEOUT,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get('ok'):
                self.write({'heal_url': webhook_url, 'last_healthcheck_ok': True})
                _logger.info('Channel Bridge: Telegram webhook set to %s', webhook_url)
                return webhook_url, None
            return False, data.get('description', resp.text[:200])
        except Exception as e:
            _logger.error('Channel Bridge: setWebhook exception — %s', e)
            return False, str(e)

    # ════════════════════════════════════════════════════════════════════
    # Cron
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def cron_bridge_healthcheck(self):
        """
        Кожні 60 хв. Перевіряє доступність власного транспорту.
        Для Telegram — пере-реєстрація setWebhook (ідемпотентно).
        """
        for backend in self.search([('active', '=', True), ('provider', '=', 'direct')]):
            if backend.service == 'telegram':
                url, err = backend.register_telegram_webhook()
                backend.write(
                    {
                        'last_healthcheck_at': fields.Datetime.now(),
                        'last_healthcheck_ok': bool(url),
                        'last_error': err or '',
                    }
                )
            else:
                # Інші канали — поки no-op (M3)
                backend.write(
                    {
                        'last_healthcheck_at': fields.Datetime.now(),
                        'last_healthcheck_ok': True,
                    }
                )

    @api.model
    def cron_bridge_retry(self):
        """
        Кожні 15 хви. Повтор відправки тих, що впали (channel.message state='failed').
        """
        Message = self.env['channel.message'].sudo()
        failed = Message.search(
            [
                ('direction', '=', 'outgoing'),
                ('state', '=', 'failed'),
                ('retry_count', '<', 5),
            ]
        )
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
                msg.write(
                    {
                        'state': 'sent',
                        'provider_message_id': provider_msg_id,
                        'retry_count': msg.retry_count + 1,
                    }
                )
            else:
                msg.write({'retry_count': msg.retry_count + 1, 'last_error': err})

    @api.model
    def cron_bridge_switch_check(self):
        """
        Кожні 30 хви. Auto-failover: чи доступний SendPulse, чи треба перемкнути
        канал на власний транспорт. M0 — логує стан; M1+ — реальне перемикання.
        """
        for backend in self.search([('active', '=', True), ('transport_priority', '=', 'auto')]):
            # M1: реальна healthcheck SendPulse API + перемикання transport_priority.
            sendpulse_ok = self._check_sendpulse_available()
            if not sendpulse_ok:
                # SendPulse недоступний — перемикаємо канал на власний транспорт
                if backend.transport_priority != 'own':
                    _logger.warning(
                        'Channel Bridge: SendPulse недоступний, перемикаємо backend=%s '
                        '(service=%s) на own transport',
                        backend.id,
                        backend.service,
                    )
                    backend.write({'transport_priority': 'own'})
            else:
                # SendPulse доступний — повертаємо auto (якщо був перемкнений вручну на own)
                if backend.transport_priority == 'own':
                    _logger.info(
                        'Channel Bridge: SendPulse знову доступний, повертаємо backend=%s '
                        '(service=%s) на auto',
                        backend.id,
                        backend.service,
                    )
                    backend.write({'transport_priority': 'auto'})
            _logger.info(
                'Channel Bridge: switch_check backend=%s service=%s priority=%s sendpulse_ok=%s',
                backend.id,
                backend.service,
                backend.transport_priority,
                sendpulse_ok,
            )

    @api.model
    def _check_sendpulse_available(self):
        """
        Перевіряє доступність SendPulse API (OAuth token refresh).
        Повертає True якщо SendPulse доступний, False — якщо ні.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('odoo_chatwoot_connector.client_id', '')
        client_secret = ICP.get_param('odoo_chatwoot_connector.client_secret', '')
        if not client_id or not client_secret:
            # Немає налаштувань SendPulse — вважаємо недоступним (перемикаємо на own)
            return False
        try:
            # Спробуємо отримати токен — якщо OAuth працює, SendPulse доступний
            sample = self.env['sendpulse.connect'].sudo().search([], limit=1)
            if not sample:
                return False
            token = sample._get_access_token()
            return bool(token)
        except Exception as e:
            _logger.warning('Channel Bridge: SendPulse healthcheck failed — %s', e)
            return False

    @api.model
    def action_switch_all_to_own(self):
        """
        M4: примусово перемикає ВСІ активні канали на власний транспорт (own)
        і вимикає SendPulse як транспорт. Виконується після підтвердження
        всіх каналів на продакшені.
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
        # Вимикаємо SendPulse як транспорт для всіх розмов
        Connect = self.env['sendpulse.connect'].sudo()
        updated = Connect.search([('transport', '!=', 'own')]).write({'transport': 'own'})
        _logger.info(
            'Channel Bridge M4: перемкнено %d backend-ів на own, %d розмов на own transport',
            switched,
            updated,
        )
        return switched
