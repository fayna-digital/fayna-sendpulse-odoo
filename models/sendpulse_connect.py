import base64
import hashlib
import logging
import time
from datetime import datetime, timedelta

import requests
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

        if post_to_channel and connect.channel_id and (
            channel_body is not None or channel_attachment_ids
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

    @api.model
    def _process_incoming_event(self, data, contact, bot, service, event_type, timestamp_ms):
        """
        Обробляє вхідну подію з SendPulse webhook.
        Логіка:
          1. Шукаємо партнера по email або sendpulse_contact_id
          2. Якщо знайдено — прив'язуємо розмову до партнера
          3. Якщо ні — створюємо нову розмову в черзі "Не ідентифікований"
          4. Зберігаємо повідомлення
          5. Якщо розмова нова — створюємо discuss.channel
        """
        # ── Перевірка: чи це коментар під постом FB/IG ─────────────────────
        channel_data_msg = (
            ((data.get('info') or {}).get('message') or {}).get('channel_data') or {}
        ).get('message') or {}
        is_comment = isinstance(channel_data_msg, dict) and (
            # Facebook format: item/verb
            (channel_data_msg.get('item') == 'comment' and channel_data_msg.get('verb') == 'add')
            # Instagram via SendPulse: media.media_product_type == FEED
            or (
                isinstance(channel_data_msg.get('media'), dict)
                and channel_data_msg['media'].get('media_product_type') == 'FEED'
            )
        )
        if is_comment:
            return self._process_comment_event(
                data=data,
                contact=contact,
                bot=bot,
                service=service,
                channel_data_msg=channel_data_msg,
            )

        contact_id = contact.get('id', '')
        contact_name = contact.get('name', 'Невідомий')
        email = contact.get('email', '') or ''
        phone = contact.get('phone', '') or ''
        last_message = contact.get('last_message', '') or ''
        variables = contact.get('variables', {}) or {}

        # Визначаємо тип медіа з last_message_data (якщо є)
        last_message_data = contact.get('last_message_data', {}) or {}
        msg_data = last_message_data.get('message', {}) or {}
        msg_type = (
            msg_data.get('type', 'text') or 'text'
        )  # text, image, sticker, audio, video, document

        # Fallback: якщо last_message виглядає як media URL — вважаємо image
        _MEDIA_URL_PATTERNS = ('lookaside.fbsbx.com', '/messages/media', 'chatbots-service')
        _MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mp3', '.ogg')
        if msg_type == 'text' and last_message.startswith('http'):
            if any(p in last_message for p in _MEDIA_URL_PATTERNS) or any(
                last_message.lower().endswith(e) for e in _MEDIA_EXTENSIONS
            ):
                msg_type = 'image'

        # Соціальні ідентифікатори
        social_username = (
            variables.get('username')
            or variables.get('telegram_username')
            or contact.get('username', '')
        )
        social_profile_url = (
            variables.get('profile_url')
            or variables.get('facebook_url')
            or variables.get('instagram_url')
            or ''
        )
        # Для Telegram будуємо URL профілю з username якщо немає
        if not social_profile_url and social_username and service == 'telegram':
            social_profile_url = f'https://t.me/{social_username}'

        # Фото контакту з webhook
        photo_url = (contact.get('photo') or contact.get('profile_pic') or '').strip() or ''

        # ── Bot-змінні ────────────────────────────────────────────────────
        sp_child_name = (variables.get('child_name') or '').strip() or False
        sp_booking_email = (variables.get('booking_email') or '').strip() or False
        # Якщо email порожній у контакті — беремо з user_email бота
        effective_email = email or (variables.get('user_email') or '').strip()

        # ── Крок 1: Ідентифікація партнера ──────────────────────────────
        partner = self._find_partner(contact_id, effective_email, phone, variables=variables)

        # ── Race-guard: advisory lock на (contact_id, service) ──────────
        # Два одночасних webhook-и (new_subscriber + incoming_message за ~1 сек)
        # раніше створювали два записи (search→∅→create у обох). Тепер другий
        # чекає COMMIT першого, тоді бачить створений запис і оновлює його
        # замість створення дублю. Авто-привітання теж не дублюється бо
        # is_brand_new=False у другого.
        if contact_id:
            lock_key1 = (
                int(hashlib.md5(f'{contact_id}|{service}'.encode()).hexdigest()[:8], 16)
                & 0x7FFFFFFF
            )
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (lock_key1, _SENDPULSE_INBOUND_LOCK_KEY2),
            )
            # Примусовий flush + invalidate cache щоб search після lock
            # повертав актуальний стан (включно з записом створеним іншим
            # worker-ом який щойно commit-нув).
            self.env.flush_all()
            self.env.invalidate_all()

        # ── Крок 2: Знаходимо або створюємо розмову ─────────────────────
        # Пріоритет 1: активна розмова по sendpulse_contact_id + service
        connect = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ],
            limit=1,
        )

        # Пріоритет 2: якщо партнер відомий — шукаємо активний чат по partner_id + service.
        # Це запобігає створенню дублікатів коли один реальний клієнт має кілька
        # контактів у SendPulse (наприклад, тестовий + реальний).
        if not connect and partner:
            connect = self.search(
                [
                    ('partner_id', '=', partner.id),
                    ('service', '=', service),
                    ('stage', '!=', 'close'),
                ],
                order='write_date desc',
                limit=1,
            )
            if connect and connect.sendpulse_contact_id != contact_id:
                # Оновлюємо contact_id на актуальний
                connect.write({'sendpulse_contact_id': contact_id})

        # Пріоритет 3: закрита розмова того ж контакту — перевідкриваємо замість створення нової
        if not connect:
            connect = self.search(
                [
                    ('sendpulse_contact_id', '=', contact_id),
                    ('service', '=', service),
                    ('stage', '=', 'close'),
                ],
                order='write_date desc',
                limit=1,
            )
            if connect:
                connect.write({'stage': 'new'})
                # Розархівовуємо discuss.channel якщо він був архівований при закритті
                if connect.channel_id:
                    connect.channel_id.write({'active': True})

        now = fields.Datetime.now()
        is_brand_new = not connect  # True тільки якщо connect щойно буде створено
        if not connect:
            create_vals = {
                'name': contact_name,
                'sendpulse_contact_id': contact_id,
                'service': service,
                'bot_id': bot.get('id', ''),
                'bot_name': bot.get('name', ''),
                'sp_child_name': sp_child_name or False,
                'sp_booking_email': sp_booking_email or False,
                'partner_id': partner.id if partner else False,
                'unidentified_email': effective_email if not partner else False,
                'unidentified_phone': phone if not partner else False,
                'social_username': social_username or False,
                'social_profile_url': social_profile_url or False,
                'last_message_preview': last_message[:100] if last_message else '',
                'last_message_date': now,
                'stage': 'new',
            }
            # Partial unique index у init() фізично блокує дублі. Ловимо
            # IntegrityError через savepoint, якщо випадково створюємо дубль —
            # відкочуємо create і підхоплюємо existing запис.
            from psycopg2 import IntegrityError

            try:
                with self.env.cr.savepoint():
                    connect = self.create(create_vals)
            except IntegrityError:
                _logger.info(
                    'SendPulse Odoo: race duplicate intercepted by unique index — '
                    'contact=%s service=%s',
                    contact_id,
                    service,
                )
                self.env.invalidate_all()
                connect = self.search(
                    [
                        ('sendpulse_contact_id', '=', contact_id),
                        ('service', '=', service),
                        ('stage', '!=', 'close'),
                    ],
                    limit=1,
                )
                if not connect:
                    # Дуже дивний стан — IntegrityError на unique, але search не знаходить
                    raise
                is_brand_new = False
            else:
                # Fallback race-guard (backup до unique index): find older duplicate
                duplicate = self.search(
                    [
                        ('sendpulse_contact_id', '=', contact_id),
                        ('service', '=', service),
                        ('stage', '!=', 'close'),
                        ('id', '<', connect.id),
                    ],
                    limit=1,
                )
                if duplicate:
                    connect.unlink()
                    connect = duplicate
                    is_brand_new = False

            # V2 F3: якщо brand-new і без партнера — бот сам запитає email
            # замість stage=new (чекання оператора). Повертає True якщо flow запустився.
            if is_brand_new and not partner:
                if connect._try_start_identification():
                    # Bot-wizard активний — не продовжуємо normal flow
                    # (не шлемо auto-greeting, не постимо у канал як стандартний inbound)
                    return connect
        else:
            # V2 F3: якщо розмова на стадії identifying — спробуємо parse email з inbound
            if connect.stage == 'identifying':
                handled = connect._try_advance_identification(last_message or '')
                if handled and connect.stage == 'identifying':
                    # Все ще identifying (retry) — не продовжуємо normal flow
                    return connect
                # Якщо identifying завершилось (done/gave_up) — продовжуємо з update_vals
                # щоб повідомлення клієнта потрапило у chatter як нормально

            # Оновлюємо існуючу розмову
            update_vals = {
                'last_message_preview': last_message[:100]
                if last_message
                else connect.last_message_preview,
                'last_message_date': now,
                'stage': 'new_message' if connect.stage == 'in_progress' else connect.stage,
                # Клієнт написав → вікно 24h відновлюється
                'sp_messenger_window_expires_at': now + timedelta(hours=24),
                'sp_window_alert_sent': False,
            }
            # Метрики: перший inbound від клієнта
            if not connect.sp_first_inbound_at:
                update_vals['sp_first_inbound_at'] = now
            # Funnel: comment_only/private_sent → customer_replied
            if connect.sp_funnel_stage in ('comment_only', 'private_sent', False, None):
                update_vals['sp_funnel_stage'] = 'customer_replied'
            if not connect.partner_id and partner:
                update_vals['partner_id'] = partner.id
            if social_username and not connect.social_username:
                update_vals['social_username'] = social_username
            if social_profile_url and not connect.social_profile_url:
                update_vals['social_profile_url'] = social_profile_url
            # Оновлюємо bot-змінні якщо вони з'явились (бот міг зібрати їх пізніше)
            if sp_child_name and not connect.sp_child_name:
                update_vals['sp_child_name'] = sp_child_name
            if sp_booking_email and not connect.sp_booking_email:
                update_vals['sp_booking_email'] = sp_booking_email
            connect.write(update_vals)

            # V2 F4: Auto-create crm.lead коли клієнт вперше відповідає у приват
            # (comment_only / private_sent → customer_replied). Ідемпотентно:
            # вже є sp_lead_id → skip. No-op якщо auto_create_lead_enabled=False.
            if update_vals.get('sp_funnel_stage') == 'customer_replied':
                connect._auto_create_crm_lead()
                # F9 A/B: зарахувати конверсію шаблону публічної відповіді (ідемпотентно)
                if (
                    connect.sp_public_template_id
                    and not connect.sp_public_template_conversion_counted
                ):
                    connect.sp_public_template_id.bump_customer_replied()
                    connect.write({'sp_public_template_conversion_counted': True})

            # V2 F1: RAG FAQ auto-answer — якщо клієнт написав питання
            # і ми маємо високий confidence на FAQ match → відповідаємо автоматично.
            # Умови: не comment-розмова, клієнт написав текст, не оператор.
            if last_message and not connect.sp_is_comment:
                connect._try_rag_auto_answer(last_message)

        # Ensure incoming Discuss messages always have a customer author,
        # never fallback to OdooBot (it breaks identity/avatar in chat UI).
        author_partner = connect.partner_id
        if not author_partner and partner:
            author_partner = partner
        if not author_partner:
            author_partner = self.env['res.partner'].search(
                [('sendpulse_contact_id', '=', contact_id)],
                order='id desc',
                limit=1,
            )
        if not author_partner:
            create_vals = {
                'name': contact_name or f'{service}:{contact_id}',
                'sendpulse_contact_id': contact_id,
            }
            if effective_email:
                create_vals['email'] = effective_email
            if phone:
                clean_phone = phone.strip().replace(' ', '')
                if clean_phone:
                    create_vals['phone'] = clean_phone
            author_partner = self.env['res.partner'].sudo().create(create_vals)
        if author_partner and not connect.partner_id:
            connect.write({'partner_id': author_partner.id})

        # ── Крок 3: Зберігаємо повідомлення ─────────────────────────────
        if last_message:
            is_image = msg_type in ('image', 'sticker')
            is_media = is_image or msg_type in ('audio', 'video', 'document')
            media_icons = {'audio': '🎵', 'video': '🎥', 'document': '📄'}

            # post_to_channel/record_partner_message=False: тут між create і
            # message_post є _check_and_record_unsubscribe (RODO), а сам
            # message_post має 3 гілки залежно від типу медіа/успіху завантаження
            # вкладення — обидва лишені на місці нижче, без змін.
            new_msg = self._record_conversation_message(
                connect,
                direction='incoming',
                sendpulse_contact_id=contact_id,
                message_type='image' if is_image else ('file' if is_media else 'text'),
                text_message='' if is_media else last_message,
                attachment_url=last_message if is_media else False,
                raw_json={'text': last_message, 'contact': contact},
                date=now,
                post_to_channel=False,
                record_partner_message=False,
            )

            # RODO: детектим unsubscribe-фрази — фіксуємо withdrawal для
            # усіх lead-magnet purposes на цьому connect.
            if not is_media and last_message:
                connect._check_and_record_unsubscribe(last_message, new_msg)

            # Якщо є активний channel — постимо туди для операторів
            if connect.channel_id:
                att = None
                if is_media:
                    att = connect._download_media_as_attachment(last_message)

                if is_image and att:
                    # Фото/стікер — скачали і показуємо як attachment.
                    # Імʼя автора Discuss малює у header bubble з author_id — у body дублювати не треба.
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body='',
                        attachment_ids=[att.id],
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                elif is_media and att:
                    icon = media_icons.get(msg_type, '📎')
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                    file_url = f'{base_url}/web/content/{att.id}?access_token={att.access_token}'
                    body = Markup("{} <a href='{}' target='_blank'>Вкладення</a>").format(
                        icon, file_url
                    )
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body=body,
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                else:
                    # Текст або fallback якщо медіа не вдалося завантажити
                    if is_media:
                        icon = media_icons.get(msg_type, '📎')
                        body = Markup("{} <a href='{}' target='_blank'>Вкладення</a>").format(
                            icon, last_message
                        )
                    else:
                        body = escape(last_message)
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body=body,
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )

            # Зберігаємо у вкладці Messaging картки партнера
            if connect.partner_id:
                if is_image:
                    partner_body = f"<img src='{last_message}' style='max-width:300px;'/>"
                elif is_media:
                    icon = media_icons.get(msg_type, '📎')
                    partner_body = f"<p>{icon} <a href='{last_message}'>Вкладення</a></p>"
                else:
                    partner_body = f'<p>{last_message}</p>'
                self.env['partner.sendpulse.message'].create(
                    {
                        'partner_id': connect.partner_id.id,
                        'date': now,
                        'text_message': partner_body,
                        'service': service,
                        'direction': 'incoming',
                    }
                )

        # ── Крок 4: Оновлюємо канали партнера ───────────────────────────
        if connect.partner_id:
            connect._update_partner_source()

        # ── Крок 5: Якщо немає каналу — створюємо discuss.channel ──────
        if not connect.channel_id:
            connect._create_discuss_channel(send_greeting=is_brand_new)

        return connect

    # ════════════════════════════════════════════════════════════════════
    # Коментарі Facebook / Instagram — автовідповідь
    # ════════════════════════════════════════════════════════════════════

    # Ротаційні шаблони публічної відповіді (fallback якщо БД порожня).
    # Основний шлях — sendpulse.public.template (data/sendpulse_public_templates_seed.xml).
    # {name}, {landing_url}, {tg_url} підставляються з runtime.
    _COMMENT_PUBLIC_TEMPLATES = [
        "{name}, дякуємо за коментар! 🏕️\n\nНа жаль, наразі ми не маємо змоги написати вам у приват.\nНапишіть нам сюди у відповідь — ми на зв'язку 24/7 ✨\n\nВся інформація про табори:\n🌐 {landing_url}",
        'Привіт, {name}! 🌟 Дякуємо що написали.\n\nЗараз технічно не виходить відповісти вам у приват —\nтому пишіть нам прямо тут, у коментарях. Відповідаємо цілодобово!\n\nДеталі про програми, дати й вартість 👇\n🌐 {landing_url}',
        '{name}, рада/радий бачити ваше повідомлення! 🏕️✨\n\nНа жаль, написати вам у Messenger зараз не можемо.\nПишіть нам тут — ми онлайн 24/7 і швидко відповімо.\n\nПрограма, безпека, харчування, ціни — все тут:\n🌐 {landing_url}',
        "Дякуємо за інтерес, {name}! 🌲\n\nНа жаль, наша сторінка зараз не може ініціювати приватну розмову.\nЗалиште питання у відповіді на цей коментар — ми на зв'язку без вихідних, 24/7 💬\n\nУся інформація про табори 2026:\n🌐 {landing_url}",
        '{name}, вітаємо! 🏕️\n\nТехнічно не маємо змоги написати вам у приватні повідомлення.\nТож запитуйте сміливо тут — відповідаємо у будь-який час, 24/7! ⚡\n\nУсі деталі про табори — за посиланням:\n🌐 {landing_url}',
        'Привіт, {name}! 💛\n\nДякуємо за коментар. Приватно написати вам, на жаль, не вдається —\nале ми тут поруч у коментарях, відповідаємо цілодобово.\n\nВсе про наші табори (програма / ціни / умови):\n🌐 {landing_url}',
        "{name}, дякуємо що цікавитесь! 🌟\n\nНаразі не маємо технічної можливості написати вам у Messenger.\nПитайте просто тут у коментарі — ми на зв'язку 24/7 і відповімо швидко 🚀\n\nВсе про табори CampScout 2026:\n🌐 {landing_url}",
    ]

    _COMMENT_PUBLIC_REPEAT_TEMPLATE = 'Раді бачити вас знову! 😊 Наш менеджер вже напише вам у повідомленнях — слідкуйте за вхідними 🏕️'

    @api.model
    def _process_comment_event(self, data, contact, bot, service, channel_data_msg):
        """
        Обробляє коментар під постом Facebook/Instagram.
        1. Дедуплікація по comment_id
        2. Знайти/створити sendpulse.connect (sp_is_comment=True)
        3. Публічна відповідь під коментарем (Graph API) — завжди
        4. Приватне повідомлення (Graph API) — тільки якщо перший коментар від контакту
        5. Нотатка оператору у Discuss
        """
        contact_id = contact.get('id', '')
        contact_name = contact.get('name', 'Невідомий')
        channel_data = data.get('info', {}).get('message', {}).get('channel_data', {})
        # FB: comment_id/message; IG via SendPulse: id/text
        comment_id = str(channel_data_msg.get('comment_id') or channel_data_msg.get('id') or '')
        comment_text = channel_data_msg.get('message') or channel_data_msg.get('text') or ''
        post_id = str(
            channel_data_msg.get('post_id')
            or (channel_data_msg.get('media') or {}).get('id')
            or (channel_data.get('media') or {}).get('id')
            or ''
        )
        post_url = (
            (channel_data_msg.get('post') or {}).get('permalink_url')
            or (channel_data.get('media') or {}).get('permalink')
            or ''
        )

        # Перевіряємо чи увімкнена автовідповідь
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.sp_comment_autoreply_enabled', 'True') != 'True':
            _logger.info('SendPulse Odoo: comment autoreply disabled, skipping %s', comment_id)
            return None

        # Multi-page: резолвимо Facebook Page запис з webhook page_id
        page_id_from_payload = str(channel_data_msg.get('page_id') or '')
        Page = self.env['sendpulse.facebook.page'].sudo()
        page = Page.find_by_page_id(page_id_from_payload) if page_id_from_payload else Page.browse()

        # Self-loop guard: не відповідаємо на коментарі від самої Сторінки / IG Business акаунта.
        # Без цього наша публічна відповідь → webhook → нова відповідь → нескінченний цикл.
        from_id = str((channel_data_msg.get('from') or {}).get('id') or '')
        # Збираємо всі свої ID: з webhook + legacy ig_user_id + з усіх активних Page-ів
        own_ids = {x for x in [page_id_from_payload] if x}
        legacy_ig = ICP.get_param('odoo_chatwoot_connector.ig_user_id', '')
        if legacy_ig:
            own_ids.add(legacy_ig)
        for p in Page.search([('active', '=', True)]):
            if p.page_id:
                own_ids.add(p.page_id)
            if p.ig_business_id:
                own_ids.add(p.ig_business_id)
        if from_id and from_id in own_ids:
            _logger.info(
                'SendPulse Odoo: self-comment detected (from=%s == own), skipping %s',
                from_id,
                comment_id,
            )
            return None

        # Race-guard: advisory lock на comment_id — якщо той самий webhook
        # прийде двічі одночасно (SendPulse іноді ретраїть), другий чекає.
        if comment_id:
            lock_key1 = (
                int(hashlib.md5(f'comment|{comment_id}'.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
            )
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (lock_key1, _SENDPULSE_INBOUND_LOCK_KEY2),
            )

        # Дедуплікація: той самий comment_id вже оброблявся
        if comment_id:
            existing = self.search([('sp_comment_id', '=', comment_id)], limit=1)
            if existing:
                _logger.info('SendPulse Odoo: comment %s already processed, skipping', comment_id)
                return existing

        # Знаходимо/створюємо розмову
        connect = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
                ('sp_is_comment', '=', True),
            ],
            limit=1,
        )

        now = fields.Datetime.now()
        if not connect:
            connect = self.create(
                {
                    'name': contact_name,
                    'sendpulse_contact_id': contact_id,
                    'service': service,
                    'bot_id': bot.get('id', ''),
                    'bot_name': bot.get('name', ''),
                    'stage': 'new',
                    'sp_is_comment': True,
                    'sp_comment_id': comment_id,
                    'sp_comment_text': comment_text[:500] if comment_text else '',
                    'sp_post_id': post_id,
                    'sp_post_url': post_url,
                    'sp_page_id': page_id_from_payload or (page.page_id if page else ''),
                    'last_message_preview': f'💬 Коментар: {comment_text[:80]}'
                    if comment_text
                    else '💬 Коментар',
                    'last_message_date': now,
                    'sp_funnel_stage': 'comment_only',
                }
            )
        else:
            connect.write(
                {
                    'sp_comment_id': comment_id,
                    'sp_comment_text': comment_text[:500] if comment_text else '',
                    'sp_post_id': post_id,
                    'sp_post_url': post_url,
                    'sp_page_id': page_id_from_payload or connect.sp_page_id,
                    'last_message_preview': f'💬 Коментар: {comment_text[:80]}'
                    if comment_text
                    else '💬 Коментар',
                    'last_message_date': now,
                }
            )

        if not connect.channel_id:
            connect._create_discuss_channel()

        # LLM-класифікація коментаря (якщо увімкнено)
        category = self._classify_comment(comment_text, service)
        connect.write({'sp_comment_category': category})
        _logger.info('SendPulse Odoo: comment %s classified as "%s"', comment_id, category)

        # Визначаємо чи надсилати приватне (тільки перший раз для цього контакту)
        already_private = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('sp_replied_private', '=', True),
            ],
            limit=1,
        )
        # Не спамимо людей у яких вже є прямий діалог (не comment)
        has_direct_dialog = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('sp_is_comment', '=', False),
            ],
            limit=1,
        )
        send_private = (
            not bool(already_private)
            and not bool(has_direct_dialog)
            and ICP.get_param('odoo_chatwoot_connector.sp_comment_private_enabled', 'True')
            == 'True'
        )

        send_public = (
            ICP.get_param('odoo_chatwoot_connector.sp_comment_public_enabled', 'True') == 'True'
        )

        # Маршрутизація за категорією (якщо класифікатор увімкнено і дав результат != 'other'):
        # - thanks / spam: не відповідаємо взагалі (автовідповідь на подяку виглядає бот-подібно)
        # - complaint: не автовідповідь, лише нотатка оператору з мітою 🚨 (ескалація)
        # - question_*: поточна логіка (публічна + приватна) — без змін
        if category in ('thanks', 'spam'):
            _logger.info(
                'SendPulse Odoo: category=%s → skip auto-reply for %s', category, comment_id
            )
            send_public = False
            send_private = False
            # Для spam — приховуємо коментар через Graph API (якщо увімкнено)
            if (
                category == 'spam'
                and ICP.get_param('odoo_chatwoot_connector.sp_comment_hide_spam_enabled', 'True')
                == 'True'
                and comment_id
            ):
                hide_ok, hide_err = connect._hide_comment(comment_id, service, page=page)
                if hide_ok:
                    _logger.info('SendPulse Odoo: spam comment %s hidden', comment_id)
                    self._notify_telegram(
                        f'🚫 <b>Спам приховано</b>\n'
                        f'Клієнт: {contact_name}\n'
                        f'Текст: <i>{(comment_text or "")[:200]}</i>\n'
                        f'{post_url}',
                        silent=True,
                    )
                else:
                    _logger.warning(
                        'SendPulse Odoo: failed to hide spam %s: %s', comment_id, hide_err
                    )
        elif category == 'complaint':
            _logger.warning(
                'SendPulse Odoo: complaint detected → escalation, no auto-reply for %s', comment_id
            )
            send_public = False
            send_private = False
            self._notify_telegram(
                f'🚨 <b>СКАРГА під постом</b> — потрібна увага!\n\n'
                f'👤 Клієнт: <b>{contact_name}</b>\n'
                f'📝 Текст: <i>{(comment_text or "")[:500]}</i>\n\n'
                f'🔗 Допис: {post_url or "—"}'
            )

        # Тексти з підстановкою URL (per-page override → глобальний ICP → дефолт)
        landing_url = (page.landing_url if page else '') or ICP.get_param(
            'odoo_chatwoot_connector.sp_comment_landing_url', 'https://lato2026.campscout.eu'
        )
        tg_url = (page.tg_url if page else '') or ICP.get_param(
            'odoo_chatwoot_connector.sp_comment_tg_url', 'https://t.me/campscouting'
        )

        # Публічна відповідь
        public_ok = False
        public_error = None
        if send_public and comment_id:
            # Ім'я для звертання у шаблоні. SendPulse webhook кладе FB profile name
            # у contact.name; коли пусто або default — використовуємо нейтральне.
            display_name = contact_name if contact_name and contact_name != 'Невідомий' else 'друже'
            # F9: Вибір шаблону через модель sendpulse.public.template (epsilon-greedy).
            # Fallback на hard-coded константи якщо модель порожня (міграція не
            # виконана або всі шаблони деактивовано).
            PublicTemplate = self.env['sendpulse.public.template'].sudo()
            template = PublicTemplate.pick_template(is_repeat=bool(already_private))
            if template:
                public_text = template.text.format(
                    name=display_name,
                    landing_url=landing_url or 'https://lato2026.campscout.eu',
                    tg_url=tg_url or 'https://t.me/campscouting',
                )
            elif bool(already_private):
                public_text = self._COMMENT_PUBLIC_REPEAT_TEMPLATE
            else:
                # Fallback: старий round-robin по константах
                if post_id:
                    count = self.search_count(
                        [
                            ('sp_is_comment', '=', True),
                            ('sp_post_id', '=', post_id),
                            ('sp_replied_public', '=', True),
                        ]
                    )
                else:
                    count = self.search_count([('sp_is_comment', '=', True)])
                tmpl = self._COMMENT_PUBLIC_TEMPLATES[count % len(self._COMMENT_PUBLIC_TEMPLATES)]
                public_text = tmpl.format(
                    name=display_name,
                    landing_url=landing_url or 'https://lato2026.campscout.eu',
                    tg_url=tg_url or 'https://t.me/campscouting',
                )
            public_ok, public_error = connect._send_comment_public_reply(
                comment_id, service, public_text, page=page
            )
            if public_ok:
                vals = {'sp_replied_public': True}
                if template:
                    vals['sp_public_template_id'] = template.id
                connect.write(vals)
                if template:
                    template.bump_use()

        # Приватне повідомлення
        private_ok = False
        private_error = None
        if send_private and comment_id:
            yt_url = ICP.get_param(
                'odoo_chatwoot_connector.sp_comment_yt_url',
                'https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
            )
            private_text_tmpl = ICP.get_param(
                'odoo_chatwoot_connector.sp_comment_private_text',
                '',
            )
            if not private_text_tmpl:
                private_text_tmpl = (
                    'Вітаємо! 🏕️ Дякуємо за ваш коментар під нашим постом.\n\n'
                    'Підготували для вас відповіді на найпоширеніші запитання — '
                    'безпека, програма, харчування, вартість, терміни:\n'
                    '🎬 {yt_url}\n\n'
                    'Вся актуальна інформація про табори 2026 також тут:\n'
                    '🌐 {landing_url}\n\n'
                    'Якщо залишились питання — пишіть тут, відповімо особисто! 😊'
                )
            private_text = private_text_tmpl.format(
                landing_url=landing_url or 'https://lato2026.campscout.eu',
                tg_url=tg_url or 'https://t.me/campscouting',
                yt_url=yt_url
                or 'https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
            )
            private_ok, private_error = connect._send_comment_private_reply(
                comment_id, private_text, service, page=page
            )
            if private_ok:
                connect.write(
                    {
                        'sp_replied_private': True,
                        'sp_messenger_window_expires_at': fields.Datetime.now()
                        + timedelta(hours=24),
                        'sp_window_alert_sent': False,
                        'sp_funnel_stage': 'private_sent',
                    }
                )

        # Нотатка оператору
        connect._notify_operator_comment(
            contact_name=contact_name,
            comment_text=comment_text,
            post_url=post_url,
            sent_public=public_ok,
            sent_private=private_ok,
            public_error=public_error,
            private_error=private_error,
            category=category,
        )

        return connect

    _COMMENT_CATEGORIES = (
        'question_price',
        'question_dates',
        'question_age',
        'question_general',
        'thanks',
        'complaint',
        'spam',
        'other',
    )

    def _classify_comment(self, text, service='facebook'):
        """
        Класифікує коментар через Anthropic Claude API.
        Повертає одну з _COMMENT_CATEGORIES. Фолбек 'other' якщо LLM вимкнено/помилка.
        """
        if not text or not text.strip():
            return 'other'
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.llm_classifier_enabled', 'False') != 'True':
            return 'other'
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return 'other'
        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')

        prompt = (
            'Класифікуй коментар під постом літнього дитячого табору CampScout в одну з категорій:\n'
            '- question_price (питання про ціну, вартість, знижки)\n'
            '- question_dates (питання про терміни, дати заїздів, коли)\n'
            '- question_age (питання про вік дітей, з якого віку)\n'
            '- question_general (інше питання: програма, харчування, безпека, місце, документи)\n'
            '- thanks (подяка, позитивні емодзі без питання, лайк)\n'
            '- complaint (скарга, негатив, претензія)\n'
            '- spam (спам, реклама, шкідливе посилання, провокація)\n'
            '- other (не вдалось класифікувати)\n\n'
            f'Коментар: "{text[:400]}"\n\n'
            'Відповідай ОДНИМ СЛОВОМ — назвою категорії без пояснень.'
        )
        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': model,
                    'max_tokens': 20,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: LLM classifier HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return 'other'
            data = resp.json()
            raw = (data.get('content') or [{}])[0].get('text', '').strip().lower()
            for valid in self._COMMENT_CATEGORIES:
                if valid in raw:
                    return valid
            _logger.info('SendPulse Odoo: LLM returned unknown category "%s"', raw)
            return 'other'
        except Exception as e:
            _logger.warning('SendPulse Odoo: LLM classifier exception — %s', e)
            return 'other'

    def _log_fb_audit(self, label, url, payload, status_code, response_text, attempts_used=1):
        """
        Зберігає запис про FB/IG API виклик у ir.logging для аудиту і дебагу.
        Токен з payload редактується (замінюється на '***REDACTED***').
        """
        try:
            redacted = {
                k: ('***REDACTED***' if k == 'access_token' else v)
                for k, v in (payload or {}).items()
            }
            level = 'INFO' if status_code == 200 else 'WARNING'
            short_resp = (response_text or '')[:500]
            msg = (
                f'[{label}] {status_code} attempts={attempts_used}\n'
                f'URL: {url}\n'
                f'Payload: {redacted}\n'
                f'Response: {short_resp}'
            )
            self.env['ir.logging'].sudo().create(
                {
                    'name': 'odoo_chatwoot_connector.fb_api',
                    'type': 'server',
                    'level': level,
                    'dbname': self.env.cr.dbname,
                    'message': msg,
                    'path': 'sendpulse_connect._fb_post_with_retry',
                    'func': label,
                    'line': '0',
                }
            )
        except Exception as e:
            # Аудит-лог не повинен ламати основний флоу
            _logger.warning('SendPulse Odoo: audit log write failed — %s', e)

    def _fb_post_with_retry(self, url, payload, label='fb-call', attempts=3, base_delay=1):
        """
        POST на Graph API з exponential backoff (1s, 3s, 9s).
        Retry на: мережеві помилки, 5xx, 429 (rate limited).
        Не retry на: 4xx (крім 429) — це permanent errors (invalid token, blocked user, etc.).
        Повертає (success: bool, error: str|None, response_json: dict|None).
        """
        last_err = None
        last_status = 0
        last_text = ''
        for attempt in range(attempts):
            try:
                resp = requests.post(url, json=payload, timeout=15)
                last_status = resp.status_code
                last_text = resp.text or ''
                if resp.status_code == 200:
                    self._log_fb_audit(label, url, payload, 200, last_text, attempt + 1)
                    try:
                        return True, None, resp.json()
                    except Exception:
                        return True, None, {}
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    last_err = self._parse_fb_error(resp)
                    _logger.warning(
                        'SendPulse Odoo %s attempt %d/%d → HTTP %d (%s) — retrying',
                        label,
                        attempt + 1,
                        attempts,
                        resp.status_code,
                        last_err,
                    )
                else:
                    err = self._parse_fb_error(resp)
                    _logger.warning('SendPulse Odoo %s failed (no retry) — %s', label, err)
                    self._log_fb_audit(
                        label, url, payload, resp.status_code, last_text, attempt + 1
                    )
                    # V2 immediate alert: якщо токен протух (code 190) — одразу Telegram,
                    # не чекаємо weekly cron. Rate-limited 1/год щоб не спамити.
                    self._maybe_alert_token_expired(err, last_text)
                    return False, err, None
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = str(e)
                last_text = f'network error: {e}'
                _logger.warning(
                    'SendPulse Odoo %s attempt %d/%d → network error (%s) — retrying',
                    label,
                    attempt + 1,
                    attempts,
                    e,
                )
            except Exception as e:
                _logger.error('SendPulse Odoo %s exception — %s', label, e)
                self._log_fb_audit(label, url, payload, 0, f'exception: {e}', attempt + 1)
                return False, str(e), None
            if attempt < attempts - 1:
                time.sleep(base_delay * (3**attempt))
        _logger.error('SendPulse Odoo %s — all %d retries exhausted: %s', label, attempts, last_err)
        self._log_fb_audit(label, url, payload, last_status, last_text, attempts)
        return False, f'retries exhausted: {last_err}', None

    @api.model
    def _maybe_alert_token_expired(self, err_text, raw_response):
        """
        Якщо Graph API відповів помилкою з кодом 190 (token issue) — одразу
        шле loud Telegram-алерт, не чекаючи weekly cron. Rate-limit 1/год
        щоб під DDoS коментарів не спамило сотнями повідомлень.
        """
        combined = f'{err_text or ""} {raw_response or ""}'.lower()
        # Meta error code 190 = invalid/expired token (також часті rbacs 102/104)
        is_token_issue = (
            'код 190' in combined
            or 'code":190' in combined
            or 'code": 190' in combined
            or 'session has expired' in combined
            or 'invalid oauth' in combined
            or 'error validating access token' in combined
        )
        if not is_token_issue:
            return
        ICP = self.env['ir.config_parameter'].sudo()
        last_alert_iso = ICP.get_param('odoo_chatwoot_connector.fb_token_invalid_last_alert_at', '')
        now = fields.Datetime.now()
        if last_alert_iso:
            try:
                last_alert = fields.Datetime.from_string(last_alert_iso)
                if last_alert and (now - last_alert) < timedelta(hours=1):
                    return  # rate-limit
            except Exception:
                pass
        ICP.set_param(
            'odoo_chatwoot_connector.fb_token_invalid_last_alert_at',
            fields.Datetime.to_string(now),
        )
        self._notify_telegram(
            '🚨 <b>FB Page Token НЕДІЙСНИЙ</b>\n\n'
            'API миттєво відхиляє запити — автовідповіді на коменти і '
            'приватні повідомлення НЕ проходять.\n\n'
            '<b>Терміново:</b> отримай новий User Token у Graph API Explorer '
            'і натисни «Синхронізувати з Meta» у Settings.\n\n'
            '<b>Довготривало:</b> заповни fb_app_id + fb_app_secret у Settings + '
            'увімкни Auto-refresh FB Page tokens — токени автоматично стануть long-lived.',
            silent=False,
        )

    _DIALOGS_URL = 'https://api.sendpulse.com/chatbots/dialogs'

    @api.model
    def cron_check_dialogs_snapshot(self):
        """
        Cron: щодня тягне ~100 найсвіжіших діалогів через офіційний
        GET /chatbots/dialogs (SendPulse Chatbots API) і звіряє
        last_inbox_message кожного з тим, що є в sendpulse.message.

        Доповнює cron_check_message_gap (модель sendpulse.webhook.data):
        той працює лише в межах власної 30-денної ретенції і лише на
        тому, що ми самі встигли зберегти ДО можливого збою. Цей — живий
        снепшот прямо з SendPulse, незалежний від нашої ретенції і від
        того, чи взагалі дійшов webhook.

        API /dialogs НЕ має фільтра по contact_id чи даті (тільки
        size/skip/search_after/order — перевірено живою OpenAPI-специфою
        SendPulse) — тому просто найсвіжіші order=desc, без спроби
        охопити всю історію. Затримка 5 хв — той самий сенс, що в
        cron_check_message_gap: дати обробці домовитись, не false-positive
        на щойно прийнятому.
        """
        token = self._get_access_token()
        if not token:
            _logger.warning('SendPulse Odoo: dialogs-снепшот пропущено — немає токена API')
            return
        try:
            resp = requests.get(
                self._DIALOGS_URL,
                params={'size': 100, 'order': 'desc'},
                headers={'Authorization': f'Bearer {token}'},
                timeout=15,
            )
            resp.raise_for_status()
            dialogs = (resp.json().get('data') or {}).get('list') or []
        except Exception as e:
            _logger.warning('SendPulse Odoo: dialogs-снепшот — помилка API: %s', e)
            return

        now_utc = datetime.utcnow()
        gaps = []
        for d in dialogs:
            inbox = d.get('last_inbox_message') or {}
            text = (inbox.get('text') or '').strip()
            date_str = inbox.get('date')
            contact = d.get('contact') or {}
            contact_id = contact.get('id')
            if not (text and date_str and contact_id):
                continue
            try:
                sp_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%fZ')
            except ValueError:
                continue
            if now_utc - sp_date < timedelta(minutes=5):
                continue
            exists = (
                self.env['sendpulse.message']
                .sudo()
                .search_count(
                    [
                        ('sendpulse_contact_id', '=', contact_id),
                        ('direction', '=', 'incoming'),
                        ('date', '>=', sp_date - timedelta(minutes=3)),
                        ('date', '<=', sp_date + timedelta(minutes=3)),
                    ]
                )
            )
            if not exists:
                gaps.append(
                    {
                        'name': contact.get('full_name') or contact_id,
                        'date': sp_date,
                        'text': text[:80],
                    }
                )

        if not gaps:
            return

        _logger.error(
            'SendPulse Odoo: dialogs-снепшот знайшов %d контакт(ів) з last_inbox_message, '
            'якого немає в sendpulse.message: %s',
            len(gaps),
            gaps,
        )
        lines = '\n'.join(f'• {g["date"]} {g["name"]} — {g["text"]}' for g in gaps[:15])
        more = f'\n... ще {len(gaps) - 15}' if len(gaps) > 15 else ''
        message = (
            f'⚠️ <b>SendPulse: dialogs-снепшот — можлива втрата</b>\n'
            f'{len(gaps)} контакт(ів), де останнє вхідне повідомлення в SendPulse '
            f'не знайдено в Odoo (live-перевірка, незалежно від webhook.data):\n'
            f'{lines}{more}'
        )
        self._notify_telegram(message, silent=False)

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

    # ── V2 F7: Bulk-archive old closed comment records ────────────────────
    @api.model
    def cron_archive_old_comment_records(self):
        """
        Раз/місяць. Soft-archive (active=False) для sp_is_comment=True записів
        у stage=close старших за auto_archive_comments_days днів. Залишає у БД
        для історії, але прибирає з default views.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if (
            ICP.get_param('odoo_chatwoot_connector.auto_archive_comments_enabled', 'False')
            != 'True'
        ):
            return
        try:
            days = int(ICP.get_param('odoo_chatwoot_connector.auto_archive_comments_days', '30'))
        except (ValueError, TypeError):
            days = 30
        threshold = fields.Datetime.now() - timedelta(days=days)
        candidates = self.search(
            [
                ('sp_is_comment', '=', True),
                ('stage', '=', 'close'),
                ('active', '=', True),
                ('write_date', '<', threshold),
            ]
        )
        if candidates:
            candidates.write({'active': False})
        _logger.info(
            'SendPulse Odoo: cron_archive_old_comment_records — archived %d',
            len(candidates),
        )

    # ── V2 F8: Weekly Telegram funnel report ──────────────────────────────
    @api.model
    def cron_weekly_telegram_report(self):
        """
        Понеділок 09:00 UTC — зводка за минулий тиждень у Telegram-групу.
        No-op якщо weekly_report_enabled=False або Telegram не налаштований.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.weekly_report_enabled', 'False') != 'True':
            return
        if ICP.get_param('odoo_chatwoot_connector.telegram_alerts_enabled', 'False') != 'True':
            _logger.info('SendPulse Odoo: weekly report skipped — Telegram disabled')
            return

        now = fields.Datetime.now()
        week_start = now - timedelta(days=7)
        stats = self._calculate_weekly_stats(week_start, now)
        message = self._format_weekly_report(stats, week_start, now)
        self._notify_telegram(message, silent=False)
        _logger.info('SendPulse Odoo: weekly report sent (%d chars)', len(message))

    @api.model
    def _calculate_weekly_stats(self, period_start, period_end):
        """Збирає метрики за період для tygodniowego report-а."""
        Connect = self.sudo()
        domain_period = [
            ('create_date', '>=', period_start),
            ('create_date', '<', period_end),
        ]
        total = Connect.search_count(domain_period)
        comments = Connect.search_count(domain_period + [('sp_is_comment', '=', True)])
        direct = total - comments

        # Комент-категорії
        cat_counts = {}
        for cat in (
            'question_price',
            'question_dates',
            'question_age',
            'question_general',
            'thanks',
            'complaint',
            'spam',
            'other',
        ):
            cat_counts[cat] = Connect.search_count(
                domain_period + [('sp_is_comment', '=', True), ('sp_comment_category', '=', cat)]
            )

        # Funnel — скільки перейшло до кожної стадії (за період створення)
        funnel = {}
        for stage in (
            'comment_only',
            'private_sent',
            'customer_replied',
            'operator_engaged',
            'lead_created',
            'closed_won',
            'closed_lost',
        ):
            funnel[stage] = Connect.search_count(domain_period + [('sp_funnel_stage', '=', stage)])

        # SLA — медіана часу до першої відповіді
        with_sla = Connect.search(domain_period + [('sp_first_reply_time_sec', '>', 0)])
        sla_values = sorted(with_sla.mapped('sp_first_reply_time_sec'))
        sla_median_sec = sla_values[len(sla_values) // 2] if sla_values else 0
        sla_median_min = sla_median_sec // 60 if sla_median_sec else 0

        # Auto-hide spam за період
        spam_hidden = Connect.search_count(
            domain_period
            + [
                ('sp_comment_category', '=', 'spam'),
                ('sp_replied_public', '=', False),
            ]
        )

        # Leads створені
        Lead = self.env['crm.lead'].sudo()
        leads_created = Lead.search_count(
            [
                ('create_date', '>=', period_start),
                ('create_date', '<', period_end),
                ('id', 'in', Connect.search(domain_period).mapped('sp_lead_id').ids),
            ]
        )

        # Token статуси
        Page = self.env['sendpulse.facebook.page'].sudo()
        bad_tokens = Page.search(
            [
                ('active', '=', True),
                '|',
                ('token_status', 'ilike', 'invalid%'),
                ('token_status', 'ilike', 'expires_soon%'),
            ]
        )

        return {
            'total': total,
            'direct': direct,
            'comments': comments,
            'cat_counts': cat_counts,
            'funnel': funnel,
            'sla_median_min': sla_median_min,
            'spam_hidden': spam_hidden,
            'leads_created': leads_created,
            'bad_tokens': bad_tokens,
        }

    @api.model
    def _format_weekly_report(self, stats, period_start, period_end):
        """HTML-форматований звіт для Telegram."""
        lines = [
            f'📊 <b>Звіт за тиждень {period_start:%d.%m} – {period_end:%d.%m}</b>',
            '',
            f'Нові розмови: <b>{stats["total"]}</b>',
            f'  ├─ Direct DM: {stats["direct"]}',
            f'  └─ Comments: {stats["comments"]}',
            '',
        ]
        if stats['comments']:
            cat = stats['cat_counts']
            lines.append('<b>Категорії коментарів:</b>')
            if cat['question_price']:
                lines.append(f'  💰 Ціна: {cat["question_price"]}')
            if cat['question_dates']:
                lines.append(f'  📅 Терміни: {cat["question_dates"]}')
            if cat['question_age']:
                lines.append(f'  👶 Вік: {cat["question_age"]}')
            if cat['question_general']:
                lines.append(f'  ❓ Загальне: {cat["question_general"]}')
            if cat['thanks']:
                lines.append(f'  🙏 Подяки: {cat["thanks"]}')
            if cat['complaint']:
                lines.append(f'  🚨 Скарги: {cat["complaint"]} (ескаловано)')
            if cat['spam']:
                lines.append(f'  🚫 Спам: {cat["spam"]} (приховано: {stats["spam_hidden"]})')
            if cat['other']:
                lines.append(f'  🔸 Інше: {cat["other"]}')
            lines.append('')

        f = stats['funnel']
        funnel_total = sum(f.values())
        if funnel_total:
            lines.append('<b>Funnel:</b>')
            lines.append(f'  Comment only: {f["comment_only"]}')
            lines.append(f'  Private sent: {f["private_sent"]}')
            lines.append(f'  Customer replied: {f["customer_replied"]}')
            lines.append(f'  Operator engaged: {f["operator_engaged"]}')
            lines.append(f'  Lead created: {f["lead_created"]}')
            if f['closed_won'] or f['closed_lost']:
                lines.append(f'  Closed: won={f["closed_won"]}, lost={f["closed_lost"]}')
            lines.append('')

        if stats['leads_created']:
            lines.append(f'💼 CRM лідів створено: <b>{stats["leads_created"]}</b>')

        if stats['sla_median_min']:
            lines.append(f'⏱ Медіана часу до першої відповіді: <b>{stats["sla_median_min"]} хв</b>')

        if stats['bad_tokens']:
            lines.append('')
            lines.append('⚠️ <b>Проблеми з токенами:</b>')
            for p in stats['bad_tokens']:
                lines.append(f'  • {p.name}: {p.token_status or "?"}')

        # F9 A/B: топ-3 і worst-1 шаблонів за conversion (мін. 10 використань)
        PublicTemplate = self.env['sendpulse.public.template'].sudo()
        significant = PublicTemplate.search(
            [
                ('active', '=', True),
                ('kind', '=', 'standard'),
                ('use_count', '>=', 10),
            ]
        )
        if significant:
            sorted_by_conv = significant.sorted(key='conversion_rate', reverse=True)
            lines.append('')
            lines.append('🏆 <b>Топ шаблонів публічної відповіді:</b>')
            for tpl in sorted_by_conv[:3]:
                lines.append(
                    f'  • {tpl.name}: {tpl.conversion_rate:.1f}% '
                    f'({tpl.customer_replied_count}/{tpl.use_count})'
                )
            if len(sorted_by_conv) > 3:
                worst = sorted_by_conv[-1]
                lines.append(
                    f'  ⚠️ Слабкий: {worst.name}: {worst.conversion_rate:.1f}% '
                    f'({worst.customer_replied_count}/{worst.use_count})'
                )

        return '\n'.join(lines)[:4000]

    # ── V2 F14: Live event seats context для AI prompts ──────────────────
    def _get_live_events_context(self, limit=15, low_ratio=0.3):
        """
        Повертає текстовий блок активних майбутніх event.event з їх
        live `seats_available` — щоб AI у F10 suggestions і F1 RAG знав
        які табори скільки мають вільних місць. Позначає 🔴 повні і
        ❗ майже повні (<low_ratio від seats_max) для FOMO.

        Повертає '' якщо feature-flag вимкнений, ORM помилка або немає
        активних подій.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.event_seats_awareness_enabled', 'True') != 'True':
            return ''
        from datetime import datetime

        try:
            events = (
                self.env['event.event']
                .sudo()
                .search(
                    [
                        ('active', '=', True),
                        ('date_begin', '>', datetime.now()),
                        ('stage_id.pipe_end', '=', False),
                    ],
                    order='date_begin',
                    limit=limit,
                )
            )
        except Exception as e:
            _logger.warning('SendPulse Odoo: F14 events query failed — %s', e)
            return ''
        lines = []
        for ev in events:
            name = (ev.name or '').strip()
            if not name:
                continue
            date_s = ev.date_begin.strftime('%d.%m') if ev.date_begin else '?'
            if ev.seats_limited and ev.seats_max:
                avail = ev.seats_available or 0
                if avail <= 0:
                    status = '🔴 ПОВНИЙ'
                elif avail / ev.seats_max <= low_ratio:
                    status = f'❗ {avail}/{ev.seats_max} (майже повний!)'
                else:
                    status = f'{avail}/{ev.seats_max} місць'
            else:
                status = 'без ліміту місць'
            lines.append(f'• {date_s} — {name[:70]} — {status}')
        if not lines:
            return ''
        return (
            'LIVE ТАБОРИ 2026 (з Odoo, seats_available АКТУАЛЬНО ЗАРАЗ '
            '— рекомендуй лише ті, де є місця; ❗ = FOMO, 🔴 = запропонуй аналог):\n'
            + '\n'.join(lines)
        )

    # ── V2 F10: Suggested reply drafts для оператора ──────────────────────
    def _generate_reply_suggestions(self, count=3):
        """
        Через Claude генерує N варіантів наступної відповіді оператора
        на основі контексту розмови. Returns list of strings.

        Для OWL-компонента у Discuss side-panel. Toggle: `suggested_reply_enabled`.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.suggested_reply_enabled', 'False') != 'True':
            return []
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return []
        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')

        # Контекст: останні 10 повідомлень обох сторін, хронологічно
        recent = self.message_ids.sorted('date', reverse=False)[-10:]
        history_lines = []
        for m in recent:
            who = '👤 Клієнт' if m.direction == 'incoming' else '🧑 Оператор'
            text = (m.text_message or '').strip().replace('\n', ' ')[:300]
            if text:
                history_lines.append(f'{who}: {text}')
        history = '\n'.join(history_lines) or '(порожньо — оператор ще не писав)'

        # F12: Спроба виявити email у останніх повідомленнях клієнта
        # і linkувати partner (ідемпотентно — якщо вже є sp_booking_email, skip).
        if not self.sp_booking_email:
            self._try_extract_email_and_link()

        # Контекст профілю (базовий)
        profile_parts = [f"Ім'я клієнта: {self.name or '—'}"]
        if self.sp_child_name:
            profile_parts.append(f'Дитина (з бота): {self.sp_child_name}')
        if self.sp_booking_email:
            profile_parts.append(f'Email: {self.sp_booking_email}')
        if self.social_username:
            profile_parts.append(f'Username: @{self.social_username}')
        profile_parts.append(f'Канал: {self._get_service_label()}')

        # F12: Розширений контекст — якщо є linked partner
        partner = self.partner_id
        if partner:
            profile_parts.append('')
            profile_parts.append('── ІДЕНТИФІКОВАНИЙ КЛІЄНТ ──')
            profile_parts.append(
                f'Partner ID: {partner.id}, створено: {partner.create_date.strftime("%Y-%m-%d") if partner.create_date else "—"}'
            )
            if partner.email and partner.email != self.sp_booking_email:
                profile_parts.append(f'Email у партнера: {partner.email}')
            if partner.phone or partner.mobile:
                profile_parts.append(f'Телефон: {partner.phone or partner.mobile}')
            if partner.city or partner.street:
                addr = ', '.join(filter(None, [partner.street, partner.city]))
                profile_parts.append(f'Адреса: {addr}')

            # crm.lead контекст — відкриті + останні закриті
            leads = (
                self.env['crm.lead']
                .sudo()
                .search(
                    [('partner_id', '=', partner.id)],
                    order='create_date desc',
                    limit=5,
                )
            )
            if leads:
                profile_parts.append('')
                profile_parts.append('CRM-ліди (останні):')
                for lead in leads:
                    stage = lead.stage_id.name if lead.stage_id else '—'
                    date = lead.create_date.strftime('%Y-%m-%d') if lead.create_date else '—'
                    probab = f'{lead.probability:.0f}%' if lead.probability else '—'
                    profile_parts.append(
                        f'  • [{date}] {lead.name or "—"} — stage: {stage}, prob: {probab}'
                    )

            # sale.order історія
            orders = (
                self.env['sale.order']
                .sudo()
                .search(
                    [('partner_id', '=', partner.id), ('state', 'in', ('sale', 'done'))],
                    order='date_order desc',
                    limit=3,
                )
            )
            if orders:
                profile_parts.append('')
                profile_parts.append('Історія замовлень:')
                for o in orders:
                    date = o.date_order.strftime('%Y-%m-%d') if o.date_order else '—'
                    amount = f'{o.amount_total:.0f} {o.currency_id.name or ""}'.strip()
                    profile_parts.append(f'  • [{date}] {o.name} — {amount}')
        else:
            profile_parts.append('')
            profile_parts.append('⚠️ КЛІЄНТ НЕ ІДЕНТИФІКОВАНИЙ — email невідомий')

        profile = '\n'.join(profile_parts)

        # F14: live seats у активних подіях — AI має знати реальну доступність
        live_events = self._get_live_events_context()
        live_events_block = f'{live_events}\n\n' if live_events else ''

        prompt = (
            f'Ти — AI-асистент менеджера CampScout (дитячі табори у Польщі).\n\n'
            f'{live_events_block}'
            f'КАНОНІЧНІ ФАКТИ (НЕ ВИГАДУВАТИ НІЧОГО ІНШОГО!):\n'
            f'• Флагмани 2026: TDK 6-11р 3 300 zł (10 днів), Дослідники морів 7-17р 3 500 zł (14 днів), '
            f'Пошумимо 12-17р 3 250 zł (14 днів)\n'
            f'• Промо-ціни ДО 01.05.2026, після +300 zł\n'
            f'• Швейцарія: 5 500 zł, страхівка+медик+дорога окремо. Франція/Італія/Іспанія 2026 — продано\n'
            f'• У польські табори входить: проживання, 4-разове харчування, програма, NNW, медик 24/7\n'
            f"• Бронь: оплата частинами або повна, за 14 днів до старту все закрите. М'яка бронь 48h без оплати\n"
            f'• Трансфер окрема послуга: 50 zł пункт збору+автобус, або індивідуальний супровід\n'
            f'• Телефони здаємо у сейф, щовечора 30хв дзвінки (крім Вовча Стежа/Цивілізація — раз на 3д)\n'
            f'• Безпека: Ustawa Kamilka + KRK, Compensa VIG 31 617 PLN, ліцензія №1129\n'
            f'• Соц-доказ: 3 сезони, 1 500+ дітей, 4.9/5 (200+ відгуків Google/FB)\n'
            f'• -5% за TG-канал: https://t.me/campscouting. Landing: https://lato2026.campscout.eu\n\n'
            f"ПРОЦЕДУРА ОФОРМЛЕННЯ (ОБОВ'ЯЗКОВО знати + пояснювати клієнту!):\n"
            f'• Дані ДИТИНИ (ПІБ, дата народження, медичні особливості, діагнози, алергії, '
            f"контакти для екстреного зв'язку) батьки заповнюють САМІ у кваліфікаційній "
            f'(табірній) картці в особистому кабінеті на сайті — це додаток №5 до Договору.\n'
            f'• ЮРИДИЧНА ПРИЧИНА: після заповнення батьки ПІДПИСУЮТЬ картку — цим вони '
            f'беруть юридичну відповідальність за достовірність даних. Ми як оператори '
            f'НЕ МАЄМО ПРАВА записувати ці дані за батьків у чаті — без їхнього підпису '
            f'картка юридичної сили не має, і дані не можуть бути використані.\n'
            f'• Тому у чаті ми ніколи не питаємо ПІБ/дату народження/медичні дані дитини. '
            f'Якщо клієнт сам пропонує — ввічливо просимо ввести у картці в панелі клієнта.\n'
            f'• У чаті з батьками питаємо ЇХНІ дані (якщо потрібно для консультації): '
            f'ПІБ замовника, адреса проживання, телефон, email.\n'
            f'• Для бронювання — відправляємо у особистий кабінет, там батьки самі заповнюють '
            f'картку Учасника, підписують, отримують рахунок, роблять оплату.\n\n'
            f'Прочитай історію і запропонуй {count} РІЗНИХ варіантів наступної відповіді.\n\n'
            f'Контекст клієнта:\n{profile}\n\n'
            f'Історія (останнє повідомлення клієнта внизу):\n{history}\n\n'
            f"Стиль (ОБОВ'ЯЗКОВО!):\n"
            f'• Звертання — ТІЛЬКИ на «Ви» (ніколи «ти/тобі/твій»). Батьки — дорослі люди, '
            f'ми продавець-консультант, не ровесники.\n'
            f'• 2-5 речень, по-людському, не формально\n'
            f'• Без клішe («Дякуємо за запитання»)\n'
            f'• Емодзі 1-2 максимум\n'
            f'• Варіанти РІЗНІ за підходом (інформативний / уточнюючий / емпатичний)\n'
            f"• Ім'я клієнта у першій фразі якщо відоме\n"
            f'• Закінчуй CTA-запитанням якщо доречно\n'
            f'• Якщо клієнт НЕ ІДЕНТИФІКОВАНИЙ (позначка у профілі ⚠️) і цікавиться '
            f'деталями/ціною/програмою — ОДИН з варіантів може ввічливо запропонувати '
            f"залишити email для особистої пропозиції (не нав'язливо, природно у контексті).\n"
            f'• Якщо клієнт ІДЕНТИФІКОВАНИЙ (є partner/ліди/замовлення) — використай контекст '
            f'(минулі табори, стадія ліда) для персоналізації, але не цитуй деталі буквально.\n'
            f'• Якщо клієнт питає про КОНКРЕТНИЙ табір/зміну — перевір LIVE ТАБОРИ вище: '
            f'❗ <30% → створи FOMO («Ірине, лишилось тільки 5 місць, радимо не тягнути»); '
            f'🔴 повний → ЧЕСНО скажи і запропонуй аналог з вільними місцями; '
            f'звичайний → не акцентуй на seats без потреби.\n\n'
            f'КАТЕГОРИЧНО ЗАБОРОНЕНО:\n'
            f'❌ Звертання на «ти» — завжди «Ви», «Вам», «Ваш», «Ваша дитина»\n'
            f'❌ Просити у чаті ПІБ дитини, дату народження, медичні дані/діагнози/алергії — '
            f'все це заповнюється батьками у кваліфікаційній картці у панелі клієнта\n'
            f'❌ Писати «надішли документи», «заповни анкету у чаті» — відправляємо у особистий кабінет\n'
            f'❌ Вигадувати ціни, дати, табори, факти яких немає у КАНОНІЧНИХ ФАКТАХ\n'
            f'❌ Слово «доставка» про дітей (тільки «трансфер», «привезти»)\n'
            f'❌ «11 років перехідний вік» (для 11 є TDK від 6)\n'
            f'❌ Агресивно порівнювати з конкурентами\n\n'
            f'Формат — STRICT JSON:\n'
            f'{{"suggestions": ["варіант 1", "варіант 2", "варіант 3"]}}\n'
            f'Поверни ЛИШЕ JSON без пояснень.'
        )

        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': model,
                    'max_tokens': 800,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: suggested_reply HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return []
            raw = (resp.json().get('content') or [{}])[0].get('text', '').strip()
            import json as _json
            import re as _re

            # Strip ```json / ``` code fences Claude любить додавати
            cleaned = _re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=_re.MULTILINE).strip()
            data = None
            try:
                data = _json.loads(cleaned)
            except Exception:
                # Balanced-brace extraction (не non-greedy, щоб не обривало на вкладених)
                start = cleaned.find('{')
                if start >= 0:
                    depth = 0
                    for i, ch in enumerate(cleaned[start:], start=start):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    data = _json.loads(cleaned[start : i + 1])
                                except Exception:
                                    pass
                                break
            if not isinstance(data, dict):
                _logger.warning(
                    'SendPulse Odoo: suggested_reply failed to parse JSON. RAW=%s',
                    raw[:500],
                )
                return []
            suggestions = data.get('suggestions') or []
            if not suggestions:
                _logger.info(
                    'SendPulse Odoo: suggested_reply — LLM повернув 0 варіантів. RAW=%s',
                    raw[:300],
                )
            # Filter: only non-empty strings, max N
            return [s.strip() for s in suggestions if isinstance(s, str) and s.strip()][:count]
        except Exception as e:
            _logger.warning('SendPulse Odoo: suggested_reply exception — %s', e)
            return []

    @api.model
    def suggested_reply_for_channel(self, channel_id, count=3):
        """RPC endpoint — для OWL-компонента. Бере connect за channel_id."""
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return []
        return connect._generate_reply_suggestions(count=count)

    # ── V2 F12: Email extraction + partner identification ────────────────
    _EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def _try_extract_email_and_link(self):
        """
        Сканує останні 20 incoming повідомлень на email (regex), бере перший.
        Якщо знайшов: set sp_booking_email + спроба link partner_id через
        існуючий _find_partner. Ідемпотентно — якщо sp_booking_email уже
        встановлений, no-op.
        """
        self.ensure_one()
        if self.sp_booking_email:
            return False
        import re as _re

        recent = self.message_ids.filtered(
            lambda m: m.direction == 'incoming' and (m.text_message or '').strip()
        ).sorted('date', reverse=True)[:20]
        for msg in recent:
            m = _re.search(self._EMAIL_REGEX, msg.text_message or '')
            if not m:
                continue
            email = m.group(0).lower().strip()
            vals = {'sp_booking_email': email}
            if not self.partner_id:
                partner = (
                    self.env['res.partner'].sudo().search([('email', '=ilike', email)], limit=1)
                )
                if partner:
                    vals['partner_id'] = partner.id
                    if self.sendpulse_contact_id and not partner.sendpulse_contact_id:
                        partner.sudo().write({'sendpulse_contact_id': self.sendpulse_contact_id})
            self.write(vals)
            _logger.info(
                'SendPulse Odoo: F12 email extracted %s from connect %s, linked partner=%s',
                email,
                self.id,
                vals.get('partner_id'),
            )
            return True
        return False

    # ── V2 F11: Auto-translate UA↔PL через Claude ────────────────────────
    def _translate_text(self, text, target_lang='pl'):
        """
        Перекладає текст на target_lang через Claude. Повертає dict:
        {translated: str, source_lang: str, error: str or None}.
        No-op якщо toggle вимкнено або API key відсутній.
        """
        if not text or not text.strip():
            return {'translated': '', 'source_lang': '', 'error': 'empty_input'}
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.auto_translate_enabled', 'False') != 'True':
            return {'translated': '', 'source_lang': '', 'error': 'disabled'}
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return {'translated': '', 'source_lang': '', 'error': 'no_api_key'}

        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')
        target_full = {
            'pl': 'польську',
            'uk': 'українську',
            'en': 'англійську',
            'ru': 'російську',
        }.get(target_lang, target_lang)
        prompt = (
            f'Визнач мову вхідного тексту і переклади його на {target_full}.\n'
            f'Якщо текст уже на цільовій мові — поверни його без змін.\n'
            f'Стиль розмовний, природній (клієнтсько-операторський чат).\n'
            f'Зберігай емодзі, URL, цифри, імена власні.\n\n'
            f'Вхідний текст:\n"""\n{text[:2000]}\n"""\n\n'
            f'Формат — STRICT JSON:\n'
            f'{{"source_lang": "uk|pl|en|ru|...", "translated": "переклад"}}\n'
            f'Поверни ТІЛЬКИ JSON без пояснень.'
        )
        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': model,
                    'max_tokens': 2000,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: translate HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return {'translated': '', 'source_lang': '', 'error': f'http_{resp.status_code}'}
            raw = (resp.json().get('content') or [{}])[0].get('text', '').strip()
            import json as _json
            import re as _re

            cleaned = _re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=_re.MULTILINE).strip()
            data = None
            try:
                data = _json.loads(cleaned)
            except Exception:
                start = cleaned.find('{')
                if start >= 0:
                    depth = 0
                    for i, ch in enumerate(cleaned[start:], start=start):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    data = _json.loads(cleaned[start : i + 1])
                                except Exception:
                                    pass
                                break
            if not isinstance(data, dict):
                _logger.warning('SendPulse Odoo: translate parse failed. RAW=%s', raw[:300])
                return {'translated': '', 'source_lang': '', 'error': 'parse_failed'}
            return {
                'translated': (data.get('translated') or '').strip(),
                'source_lang': (data.get('source_lang') or '').strip().lower(),
                'error': None,
            }
        except Exception as e:
            _logger.warning('SendPulse Odoo: translate exception — %s', e)
            return {'translated': '', 'source_lang': '', 'error': f'exception:{e}'}

    @api.model
    def translate_last_inbound_for_channel(self, channel_id, target_lang='pl'):
        """
        RPC для OWL-панелі. Перекладає останнє incoming повідомлення у
        channel на target_lang. Повертає {'translated', 'source_lang',
        'original', 'error'}.
        """
        empty = {'translated': '', 'source_lang': '', 'original': '', 'error': None}
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return {**empty, 'error': 'no_connect'}
        last_in = connect.message_ids.filtered(
            lambda m: m.direction == 'incoming' and (m.text_message or '').strip()
        ).sorted('date', reverse=True)[:1]
        if not last_in:
            return {**empty, 'error': 'no_inbound'}
        text = (last_in.text_message or '').strip()
        result = connect._translate_text(text, target_lang=target_lang)
        return {
            'translated': result['translated'],
            'source_lang': result['source_lang'],
            'original': text[:2000],
            'error': result['error'],
        }

    # ── V2 F13: Lead magnet — PDF-каталог + SMS-купон ─────────────────────
    def _send_pdf_catalog_email(self, to_email=None):
        """
        Надсилає lead-magnet PDF-каталог на email клієнта.
        Повертає {'ok': bool, 'error': str or None, 'message_id': int or None}.
        Ідемпотентно — якщо sp_pdf_sent_at уже встановлено на цей email, skip.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.lead_magnet_enabled', 'False') != 'True':
            return {'ok': False, 'error': 'disabled', 'message_id': None}
        to_email = (
            to_email or self.sp_booking_email or (self.partner_id.email if self.partner_id else '')
        ).strip()
        if not to_email:
            return {'ok': False, 'error': 'no_email', 'message_id': None}
        # Idempotency
        if self.sp_pdf_sent_at and self.sp_pdf_sent_to_email == to_email:
            return {'ok': True, 'error': 'already_sent', 'message_id': None}

        # RODO/GDPR: перед send — перевірити явне відкликання згоди.
        # Якщо клієнт писав «STOP» / «отписка» / «nie chcę» — skip.
        # Якщо consent record відсутній — трактуємо надання email як неявну
        # згоду (unambiguous action per art. 4(11) RODO) і фіксуємо її.
        ConsentLog = self.env['sendpulse.privacy.consent.log'].sudo()
        enforce_consent = (
            ICP.get_param('odoo_chatwoot_connector.consent_enforcement_enabled', 'True') == 'True'
        )
        if enforce_consent:
            last_consent = ConsentLog.search(
                [
                    ('purpose', '=', 'lead_magnet_email'),
                    ('email', '=', to_email.lower()),
                ],
                order='consent_timestamp desc, id desc',
                limit=1,
            )
            if last_consent and not last_consent.consent_given:
                _logger.info(
                    'SendPulse Odoo: F13 PDF skip — consent withdrawn for %s',
                    to_email,
                )
                return {'ok': False, 'error': 'consent_withdrawn', 'message_id': None}

        att_id_raw = ICP.get_param('odoo_chatwoot_connector.lead_magnet_pdf_attachment_id', '')
        try:
            att_id = int(att_id_raw)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'no_attachment_configured', 'message_id': None}
        attachment = self.env['ir.attachment'].sudo().browse(att_id)
        if not attachment.exists() or not attachment.datas:
            return {'ok': False, 'error': 'attachment_missing', 'message_id': None}

        # Надсилаємо PL-оферту з ПОСИЛАННЯМ на каталог (без важкого вкладення —
        # уникаємо SMTP 552 "message size"). Делегуємо channel-independent методу
        # на res.partner; F13-специфічний RODO-запис (record_consent) — нижче.
        partner = self.partner_id or self.env['res.partner']
        res = partner._send_offer_catalog(to_email, source='f13')
        if not res.get('ok'):
            _logger.warning('SendPulse Odoo: F13 offer email failed — %s', res.get('error'))
            return res
        self.sudo().write(
            {
                'sp_pdf_sent_at': fields.Datetime.now(),
                'sp_pdf_sent_to_email': to_email,
            }
        )
        # RODO: фіксуємо згоду як факт — email був наданий клієнтом у чаті
        # з метою отримати каталог (unambiguous action per art. 4(11)).
        # Беремо останнє incoming повідомлення як доказ.
        if enforce_consent:
            last_in_msg = (
                self.env['sendpulse.message']
                .sudo()
                .search(
                    [
                        ('connect_id', '=', self.id),
                        ('direction', '=', 'incoming'),
                    ],
                    order='date desc, id desc',
                    limit=1,
                )
            )
            ConsentLog.record_consent(
                purpose='lead_magnet_email',
                channel='email',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=last_in_msg.id if last_in_msg else False,
                email=to_email,
                consent_given=True,
                exact_response=(last_in_msg.text_message or to_email) if last_in_msg else to_email,
                notes=f'Auto-recorded on PDF send for connect {self.id}',
            )
        _logger.info(
            'SendPulse Odoo: F13 PDF sent to %s for connect %s',
            to_email,
            self.id,
        )
        return {'ok': True, 'error': None, 'message_id': res.get('message_id')}

    def _get_email_logo_png_b64(self, company):
        """
        Повертає base64-PNG логотипа для email. Gmail не рендерить SVG,
        тому `res.company.logo` (SVG у CampScout) не годиться — віддаємо
        shipped PNG з модуля (static/src/img/campscout_logo.png). Fallback
        на company.logo якщо PNG в модулі немає.
        """
        import base64
        import os

        module_root = os.path.dirname(os.path.dirname(__file__))
        png_path = os.path.join(module_root, 'static', 'src', 'img', 'campscout_logo.png')
        if os.path.exists(png_path):
            try:
                with open(png_path, 'rb') as f:
                    return base64.b64encode(f.read())
            except Exception as e:
                _logger.warning('SendPulse Odoo: cannot read shipped logo — %s', e)
        if company and company.logo:
            try:
                raw = base64.b64decode(company.logo[:30])
                # Якщо company.logo растровий (PNG/JPEG) — годиться
                if raw.startswith(b'\x89PNG') or raw.startswith(b'\xff\xd8\xff'):
                    return company.logo
            except Exception:
                pass
        return False

    def _get_or_create_public_image(self, name, image_b64):
        """
        Створити (або знайти) публічний ir.attachment для inline-картинки в email.
        Кеш — в ir.config_parameter (lead_magnet_{name}_attachment_id).
        Автоматично пересоздає якщо картинка змінилась (checksum mismatch).
        Повертає ir.attachment recordset (може бути empty).
        """
        if not image_b64:
            return self.env['ir.attachment'].sudo()
        ICP = self.env['ir.config_parameter'].sudo()
        key = f'odoo_chatwoot_connector.{name}_attachment_id'
        att_id_raw = ICP.get_param(key, '')
        try:
            att_id = int(att_id_raw)
        except (TypeError, ValueError):
            att_id = 0
        Att = self.env['ir.attachment'].sudo()
        if att_id:
            att = Att.browse(att_id)
            if att.exists() and att.public and att.datas == image_b64:
                return att
        att = Att.create(
            {
                'name': f'{name}.png',
                'datas': image_b64,
                'mimetype': 'image/png',
                'res_model': 'ir.ui.view',
                'res_id': 0,
                'public': True,
            }
        )
        ICP.set_param(key, str(att.id))
        return att

    def _generate_and_send_sms_coupon(self, to_phone=None):
        """
        Надсилає SMS зі shared-купоном lead_magnet_coupon_program_id.
        Один код на всіх клієнтів — спільний pool, Odoo loyalty знижує
        points на кожному використанні.

        Повертає {'ok', 'error', 'code', 'remaining', 'expires'}.
        Ідемпотентно — якщо клієнту SMS уже надіслано, повертає existing.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        empty = {'ok': False, 'error': '', 'code': '', 'remaining': 0, 'expires': ''}
        if ICP.get_param('odoo_chatwoot_connector.lead_magnet_enabled', 'False') != 'True':
            return {**empty, 'error': 'disabled'}
        to_phone = (
            to_phone
            or (self.partner_id.mobile or self.partner_id.phone if self.partner_id else '')
            or ''
        ).strip()
        if not to_phone:
            return {**empty, 'error': 'no_phone'}
        # Idempotency: той самий клієнт — той самий код (shared pool)
        if self.sp_coupon_code and self.sp_coupon_sent_at:
            return {**empty, 'ok': True, 'error': 'already_sent', 'code': self.sp_coupon_code}

        # RODO/PKE: SMS — окремий канал, потрібна окрема згода.
        ConsentLog = self.env['sendpulse.privacy.consent.log'].sudo()
        enforce_consent = (
            ICP.get_param('odoo_chatwoot_connector.consent_enforcement_enabled', 'True') == 'True'
        )
        if enforce_consent:
            last_consent = ConsentLog.search(
                [
                    ('purpose', '=', 'lead_magnet_sms'),
                    ('phone', '=', to_phone),
                ],
                order='consent_timestamp desc, id desc',
                limit=1,
            )
            if last_consent and not last_consent.consent_given:
                _logger.info(
                    'SendPulse Odoo: F13 SMS skip — consent withdrawn for %s',
                    to_phone,
                )
                return {**empty, 'error': 'consent_withdrawn'}

        program_id_raw = ICP.get_param('odoo_chatwoot_connector.lead_magnet_coupon_program_id', '')
        try:
            program_id = int(program_id_raw)
        except (TypeError, ValueError):
            return {**empty, 'error': 'no_program_configured'}
        program = self.env['loyalty.program'].sudo().browse(program_id)
        if not program.exists():
            return {**empty, 'error': 'program_missing'}

        # Беремо shared card програми (перший active card з points > 0).
        # Якщо нема — fallback: створюємо одну spільну.
        card = (
            self.env['loyalty.card']
            .sudo()
            .search(
                [('program_id', '=', program.id), ('points', '>', 0)],
                order='id',
                limit=1,
            )
        )
        if not card:
            card = (
                self.env['loyalty.card']
                .sudo()
                .search(
                    [('program_id', '=', program.id)],
                    order='id desc',
                    limit=1,
                )
            )
            if not card:
                try:
                    card = (
                        self.env['loyalty.card']
                        .sudo()
                        .create(
                            {
                                'program_id': program.id,
                                'points': 100.0,
                            }
                        )
                    )
                except Exception as e:
                    return {**empty, 'error': f'coupon_create:{e}'}
        code = card.code
        remaining = int(card.points) if card.points is not None else 0
        expires_str = card.expiration_date.strftime('%d.%m.%Y') if card.expiration_date else ''

        if remaining <= 0:
            return {**empty, 'error': 'coupon_exhausted', 'code': code, 'expires': expires_str}

        # Compose SMS text
        sms_tmpl = ICP.get_param(
            'odoo_chatwoot_connector.lead_magnet_sms_template',
            '',
        ) or (
            'CampScout: код 5% знижки — {code}. Залишилось {remaining} '
            'купонів! Діє до {expires}. Оформляйте: campscout.eu'
        )
        sms_text = (
            sms_tmpl.replace('{code}', code)
            .replace('{remaining}', str(remaining))
            .replace('{expires}', expires_str or '01.07.2026')
        )

        # Send via kw_sms_api (TurboSMS) — sms.sms record with kw_sms_provider_id set
        sms_provider_id = ICP.get_param('odoo_chatwoot_connector.sms_provider_id', '')
        try:
            sms_provider_id = int(sms_provider_id)
        except (TypeError, ValueError):
            sms_provider_id = False

        sms_vals = {
            'number': to_phone,
            'body': sms_text[:300],
            'partner_id': self.partner_id.id if self.partner_id else False,
        }
        # kw_sms_api додає поле kw_sms_provider_id — ставимо якщо налаштовано
        if sms_provider_id and 'kw_sms_provider_id' in self.env['sms.sms']._fields:
            sms_vals['kw_sms_provider_id'] = sms_provider_id
        try:
            sms = self.env['sms.sms'].sudo().create(sms_vals)
            sms.send()
        except Exception as e:
            _logger.warning('SendPulse Odoo: F13 SMS send exception — %s', e)
            return {'ok': False, 'error': f'sms_send:{e}', 'code': code}

        self.sudo().write(
            {
                'sp_coupon_code': code,
                'sp_coupon_sent_at': fields.Datetime.now(),
                'sp_coupon_sent_to_phone': to_phone,
            }
        )
        # RODO/PKE: фіксуємо SMS-консент (окремий канал від email).
        if enforce_consent:
            last_in_msg = (
                self.env['sendpulse.message']
                .sudo()
                .search(
                    [
                        ('connect_id', '=', self.id),
                        ('direction', '=', 'incoming'),
                    ],
                    order='date desc, id desc',
                    limit=1,
                )
            )
            ConsentLog.record_consent(
                purpose='lead_magnet_sms',
                channel='sms',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=last_in_msg.id if last_in_msg else False,
                phone=to_phone,
                consent_given=True,
                exact_response=(last_in_msg.text_message or to_phone) if last_in_msg else to_phone,
                notes=f'Auto-recorded on SMS coupon send for connect {self.id}',
            )
        _logger.info(
            'SendPulse Odoo: F13 coupon %s sent to %s for connect %s (remaining=%d)',
            code,
            to_phone,
            self.id,
            remaining,
        )
        return {
            'ok': True,
            'error': None,
            'code': code,
            'remaining': remaining,
            'expires': expires_str,
        }

    @api.model
    def send_pdf_catalog_for_channel(self, channel_id, to_email=None):
        """RPC для OWL-панелі. Надсилає PDF-каталог на email."""
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return {'ok': False, 'error': 'no_connect', 'message_id': None}
        return connect._send_pdf_catalog_email(to_email=to_email)

    @api.model
    def send_sms_coupon_for_channel(self, channel_id, to_phone=None):
        """RPC для OWL-панелі. Генерує coupon + SMS."""
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return {'ok': False, 'error': 'no_connect', 'code': ''}
        return connect._generate_and_send_sms_coupon(to_phone=to_phone)

    # ── V2 F1: RAG FAQ auto-answer ────────────────────────────────────────
    def _rag_answer_question(self, question_text, contact_name=''):
        """
        Через Anthropic Claude підбирає найкращу FAQ відповідь на питання клієнта
        і персоналізує її. Модель читає список всіх активних FAQ у контексті
        (не embedding-based, а in-context retrieval — простіше і достатньо для <100 FAQ).

        Повертає dict:
        {
            'matched': bool,
            'faq_id': int or None,
            'confidence': float (0..1),
            'answer': str,
            'reason': str (для debug),
        }

        No-op повертає {'matched': False, ...} якщо RAG вимкнений або API key відсутній.
        """
        empty = {
            'matched': False,
            'faq_id': None,
            'confidence': 0.0,
            'answer': '',
            'reason': 'not_configured',
        }
        if not question_text or not question_text.strip():
            return empty

        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.rag_auto_answer_enabled', 'False') != 'True':
            return empty
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return {**empty, 'reason': 'no_api_key'}

        Faq = self.env['sendpulse.faq.entry'].sudo()
        faqs = Faq.get_active_faq_for_prompt()
        if not faqs:
            return {**empty, 'reason': 'no_faqs'}

        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')

        # Будуємо prompt з переліком FAQ у компактному форматі
        faq_block = '\n'.join(
            [f'FAQ_{f["id"]}: Q: {f["question"]}\n   A: {f["answer"]}' for f in faqs]
        )
        contact_hint = f' Клієнт: {contact_name}.' if contact_name else ''
        # F14: live seats якщо питання стосується конкретного табору
        live_events = self._get_live_events_context()
        live_events_block = f'{live_events}\n\n' if live_events else ''
        prompt = (
            f'Ти — AI-асистент менеджера CampScout (дитячі табори 6-17 років у Польщі).\n'
            f'Наш стиль: продавці-консультанти, не сухі факти — ЦІННІСТЬ + ТЕРМІНОВІСТЬ + CTA.\n\n'
            f'Клієнт написав у приват:\n'
            f'"""\n{question_text[:500]}\n"""\n\n'
            f'{contact_hint}\n\n'
            f'{live_events_block}'
            f'База FAQ з canonical відповідями:\n\n'
            f'{faq_block}\n\n'
            f'Завдання:\n'
            f'1. Знайди FAQ-match (навіть перефразованого). Якщо жоден не підходить — NO_MATCH.\n'
            f'2. Якщо match — перепиши canonical answer персоналізовано для клієнта:\n'
            f'   - Звертайся ТІЛЬКИ на «Ви» (ніколи «ти» — батьки, не ровесники), 3-6 речень\n'
            f'   - ЗБЕРЕЖИ ключові ЦИФРИ, НАЗВИ ТАБОРІВ, URL з canonical (НЕ вигадуй власні!)\n'
            f'   - Якщо питання про конкретний табір/зміну і він є у LIVE ТАБОРИ — '
            f'додай актуальну доступність: ❗ <30% = FOMO, 🔴 = запропонуй аналог.\n'
            f"   - Якщо є ім'я клієнта — вплети у першу фразу\n"
            f'   - Закінчуй CTA-запитанням (ведемо у діалог, не закриваємо)\n'
            f'   - Емодзі 1-2 максимум\n'
            f'3. Оціни confidence 0.0-1.0 наскільки певен що це саме цей FAQ.\n\n'
            f'КАТЕГОРИЧНО ЗАБОРОНЕНО:\n'
            f'❌ Звертання на «ти/тобі/твій» — завжди «Ви», «Вам», «Ваш», «Ваша дитина»\n'
            f'❌ Просити у чаті ПІБ/дату народження/медичні дані дитини — батьки '
            f'заповнюють картку САМІ у особистому кабінеті і ПІДПИСУЮТЬ. Без підпису '
            f'картка юридичної сили не має, тому ми не маємо права записувати за них.\n'
            f'❌ Слово «доставка» стосовно дітей — ми НЕ вантаж. Правильно: «трансфер», «привезти», «забрати», «супровід»\n'
            f'❌ Вигадувати факти яких нема у canonical (ціни, дати, програми)\n'
            f'❌ Починати з «Дякую за питання» / «Чудове питання» / «Радий вашому коментарю»\n'
            f'❌ «Там все є» / «Все на сайті» — завжди 2-3 конкретних факти, ПОТІМ URL\n'
            f'❌ «11 років — перехідний вік» (для 11 є TDK від 6 до 11)\n'
            f'❌ Агресивно порівнювати з конкурентами\n'
            f'❌ 3 URL підряд без пояснення\n\n'
            f'Формат — STRICT JSON:\n'
            f'{{"faq_id": 42 або null, "confidence": 0.9, "answer": "text"}}\n'
            f'NO_MATCH: {{"faq_id": null, "confidence": 0.0, "answer": ""}}\n'
            f'Поверни ТІЛЬКИ JSON, без пояснень.'
        )

        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': model,
                    'max_tokens': 500,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: RAG HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return {**empty, 'reason': f'http_{resp.status_code}'}

            raw = (resp.json().get('content') or [{}])[0].get('text', '').strip()
            # Claude іноді обрамляє у ```json ... ```; зрізаємо
            import json as _json
            import re as _re

            m = _re.search(r'\{[\s\S]*?\}', raw)
            if not m:
                _logger.warning('SendPulse Odoo: RAG no JSON in response — %s', raw[:200])
                return {**empty, 'reason': 'no_json'}
            data = _json.loads(m.group(0))
            faq_id_raw = data.get('faq_id')
            confidence = float(data.get('confidence') or 0.0)
            answer = (data.get('answer') or '').strip()

            if not faq_id_raw or not answer:
                return {
                    'matched': False,
                    'faq_id': None,
                    'confidence': confidence,
                    'answer': '',
                    'reason': 'no_match',
                }

            # Normalize faq_id: Claude іноді повертає "FAQ_6" або "6" замість integer
            faq_id = None
            if isinstance(faq_id_raw, int):
                faq_id = faq_id_raw
            elif isinstance(faq_id_raw, str):
                digits = _re.search(r'\d+', faq_id_raw)
                if digits:
                    try:
                        faq_id = int(digits.group(0))
                    except (ValueError, TypeError):
                        pass
            if not faq_id:
                return {
                    'matched': False,
                    'faq_id': None,
                    'confidence': confidence,
                    'answer': '',
                    'reason': 'bad_faq_id',
                }

            # Increment hit count + last_used_at
            faq = Faq.browse(faq_id).exists()
            if faq:
                faq.sudo().write(
                    {
                        'hit_count': faq.hit_count + 1,
                        'last_used_at': fields.Datetime.now(),
                    }
                )

            return {
                'matched': True,
                'faq_id': faq_id,
                'confidence': confidence,
                'answer': answer,
                'reason': 'ok',
            }
        except Exception as e:
            _logger.error('SendPulse Odoo: RAG exception — %s', e)
            return {**empty, 'reason': f'exception: {str(e)[:100]}'}

    def _try_rag_auto_answer(self, question_text):
        """
        Helper: якщо RAG дав match з достатнім confidence — надсилає автовідповідь
        клієнту через SendPulse + постить у Discuss-канал з 🤖 маркером.

        Гейт: respects `rag_auto_confidence_threshold` (default 0.85).
        Ідемпотентний — rag_auto_answered_at не дозволяє спамити автовідповіді частіше ніж раз/годину.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.rag_auto_answer_enabled', 'False') != 'True':
            return

        # V2 F1 guard: RAG НЕ втручається у активну розмову з оператором.
        # Критерії «оператор вже у чаті»:
        #   1. Оператор уже відповідав (sp_first_reply_at не порожнє) — класичний pickup
        #   2. Stage = in_progress — оператор взяв чат у роботу через action_open_discuss
        #   3. У каналі є non-bot members (оператори долучені)
        # Також не лізти у identifying / close.
        if self.stage in ('in_progress', 'close', 'identifying'):
            _logger.info(
                'SendPulse Odoo: RAG skip for connect %s — stage=%s (operator engaged)',
                self.id,
                self.stage,
            )
            return
        if self.sp_first_reply_at:
            _logger.info(
                'SendPulse Odoo: RAG skip for connect %s — operator already replied at %s',
                self.id,
                self.sp_first_reply_at,
            )
            return

        try:
            threshold = float(
                ICP.get_param('odoo_chatwoot_connector.rag_auto_confidence_threshold', '0.85')
            )
        except (ValueError, TypeError):
            threshold = 0.85

        # Rate-limit: якщо нещодавно (< 1h) вже відповіли автоматично — skip
        now = fields.Datetime.now()
        if self.rag_auto_answered_at and (now - self.rag_auto_answered_at) < timedelta(hours=1):
            return

        result = self._rag_answer_question(question_text, contact_name=self.name or '')
        if not result.get('matched'):
            return
        if result.get('confidence', 0.0) < threshold:
            _logger.info(
                'SendPulse Odoo: RAG match below threshold for connect %s (conf=%.2f < %.2f)',
                self.id,
                result.get('confidence'),
                threshold,
            )
            return

        answer = result['answer']
        faq_id = result['faq_id']
        try:
            # Шлемо через SendPulse API
            sent = self.send_message_to_sendpulse(answer, attachment_url=None)
            if not sent:
                _logger.warning(
                    'SendPulse Odoo: RAG auto-answer send failed for connect %s', self.id
                )
                return
            # Мітимо розмову
            self.write(
                {
                    'rag_auto_answered_at': now,
                    'rag_last_faq_id': faq_id,
                }
            )
            # Нотатка у Discuss-канал з маркером
            if self.channel_id:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=Markup(
                        '🤖 <b>Auto-answered (RAG FAQ #{faq_id}, confidence {conf:.0%})</b><br/>'
                        '<i>Питання клієнта:</i> {q}<br/>'
                        '<i>Відповідь:</i> {a}'
                    ).format(
                        faq_id=faq_id,
                        conf=result.get('confidence', 0.0),
                        q=escape(question_text[:200]),
                        a=escape(answer),
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            _logger.info(
                'SendPulse Odoo: RAG auto-answered connect %s from FAQ #%s (conf=%.2f)',
                self.id,
                faq_id,
                result.get('confidence', 0.0),
            )
        except Exception as e:
            _logger.error(
                'SendPulse Odoo: RAG auto-answer exception for connect %s: %s', self.id, e
            )

    # ── V2 F6: Long-lived token auto-refresh ──────────────────────────────
    @api.model
    def _exchange_token_for_long_lived(self, short_lived_token):
        """
        Обмінює токен на long-lived через Meta Graph /oauth/access_token.
        Повертає (new_token, expires_in) або (None, None) на помилку.
        Потребує fb_app_id + fb_app_secret у ir.config_parameter.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        app_id = ICP.get_param('odoo_chatwoot_connector.fb_app_id', '')
        app_secret = ICP.get_param('odoo_chatwoot_connector.fb_app_secret', '')
        if not (app_id and app_secret and short_lived_token):
            return None, None
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/oauth/access_token',
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': app_id,
                    'client_secret': app_secret,
                    'fb_exchange_token': short_lived_token,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                err = self._parse_fb_error(resp)
                _logger.error('SendPulse Odoo: token exchange HTTP %d — %s', resp.status_code, err)
                return None, None
            data = resp.json()
            new_token = data.get('access_token') or ''
            expires_in = data.get('expires_in')  # seconds, або null для безстрокового
            return new_token or None, expires_in
        except Exception as e:
            _logger.error('SendPulse Odoo: token exchange exception — %s', e)
            return None, None

    @api.model
    def cron_refresh_fb_tokens(self):
        """
        Weekly. Для кожного Page де токен помирає < token_refresh_threshold_days днів —
        exchange на long-lived.
        No-op якщо auto_refresh_tokens_enabled=False або app credentials не налаштовані.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.auto_refresh_tokens_enabled', 'False') != 'True':
            return
        app_id = ICP.get_param('odoo_chatwoot_connector.fb_app_id', '')
        app_secret = ICP.get_param('odoo_chatwoot_connector.fb_app_secret', '')
        if not (app_id and app_secret):
            _logger.info('SendPulse Odoo: token refresh skipped — no app_id/secret')
            return
        try:
            threshold_days = int(
                ICP.get_param('odoo_chatwoot_connector.token_refresh_threshold_days', '14')
            )
        except (ValueError, TypeError):
            threshold_days = 14

        Page = self.env['sendpulse.facebook.page'].sudo()
        refreshed = 0
        failed = 0
        for page in Page.search([('active', '=', True)]):
            if not page.access_token:
                continue
            result = self._check_single_fb_token(page.access_token, page.name or page.page_id)
            days_left = result.get('days_left')
            # Exchange тільки якщо знаємо скільки лишилось і мало
            if days_left is None or days_left >= threshold_days:
                continue
            _logger.info(
                'SendPulse Odoo: refreshing token for %s (%d days left)',
                page.name,
                days_left,
            )
            new_token, expires_in = self._exchange_token_for_long_lived(page.access_token)
            if new_token:
                page.write(
                    {
                        'access_token': new_token,
                        'last_checked_at': fields.Datetime.now(),
                    }
                )
                # Одразу перевіряємо новий токен щоб оновити token_status
                new_result = self._check_single_fb_token(new_token, page.name)
                page.write({'token_status': new_result.get('status', 'refreshed')})
                refreshed += 1
                self._notify_telegram(
                    f'🔄 <b>FB Page Token refreshed</b> [{page.name}]\n'
                    f'Новий статус: {new_result.get("status", "valid")}',
                    silent=True,
                )
            else:
                failed += 1
                self._notify_telegram(
                    f'❌ <b>FB Page Token refresh FAILED</b> [{page.name}]\n'
                    f'Потрібна ручна регенерація — токен помре за {days_left}д.',
                    silent=False,
                )
        _logger.info(
            'SendPulse Odoo: cron_refresh_fb_tokens — refreshed %d, failed %d',
            refreshed,
            failed,
        )

    def _hide_comment(self, comment_id, service='facebook', page=None):
        """
        Приховує коментар через Graph API.
        FB: POST /{comment_id} body={'is_hidden': true}
        IG: POST /{comment_id} body={'hide': true}
        Повертає (success: bool, error: str|None).
        """
        token = self._get_fb_page_token(page=page)
        if not token or not comment_id:
            return False, 'token або comment_id відсутні'
        url = f'https://graph.facebook.com/v25.0/{comment_id}'
        payload = (
            {'hide': True, 'access_token': token}
            if service == 'instagram'
            else {'is_hidden': True, 'access_token': token}
        )
        ok, err, _resp = self._fb_post_with_retry(
            url,
            payload,
            label=f'hide-comment {comment_id} ({service})',
        )
        if ok:
            _logger.info('SendPulse Odoo: comment %s hidden (%s)', comment_id, service)
        return ok, err

    def _send_comment_public_reply(self, comment_id, service, text, page=None):
        """
        Публікує публічну відповідь під коментарем через Facebook Graph API.
        Facebook: POST /v25.0/{comment_id}/comments
        Instagram: POST /v25.0/{comment_id}/replies
        page — sendpulse.facebook.page record (опц.). Якщо не задано — fallback на legacy.
        Повертає (success: bool, error: str|None)
        """
        token = self._get_fb_page_token(page=page)
        if not token:
            return (
                False,
                'Page Access Token не налаштований (Налаштування → SendPulse → Facebook Page Access Token, або створіть запис у Facebook Pages)',
            )

        endpoint = 'replies' if service == 'instagram' else 'comments'
        url = f'https://graph.facebook.com/v25.0/{comment_id}/{endpoint}'
        ok, err, _resp = self._fb_post_with_retry(
            url,
            {'message': text, 'access_token': token},
            label=f'public-reply {comment_id}',
        )
        if ok:
            _logger.info('SendPulse Odoo: public reply posted for comment %s', comment_id)
        return ok, err

    def _send_comment_private_reply(self, comment_id, text, service='facebook', page=None):
        """
        Надсилає приватне повідомлення у відповідь на коментар.
        Facebook: POST /{comment_id}/private_replies
        Instagram: POST /{ig-user-id}/messages з recipient.comment_id
        page — sendpulse.facebook.page record (опц.). Для IG використовує page.ig_business_id.
        Повертає (success: bool, error: str|None)
        """
        token = self._get_fb_page_token(page=page)
        if not token:
            return False, 'Page Access Token не налаштований'

        if service == 'instagram':
            # Спочатку пробуємо per-page ig_business_id, потім глобальний fallback
            ig_user_id = (page.ig_business_id if page else False) or self.env[
                'ir.config_parameter'
            ].sudo().get_param('odoo_chatwoot_connector.ig_user_id', '')
            if not ig_user_id:
                return (
                    False,
                    'Instagram Business Account ID не налаштований (ні на Page, ні в глобальних settings)',
                )
            url = f'https://graph.facebook.com/v25.0/{ig_user_id}/messages'
            payload = {
                'recipient': {'comment_id': comment_id},
                'message': {'text': text},
                'access_token': token,
            }
        else:
            url = f'https://graph.facebook.com/v25.0/{comment_id}/private_replies'
            payload = {'message': text, 'access_token': token}

        ok, err, _resp = self._fb_post_with_retry(
            url,
            payload,
            label=f'private-reply {comment_id} ({service})',
        )
        if ok:
            _logger.info(
                'SendPulse Odoo: private reply sent for comment %s (%s)', comment_id, service
            )
        return ok, err

    def _get_fb_page_token(self, page=None):
        """
        Повертає Facebook Page Access Token.

        Пріоритет:
        1. page.access_token — якщо передано Page record з токеном
        2. Page за sp_page_id цієї розмови (self) — для multi-page webhook-ів
        3. Default Page у sendpulse.facebook.page (is_default=True, active=True)
        4. Legacy fallback — `ir.config_parameter.fb_page_access_token`
        """
        if page and page.access_token:
            return page.access_token
        # Якщо self — sendpulse.connect запис з sp_page_id, спробуємо знайти Page
        if self and hasattr(self, 'sp_page_id') and self.sp_page_id:
            Page = self.env['sendpulse.facebook.page'].sudo()
            found = Page.find_by_page_id(self.sp_page_id)
            if found and found.access_token:
                return found.access_token
        # Default Page
        Page = self.env['sendpulse.facebook.page'].sudo()
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

    @api.model
    def cron_check_messenger_windows(self):
        """
        Шукає розмови де Messenger 24h-вікно закривається менш ніж за 2 години.
        Надсилає Telegram-алерт + нотатку у Discuss-канал, позначає sp_window_alert_sent=True
        щоб не повторювати сповіщення.
        """
        now = fields.Datetime.now()
        threshold = now + timedelta(hours=2)
        records = self.search(
            [
                ('sp_messenger_window_expires_at', '!=', False),
                ('sp_messenger_window_expires_at', '<=', threshold),
                ('sp_messenger_window_expires_at', '>', now),
                ('sp_window_alert_sent', '=', False),
                ('stage', '!=', 'close'),
            ]
        )
        for rec in records:
            minutes_left = int((rec.sp_messenger_window_expires_at - now).total_seconds() / 60)
            _logger.info(
                'SendPulse Odoo: window closing in %d min for connect %s (%s)',
                minutes_left,
                rec.id,
                rec.name,
            )
            self._notify_telegram(
                f'⏳ <b>Вікно 24h скоро закриється</b>\n\n'
                f'👤 {rec.name} ({rec._get_service_label()})\n'
                f'⏱ Залишилось: <b>{minutes_left} хв</b>\n\n'
                f'Після цього не зможемо писати клієнту поки він не напише сам.',
                silent=True,
            )
            if rec.channel_id:
                rec.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=Markup(  # noqa: S704 internal int, no user input
                        f'⏳ <b>Вікно 24h закривається за {minutes_left} хв.</b> '
                        f'Якщо потрібно — напишіть клієнту зараз.'
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            rec.write({'sp_window_alert_sent': True})

    @api.model
    def _check_single_fb_token(self, token, label):
        """
        Перевіряє один Facebook Page Access Token.
        Повертає dict: {valid: bool, status: str, days_left: int|None, error: str|None}.
        При `invalid` — надсилає Telegram-алерт з міткою label (напр. "CampScout" або "legacy").
        """
        if not token:
            return {'valid': False, 'status': 'not_configured', 'days_left': None, 'error': None}
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/me',
                params={'access_token': token, 'fields': 'id,name'},
                timeout=15,
            )
            if resp.status_code != 200:
                err = self._parse_fb_error(resp)
                _logger.error('SendPulse Odoo [%s]: FB token invalid — %s', label, err)
                self._notify_telegram(
                    f'⚠️ <b>FB Page Token НЕДІЙСНИЙ</b> [{label}]\n\n'
                    f'Причина: {err}\n\n'
                    f'Автовідповіді і приватні повідомлення для цієї Page не працюють. '
                    f'Потрібно згенерувати новий токен.'
                )
                return {
                    'valid': False,
                    'status': f'invalid: {err[:100]}',
                    'days_left': None,
                    'error': err,
                }
        except Exception as e:
            _logger.error('SendPulse Odoo [%s]: FB token check failed — %s', label, e)
            return {
                'valid': False,
                'status': f'check_failed: {str(e)[:100]}',
                'days_left': None,
                'error': str(e),
            }

        # /debug_token (якщо є app credentials)
        ICP = self.env['ir.config_parameter'].sudo()
        app_id = ICP.get_param('odoo_chatwoot_connector.fb_app_id', '')
        app_secret = ICP.get_param('odoo_chatwoot_connector.fb_app_secret', '')
        if not (app_id and app_secret):
            return {
                'valid': True,
                'status': 'valid (no app_id/secret for expiry)',
                'days_left': None,
                'error': None,
            }
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/debug_token',
                params={'input_token': token, 'access_token': f'{app_id}|{app_secret}'},
                timeout=15,
            )
            if resp.status_code != 200:
                return {
                    'valid': True,
                    'status': 'valid (debug_token failed)',
                    'days_left': None,
                    'error': None,
                }
            data = resp.json().get('data', {})
            expires_at = data.get('expires_at', 0)
            if expires_at == 0:
                return {
                    'valid': True,
                    'status': 'valid: never expires',
                    'days_left': None,
                    'error': None,
                }
            exp_dt = datetime.utcfromtimestamp(expires_at)
            days_left = (exp_dt - datetime.utcnow()).days
            if days_left < 7:
                _logger.error('SendPulse Odoo [%s]: FB token expires in %d days!', label, days_left)
                self._notify_telegram(
                    f'⚠️ <b>FB Page Token скоро помре</b> [{label}]\n\n'
                    f'Залишилось днів: <b>{days_left}</b>\n'
                    f'Треба згенерувати новий у Business Manager → System Users → Generate Token.'
                )
                return {
                    'valid': True,
                    'status': f'expires_soon: {days_left}d',
                    'days_left': days_left,
                    'error': None,
                }
            return {
                'valid': True,
                'status': f'valid: {days_left}d left',
                'days_left': days_left,
                'error': None,
            }
        except Exception as e:
            _logger.warning('SendPulse Odoo [%s]: debug_token exception — %s', label, e)
            return {
                'valid': True,
                'status': 'valid (debug_token error)',
                'days_left': None,
                'error': None,
            }

    @api.model
    def cron_check_fb_token_expiry(self):
        """
        Щотижнева перевірка токенів. Перевіряє:
        1. Усі записи sendpulse.facebook.page (active=True)
        2. Legacy fb_page_access_token (якщо ще використовується)
        """
        now_iso = fields.Datetime.now()
        ICP = self.env['ir.config_parameter'].sudo()

        # 1. Multi-page токени
        Page = self.env['sendpulse.facebook.page'].sudo()
        for page in Page.search([('active', '=', True)]):
            res = self._check_single_fb_token(page.access_token, page.name or page.page_id)
            page.write(
                {
                    'token_status': res['status'],
                    'last_checked_at': now_iso,
                }
            )

        # 2. Legacy токен (для обратної сумісності — поки не всі міграли на Page records)
        legacy_token = ICP.get_param('odoo_chatwoot_connector.fb_page_access_token', '')
        ICP.set_param('odoo_chatwoot_connector.fb_token_last_check', now_iso.isoformat())
        if legacy_token:
            # Перевіряємо тільки якщо legacy не дублює якусь Page (щоб не слати 2 алерти)
            duplicate = Page.search(
                [('access_token', '=', legacy_token), ('active', '=', True)], limit=1
            )
            if not duplicate:
                res = self._check_single_fb_token(legacy_token, 'legacy fb_page_access_token')
                ICP.set_param('odoo_chatwoot_connector.fb_token_status', res['status'])
                if res.get('days_left') is not None:
                    ICP.set_param(
                        'odoo_chatwoot_connector.fb_token_expires_at',
                        (datetime.utcnow() + timedelta(days=res['days_left'])).isoformat(),
                    )
            else:
                ICP.set_param(
                    'odoo_chatwoot_connector.fb_token_status',
                    f'valid (mirrored by Page "{duplicate.name}")',
                )
        else:
            ICP.set_param('odoo_chatwoot_connector.fb_token_status', 'not_configured')

    @staticmethod
    def _parse_fb_error(resp):
        """Витягує людиночитане повідомлення про помилку з відповіді Graph API."""
        try:
            data = resp.json()
            err = data.get('error', {})
            msg = err.get('message', '') or ''
            code = err.get('code', '')
            subcode = err.get('error_subcode', '')
            parts = [
                p
                for p in [
                    f'код {code}' if code else '',
                    f'підкод {subcode}' if subcode else '',
                    msg,
                ]
                if p
            ]
            return ' — '.join(parts) or resp.text[:200]
        except Exception:
            return resp.text[:200] if resp.text else f'HTTP {resp.status_code}'

    _CATEGORY_LABELS = {
        'question_price': '💰 Питання про ціну',
        'question_dates': '📅 Питання про терміни',
        'question_age': '👶 Питання про вік',
        'question_general': '❓ Загальне питання',
        'thanks': '🙏 Подяка / позитив',
        'complaint': '🚨 СКАРГА — потрібна увага оператора',
        'spam': '🚫 Спам',
        'other': '🔸 Інше',
    }

    def _notify_operator_comment(
        self,
        contact_name,
        comment_text,
        post_url,
        sent_public,
        sent_private,
        public_error,
        private_error,
        category=None,
    ):
        """Надсилає системну нотатку від OdooBot у Discuss-канал розмови."""
        if not self.channel_id:
            return

        lines = [f'💬 Новий коментар під постом [{self._get_service_label()}]', '']
        lines.append(f'👤 Клієнт: {contact_name}')
        if comment_text:
            lines.append(f'📝 Коментар: "{comment_text}"')
        if category and category != 'other':
            lines.append(f'🏷️ Категорія: {self._CATEGORY_LABELS.get(category, category)}')
        if post_url:
            lines.append(f'🔗 Допис: {post_url}')
        lines.append('')

        if sent_public:
            lines.append('✅ Публічна відповідь опублікована під коментарем')
        elif public_error:
            lines.append(f'❌ Публічна відповідь не надіслана: {public_error}')
        else:
            lines.append('⏭️ Публічна відповідь вимкнена в налаштуваннях')

        if sent_private:
            lines.append('✅ Приватне повідомлення надіслано у Messenger')
            lines.append(
                '⏳ Очікуємо відповіді від клієнта — поки клієнт не відповів, писати йому не можна (правило Meta)'
            )
        elif private_error:
            lines.append(f'❌ Приватне повідомлення не надіслано: {private_error}')
        else:
            lines.append(
                '⏭️ Приватне повідомлення не надіслається (клієнт вже отримував раніше або вимкнено)'
            )

        body = Markup('<br/>').join(escape(line) if line else Markup('') for line in lines)
        self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
            author_id=self.env.ref('base.partner_root').id,
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

    @api.model
    def _process_outgoing_event(self, contact, service, timestamp_ms):
        """
        Обробляє outbound_message / outgoing_message events.

        У payload.contact.last_message SendPulse завжди тримає ОСТАННЄ
        КЛІЄНТСЬКЕ повідомлення (не текст оператора). Використовуємо це
        для backfill missed incoming — SendPulse іноді не шле окремий
        incoming_message webhook коли new_subscriber і перший текст
        клієнта приходять з дуже малою різницею у часі.
        """
        contact_id = contact.get('id', '')
        last_message = contact.get('last_message', '') or ''

        if not last_message or not contact_id:
            return

        # Guard: якщо цей текст уже є як incoming → нічого робити не треба
        already_incoming = self.env['sendpulse.message'].search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('direction', '=', 'incoming'),
                ('text_message', '=', last_message),
            ],
            limit=1,
        )
        if already_incoming:
            return

        # Знаходимо активну розмову
        connect = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ],
            limit=1,
        )
        if not connect:
            return

        # ── Backfill MISSED incoming ────────────────────────────────────────
        # Текст клієнта якого немає у incoming → SendPulse пропустив webhook.
        # Створюємо як incoming з поміткою у channel.
        now = fields.Datetime.now()
        _logger.info(
            'SendPulse Odoo: backfill missed incoming для contact=%s: %r',
            contact_id,
            last_message[:80],
        )

        author_id = (
            connect.partner_id.id if connect.partner_id else self.env.ref('base.partner_root').id
        )
        # Тут (на відміну від greeting і incoming-media сайтів) create → post →
        # partner-create йдуть підряд без жодного side-effecting виклику між
        # ними в оригінальному коді — тому єдиний виклик helper-а безпечний і
        # відтворює той самий порядок.
        self._record_conversation_message(
            connect,
            direction='incoming',
            sendpulse_contact_id=contact_id,
            message_type='text',
            text_message=last_message,
            raw_json={'text': last_message, 'source': 'backfill_from_outgoing_event'},
            date=now,
            channel_body=Markup(
                '<p><em>(backfill — SendPulse пропустив webhook)</em><br/>{}</p>'
            ).format(escape(last_message)),
            channel_author_id=author_id,
            partner_body=f'<p>👤 {last_message}</p>',
        )

        update_vals = {
            'last_message_preview': last_message[:100],
            'last_message_date': now,
        }
        # Клієнт написав → вікно 24h відновлюється
        update_vals['sp_messenger_window_expires_at'] = now + timedelta(hours=24)
        update_vals['sp_window_alert_sent'] = False
        if connect.sp_funnel_stage in ('comment_only', 'private_sent', False, None):
            update_vals['sp_funnel_stage'] = 'customer_replied'
        if connect.stage == 'in_progress':
            update_vals['stage'] = 'new_message'
        connect.write(update_vals)

    @api.model
    def _process_unsubscribe(self, contact_id, service):
        """Відмічає розмову як закриту при відписці клієнта."""
        connects = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ]
        )
        for connect in connects:
            connect.write({'stage': 'close'})
            _logger.info(
                'SendPulse Odoo: контакт %s відписався (%s), розмова закрита',
                contact_id,
                service,
            )

    _ALLOWED_MEDIA_DOMAINS = ('sendpulse.com', 'sendpulse.net')
    _MEDIA_MAX_BYTES = 20 * 1024 * 1024  # 20 MB

    @staticmethod
    def _is_allowed_media_url(url):
        """SSRF guard: дозволяємо завантажувати медіа лише з доменів SendPulse."""
        from urllib.parse import urlparse

        try:
            host = (urlparse(url).hostname or '').lower()
            allowed = SendpulseConnect._ALLOWED_MEDIA_DOMAINS
            return host in allowed or any(host.endswith('.' + d) for d in allowed)
        except Exception:
            return False

    def _download_media_as_attachment(self, media_url):
        """
        Download media file from SendPulse API (requires Bearer token) and
        save as ir.attachment so Odoo can display it inline in Discuss.
        Returns ir.attachment record or None on failure.
        """
        try:
            # SSRF guard
            if not self._is_allowed_media_url(media_url):
                _logger.warning(
                    'SendPulse Odoo: заблоковано URL не з домену SendPulse: %s', media_url
                )
                return None

            token = self._get_access_token()
            if not token:
                return None

            def _fetch(t):
                return requests.get(
                    media_url,
                    headers={'Authorization': f'Bearer {t}'},
                    timeout=30,
                    stream=True,
                )

            resp = _fetch(token)
            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    resp = _fetch(token)
            resp.raise_for_status()

            # Перевіряємо оголошений розмір перед завантаженням
            content_length = resp.headers.get('Content-Length')
            if content_length:
                try:
                    if int(content_length) > self._MEDIA_MAX_BYTES:
                        _logger.warning(
                            'SendPulse Odoo: медіа завелике (%s байт), пропускаємо', content_length
                        )
                        return None
                except ValueError:
                    pass

            content_type = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
            ext_map = {
                'image/jpeg': 'jpg',
                'image/png': 'png',
                'image/gif': 'gif',
                'image/webp': 'webp',
                'video/mp4': 'mp4',
                'audio/ogg': 'ogg',
                'audio/mpeg': 'mp3',
                'application/pdf': 'pdf',
            }
            ext = ext_map.get(content_type, 'bin')
            filename = f'sendpulse_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}.{ext}'

            # Потокове завантаження з жорстким лімітом
            data = b''
            for chunk in resp.iter_content(8192):
                data += chunk
                if len(data) > self._MEDIA_MAX_BYTES:
                    _logger.warning('SendPulse Odoo: медіа перевищило 20 MB ліміт, скасовуємо')
                    return None

            att = self.env['ir.attachment'].create(
                {
                    'name': filename,
                    'datas': base64.b64encode(data).decode(),
                    'mimetype': content_type,
                }
            )
            att.generate_access_token()
            return att
        except Exception as e:
            _logger.warning('SendPulse Odoo: не вдалося завантажити медіа %s: %s', media_url, e)
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

    # Ліміти SendPulse API по довжині тексту (chars). Перевищення → 400 (#100).
    _SERVICE_TEXT_LIMITS = {
        'telegram': 4096,
        'instagram': 1000,  # SendPulse-side ліміт для IG
        'facebook': 2000,
        'messenger': 2000,
        'whatsapp': 1600,
        'viber': 7000,
        'livechat': 4000,
        'tiktok': 1000,
    }

    @staticmethod
    def _split_text_by_limit(text, max_chars):
        """
        Розбиває текст на частини не довші за max_chars зі збереженням абзаців
        і речень. Стратегія: абзаци → речення → слова → hard cut.
        Повертає list of chunks.
        """
        if not text or len(text) <= max_chars:
            return [text] if text else []

        # Safety margin — залишаємо 20 chars на нумерацію "(1/3) "
        effective_max = max_chars - 20

        def flush(acc, chunks):
            if acc.strip():
                chunks.append(acc.strip())

        chunks = []
        current = ''

        # Крок 1: по абзацах (\n\n)
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if not para.strip():
                continue
            candidate = (current + '\n\n' + para) if current else para
            if len(candidate) <= effective_max:
                current = candidate
                continue
            # Pending current → flush
            flush(current, chunks)
            current = ''
            # Абзац вміщується сам — стаємо ним
            if len(para) <= effective_max:
                current = para
                continue
            # Абзац занадто довгий — по реченнях
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
                # Речення ще довше — по словах
                words = sent.split(' ')
                wbuf = ''
                for w in words:
                    cand3 = (wbuf + ' ' + w) if wbuf else w
                    if len(cand3) <= effective_max:
                        wbuf = cand3
                    else:
                        flush(wbuf, chunks)
                        # Hard cut якщо навіть одне слово > max
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

    def send_message_to_sendpulse(self, text, attachment_url=None):
        """
        Відправляє текстове повідомлення клієнту через SendPulse API.
        Викликається з mail_channel.py при відповіді оператора в Discuss.
        Auto-split: якщо text довший за per-service limit — розбиває на частини
        і шле по черзі. Повертає True якщо ВСІ частини пройшли.
        """
        self.ensure_one()
        if not self.sendpulse_contact_id:
            _logger.warning('SendPulse Odoo: немає contact_id для відправки')
            return False

        # ── V2 F13: Pre-flight check довжини + auto-split ────────────────
        service = self.service or 'telegram'
        limit = self._SERVICE_TEXT_LIMITS.get(service, 2000)
        if text and len(text) > limit:
            chunks = self._split_text_by_limit(text, limit)
            total = len(chunks)
            _logger.info(
                'SendPulse Odoo: text %d chars > %d limit for %s → split into %d chunks',
                len(text),
                limit,
                service,
                total,
            )
            all_ok = True
            for i, chunk in enumerate(chunks, 1):
                prefix = f'({i}/{total}) ' if total > 1 else ''
                piece = prefix + chunk
                # Перша частина несе attachment, решта — лише текст
                att = attachment_url if i == 1 else None
                ok = self._send_single_message(piece, att)
                if not ok:
                    all_ok = False
                    _logger.warning(
                        'SendPulse Odoo: chunk %d/%d failed for contact %s',
                        i,
                        total,
                        self.sendpulse_contact_id,
                    )
                    break
                if i < total:
                    time.sleep(0.7)  # ratelimit-safe pause
            if self.channel_id and total > 1:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=(
                        f'ℹ️ Повідомлення було довше за ліміт {service.title()} ({limit} chars) — '
                        f'автоматично розбите на {total} частин{"" if all_ok else ", АЛЕ не всі пройшли"}.'
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            return all_ok

        return self._send_single_message(text, attachment_url)

    def _send_single_message(self, text, attachment_url=None):
        """Low-level send — без перевірки довжини (для chunk-sending)."""
        self.ensure_one()
        if not self.sendpulse_contact_id:
            return False

        token = self._get_access_token()
        if not token:
            return False

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

        # Маршрутизація по сервісу
        service = self.service or 'telegram'
        endpoint_map = {
            'telegram': 'https://api.sendpulse.com/telegram/contacts/send',
            'instagram': 'https://api.sendpulse.com/instagram/contacts/send',
            'facebook': 'https://api.sendpulse.com/facebook/contacts/send',
            'messenger': 'https://api.sendpulse.com/messenger/contacts/send',
            'viber': 'https://api.sendpulse.com/viber/contacts/send',
            'whatsapp': 'https://api.sendpulse.com/whatsapp/contacts/send',
            'livechat': 'https://api.sendpulse.com/livechat/contacts/send',
        }
        endpoint = endpoint_map.get(service, endpoint_map['telegram'])

        # Кожен канал має свій формат payload
        if service == 'telegram':
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'message': {'type': 'text', 'text': text},
            }
            if attachment_url:
                payload['message'] = {'type': 'photo', 'photo': attachment_url}
        elif service == 'messenger':
            # Facebook Messenger: singular message, messaging_type RESPONSE/UPDATE/MESSAGE_TAG
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'message': {'type': 'RESPONSE', 'content_type': 'message', 'text': text},
            }
            if attachment_url:
                payload['message'] = {
                    'type': 'RESPONSE',
                    'content_type': 'message',
                    'text': attachment_url,
                }
        elif service == 'whatsapp':
            # WhatsApp Business API: singular message, text вкладений як {body: "..."}
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'message': {'type': 'text', 'text': {'body': text}},
            }
            if attachment_url:
                payload['message'] = {'type': 'image', 'image': {'link': attachment_url}}
        else:
            messages = []
            if text:
                messages.append({'type': 'text', 'message': {'text': text}})
            if attachment_url:
                messages.append({'type': 'image', 'message': {'url': attachment_url}})
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'messages': messages,
            }

        try:
            _logger.info(
                'SendPulse Odoo: відправляємо в %s contact=%s payload=%s',
                endpoint,
                self.sendpulse_contact_id,
                payload,
            )
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            _logger.info(
                'SendPulse Odoo: відповідь API status=%s body=%s',
                resp.status_code,
                resp.text.replace('\n', ' ').replace('\r', '')[:500],
            )

            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
                    _logger.info(
                        'SendPulse Odoo: повтор після 401 status=%s body=%s',
                        resp.status_code,
                        resp.text.replace('\n', ' ').replace('\r', '')[:500],
                    )

            # Карта назв каналів для повідомлень оператору
            _SERVICE_LABELS = {
                'telegram': 'Telegram',
                'instagram': 'Instagram',
                'facebook': 'Facebook',
                'messenger': 'Messenger',
                'viber': 'Viber',
                'whatsapp': 'WhatsApp',
                'livechat': 'LiveChat',
                'tiktok': 'TikTok',
            }

            # 400 = контакт неактивний або невалідний запит
            if resp.status_code == 400:
                service_label = _SERVICE_LABELS.get(service, service or 'канал')
                try:
                    err_data = resp.json()
                    contact_errors = (err_data.get('errors') or {}).get('contact_id', [])
                    err_code = contact_errors[0] if contact_errors else ''
                except Exception:
                    err_code = ''

                if err_code == 'contact.errors.not_active':
                    if service in ('messenger', 'facebook'):
                        hint = (
                            'Facebook Messenger: вікно 24 години закрите — '
                            'клієнт не писав першим більше доби. '
                            'Надсилати через Messenger вже немає сенсу. '
                            'Зверніться через інший канал (WhatsApp, email).'
                        )
                    else:
                        hint = (
                            f'Контакт неактивний у {service_label} — '
                            'клієнт відписався від бота або заблокував його.'
                        )
                else:
                    raw = (resp.text or '').replace('\n', ' ').strip()[:200]
                    hint = f'API відхилив запит. Код: {err_code or raw or "невідомо"}.'

                _logger.warning(
                    'SendPulse Odoo: 400 for %s contact=%s (%s): %s',
                    service,
                    self.sendpulse_contact_id,
                    self.name,
                    err_code,
                )
                if self.channel_id:
                    self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                        body=f'❌ Повідомлення не доставлено у {service_label}.\n{hint}',
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=self.env.ref('base.partner_root').id,
                    )
                return False

            # 422 = provider policy/payload rejection (not always the same reason).
            if resp.status_code == 422:
                service_label = _SERVICE_LABELS.get(service, service or 'канал')
                raw_reason = (resp.text or '').replace('\n', ' ').replace('\r', ' ').strip()
                short_reason = raw_reason[:220] if raw_reason else 'Без деталей від API.'
                _logger.warning(
                    'SendPulse Odoo: 422 for %s contact=%s (%s): %s',
                    service,
                    self.sendpulse_contact_id,
                    self.name,
                    short_reason,
                )
                # Розбираємо тіло відповіді щоб дати точну підказку
                try:
                    err_data = resp.json()
                    err_code = err_data.get('error_code')
                    err_errors = err_data.get('errors', {})
                    err_text = ' '.join(
                        str(v)
                        for vals in err_errors.values()
                        for v in (vals if isinstance(vals, list) else [vals])
                    ).lower()
                except Exception:
                    err_code = None
                    err_text = ''

                if err_code == 403 or 'blocked by the user' in err_text or 'forbidden' in err_text:
                    policy_hint = (
                        f'Клієнт заблокував бота у {service_label}. '
                        "Написати через цей канал більше неможливо — зверніться через інший спосіб зв'язку."
                    )
                elif 'invalid' in err_text or 'invalid data' in err_text:
                    policy_hint = (
                        f'API {service_label} відхилив повідомлення: невалідний формат. '
                        'Можливо тип вкладення не підтримується (Instagram не підтримує PDF/документи).'
                    )
                elif service in ('messenger', 'facebook', 'instagram'):
                    policy_hint = (
                        f'Вікно відповіді {service_label} закрите (24 години). '
                        'Зверніться через інший канал (WhatsApp, email).'
                    )
                else:
                    policy_hint = (
                        'Можлива причина: вікно відповіді для каналу закрите '
                        'або формат повідомлення не прийнято API.'
                    )
                if self.channel_id:
                    self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                        body=(
                            f'⚠️ Повідомлення не доставлено у {service_label}.\n'
                            f'{policy_hint}\nAPI: {short_reason}'
                        ),
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=self.env.ref('base.partner_root').id,
                    )
                return False

            resp.raise_for_status()
            _logger.info(
                'SendPulse Odoo: повідомлення відправлено контакту %s', self.sendpulse_contact_id
            )
            # Метрики: фіксуємо першу відповідь оператора
            if not self.sp_first_reply_at:
                update_metrics = {'sp_first_reply_at': fields.Datetime.now()}
                if self.sp_funnel_stage in (
                    'comment_only',
                    'private_sent',
                    'customer_replied',
                    False,
                    None,
                ):
                    update_metrics['sp_funnel_stage'] = 'operator_engaged'
                self.sudo().write(update_metrics)
            return True
        except Exception as e:
            _logger.error('SendPulse Odoo: помилка відправки: %s', e)
            if self.channel_id:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=f'❌ Помилка відправки повідомлення: {e}',
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            return False

    # ════════════════════════════════════════════════════════════════════
    # Cron: Pull Missing Contacts from SendPulse API
    # ════════════════════════════════════════════════════════════════════

    _CONTACT_LIST_ENDPOINTS = {
        'telegram': 'https://api.sendpulse.com/telegram/contacts',
        'instagram': 'https://api.sendpulse.com/instagram/contacts',
        'facebook': 'https://api.sendpulse.com/facebook/contacts',
        'viber': 'https://api.sendpulse.com/viber/contacts',
        'whatsapp': 'https://api.sendpulse.com/whatsapp/contacts',
    }

    @api.model
    def cron_pull_missing_contacts(self):
        """
        Щогодинний крон: тягне активні контакти з SendPulse API та
        створює в Odoo ті що відсутні. Якщо всі є — нічого не робить.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('odoo_chatwoot_connector.client_id', '')
        client_secret = ICP.get_param('odoo_chatwoot_connector.client_secret', '')
        if not client_id or not client_secret:
            _logger.warning('SendPulse cron_pull: client_id/secret не налаштовані')
            return

        # Отримуємо токен через singleton-запис (будь-який активний)
        sample = self.search([], limit=1)
        if not sample:
            _logger.info('SendPulse cron_pull: нема жодного connect-запису, пропускаємо')
            return
        token = sample._get_access_token()
        if not token:
            _logger.warning('SendPulse cron_pull: не вдалося отримати токен')
            return

        # Збираємо унікальні (service, bot_id) з існуючих записів
        self.env.cr.execute("""
            SELECT DISTINCT service, bot_id
            FROM sendpulse_connect
            WHERE service IS NOT NULL AND bot_id IS NOT NULL
        """)
        bots = self.env.cr.fetchall()
        if not bots:
            _logger.info('SendPulse cron_pull: нема ботів для перевірки')
            return

        total_created = 0
        total_updated = 0

        for service, bot_id in bots:
            endpoint = self._CONTACT_LIST_ENDPOINTS.get(service)
            if not endpoint:
                continue

            # Тягнемо контакти з SendPulse по 100 за раз
            offset = 0
            page_size = 100
            while True:
                try:
                    resp = requests.get(
                        endpoint,
                        params={'bot_id': bot_id, 'from': offset, 'count': page_size},
                        headers={'Authorization': f'Bearer {token}'},
                        timeout=15,
                    )
                    if resp.status_code == 401:
                        self._sendpulse_oauth_invalidate_cache()
                        token = sample._get_access_token(force_refresh=True)
                        if not token:
                            _logger.warning('SendPulse cron_pull: 401 і не вдалося оновити токен')
                            break
                        resp = requests.get(
                            endpoint,
                            params={'bot_id': bot_id, 'from': offset, 'count': page_size},
                            headers={'Authorization': f'Bearer {token}'},
                            timeout=15,
                        )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    _logger.warning(
                        'SendPulse cron_pull: помилка API %s bot=%s: %s', service, bot_id, e
                    )
                    break

                contacts = data if isinstance(data, list) else data.get('data', [])
                if not contacts:
                    break

                # ID контактів що вже є в Odoo
                sp_ids = [c.get('id') for c in contacts if c.get('id')]
                existing = self.search([('sendpulse_contact_id', 'in', sp_ids)])
                existing_ids = set(existing.mapped('sendpulse_contact_id'))

                for contact in contacts:
                    cid = contact.get('id')
                    if not cid:
                        continue

                    if cid not in existing_ids:
                        # Контакту нема — створюємо
                        name = contact.get('name') or contact.get('username') or 'Невідомий'
                        new_rec = self.create(
                            {
                                'sendpulse_contact_id': cid,
                                'name': name,
                                'service': service,
                                'bot_id': bot_id,
                            }
                        )
                        # Підтягуємо повний профіль з API
                        try:
                            new_rec.action_fetch_contact_info()
                        except Exception as e:
                            _logger.warning('SendPulse cron_pull: fetch_info failed %s: %s', cid, e)
                        total_created += 1
                        _logger.info('SendPulse cron_pull: створено контакт %s (%s)', name, cid)
                    else:
                        # Контакт є — перевіряємо чи потрібне оновлення
                        rec = existing.filtered(lambda r: r.sendpulse_contact_id == cid)
                        if rec and not rec.avatar_url:
                            try:
                                rec.action_fetch_contact_info()
                                total_updated += 1
                            except Exception as e:
                                _logger.warning('SendPulse cron_pull: update failed %s: %s', cid, e)

                if len(contacts) < page_size:
                    break
                offset += page_size

        if total_created or total_updated:
            _logger.info(
                'SendPulse cron_pull: завершено — створено: %d, оновлено: %d',
                total_created,
                total_updated,
            )
        else:
            _logger.debug('SendPulse cron_pull: всі контакти в Odoo, нічого не змінено')
