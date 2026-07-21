import logging
from datetime import datetime, timedelta

from markupsafe import Markup, escape
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import plaintext2html

_logger = logging.getLogger(__name__)

UTM_SOURCE_MAP = {
    'telegram': 'odoo_chatwoot_connector.utm_source_telegram',
    'instagram': 'odoo_chatwoot_connector.utm_source_instagram',
    'facebook': 'odoo_chatwoot_connector.utm_source_facebook',
    'messenger': 'odoo_chatwoot_connector.utm_source_messenger',
    'viber': 'odoo_chatwoot_connector.utm_source_viber',
    'whatsapp': 'odoo_chatwoot_connector.utm_source_whatsapp',
    'tiktok': 'odoo_chatwoot_connector.utm_source_tiktok',
    'livechat': 'odoo_chatwoot_connector.utm_source_livechat',
}

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
    ('new', 'Новий'),
    ('identifying', 'Ідентифікація (bot)'),
    ('in_progress', 'В роботі'),
    ('new_message', 'Нове повідомлення'),
    ('close', 'Закрито'),
]

ID_STEP_SELECTION = [
    ('ask_email', 'Чекаємо email'),
    ('ask_email_retry', 'Повторно просимо email'),
    ('done', 'Ідентифіковано'),
    ('gave_up', 'Клієнт не надав — передано оператору'),
]

# Advisory lock для запобігання race condition при конкурентних webhook-ах
# від SendPulse для одного контакту (щоб search→create не створював дублікатів).
_SENDPULSE_INBOUND_LOCK_KEY2 = 71234


