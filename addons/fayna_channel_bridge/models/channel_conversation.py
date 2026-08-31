import hashlib
import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import escape

_logger = logging.getLogger(__name__)

# Advisory lock key для race-guard на вхідні події
_BRIDGE_INBOUND_LOCK_KEY2 = 0x5B1D6E

# Вікно 24h для Messenger (відновлюється при кожному inbound від клієнта)
_BRIDGE_MESSENGER_WINDOW_HOURS = 24

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

STAGE_SELECTION = [
    ('new', 'New'),
    ('new_message', 'New message'),
    ('in_progress', 'In progress'),
    ('close', 'Closed'),
]

TRANSPORT_SELECTION = [
    ('own', 'Own'),
    ('auto', 'Auto (fallback)'),
]


class ChannelConversation(models.Model):
    """
    Розмова власного прямого транспорту (автономна модель).

    Зберігає розмову чат-каналу (Telegram, Instagram, Facebook/Messenger,
    Viber, WhatsApp, TikTok, LiveChat) без жодної залежності від зовнішнього
    посередника. Прив'язується до discuss.channel, через який оператори
    відповідають клієнтам.
    """

    _name = 'channel.conversation'
    _description = 'Channel Bridge Conversation'
    _order = 'last_message_date desc'

    def init(self):
        """
        Partial unique index: (provider_user_id, service) унікальні для активних
        розмов. Захищає від дублікатів при повторних webhook-ах.
        """
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS channel_conversation_active_provider_uniq
            ON channel_conversation (provider_user_id, service)
            WHERE active = true AND provider_user_id IS NOT NULL AND provider_user_id != ''
        """)

    # ── Основні поля ────────────────────────────────────────────────────
    name = fields.Char(string='Name', required=True, index=True)
    service = fields.Selection(
        SERVICE_SELECTION,
        string='Channel',
        required=True,
        index=True,
    )
    backend_id = fields.Many2one(
        'channel.backend',
        string='Backend',
        ondelete='set null',
        index=True,
    )
    channel_id = fields.Many2one(
        'discuss.channel',
        string='Discuss Channel',
        ondelete='set null',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        ondelete='set null',
        index=True,
    )
    provider_user_id = fields.Char(
        string='Provider User ID',
        index=True,
        help='User ID at the provider (chat_id for Telegram, PSID for Messenger, etc.)',
    )
    provider_bot_id = fields.Char(
        string='Provider Bot ID',
        help='Bot/page ID at the provider (to distinguish several bots of one channel)',
    )
    bot_name = fields.Char(string='Bot name')
    active = fields.Boolean(string='Active', default=True, index=True)
    stage = fields.Selection(
        STAGE_SELECTION,
        string='Stage',
        default='new',
        index=True,
    )
    transport = fields.Selection(
        TRANSPORT_SELECTION,
        string='Transport',
        default='own',
        help='own = own transport, auto = own first, fallback on error',
    )

    # ── Контакт ─────────────────────────────────────────────────────────
    social_username = fields.Char(string='Username')
    social_profile_url = fields.Char(string='Profile')
    last_message_preview = fields.Char(string='Last message')
    last_message_date = fields.Datetime(string='Last message date', index=True)

    # ── Оператори ───────────────────────────────────────────────────────
    user_ids = fields.Many2many(
        'res.users',
        string='Operators',
        domain=[('share', '=', False), ('active', '=', True)],
    )

    # ════════════════════════════════════════════════════════════════════
    # Receive — обробка вхідної події (webhook)
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def _process_incoming_event(self, data, contact, bot, service, event_type, timestamp_ms):
        """
        Обробляє вхідну подію з webhook провайдера (автономна версія).

        Логіка:
          1. Знаходимо або створюємо розмову за (provider_user_id, service)
          2. Створюємо discuss.channel якщо розмова нова
          3. Зберігаємо повідомлення в channel.message і постимо в discuss.channel
        """
        contact_id = contact.get('id', '')
        contact_name = contact.get('name', 'Unknown')
        email = contact.get('email', '') or ''
        phone = contact.get('phone', '') or ''
        last_message = contact.get('last_message', '') or ''
        variables = contact.get('variables', {}) or {}
        bot_id = bot.get('id', '') or ''
        bot_name = bot.get('name', '') or ''

        # provider_user_id: contact.id має формат own:{service}:{bot_id}:{user_id}
        # або own:{service}:{user_id} — парсимо останній сегмент
        provider_user_id = self._parse_provider_user_id(contact_id, service)

        # ── Race-guard: advisory lock на (provider_user_id, service) ──
        if provider_user_id:
            lock_key1 = (
                int(
                    hashlib.md5(f'{provider_user_id}|{service}'.encode()).hexdigest()[:8],
                    16,
                )
                & 0x7FFFFFFF
            )
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (lock_key1, _BRIDGE_INBOUND_LOCK_KEY2),
            )
            self.env.flush_all()
            self.env.invalidate_all()

        # ── Знаходимо або створюємо розмову ────────────────────────────
        conv = self.search(
            [
                ('provider_user_id', '=', provider_user_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ],
            limit=1,
        )

        # Закрита розмова того ж контакту — перевідкриваємо
        if not conv:
            conv = self.search(
                [
                    ('provider_user_id', '=', provider_user_id),
                    ('service', '=', service),
                    ('stage', '=', 'close'),
                ],
                order='write_date desc',
                limit=1,
            )
            if conv:
                conv.write({'stage': 'new'})
                if conv.channel_id:
                    conv.channel_id.write({'active': True})

        now = fields.Datetime.now()
        is_brand_new = not conv

        if not conv:
            create_vals = {
                'name': contact_name,
                'service': service,
                'backend_id': self._find_backend(service, bot_id).id
                if self._find_backend(service, bot_id)
                else False,
                'provider_user_id': provider_user_id,
                'provider_bot_id': bot_id or False,
                'bot_name': bot_name or False,
                'partner_id': self._find_partner(provider_user_id, service, email, phone) or False,
                'social_username': variables.get('username') or False,
                'social_profile_url': self._build_profile_url(variables, service) or False,
                'last_message_preview': last_message[:100] if last_message else '',
                'last_message_date': now,
                'stage': 'new',
            }
            from psycopg2 import IntegrityError

            try:
                with self.env.cr.savepoint():
                    conv = self.create(create_vals)
            except IntegrityError:
                _logger.info(
                    'Channel Bridge: race duplicate intercepted by unique index — '
                    'user=%s service=%s',
                    provider_user_id,
                    service,
                )
                self.env.invalidate_all()
                conv = self.search(
                    [
                        ('provider_user_id', '=', provider_user_id),
                        ('service', '=', service),
                        ('stage', '!=', 'close'),
                    ],
                    limit=1,
                )
                if not conv:
                    raise
                is_brand_new = False
        else:
            update_vals = {
                'last_message_preview': last_message[:100]
                if last_message
                else conv.last_message_preview,
                'last_message_date': now,
                'stage': 'new_message' if conv.stage == 'in_progress' else conv.stage,
            }
            if not conv.partner_id:
                partner = self._find_partner(
                    provider_user_id, service, email, phone, exclude_id=conv.id
                )
                if partner:
                    update_vals['partner_id'] = partner.id
            try:
                with self.env.cr.savepoint():
                    conv.write(update_vals)
            except Exception:
                _logger.warning(
                    'Channel Bridge: concurrent update on conv=%s (user=%s), retrying once',
                    conv.id,
                    provider_user_id,
                )
                self.env.invalidate_all()
                conv.write(update_vals)

        # ── Створюємо discuss.channel для нової розмови ────────────────
        if is_brand_new and not conv.channel_id:
            conv._create_discuss_channel()

        # ── Постимо в discuss.channel для операторів ─────────────────────
        # Журнал channel.message на вхідні повідомлення тут НЕ створюємо:
        # він дублює запис із порожнім provider_message_id (F-04). Запис
        # створюється лише у вихідному напрямку (див. _send_via_own).
        if last_message and conv.channel_id:
            author_partner = conv.partner_id
            if not author_partner:
                author_partner = self.env['res.partner'].search(
                    [('name', '=', contact_name)], order='id desc', limit=1
                )
            conv.channel_id.with_context(bridge_incoming=True).message_post(
                body=escape(last_message),
                author_id=author_partner.id if author_partner else False,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        return conv

    @staticmethod
    def _parse_provider_user_id(contact_id, service):
        """Парсить provider_user_id з contact.id (own:{service}:{bot_id}:{user_id})."""
        if not contact_id:
            return ''
        if contact_id.startswith('own:'):
            parts = contact_id.split(':')
            if len(parts) >= 3:
                return parts[3] if len(parts) >= 4 else parts[2]
        return contact_id

    @staticmethod
    def _extract_provider_message_id(data, service):
        """Дістає provider_message_id з payload (для журналу).

        Увага: на вхідних подіях normalized-payload не містить ключа
        "message", тому метод повертає "" (це корінь F-04). Наразі метод
        не використовується для вхідних повідомлень — журнал вхідних
        повідомлень більше не створюється (див. _process_incoming_event).
        Знадобиться в Етапі 2, коли запровадимо коректний розбір
        provider_message_id з оригінального payload.
        """
        message = (data.get('message') or {}) if isinstance(data, dict) else {}
        return str(message.get('message_id', '') or '') if isinstance(message, dict) else ''

    def _find_backend(self, service, bot_id):
        """Знаходить активний channel.backend за service (+ bot_id)."""
        # Викликається з публічного webhook: анонімний запит не має прав
        # на channel.backend.
        Backend = self.env['channel.backend'].sudo()
        domain = [
            ('service', '=', service),
            ('provider', '=', 'direct'),
            ('active', '=', True),
        ]
        backends = Backend.search(domain)
        if not backends:
            return None
        if len(backends) == 1:
            return backends
        if bot_id:
            for b in backends:
                if b.bot_id and b.bot_id == bot_id:
                    return b
        return backends[0]

    def _find_partner(self, provider_user_id, service, email, phone, exclude_id=None):
        """Шукає партнера за provider_user_id, потім email/phone.

        Спочатку шукаємо партнера за історією розмов із таким самим
        provider_user_id і service, у якої вже заповнений partner_id (F-05):
        це найнадійніший зв'язок для повторних звернень. Лише якщо історії
        немає — пробуємо email/phone. Пряме прив'язування partner↔telegram
        без нових полів на res.partner запроваджується в Етапі 3.
        """
        # Публічний webhook: анонімний запит не має прав на res.partner.
        Partner = self.env['res.partner'].sudo()
        if provider_user_id:
            domain = [
                ('provider_user_id', '=', provider_user_id),
                ('service', '=', service),
                ('partner_id', '!=', False),
            ]
            if exclude_id:
                domain.append(('id', '!=', exclude_id))
            # Публічний webhook: анонімний запит не має прав на channel.conversation.
            history = (
                self.env['channel.conversation']
                .sudo()
                .search(domain, order='write_date desc', limit=1)
            )
            if history and history.partner_id:
                return history.partner_id
        if email:
            partner = Partner.search([('email', '=', email)], limit=1)
            if partner:
                return partner
        if phone:
            clean_phone = phone.strip().replace(' ', '')
            if clean_phone:
                partner = Partner.search([('phone', '=', clean_phone)], limit=1)
                if partner:
                    return partner
        return None

    @staticmethod
    def _build_profile_url(variables, service):
        """Будує URL профілю з variables."""
        username = variables.get('username') or ''
        if not username:
            return ''
        if service == 'telegram':
            return f'https://t.me/{username}'
        return ''

    # ════════════════════════════════════════════════════════════════════
    # Discuss channel
    # ════════════════════════════════════════════════════════════════════

    def _create_discuss_channel(self):
        """Створює discuss.channel для розмови."""
        self.ensure_one()
        channel_name = f'[{self._get_service_label()}] {self.name}'
        channel = self.env['discuss.channel'].create(
            {
                'name': channel_name,
                'channel_type': 'group',
                'description': self._get_channel_description(),
            }
        )
        partner_ids = self._collect_channel_partner_ids()
        if partner_ids:
            channel.add_members(partner_ids=partner_ids)
        self.write({'channel_id': channel.id, 'stage': 'in_progress'})
        return channel

    def _collect_channel_partner_ids(self):
        """
        Збирає partner_id учасників каналу трирівневим падінням:

        1. оператори розмови (self.user_ids);
        2. інакше — оператори backend (self.backend_id.user_ids);
        3. інакше — усі активні користувачі групи group_channel_bridge_officer.

        Бере лише активних користувачів і лише непорожні partner_id, прибирає
        дублікати. Якщо після всіх рівнів список порожній — логує попередження.
        """
        users = self.user_ids.filtered(lambda u: u.active)
        if not users and self.backend_id:
            users = self.backend_id.user_ids.filtered(lambda u: u.active)
        if not users:
            officer_group = self.env.ref(
                'fayna_channel_bridge.group_channel_bridge_officer',
                raise_if_not_found=False,
            )
            if officer_group:
                users = officer_group.users.filtered(lambda u: u.active)

        partner_ids = list({u.partner_id.id for u in users if u.partner_id and u.partner_id.id})
        if not partner_ids:
            _logger.warning(
                'Channel Bridge: жодного учасника для каналу розмови %s — '
                'канал створено без операторів',
                self.id,
            )
        return partner_ids

    def _get_service_label(self):
        labels = {
            'telegram': 'Telegram',
            'instagram': 'Instagram',
            'facebook': 'Facebook',
            'messenger': 'Messenger',
            'viber': 'Viber',
            'whatsapp': 'WhatsApp',
            'tiktok': 'TikTok',
            'livechat': 'LiveChat',
        }
        return labels.get(self.service, self.service)

    def _get_channel_description(self):
        parts = [f'Channel: {self._get_service_label()}']
        if self.provider_user_id:
            parts.append(f'Provider User ID: {self.provider_user_id}')
        return '\n'.join(parts)

    # ════════════════════════════════════════════════════════════════════
    # Send — відправка через власний транспорт
    # ════════════════════════════════════════════════════════════════════

    def _get_channel_backend(self):
        """Знаходить активний channel.backend для цієї розмови."""
        self.ensure_one()
        if self.backend_id and self.backend_id.active:
            return self.backend_id
        if not self.service:
            return None
        return self._find_backend(self.service, self.provider_bot_id or '')

    def _send_single_message(self, text, attachment_url=None):
        """Надсилає повідомлення через власний транспорт (channel.backend)."""
        self.ensure_one()
        backend = self._get_channel_backend()
        if not backend:
            _logger.error(
                'Channel Bridge: no active backend for conversation=%s (service=%s)',
                self.id,
                self.service,
            )
            return False
        return self._send_via_own(backend, text, attachment_url)

    def _send_via_own(self, backend, text, attachment_url=None):
        """Надсилає через власний транспорт і логує у channel.message."""
        provider_user_id = self.provider_user_id or ''
        ok, provider_msg_id, err = backend.send_message(
            text,
            attachment_url=attachment_url,
            provider_user_id=provider_user_id,
        )
        # Журнал channel.message створюється від імені системи, щоб не
        # залежати від прав поточного користувача.
        self.env['channel.message'].sudo().create(
            {
                'backend_id': backend.id,
                'service': self.service,
                'direction': 'outgoing',
                'state': 'sent' if ok else 'failed',
                'provider_message_id': provider_msg_id,
                'provider_user_id': provider_user_id,
                'text_message': text,
                'attachment_url': attachment_url or False,
                'last_error': err or '',
            }
        )
        if not ok:
            _logger.error(
                'Channel Bridge: own transport send failed for conversation=%s — %s',
                self.id,
                err,
            )
        return ok

    # ════════════════════════════════════════════════════════════════════
    # Дії оператора
    # ════════════════════════════════════════════════════════════════════

    def action_open_discuss(self):
        """Відкриває Odoo Discuss для цієї розмови."""
        self.ensure_one()
        if not self.channel_id:
            self._create_discuss_channel()
        if not self.channel_id:
            raise UserError(_('Could not open the chat. Please try again.'))
        member = self.env['discuss.channel.member'].search(
            [
                ('channel_id', '=', self.channel_id.id),
                ('partner_id', '=', self.env.user.partner_id.id),
            ],
            limit=1,
        )
        if not member:
            self.channel_id.add_members(partner_ids=[self.env.user.partner_id.id])
        if self.stage == 'new_message':
            self.write({'stage': 'in_progress'})
        ctx = self.env.context.copy()
        ctx['active_id'] = self.channel_id.id
        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
            'context': ctx,
        }

    def action_close(self):
        """Закриває розмову (stage → close). Канал НЕ архівується."""
        self.ensure_one()
        self.write({'stage': 'close'})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reopen(self):
        """Повторно відкриває закриту розмову і розархівує discuss.channel."""
        self.ensure_one()
        self.write({'stage': 'in_progress'})
        if self.channel_id:
            self.channel_id.write({'active': True})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # ════════════════════════════════════════════════════════════════════
    # Archive cron
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def cron_archive_old_conversations(self, limit=200):
        """Архівує (active=False) розмови, неактивні понад N днів (за замовч. 30).

        Використовує нативний механізм архівації Odoo — поле ``active``.
        Історія повністю зберігається; заархівовані розмови просто ховаються
        з активного інбоксу і можуть бути відкриті оператором у будь-який момент.

        Кількість днів конфігурується через ir.config_parameter
        ``fayna_channel_bridge.archive_inactive_days`` (мінімум 7).
        """
        # Крон: читання системного параметра потребує прав адміністратора.
        icp = self.env['ir.config_parameter'].sudo()
        try:
            archive_days = int(icp.get_param('fayna_channel_bridge.archive_inactive_days', '30'))
        except ValueError:
            archive_days = 30
        archive_days = max(7, archive_days)
        cutoff = datetime.now() - timedelta(days=archive_days)

        # Крон: вибірка розмов без контексту користувача.
        conversations = self.sudo().search(
            [
                ('active', '=', True),
                ('last_message_date', '!=', False),
                ('last_message_date', '<', cutoff),
            ],
            order='last_message_date asc',
            limit=max(1, int(limit)),
        )
        if not conversations:
            return 0

        channels = conversations.mapped('channel_id').filtered(lambda c: c.active)
        if channels:
            # Крон: архівація каналів без контексту користувача.
            channels.sudo().write({'active': False})

        # Крон: архівація розмов без контексту користувача.
        conversations.sudo().write({'active': False})
        _logger.info(
            'Channel Bridge: заархівовано %s неактивних розмов (cutoff %s, каналів %s)',
            len(conversations),
            cutoff,
            len(channels),
        )
        return len(conversations)