class SendpulseConnect(models.Model):
    """
    Центральна модель розмови SendPulse.
    Кожна розмова = один запис тут + один discuss.channel в Odoo.
    """

    _name = 'sendpulse.connect'
    _description = 'SendPulse Розмова'
    _order = 'stage_sort asc, last_message_date desc'

    def init(self):
        """
        Partial unique index: (sendpulse_contact_id, service) мають бути
        унікальними у межах **активних** розмов (stage != 'close').
        Захищає від race condition коли два webhooks одночасно створюють
        дублі (advisory_xact_lock — софт-захист, це — хард-захист DB-рівня).
        """
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS sendpulse_connect_active_contact_service_uniq
            ON sendpulse_connect (sendpulse_contact_id, service)
            WHERE stage != 'close' AND sendpulse_contact_id IS NOT NULL
              AND sendpulse_contact_id != ''
        """)

    # ── Основні поля ────────────────────────────────────────────────────
    active = fields.Boolean(
        string='Активна',
        default=True,
        index=True,
        help='Знімається для soft-archive — запис ховається з default views '
        'але зберігається у БД для історії.',
    )
    name = fields.Char(string="Ім'я контакту", required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Клієнт',
        index=True,
        ondelete='set null',
        help='Порожньо = контакт ще не ідентифікований',
    )
    stage = fields.Selection(STAGE_SELECTION, string='Статус', default='new', index=True)
    service = fields.Selection(SERVICE_SELECTION, string='Канал', index=True)

    # ── Дані з SendPulse ────────────────────────────────────────────────
    sendpulse_contact_id = fields.Char(
        string='SendPulse Contact ID',
        index=True,
        help='UUID контакту в SendPulse — головний ключ ідентифікації',
    )
    bot_id = fields.Char(string='Bot ID')
    bot_name = fields.Char(string='Бот')
    last_message_preview = fields.Char(string='Останнє повідомлення')
    last_message_date = fields.Datetime(string='Дата останнього повідомлення')

    # ── Ідентифікаційні дані соцмереж ───────────────────────────────────
    social_username = fields.Char(
        string='Username / Профіль',
        help="Ім'я користувача або посилання на профіль у соцмережах",
    )
    social_profile_url = fields.Char(
        string='URL профілю',
        help='Пряме посилання на профіль (для Facebook, Instagram тощо)',
    )
    unidentified_email = fields.Char(
        string='Email (з SendPulse)',
        help='Email отриманий від SendPulse до ідентифікації партнера',
    )
    unidentified_phone = fields.Char(string='Телефон (з SendPulse)')

    # ── Змінні бота SendPulse ────────────────────────────────────────────
    sp_child_name = fields.Char(
        string="Ім'я дитини",
        help='Змінна child_name зібрана ботом SendPulse',
    )
    sp_booking_email = fields.Char(
        string='Email бронювання',
        help='Змінна booking_email зібрана ботом SendPulse',
    )

    # ── Профіль з SendPulse API ──────────────────────────────────────────
    avatar_url = fields.Char(
        string='Аватар (URL)',
        help='URL аватара контакту з SendPulse API',
    )
    language_code = fields.Char(
        string='Мова',
        help='Код мови контакту (наприклад: uk, en, ru)',
    )
    subscription_status = fields.Selection(
        [
            ('active', 'Активний'),
            ('unsubscribed', 'Відписаний'),
            ('deleted', 'Видалений'),
            ('unconfirmed', 'Непідтверджений'),
        ],
        string='Статус підписки',
    )

    # ── Odoo Discuss ────────────────────────────────────────────────────
    channel_id = fields.Many2one(
        'discuss.channel',
        string='Discuss Канал',
        ondelete='set null',
    )
    user_ids = fields.Many2many(
        'res.users',
        string='Оператори',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Оператори, призначені на цю розмову',
    )

    # ── Повідомлення ────────────────────────────────────────────────────
    message_ids = fields.One2many(
        'sendpulse.message',
        'connect_id',
        string='Повідомлення',
    )
    message_count = fields.Integer(
        string='Кількість повідомлень',
        compute='_compute_message_count',
    )

    # ── Допоміжні ───────────────────────────────────────────────────────
    last_notified_at = fields.Datetime(string='Остання сповіщення')
    source_id = fields.Many2one('utm.source', string='UTM Джерело')

    # ── Коментар (Facebook / Instagram) ─────────────────────────────────
    sp_is_comment = fields.Boolean(
        string='Ініційовано з коментаря',
        default=False,
        help='True якщо розмову відкрито автоматично після коментаря під постом',
    )
    sp_comment_id = fields.Char(
        string='Comment ID',
        help='Facebook/Instagram comment_id з webhook payload',
        index=True,
    )
    sp_comment_text = fields.Char(
        string='Текст коментаря',
        size=500,
        help='Текст коментаря клієнта під постом',
    )
    sp_post_id = fields.Char(string='Post ID')
    sp_post_url = fields.Char(string='URL допису')
    sp_page_id = fields.Char(
        string='FB Page ID',
        index=True,
        help='ID сторінки з webhook — для multi-page маршрутизації на sendpulse.facebook.page.',
    )
    sp_replied_public = fields.Boolean(
        string='Публічна відповідь надіслана',
        default=False,
        help='True якщо публічна відповідь під коментарем успішно опублікована',
    )
    sp_public_template_id = fields.Many2one(
        'sendpulse.public.template',
        string='Публічний шаблон',
        ondelete='set null',
        help='Який шаблон (A/B) використано для публічної відповіді — для conversion tracking.',
    )
    sp_public_template_conversion_counted = fields.Boolean(
        default=False,
        readonly=True,
        help='True якщо конверсія customer_replied вже зарахована цьому шаблону (щоб не дублювати).',
    )
    # F13 Lead magnet tracking
    sp_pdf_sent_at = fields.Datetime(
        string='PDF-каталог надіслано',
        readonly=True,
        help='Коли було надіслано lead-magnet PDF на email клієнта.',
    )
    sp_pdf_sent_to_email = fields.Char(
        string='Email для PDF',
        readonly=True,
    )
    sp_coupon_code = fields.Char(
        string='Купон-код',
        readonly=True,
        help='Згенерований промокод (loyalty.card) — відправлений SMS-ом.',
    )
    sp_coupon_sent_at = fields.Datetime(
        string='Купон надіслано SMS',
        readonly=True,
    )
    sp_coupon_sent_to_phone = fields.Char(
        string='Телефон для купона',
        readonly=True,
    )
    sp_replied_private = fields.Boolean(
        string='Приватне повідомлення надіслано',
        default=False,
        help='True якщо private_reply успішно надіслано через Graph API',
    )
    sp_messenger_window_expires_at = fields.Datetime(
        string='Messenger 24h вікно до',
        help='Коли закривається 24-годинне вікно Meta для вільного обміну повідомленнями. '
        'Після цього менеджер не може писати клієнту (поки той не відповість).',
    )
    sp_window_alert_sent = fields.Boolean(
        string='Алерт про закриття вікна надіслано',
        default=False,
        help='True якщо Telegram-сповіщення за 2h до закриття вікна вже надіслано. '
        'Скидається при новому inbound від клієнта.',
    )
    sp_comment_category = fields.Selection(
        selection=[
            ('question_price', 'Питання про ціну'),
            ('question_dates', 'Питання про терміни'),
            ('question_age', 'Питання про вік'),
            ('question_general', 'Загальне питання'),
            ('thanks', 'Подяка / позитив'),
            ('complaint', 'Скарга'),
            ('spam', 'Спам'),
            ('other', 'Інше'),
        ],
        string='Категорія коментаря',
        help='Автоматична класифікація коментаря через LLM для маршрутизації',
    )

    # ── Метрики воронки конверсії ───────────────────────────────────────
    sp_funnel_stage = fields.Selection(
        selection=[
            ('comment_only', 'Коментар без реакції'),
            ('private_sent', 'Надіслано приватне'),
            ('customer_replied', 'Клієнт відповів'),
            ('operator_engaged', 'Оператор підключився'),
            ('lead_created', 'Створено лід'),
            ('closed_won', 'Конверсія: замовлення'),
            ('closed_lost', 'Втрата'),
        ],
        string='Стадія воронки',
        index=True,
    )
    sp_first_inbound_at = fields.Datetime(
        string='Перше повідомлення клієнта',
        help='Коли клієнт написав перший раз (не коментар, а DM/чат)',
    )
    sp_first_reply_at = fields.Datetime(
        string='Перша відповідь оператора',
        help='Коли оператор відповів уперше (не автовідповідь)',
    )
    sp_first_reply_time_sec = fields.Integer(
        string='Час до першої відповіді (сек)',
        compute='_compute_first_reply_time',
        store=True,
        help='Скільки секунд між першим повідомленням клієнта і першою відповіддю оператора',
    )
    sp_lead_id = fields.Many2one(
        'crm.lead',
        string='Лід',
        help='CRM-лід створений з цієї розмови',
    )

    # V2 F1 RAG auto-answer tracking
    rag_auto_answered_at = fields.Datetime(
        string='Auto-answered (RAG) at',
        help='Коли модуль востаннє автоматично відповів через FAQ RAG.',
    )
    rag_last_faq_id = fields.Many2one(
        'sendpulse.faq.entry',
        string='Останній match FAQ',
        help='Яка FAQ-запис була останньою використана для авто-відповіді.',
    )

    # V2 F3 Bot-wizard ідентифікації
    id_step = fields.Selection(
        ID_STEP_SELECTION,
        string='Крок ідентифікації',
        help='Поточний стан bot-wizard автоматичної ідентифікації контакту.',
    )
    id_attempts = fields.Integer(
        string='Спроби ідентифікації',
        default=0,
        help='Скільки разів bot просив email. Limit ~3, потім skip до оператора.',
    )

    # V2 F2 Drip campaigns tracking
    drip_reminder_6h_sent = fields.Boolean(
        string='Reminder 6h надіслано',
        default=False,
        help='True після drip-нагадування про неотриману відповідь від клієнта.',
    )
    drip_followup_24h_sent = fields.Boolean(
        string='Follow-up 24h надіслано',
        default=False,
        help='True після follow-up від оператора після 24h мовчанки клієнта.',
    )
    drip_booking_3d_sent = fields.Boolean(
        string='Booking reminder 3d надіслано',
        default=False,
        help='True після нагадування про бронь (якщо є лід без оплати).',
    )
    drip_stop_requested = fields.Boolean(
        string='Opt-out drip',
        default=False,
        help='True якщо клієнт написав STOP / "не писати" / unsubscribe — '
        'модуль не шле більше автоматичних нагадувань.',
    )

    @api.depends('sp_first_inbound_at', 'sp_first_reply_at')
    def _compute_first_reply_time(self):
        for rec in self:
            if (
                rec.sp_first_inbound_at
                and rec.sp_first_reply_at
                and rec.sp_first_reply_at > rec.sp_first_inbound_at
            ):
                rec.sp_first_reply_time_sec = int(
                    (rec.sp_first_reply_at - rec.sp_first_inbound_at).total_seconds()
                )
            else:
                rec.sp_first_reply_time_sec = 0

    # ── Computed ────────────────────────────────────────────────────────
    is_unidentified = fields.Boolean(
        string='Не ідентифікований',
        compute='_compute_is_unidentified',
        store=True,
    )
    service_icon = fields.Char(
        string='Іконка каналу',
        compute='_compute_service_icon',
    )
    stage_sort = fields.Integer(
        string='Порядок сортування',
        compute='_compute_stage_sort',
        store=True,
        help='0=нові, 1=нові повідомлення, 2=в роботі, 3=закриті',
    )

    @api.depends('partner_id')
    def _compute_is_unidentified(self):
        for rec in self:
            rec.is_unidentified = not bool(rec.partner_id)

    @api.depends('service')
    def _compute_service_icon(self):
        icons = {
            'telegram': '✈️',
            'instagram': '📸',
            'facebook': '👍',
            'messenger': '💬',
            'viber': '📳',
            'whatsapp': '🟢',
            'tiktok': '🎵',
            'livechat': '🌐',
        }
        for rec in self:
            rec.service_icon = icons.get(rec.service, '💬')

    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    @api.depends('stage')
    def _compute_stage_sort(self):
        order = {'new': 0, 'new_message': 1, 'in_progress': 2, 'close': 3}
        for rec in self:
            rec.stage_sort = order.get(rec.stage, 2)

    # ════════════════════════════════════════════════════════════════════
    # ORM Overrides
    # ════════════════════════════════════════════════════════════════════

    def create(self, vals):
        rec = super().create(vals)
        # Сповіщаємо операторів про нову розмову
        rec._notify_operators_new_conversation()
        return rec

    def write(self, vals):
        result = super().write(vals)
        if 'stage' in vals and vals['stage'] == 'new_message':
            for rec in self:
                rec._notify_operators_new_message()
        return result

    def unlink(self):
        for rec in self:
            rec._close_channel()
        return super().unlink()

    # ════════════════════════════════════════════════════════════════════
    # Основні методи
    # ════════════════════════════════════════════════════════════════════

    def action_open_discuss(self):
        """Відкриває Odoo Discuss для цієї розмови."""
        self.ensure_one()
        if not self.channel_id:
            self._create_discuss_channel()
        if not self.channel_id:
            raise UserError(_('Не вдалося відкрити чат. Спробуйте ще раз.'))

        # Перевіряємо чи поточний юзер є учасником
        member = self.env['discuss.channel.member'].search(
            [
                ('channel_id', '=', self.channel_id.id),
                ('partner_id', '=', self.env.user.partner_id.id),
            ],
            limit=1,
        )
        if not member:
            self.channel_id.add_members(partner_ids=[self.env.user.partner_id.id])

        # Знімаємо позначку "Нове повідомлення" при відкритті чату
        if self.stage == 'new_message':
            self.write({'stage': 'in_progress'})

        ctx = self.env.context.copy()
        ctx['active_id'] = self.channel_id.id
        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
            'context': ctx,
        }

    def action_identify_partner(self):
        """Відкриває wizard для прив'язки неідентифікованого чату до партнера."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ідентифікувати клієнта'),
            'res_model': 'sendpulse.identify.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_connect_id': self.id},
        }

    def action_close(self):
        """Закриває розмову (stage → close). Канал НЕ архівується — історія залишається доступною."""
        self.ensure_one()
        self.write({'stage': 'close'})
        if self.partner_id:
            self._post_history_to_partner()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reopen(self):
        """Повторно відкриває закриту розмову і розархівує discuss.channel."""
        self.ensure_one()
        self.write({'stage': 'in_progress'})
        if self.channel_id:
            self.channel_id.write({'active': True})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _create_discuss_channel(self, send_greeting=False):
        """
        Створює discuss.channel для розмови.
        Менеджери бачать новий чат у черзі і долучаються вручну.
        send_greeting=True → надсилає авто-привітання клієнту через SendPulse.
        """
        self.ensure_one()
        channel_name = f'[{self._get_service_label()}] {self.name}'

        channel = self.env['discuss.channel'].create(
            {
                'name': channel_name,
                'channel_type': 'group',
                'sendpulse_connect_id': self.id,
                'description': self._get_channel_description(),
            }
        )

        # Додаємо тільки явно призначених операторів цієї розмови.
        # Ніякого fallback на всіх внутрішніх користувачів — менеджер долучається сам.
        partner_ids = [u.partner_id.id for u in self.user_ids if u.active]
        if partner_ids:
            channel.add_members(partner_ids=partner_ids)

        # Якщо є збережені повідомлення — постимо їх в канал як історію
        # ВАЖЛИВО: sendpulse_incoming=True щоб mail_channel.py НЕ відправляв
        # ці повідомлення назад у SendPulse і НЕ створював дублікати sendpulse.message
        for msg in self.message_ids.sorted('date'):
            direction_label = '👤 Клієнт' if msg.direction == 'incoming' else '🧑‍💼 Оператор'
            body = Markup('<b>{}</b><br/>{}').format(
                direction_label, escape(msg.text_message or '')
            )
            if msg.attachment_url:
                body += Markup('<br/><a href="{}" target="_blank">📎 Вкладення</a>').format(
                    msg.attachment_url
                )
            if msg.direction == 'incoming':
                # Клієнт — підставляємо партнера, щоб не було Public User (Olha Lipowa)
                author_id = (
                    self.partner_id.id if self.partner_id else self.env.ref('base.partner_root').id
                )
            else:
                # Оператор — використовуємо OdooBot (менеджер невідомий)
                author_id = self.env.ref('base.partner_root').id
            channel.with_context(sendpulse_incoming=True).message_post(
                body=body,
                author_id=author_id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        self.write(
            {
                'channel_id': channel.id,
                'stage': 'in_progress',
            }
        )

        if send_greeting:
            self._send_autoreply_greeting(channel)

        return channel

    def _send_autoreply_greeting(self, channel=None):
        """
        Надсилає два автоматичних повідомлення клієнту через SendPulse
        і дублює їх в discuss.channel щоб менеджер бачив контекст.

        Тексти конфігуруються через System Parameters:
          odoo_chatwoot_connector.greeting_enabled      ('True'/'False', за замовч. 'True')
          odoo_chatwoot_connector.new_contact_greeting  (перше повідомлення)
          odoo_chatwoot_connector.new_contact_greeting2 (друге повідомлення, необов'язкове)
        """
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()

        if params.get_param('odoo_chatwoot_connector.greeting_enabled', 'True') != 'True':
            return

        messages = [
            params.get_param(
                'odoo_chatwoot_connector.new_contact_greeting',
                'Доброго дня! 👋 Дякуємо за звернення до CampScout. '
                'Наш менеджер відповість вам найближчим часом 🙂',
            ),
            params.get_param(
                'odoo_chatwoot_connector.new_contact_greeting2',
                'Поки очікуєте, можете переглянути питання інших батьків та відповіді на них: '
                'https://campscout.eu/pitannia-batkiv',
            ),
        ]
        messages = [m for m in messages if m]
        if not messages:
            return

        ch = channel or self.channel_id
        now = fields.Datetime.now()

        for text in messages:
            # Зберігаємо ДО відправки — щоб outbound_message webhook одразу знайшов запис
            # і не задублював повідомлення у discuss.channel
            # (post_to_channel/record_partner_message=False: цей сайт постить у канал
            # САМ, нижче, ПІСЛЯ спроби send_message_to_sendpulse — порядок «create →
            # send → post» лишається як був, helper тут відповідає лише за create)
            self._record_conversation_message(
                self,
                direction='outgoing',
                sendpulse_contact_id=self.sendpulse_contact_id,
                message_type='text',
                text_message=text,
                raw_json={'text': text, 'source': 'auto_greeting'},
                date=now,
                post_to_channel=False,
                record_partner_message=False,
            )

            # Надсилаємо клієнту через SendPulse
            try:
                self.send_message_to_sendpulse(text)
            except Exception as e:
                _logger.warning('SendPulse auto-greeting send failed for %s: %s', self.name, e)

            # Постимо в канал щоб менеджер бачив (з OdooBot як автором)
            if ch:
                ch.with_context(sendpulse_incoming=True).message_post(
                    body=Markup('🤖 <i>Авто-привітання:</i> {}').format(escape(text)),
                    author_id=self.env.ref('base.partner_root').id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

    def _get_service_label(self):
        labels = {
            'telegram': 'TG',
            'instagram': 'IG',
            'facebook': 'FB',
            'messenger': 'MSG',
            'viber': 'VB',
            'whatsapp': 'WA',
            'tiktok': 'TT',
            'livechat': 'LC',
        }
        return labels.get(self.service, self.service or '?')

    def _get_channel_description(self):
        parts = [f'SendPulse | {self.service or "?"}']
        if self.social_username:
            parts.append(f'@{self.social_username}')
        if self.social_profile_url:
            parts.append(self.social_profile_url)
        if self.unidentified_email:
            parts.append(self.unidentified_email)
        return ' | '.join(parts)

    def _close_channel(self):
        """Канал НЕ архівується — щоб не втрачати історію переписки."""
        pass

    def action_sync_discuss_channels(self):
        """
        Масова синхронізація Discuss-каналів:
        - Для розмов без каналу → створює новий channel
        - Для розмов з каналом → нічого (менеджери долучаються самостійно)

        Викликається вручну з list-view (кнопка Action).
        """
        created = 0
        skipped = 0
        for connect in self:
            if connect.stage == 'close':
                continue
            if not connect.channel_id:
                connect._create_discuss_channel()
                created += 1
            else:
                skipped += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'SendPulse: Sync завершено',
                'message': f'Створено каналів: {created}. Вже мають канал: {skipped}.',
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def cron_sync_discuss_channels(self):
        """
        Автоматична синхронізація Discuss-каналів (планувальник задач).
        Знаходить активні розмови без каналу та створює їх.
        """
        connects_without_channel = self.search(
            [
                ('stage', '!=', 'close'),
                ('channel_id', '=', False),
            ]
        )
        if connects_without_channel:
            _logger.info(
                'SendPulse Odoo cron: знайдено %d розмов без каналу, синхронізуємо...',
                len(connects_without_channel),
            )
            connects_without_channel.action_sync_discuss_channels()

    def _post_history_to_partner(self):
        """Зберігає всі повідомлення у вкладці Messaging картки партнера."""
        self.ensure_one()
        if not self.partner_id:
            return
        # Дедуплікація: не дублювати якщо викликається повторно (assign + close)
        existing = self.env['partner.sendpulse.message'].search(
            [
                ('partner_id', '=', self.partner_id.id),
                ('service', '=', self.service),
            ]
        )
        existing_keys = {(r.date, r.direction) for r in existing}
        for msg in self.message_ids.sorted('date'):
            if (msg.date, msg.direction) not in existing_keys:
                self.env['partner.sendpulse.message'].create(
                    {
                        'partner_id': self.partner_id.id,
                        'date': msg.date,
                        'text_message': plaintext2html(msg.text_message or ''),
                        'service': self.service,
                        'direction': msg.direction,
                    }
                )

    def assign_partner(self, partner_id):
        """
        Прив'язує ідентифікованого партнера до розмови.
        Переносить усю історію в його картку.
        """
        self.ensure_one()
        self.write({'partner_id': partner_id})
        self._post_history_to_partner()
        # Оновлюємо UTM джерело у партнера
        self._update_partner_source()
        # Оновлюємо назву каналу
        if self.channel_id:
            partner = self.env['res.partner'].browse(partner_id)
            self.channel_id.write(
                {
                    'name': f'[{self._get_service_label()}] {partner.name}',
                }
            )
        # Синхронізуємо аватар у картку партнера якщо він є
        if self.avatar_url:
            self._sync_avatar_to_partner()

    def _update_partner_source(self):
        """
        Додає або оновлює запис у partner.sendpulse.channel для партнера.
        Якщо клієнт написав з кількох каналів — кожен зберігається окремо.
        """
        if not self.partner_id or not self.service:
            return

        # Знаходимо UTM джерело
        source_id = False
        utm_xml_id = UTM_SOURCE_MAP.get(self.service)
        if utm_xml_id:
            try:
                source_id = self.env.ref(utm_xml_id).id
            except Exception:
                pass

        # Шукаємо чи вже є запис для цього каналу у цього партнера
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('service', '=', self.service),
        ]
        if self.sendpulse_contact_id:
            domain.append(('sendpulse_contact_id', '=', self.sendpulse_contact_id))

        existing = self.env['partner.sendpulse.channel'].search(domain, limit=1)

        if existing:
            # Оновлюємо дату останнього контакту і лічильник
            update_vals = {'last_contact_date': fields.Datetime.now()}
            if self.social_username and not existing.social_username:
                update_vals['social_username'] = self.social_username
            if self.social_profile_url and not existing.social_profile_url:
                update_vals['social_profile_url'] = self.social_profile_url
            existing.write(update_vals)
            # savepoint: конкурентні webhook-и на той самий канал інколи
            # ловлять serialization failure на цьому UPDATE. Без savepoint
            # виняток абортує ВСЮ транзакцію запиту — разом з уже створеним
            # sendpulse.message і webhook-audit записом (повідомлення клієнта
            # зникає безслідно, а SendPulse все одно отримує 200 і не ретраїть).
            # message_count — лічильник для UI картки партнера, не критичний:
            # краще відстане на 1, ніж зжере реальне повідомлення.
            try:
                with self.env.cr.savepoint():
                    existing._cr.execute(
                        'UPDATE partner_sendpulse_channel SET message_count = message_count + 1 WHERE id = %s',
                        (existing.id,),
                    )
            except Exception as e:
                _logger.warning(
                    'SendPulse Odoo: message_count increment skipped (channel=%s) — %s',
                    existing.id,
                    e,
                )
        else:
            # Новий канал для цього партнера — створюємо запис
            self.env['partner.sendpulse.channel'].create(
                {
                    'partner_id': self.partner_id.id,
                    'service': self.service,
                    'sendpulse_contact_id': self.sendpulse_contact_id or False,
                    'social_username': self.social_username or False,
                    'social_profile_url': self.social_profile_url or False,
                    'source_id': source_id or False,
                    'first_contact_date': fields.Datetime.now(),
                    'last_contact_date': fields.Datetime.now(),
                    'message_count': 1,
                }
            )

    # ════════════════════════════════════════════════════════════════════
    # Сповіщення
    # ════════════════════════════════════════════════════════════════════

    def _notify_operators_new_conversation(self):
        """Сповіщає операторів про нову розмову через Odoo Discuss."""
        group = self.env.ref(
            'odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False
        )
        if not group:
            return
        partner_ids = group.users.mapped('partner_id').ids
        if partner_ids:
            self.env['bus.bus']._sendmany(
                [
                    (
                        partner_id,
                        'simple_notification',
                        {
                            'title': _('SendPulse: Нова розмова'),
                            'message': f'{self.service_icon} {self.name}: нова розмова з {self.service or "SendPulse"}',
                            'sticky': False,
                        },
                    )
                    for partner_id in partner_ids
                ]
            )

    def _notify_operators_new_message(self):
        """Сповіщає операторів про нове повідомлення (throttle: 1/год)."""
        now = datetime.now()
        if self.last_notified_at and (now - self.last_notified_at) < timedelta(hours=1):
            return
        self.write({'last_notified_at': now})
        target_partners = []
        if self.user_ids:
            target_partners = self.user_ids.mapped('partner_id').ids
        else:
            group = self.env.ref(
                'odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False
            )
            if group:
                target_partners = group.users.mapped('partner_id').ids
        if target_partners:
            self.env['bus.bus']._sendmany(
                [
                    (
                        pid,
                        'simple_notification',
                        {
                            'title': _('SendPulse: Нове повідомлення'),
                            'message': f'{self.service_icon} {self.name}: {self.last_message_preview or "..."}',
                            'sticky': False,
                        },
                    )
                    for pid in target_partners
                ]
            )

    # ════════════════════════════════════════════════════════════════════
    # Webhook Processing — викликається з controllers/main.py
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def _record_conversation_message(
        self,
        connect,
        *,
        direction,
        sendpulse_contact_id,
        message_type='text',
        text_message='',
        attachment_url=False,
        raw_json=None,
        date=None,
        channel_body=None,
        channel_attachment_ids=None,
        channel_author_id=None,
        post_to_channel=True,
        partner_body=None,
        record_partner_message=True,
    ):
        """Спільний helper для патерну "sendpulse.message → message_post
        (discuss.channel) → partner.sendpulse.message", який раніше був
        незалежно продубльований (і трохи розходився) у 3 місцях:
        `_send_autoreply_greeting`, `_process_incoming_event`,
        `_process_outgoing_event` (backfill missed incoming).

        Це МЕХАНІЧНА екстракція — кожен call-site і далі керує СВОЇМ
        форматуванням (media-іконки, backfill-нотатка, greeting-emoji) і
        своїми умовами; helper лише виконує сам ORM create/post. Деякі
        call-site'и (greeting, incoming-media) свідомо викликають helper
        лише для кроку `sendpulse.message.create` (post_to_channel=False,
        record_partner_message=False) і лишають message_post /
        partner.sendpulse.message на місці — бо там між кроками є
        side-effecting виклики (send_message_to_sendpulse,
        _check_and_record_unsubscribe), чий порядок відносно
        message_post/partner-create — частина поточної поведінки і його
        не можна безпечно перемішати без зміни функціональності.

        Повертає створений sendpulse.message.
        """
        now = date or fields.Datetime.now()
        msg = self.env['sendpulse.message'].create(
            {
                'name': now.strftime('%Y-%m-%d %H:%M'),
                'date': now,
                'connect_id': connect.id,
                'sendpulse_contact_id': sendpulse_contact_id,
                'direction': direction,
                'message_type': message_type,
                'text_message': text_message,
                'attachment_url': attachment_url,
                'raw_json': str(raw_json) if raw_json is not None else '',
            }
        )

        if (
            post_to_channel
            and connect.channel_id
            and (channel_body is not None or channel_attachment_ids)
        ):
            post_kwargs = {
                'body': channel_body if channel_body is not None else '',
                'author_id': channel_author_id or False,
                'message_type': 'comment',
                'subtype_xmlid': 'mail.mt_comment',
            }
            if channel_attachment_ids:
                post_kwargs['attachment_ids'] = channel_attachment_ids
            connect.channel_id.with_context(sendpulse_incoming=True).message_post(**post_kwargs)

        if record_partner_message and connect.partner_id and partner_body is not None:
            self.env['partner.sendpulse.message'].create(
                {
                    'partner_id': connect.partner_id.id,
                    'date': now,
                    'text_message': partner_body,
                    'service': connect.service,
                    'direction': direction,
                }
            )

        return msg

    # ── V2 F5: Auto-close inactive conversations ──────────────────────────
    @api.model
    def cron_auto_close_inactive(self):
        """
        Щоденний cron. Закриває розмови з stage in_progress/new_message
        якщо клієнт не писав auto_close_inactive_days днів.
        Не чіпає розмови з активним crm.lead у non-cold стадіях.
        Опційно — шле goodbye message якщо 24h-вікно Meta відкрите.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.auto_close_inactive_enabled', 'False') != 'True':
            return
        try:
            days = int(ICP.get_param('odoo_chatwoot_connector.auto_close_inactive_days', '7'))
        except (ValueError, TypeError):
            days = 7
        goodbye = ICP.get_param('odoo_chatwoot_connector.auto_close_goodbye_text', '') or ''
        threshold = fields.Datetime.now() - timedelta(days=days)

        candidates = self.search(
            [
                ('stage', 'in', ['in_progress', 'new_message']),
                ('last_message_date', '<', threshold),
                ('sp_first_inbound_at', '<', threshold),
            ]
        )
        closed_count = 0
        goodbye_sent = 0
        for rec in candidates:
            # Не чіпаємо якщо є активний (не won/lost) лід — sales team ще працює
            if rec.sp_lead_id and rec.sp_lead_id.type == 'opportunity' and rec.sp_lead_id.active:
                continue
            # Goodbye повідомлення (якщо є шаблон + 24h вікно відкрите)
            now = fields.Datetime.now()
            window_open = (
                not rec.sp_messenger_window_expires_at or rec.sp_messenger_window_expires_at > now
            )
            if goodbye and window_open and not rec.sp_is_comment:
                try:
                    rec.send_message_to_sendpulse(goodbye, attachment_url=None)
                    goodbye_sent += 1
                except Exception as e:
                    _logger.warning(
                        'SendPulse Odoo: goodbye send failed for connect %s: %s', rec.id, e
                    )
            rec.write({'stage': 'close'})
            closed_count += 1
        _logger.info(
            'SendPulse Odoo: cron_auto_close_inactive — closed %d, goodbye sent %d',
            closed_count,
            goodbye_sent,
        )

    @api.model
    def _find_partner(self, contact_id, email, phone, variables=None):
        """
        Шукає партнера в такому порядку пріоритетів:
        1. sendpulse_contact_id (якщо вже бачили цей контакт)
        2. email (з даних контакту SendPulse)
        3. user_email з bot-змінних (те, що клієнт ввів у боті)
        4. booking_email з bot-змінних
        5. phone
        """
        variables = variables or {}

        if contact_id:
            partner = self.env['res.partner'].search(
                [('sendpulse_contact_id', '=', contact_id)], limit=1
            )
            if partner:
                return partner

        def _search_by_email(addr):
            if not addr:
                return None
            p = self.env['res.partner'].search([('email', '=ilike', addr.strip())], limit=1)
            if p and not p.sendpulse_contact_id:
                p.write({'sendpulse_contact_id': contact_id})
            return p or None

        partner = _search_by_email(email)
        if partner:
            return partner

        # Fallback: email зібраний ботом (user_email)
        partner = _search_by_email(variables.get('user_email', ''))
        if partner:
            return partner

        # Fallback: email для бронювання (booking_email)
        partner = _search_by_email(variables.get('booking_email', ''))
        if partner:
            return partner

        if phone:
            clean_phone = phone.strip().replace(' ', '')
            partner = self.env['res.partner'].search(
                ['|', ('phone', '=', clean_phone), ('mobile', '=', clean_phone)], limit=1
            )
            if partner:
                if not partner.sendpulse_contact_id:
                    partner.write({'sendpulse_contact_id': contact_id})
                return partner

        return None

    # ════════════════════════════════════════════════════════════════════
    # RPC для OWL-панелі (Priority 2)
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def get_connect_for_channel(self, channel_id):
        """
        Повертає дані sendpulse.connect для вказаного discuss.channel ID.
        Викликається OWL-компонентом SendpulseInfoPanel.
        """
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return False

        service_labels = {
            'telegram': 'Telegram',
            'instagram': 'Instagram',
            'facebook': 'Facebook',
            'messenger': 'Messenger',
            'viber': 'Viber',
            'whatsapp': 'WhatsApp',
            'tiktok': 'TikTok',
            'livechat': 'LiveChat',
        }
        status_labels = {
            'active': 'Активний',
            'unsubscribed': 'Відписаний',
            'deleted': 'Видалений',
            'unconfirmed': 'Непідтверджений',
        }

        result = {
            'id': connect.id,
            'name': connect.name,
            'service': connect.service or '',
            'service_label': service_labels.get(connect.service, connect.service or ''),
            'stage': connect.stage,
            'social_username': connect.social_username or '',
            'social_profile_url': connect.social_profile_url or '',
            'unidentified_email': connect.unidentified_email or '',
            'unidentified_phone': connect.unidentified_phone or '',
            'sp_child_name': connect.sp_child_name or '',
            'sp_booking_email': connect.sp_booking_email or '',
            'avatar_url': connect.avatar_url or '',
            'language_code': connect.language_code or '',
            'subscription_status': connect.subscription_status or '',
            'subscription_status_label': status_labels.get(connect.subscription_status, ''),
            'partner': False,
            # F13 tracking
            'pdf_sent_at': connect.sp_pdf_sent_at
            and connect.sp_pdf_sent_at.strftime('%Y-%m-%d %H:%M')
            or '',
            'pdf_sent_to_email': connect.sp_pdf_sent_to_email or '',
            'coupon_code': connect.sp_coupon_code or '',
            'coupon_sent_at': connect.sp_coupon_sent_at
            and connect.sp_coupon_sent_at.strftime('%Y-%m-%d %H:%M')
            or '',
            'coupon_sent_to_phone': connect.sp_coupon_sent_to_phone or '',
        }
        if connect.partner_id:
            p = connect.partner_id.sudo().with_context(active_test=False)
            result['partner'] = {
                'id': p.id,
                'name': p.name,
                'email': p.email or '',
                'phone': p.phone or p.mobile or '',
                'active': bool(p.active),
            }
        # F13: prefill values для кнопок — беремо існуючий email/phone
        result['prefill_email'] = (
            connect.sp_booking_email
            or (connect.partner_id.email if connect.partner_id else '')
            or connect.unidentified_email
            or ''
        )
        result['prefill_phone'] = (
            (connect.partner_id.mobile or connect.partner_id.phone if connect.partner_id else '')
            or connect.unidentified_phone
            or ''
        )
        # F13: чи ввімкнено master-switch lead_magnet
        ICP = self.env['ir.config_parameter'].sudo()
        result['lead_magnet_enabled'] = (
            ICP.get_param('odoo_chatwoot_connector.lead_magnet_enabled', 'False') == 'True'
        )
        return result

    def unarchive_partner_for_channel(self, channel_id):
        """
        Розархівує partner прив'язаний до SendPulse-каналу. Викликається з InfoPanel,
        коли оператор клацає «Розархівувати» над badge "Контакт в архіві".
        Discuss не показує аватар archived партнера у bubble — цей метод повертає видимість.
        """
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect or not connect.partner_id:
            return {'ok': False, 'error': 'no_partner'}
        p = connect.partner_id.sudo().with_context(active_test=False)
        if p.active:
            return {'ok': True, 'already_active': True}
        p.write({'active': True})
        return {'ok': True, 'partner_id': p.id, 'partner_name': p.name}
