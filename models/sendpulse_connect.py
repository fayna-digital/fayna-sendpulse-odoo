# -*- coding: utf-8 -*-
import base64
import logging
import time
import requests
from datetime import datetime, timedelta

from markupsafe import Markup, escape

from odoo import models, fields, api, _
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
    ('in_progress', 'В роботі'),
    ('new_message', 'Нове повідомлення'),
    ('close', 'Закрито'),
]

# OAuth кеш (як sendpulse-rest-api-python: один токен до закінчення TTL, не POST на кожен виклик API).
_SENDPULSE_OAUTH_TOKEN_PARAM = 'odoo_chatwoot_connector.oauth_access_token'
_SENDPULSE_OAUTH_UNTIL_PARAM = 'odoo_chatwoot_connector.oauth_valid_until'
_SENDPULSE_OAUTH_LOCK_KEY1 = 94219
_SENDPULSE_OAUTH_LOCK_KEY2 = 55817


class SendpulseConnect(models.Model):
    """
    Центральна модель розмови SendPulse.
    Кожна розмова = один запис тут + один discuss.channel в Odoo.
    """
    _name = 'sendpulse.connect'
    _description = 'SendPulse Розмова'
    _order = 'stage_sort asc, last_message_date desc'

    # ── Основні поля ────────────────────────────────────────────────────
    name = fields.Char(string='Ім\'я контакту', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner', string='Клієнт', index=True, ondelete='set null',
        help='Порожньо = контакт ще не ідентифікований',
    )
    stage = fields.Selection(STAGE_SELECTION, string='Статус', default='new', index=True)
    service = fields.Selection(SERVICE_SELECTION, string='Канал', index=True)

    # ── Дані з SendPulse ────────────────────────────────────────────────
    sendpulse_contact_id = fields.Char(
        string='SendPulse Contact ID', index=True,
        help='UUID контакту в SendPulse — головний ключ ідентифікації',
    )
    bot_id = fields.Char(string='Bot ID')
    bot_name = fields.Char(string='Бот')
    last_message_preview = fields.Char(string='Останнє повідомлення')
    last_message_date = fields.Datetime(string='Дата останнього повідомлення')

    # ── Ідентифікаційні дані соцмереж ───────────────────────────────────
    social_username = fields.Char(
        string='Username / Профіль',
        help='Ім\'я користувача або посилання на профіль у соцмережах',
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
        help="Змінна child_name зібрана ботом SendPulse",
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
    subscription_status = fields.Selection([
        ('active', 'Активний'),
        ('unsubscribed', 'Відписаний'),
        ('deleted', 'Видалений'),
        ('unconfirmed', 'Непідтверджений'),
    ], string='Статус підписки')

    # ── Odoo Discuss ────────────────────────────────────────────────────
    channel_id = fields.Many2one(
        'discuss.channel', string='Discuss Канал',
        ondelete='set null',
    )
    user_ids = fields.Many2many(
        'res.users', string='Оператори',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Оператори, призначені на цю розмову',
    )

    # ── Повідомлення ────────────────────────────────────────────────────
    message_ids = fields.One2many(
        'sendpulse.message', 'connect_id', string='Повідомлення',
    )
    message_count = fields.Integer(
        string='Кількість повідомлень', compute='_compute_message_count',
    )

    # ── Допоміжні ───────────────────────────────────────────────────────
    last_notified_at = fields.Datetime(string='Остання сповіщення')
    source_id = fields.Many2one('utm.source', string='UTM Джерело')

    # ── Коментар (Facebook / Instagram) ─────────────────────────────────
    sp_is_comment = fields.Boolean(
        string='Ініційовано з коментаря', default=False,
        help='True якщо розмову відкрито автоматично після коментаря під постом',
    )
    sp_comment_id = fields.Char(
        string='Comment ID',
        help='Facebook/Instagram comment_id з webhook payload',
        index=True,
    )
    sp_comment_text = fields.Char(
        string='Текст коментаря', size=500,
        help='Текст коментаря клієнта під постом',
    )
    sp_post_id = fields.Char(string='Post ID')
    sp_post_url = fields.Char(string='URL допису')
    sp_replied_public = fields.Boolean(
        string='Публічна відповідь надіслана', default=False,
        help='True якщо публічна відповідь під коментарем успішно опублікована',
    )
    sp_replied_private = fields.Boolean(
        string='Приватне повідомлення надіслано', default=False,
        help='True якщо private_reply успішно надіслано через Graph API',
    )

    # ── Computed ────────────────────────────────────────────────────────
    is_unidentified = fields.Boolean(
        string='Не ідентифікований', compute='_compute_is_unidentified', store=True,
    )
    service_icon = fields.Char(
        string='Іконка каналу', compute='_compute_service_icon',
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
            'telegram': '✈️', 'instagram': '📸', 'facebook': '👍',
            'messenger': '💬', 'viber': '📳', 'whatsapp': '🟢',
            'tiktok': '🎵', 'livechat': '🌐',
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
        member = self.env['discuss.channel.member'].search([
            ('channel_id', '=', self.channel_id.id),
            ('partner_id', '=', self.env.user.partner_id.id),
        ], limit=1)
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

    def _create_discuss_channel(self):
        """
        Створює discuss.channel для розмови.
        Канал з'являється у Discuss (дзвіночок) для призначених операторів.
        """
        self.ensure_one()
        channel_name = f"[{self._get_service_label()}] {self.name}"

        channel = self.env['discuss.channel'].create({
            'name': channel_name,
            'channel_type': 'group',
            'sendpulse_connect_id': self.id,
            'description': self._get_channel_description(),
        })

        # Збираємо партнерів для каналу
        partner_ids = set()

        # 1. Всі активні користувачі групи officer
        officer_group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False)
        if officer_group:
            partner_ids.update(officer_group.users.filtered('active').mapped('partner_id').ids)

        # 2. Всі активні користувачі групи admin
        admin_group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_admin', raise_if_not_found=False)
        if admin_group:
            partner_ids.update(admin_group.users.filtered('active').mapped('partner_id').ids)

        # 3. Призначені оператори розмови
        for user in self.user_ids:
            if user.active:
                partner_ids.add(user.partner_id.id)

        # 4. Fallback: якщо жодного реального оператора не налаштовано — додаємо всіх
        #    внутрішніх (не портальних) активних користувачів системи.
        #    OdooBot (partner_root) не рахується як реальний оператор — виключаємо
        #    його ДО перевірки, щоб fallback спрацював коли в групі лише бот.
        bot = self.env.ref('base.partner_root', raise_if_not_found=False)
        bot_id = bot.id if bot else None
        real_partner_ids = {pid for pid in partner_ids if pid != bot_id}
        if not real_partner_ids:
            internal_users = self.env['res.users'].search([
                ('share', '=', False),
                ('active', '=', True),
            ])
            partner_ids.update(internal_users.mapped('partner_id').ids)
            # OdooBot може бути серед внутрішніх — прибираємо його з fallback набору
            if bot_id:
                partner_ids.discard(bot_id)

        channel.add_members(partner_ids=list(partner_ids))

        # Якщо є збережені повідомлення — постимо їх в канал як історію
        # ВАЖЛИВО: sendpulse_incoming=True щоб mail_channel.py НЕ відправляв
        # ці повідомлення назад у SendPulse і НЕ створював дублікати sendpulse.message
        for msg in self.message_ids.sorted('date'):
            direction_label = '👤 Клієнт' if msg.direction == 'incoming' else '🧑‍💼 Оператор'
            body = Markup("<b>{}</b><br/>{}").format(direction_label, escape(msg.text_message or ''))
            if msg.attachment_url:
                body += Markup('<br/><a href="{}" target="_blank">📎 Вкладення</a>').format(msg.attachment_url)
            if msg.direction == 'incoming':
                # Клієнт — підставляємо партнера, щоб не було Public User (Olha Lipowa)
                author_id = self.partner_id.id if self.partner_id else self.env.ref('base.partner_root').id
            else:
                # Оператор — використовуємо OdooBot (менеджер невідомий)
                author_id = self.env.ref('base.partner_root').id
            channel.with_context(sendpulse_incoming=True).message_post(
                body=body,
                author_id=author_id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        self.write({
            'channel_id': channel.id,
            'stage': 'in_progress',
        })
        return channel

    def _get_service_label(self):
        labels = {
            'telegram': 'TG', 'instagram': 'IG', 'facebook': 'FB',
            'messenger': 'MSG', 'viber': 'VB', 'whatsapp': 'WA',
            'tiktok': 'TT', 'livechat': 'LC',
        }
        return labels.get(self.service, self.service or '?')

    def _get_channel_description(self):
        parts = [f"SendPulse | {self.service or '?'}"]
        if self.social_username:
            parts.append(f"@{self.social_username}")
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
        - Для розмов з каналом → додає всіх поточних операторів як учасників

        Викликається вручну з list-view (кнопка Action).
        """
        # Збираємо партнерів усіх операторів
        partner_ids = set()
        officer_group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False)
        if officer_group:
            partner_ids.update(officer_group.users.filtered('active').mapped('partner_id').ids)
        admin_group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_admin', raise_if_not_found=False)
        if admin_group:
            partner_ids.update(admin_group.users.filtered('active').mapped('partner_id').ids)
        bot = self.env.ref('base.partner_root', raise_if_not_found=False)
        bot_id = bot.id if bot else None
        real_partner_ids = {pid for pid in partner_ids if pid != bot_id}
        if not real_partner_ids:
            internal_users = self.env['res.users'].search([
                ('share', '=', False), ('active', '=', True),
            ])
            partner_ids.update(internal_users.mapped('partner_id').ids)
            if bot_id:
                partner_ids.discard(bot_id)
        partner_ids = list(partner_ids)

        created = 0
        synced = 0
        for connect in self:
            if connect.stage == 'close':
                continue
            if not connect.channel_id:
                connect._create_discuss_channel()
                created += 1
            else:
                # Переконуємось що всі оператори є учасниками
                if partner_ids:
                    connect.channel_id.add_members(partner_ids=partner_ids)
                synced += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'SendPulse: Sync завершено',
                'message': f'Створено каналів: {created}. Оновлено: {synced}.',
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
        connects_without_channel = self.search([
            ('stage', '!=', 'close'),
            ('channel_id', '=', False),
        ])
        if connects_without_channel:
            _logger.info(
                'SendPulse Odo cron: знайдено %d розмов без каналу, синхронізуємо...',
                len(connects_without_channel),
            )
            connects_without_channel.action_sync_discuss_channels()

    def _post_history_to_partner(self):
        """Зберігає всі повідомлення у вкладці Messaging картки партнера."""
        self.ensure_one()
        if not self.partner_id:
            return
        for msg in self.message_ids.sorted('date'):
            self.env['partner.sendpulse.message'].create({
                'partner_id': self.partner_id.id,
                'date': msg.date,
                'text_message': plaintext2html(msg.text_message or ''),
                'service': self.service,
                'direction': msg.direction,
            })

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
            self.channel_id.write({
                'name': f"[{self._get_service_label()}] {partner.name}",
            })
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
            existing._cr.execute(
                "UPDATE partner_sendpulse_channel SET message_count = message_count + 1 WHERE id = %s",
                (existing.id,)
            )
        else:
            # Новий канал для цього партнера — створюємо запис
            self.env['partner.sendpulse.channel'].create({
                'partner_id': self.partner_id.id,
                'service': self.service,
                'sendpulse_contact_id': self.sendpulse_contact_id or False,
                'social_username': self.social_username or False,
                'social_profile_url': self.social_profile_url or False,
                'source_id': source_id or False,
                'first_contact_date': fields.Datetime.now(),
                'last_contact_date': fields.Datetime.now(),
                'message_count': 1,
            })

    # ════════════════════════════════════════════════════════════════════
    # Сповіщення
    # ════════════════════════════════════════════════════════════════════

    def _notify_operators_new_conversation(self):
        """Сповіщає операторів про нову розмову через Odoo Discuss."""
        group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False)
        if not group:
            return
        partner_ids = group.users.mapped('partner_id').ids
        if partner_ids:
            self.env['bus.bus']._sendmany([
                (partner_id, 'simple_notification', {
                    'title': _('SendPulse: Нова розмова'),
                    'message': f"{self.service_icon} {self.name}: нова розмова з {self.service or 'SendPulse'}",
                    'sticky': False,
                })
                for partner_id in partner_ids
            ])

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
            group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False)
            if group:
                target_partners = group.users.mapped('partner_id').ids
        if target_partners:
            self.env['bus.bus']._sendmany([
                (pid, 'simple_notification', {
                    'title': _('SendPulse: Нове повідомлення'),
                    'message': f"{self.service_icon} {self.name}: {self.last_message_preview or '...'}",
                    'sticky': False,
                })
                for pid in target_partners
            ])

    # ════════════════════════════════════════════════════════════════════
    # SendPulse API — відправка повідомлень
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def _sendpulse_oauth_invalidate_cache(self):
        """Примусово вважати кеш токена простроченим (наприклад після 401 від API)."""
        self.env['ir.config_parameter'].sudo().set_param(_SENDPULSE_OAUTH_UNTIL_PARAM, '0')

    def _sendpulse_oauth_read_cache_db(self):
        """Читає кеш токена з БД (після pg_advisory_xact_lock — актуальні значення від інших воркерів)."""
        self.env.cr.execute(
            'SELECT key, value FROM ir_config_parameter WHERE key IN (%s, %s)',
            (_SENDPULSE_OAUTH_TOKEN_PARAM, _SENDPULSE_OAUTH_UNTIL_PARAM),
        )
        rows = dict(self.env.cr.fetchall())
        return (
            (rows.get(_SENDPULSE_OAUTH_TOKEN_PARAM) or '').strip(),
            (rows.get(_SENDPULSE_OAUTH_UNTIL_PARAM) or '').strip(),
        )

    @api.model
    def _sendpulse_oauth_do_refresh(self):
        """POST oauth/access_token з backoff на 429; зберігає токен і час придатності в ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('odoo_chatwoot_connector.client_id', '')
        client_secret = ICP.get_param('odoo_chatwoot_connector.client_secret', '')
        if not client_id or not client_secret:
            _logger.warning('SendPulse Odo: не налаштовані client_id / client_secret')
            return None
        max_attempts = 5
        last_err = None
        for attempt in range(max_attempts):
            try:
                resp = requests.post(
                    'https://api.sendpulse.com/oauth/access_token',
                    json={
                        'grant_type': 'client_credentials',
                        'client_id': client_id,
                        'client_secret': client_secret,
                    },
                    timeout=15,
                )
                if resp.status_code == 429:
                    ra = (resp.headers.get('Retry-After') or '').strip()
                    try:
                        wait = float(ra) if ra else None
                    except ValueError:
                        wait = None
                    if wait is None or wait <= 0:
                        wait = min(2.0 ** attempt, 30.0)
                    _logger.warning(
                        'SendPulse Odo: OAuth 429 Too Many Requests, sleep %.1fs (attempt %s/%s)',
                        wait, attempt + 1, max_attempts,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                token = (data.get('access_token') or '').strip()
                if not token:
                    _logger.error('SendPulse Odo: у відповіді OAuth немає access_token')
                    return None
                try:
                    expires_in = int(data.get('expires_in') or 3600)
                except (TypeError, ValueError):
                    expires_in = 3600
                # Запас до реального expiry (офіційна рекомендація — не стукати в OAuth щохвилини).
                margin = 120
                valid_until = time.time() + max(expires_in - margin, 60)
                ICP.set_param(_SENDPULSE_OAUTH_TOKEN_PARAM, token)
                ICP.set_param(_SENDPULSE_OAUTH_UNTIL_PARAM, str(valid_until))
                return token
            except Exception as e:
                last_err = e
                _logger.error('SendPulse Odo: помилка отримання токена: %s', e)
                if attempt < max_attempts - 1:
                    time.sleep(min(2.0 ** attempt, 10.0))
        if last_err:
            _logger.error('SendPulse Odo: OAuth після %s спроб не вдався: %s', max_attempts, last_err)
        return None

    @api.model
    def _get_access_token(self, force_refresh=False):
        """
        OAuth2 Bearer для SendPulse.
        Кешує токен до закінчення терміну (expires_in від API), щоб уникнути 429 на oauth/access_token.
        Між воркерами Odoo — pg_advisory_xact_lock + повторне читання з БД після очікування.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        now = time.time()
        if not force_refresh:
            token = ICP.get_param(_SENDPULSE_OAUTH_TOKEN_PARAM, '')
            until_s = ICP.get_param(_SENDPULSE_OAUTH_UNTIL_PARAM, '')
            if token and until_s:
                try:
                    if now < float(until_s):
                        return token
                except ValueError:
                    pass
        self.env.cr.execute(
            'SELECT pg_advisory_xact_lock(%s, %s)',
            (_SENDPULSE_OAUTH_LOCK_KEY1, _SENDPULSE_OAUTH_LOCK_KEY2),
        )
        token, until_s = self._sendpulse_oauth_read_cache_db()
        if not force_refresh and token and until_s:
            try:
                if now < float(until_s):
                    return token
            except ValueError:
                pass
        return self._sendpulse_oauth_do_refresh()

    # ════════════════════════════════════════════════════════════════════
    # Webhook Processing — викликається з controllers/main.py
    # ════════════════════════════════════════════════════════════════════

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
            (((data.get('info') or {})
            .get('message') or {})
            .get('channel_data') or {})
            .get('message') or {}
        )
        is_comment = (
            isinstance(channel_data_msg, dict)
            and (
                # Facebook format: item/verb
                (channel_data_msg.get('item') == 'comment' and channel_data_msg.get('verb') == 'add')
                # Instagram via SendPulse: media.media_product_type == FEED
                or (isinstance(channel_data_msg.get('media'), dict)
                    and channel_data_msg['media'].get('media_product_type') == 'FEED')
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
        msg_data = (last_message_data.get('message', {}) or {})
        msg_type = msg_data.get('type', 'text') or 'text'  # text, image, sticker, audio, video, document

        # Fallback: якщо last_message виглядає як media URL — вважаємо image
        _MEDIA_URL_PATTERNS = ('lookaside.fbsbx.com', '/messages/media', 'chatbots-service')
        _MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mp3', '.ogg')
        if msg_type == 'text' and last_message.startswith('http'):
            if any(p in last_message for p in _MEDIA_URL_PATTERNS) or \
               any(last_message.lower().endswith(e) for e in _MEDIA_EXTENSIONS):
                msg_type = 'image'

        # Соціальні ідентифікатори
        social_username = (
            variables.get('username') or
            variables.get('telegram_username') or
            contact.get('username', '')
        )
        social_profile_url = (
            variables.get('profile_url') or
            variables.get('facebook_url') or
            variables.get('instagram_url') or ''
        )
        # Для Telegram будуємо URL профілю з username якщо немає
        if not social_profile_url and social_username and service == 'telegram':
            social_profile_url = f"https://t.me/{social_username}"

        # Фото контакту з webhook
        photo_url = (contact.get('photo') or contact.get('profile_pic') or '').strip() or ''

        # ── Bot-змінні ────────────────────────────────────────────────────
        sp_child_name = (variables.get('child_name') or '').strip() or False
        sp_booking_email = (variables.get('booking_email') or '').strip() or False
        # Якщо email порожній у контакті — беремо з user_email бота
        effective_email = email or (variables.get('user_email') or '').strip()

        # ── Крок 1: Ідентифікація партнера ──────────────────────────────
        partner = self._find_partner(contact_id, effective_email, phone, variables=variables)

        # ── Крок 2: Знаходимо або створюємо розмову ─────────────────────
        # Пріоритет 1: активна розмова по sendpulse_contact_id + service
        connect = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('service', '=', service),
            ('stage', '!=', 'close'),
        ], limit=1)

        # Пріоритет 2: якщо партнер відомий — шукаємо активний чат по partner_id + service.
        # Це запобігає створенню дублікатів коли один реальний клієнт має кілька
        # контактів у SendPulse (наприклад, тестовий + реальний).
        if not connect and partner:
            connect = self.search([
                ('partner_id', '=', partner.id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ], order='write_date desc', limit=1)
            if connect and connect.sendpulse_contact_id != contact_id:
                # Оновлюємо contact_id на актуальний
                connect.write({'sendpulse_contact_id': contact_id})

        # Пріоритет 3: закрита розмова того ж контакту — перевідкриваємо замість створення нової
        if not connect:
            connect = self.search([
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '=', 'close'),
            ], order='write_date desc', limit=1)
            if connect:
                connect.write({'stage': 'new'})
                # Розархівовуємо discuss.channel якщо він був архівований при закритті
                if connect.channel_id:
                    connect.channel_id.write({'active': True})

        now = fields.Datetime.now()
        if not connect:
            connect = self.create({
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
            })
        else:
            # Оновлюємо існуючу розмову
            update_vals = {
                'last_message_preview': last_message[:100] if last_message else connect.last_message_preview,
                'last_message_date': now,
                'stage': 'new_message' if connect.stage == 'in_progress' else connect.stage,
            }
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
            author_partner = self.env['res.partner'].create(create_vals)
        if author_partner and not connect.partner_id:
            connect.write({'partner_id': author_partner.id})

        # ── Крок 3: Зберігаємо повідомлення ─────────────────────────────
        if last_message:
            is_image = msg_type in ('image', 'sticker')
            is_media = is_image or msg_type in ('audio', 'video', 'document')
            media_icons = {'audio': '🎵', 'video': '🎥', 'document': '📄'}

            self.env['sendpulse.message'].create({
                'name': now.strftime('%Y-%m-%d %H:%M'),
                'date': now,
                'connect_id': connect.id,
                'sendpulse_contact_id': contact_id,
                'direction': 'incoming',
                'message_type': 'image' if is_image else ('file' if is_media else 'text'),
                'text_message': '' if is_media else last_message,
                'attachment_url': last_message if is_media else False,
                'raw_json': str({'text': last_message, 'contact': contact}),
            })

            # Якщо є активний channel — постимо туди для операторів
            if connect.channel_id:
                att = None
                if is_media:
                    att = connect._download_media_as_attachment(last_message)

                if is_image and att:
                    # Фото/стікер — скачали і показуємо як attachment
                    body = Markup("<b>👤 {}</b>").format(escape(contact_name))
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body=body,
                        attachment_ids=[att.id],
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                elif is_media and att:
                    icon = media_icons.get(msg_type, '📎')
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                    file_url = f"{base_url}/web/content/{att.id}?access_token={att.access_token}"
                    body = Markup("<b>👤 {}</b><br/>{} <a href='{}' target='_blank'>Вкладення</a>").format(
                        escape(contact_name), icon, file_url,
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
                        body = Markup("<b>👤 {}</b><br/>{} <a href='{}' target='_blank'>Вкладення</a>").format(
                            escape(contact_name), icon, last_message,
                        )
                    else:
                        body = Markup("<b>👤 {}</b><br/>{}").format(escape(contact_name), escape(last_message))
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
                    partner_body = f"<p>{last_message}</p>"
                self.env['partner.sendpulse.message'].create({
                    'partner_id': connect.partner_id.id,
                    'date': now,
                    'text_message': partner_body,
                    'service': service,
                    'direction': 'incoming',
                })

        # ── Крок 4: Оновлюємо канали партнера ───────────────────────────
        if connect.partner_id:
            connect._update_partner_source()

        # ── Крок 5: Якщо немає каналу — створюємо discuss.channel ──────
        if not connect.channel_id:
            connect._create_discuss_channel()

        return connect

    # ════════════════════════════════════════════════════════════════════
    # Коментарі Facebook / Instagram — автовідповідь
    # ════════════════════════════════════════════════════════════════════

    # Ротаційні шаблони публічної відповіді.
    # {landing_url} і {tg_url} підставляються з ir.config_parameter.
    _COMMENT_PUBLIC_TEMPLATES = [
        "Дякуємо за коментар! 🏕️ Написали вам детальніше у приватні — перевірте вхідні 😊 Або одразу: {landing_url}",
        "Дякуємо! 🌟 Всі деталі надіслали в особисті. Також можна одразу глянути програму: {landing_url}",
        "Радіємо вашій зацікавленості! ✨ Написали в приват — там детальна відповідь. Підписуйтесь на наш ТГ-канал і отримайте -5% на табір: {tg_url} 🎁",
        "Привіт! Відповіли вам у повідомленнях 📩 Актуальні табори 2026 та знижка -5% за підписку: {tg_url}",
        "Дякуємо за інтерес! 🏕️ Детальніше написали у приватних. Все про табори 2026: {landing_url}",
    ]

    _COMMENT_PUBLIC_REPEAT_TEMPLATE = (
        "Раді бачити вас знову! 😊 Наш менеджер вже напише вам у повідомленнях — слідкуйте за вхідними 🏕️"
    )

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
        comment_id = str(
            channel_data_msg.get('comment_id')
            or channel_data_msg.get('id')
            or ''
        )
        comment_text = (
            channel_data_msg.get('message')
            or channel_data_msg.get('text')
            or ''
        )
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
        if not ICP.get_param('odoo_chatwoot_connector.sp_comment_autoreply_enabled', 'True') == 'True':
            _logger.info('SendPulse Odo: comment autoreply disabled, skipping %s', comment_id)
            return None

        # Дедуплікація: той самий comment_id вже оброблявся
        if comment_id:
            existing = self.search([('sp_comment_id', '=', comment_id)], limit=1)
            if existing:
                _logger.info('SendPulse Odo: comment %s already processed, skipping', comment_id)
                return existing

        # Знаходимо/створюємо розмову
        connect = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('service', '=', service),
            ('stage', '!=', 'close'),
            ('sp_is_comment', '=', True),
        ], limit=1)

        now = fields.Datetime.now()
        if not connect:
            connect = self.create({
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
                'last_message_preview': f'💬 Коментар: {comment_text[:80]}' if comment_text else '💬 Коментар',
                'last_message_date': now,
            })
        else:
            connect.write({
                'sp_comment_id': comment_id,
                'sp_comment_text': comment_text[:500] if comment_text else '',
                'sp_post_id': post_id,
                'sp_post_url': post_url,
                'last_message_preview': f'💬 Коментар: {comment_text[:80]}' if comment_text else '💬 Коментар',
                'last_message_date': now,
            })

        if not connect.channel_id:
            connect._create_discuss_channel()

        # Визначаємо чи надсилати приватне (тільки перший раз для цього контакту)
        already_private = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('sp_replied_private', '=', True),
        ], limit=1)
        # Не спамимо людей у яких вже є прямий діалог (не comment)
        has_direct_dialog = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('sp_is_comment', '=', False),
        ], limit=1)
        send_private = (
            not bool(already_private)
            and not bool(has_direct_dialog)
            and ICP.get_param('odoo_chatwoot_connector.sp_comment_private_enabled', 'True') == 'True'
        )

        send_public = (
            ICP.get_param('odoo_chatwoot_connector.sp_comment_public_enabled', 'True') == 'True'
        )

        # Тексти з підстановкою URL
        landing_url = ICP.get_param('odoo_chatwoot_connector.sp_comment_landing_url', 'https://lato2026.campscout.eu')
        tg_url = ICP.get_param('odoo_chatwoot_connector.sp_comment_tg_url', 'https://t.me/campscouting')

        # Публічна відповідь
        public_ok = False
        public_error = None
        if send_public and comment_id:
            # Ротація по кількості наявних comment-розмов
            count = self.search_count([('sp_is_comment', '=', True)])
            # Якщо вже є приватне від цього контакту — використовуємо repeat шаблон
            if bool(already_private):
                public_text = self._COMMENT_PUBLIC_REPEAT_TEMPLATE
            else:
                tmpl = self._COMMENT_PUBLIC_TEMPLATES[count % len(self._COMMENT_PUBLIC_TEMPLATES)]
                public_text = tmpl.format(
                    landing_url=landing_url or 'https://lato2026.campscout.eu',
                    tg_url=tg_url or 'https://t.me/campscouting',
                )
            public_ok, public_error = connect._send_comment_public_reply(comment_id, service, public_text)
            if public_ok:
                connect.write({'sp_replied_public': True})

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
                    "Вітаємо! 🏕️ Дякуємо за ваш коментар під нашим постом.\n\n"
                    "Підготували для вас відповіді на найпоширеніші запитання — "
                    "безпека, програма, харчування, вартість, терміни:\n"
                    "🎬 {yt_url}\n\n"
                    "Вся актуальна інформація про табори 2026 також тут:\n"
                    "🌐 {landing_url}\n\n"
                    "Якщо залишились питання — пишіть тут, відповімо особисто! 😊"
                )
            private_text = private_text_tmpl.format(
                landing_url=landing_url or 'https://lato2026.campscout.eu',
                tg_url=tg_url or 'https://t.me/campscouting',
                yt_url=yt_url or 'https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
            )
            private_ok, private_error = connect._send_comment_private_reply(comment_id, private_text, service)
            if private_ok:
                connect.write({'sp_replied_private': True})

        # Нотатка оператору
        connect._notify_operator_comment(
            contact_name=contact_name,
            comment_text=comment_text,
            post_url=post_url,
            sent_public=public_ok,
            sent_private=private_ok,
            public_error=public_error,
            private_error=private_error,
        )

        return connect

    def _send_comment_public_reply(self, comment_id, service, text):
        """
        Публікує публічну відповідь під коментарем через Facebook Graph API.
        Facebook: POST /v19.0/{comment_id}/comments
        Instagram: POST /v19.0/{comment_id}/replies
        Повертає (success: bool, error: str|None)
        """
        token = self._get_fb_page_token()
        if not token:
            return False, 'Page Access Token не налаштований (Налаштування → SendPulse → Facebook Page Access Token)'

        endpoint = 'replies' if service == 'instagram' else 'comments'
        url = f'https://graph.facebook.com/v19.0/{comment_id}/{endpoint}'
        try:
            resp = requests.post(url, json={'message': text, 'access_token': token}, timeout=15)
            if resp.status_code == 200:
                _logger.info('SendPulse Odo: public reply posted for comment %s', comment_id)
                return True, None
            err = self._parse_fb_error(resp)
            _logger.warning('SendPulse Odo: public reply failed for %s: %s', comment_id, err)
            return False, err
        except Exception as e:
            _logger.error('SendPulse Odo: public reply exception for %s: %s', comment_id, e)
            return False, str(e)

    def _send_comment_private_reply(self, comment_id, text, service='facebook'):
        """
        Надсилає приватне повідомлення у відповідь на коментар.
        Facebook: POST /{comment_id}/private_replies
        Instagram: POST /{ig-user-id}/messages з recipient.comment_id
        Повертає (success: bool, error: str|None)
        """
        token = self._get_fb_page_token()
        if not token:
            return False, 'Page Access Token не налаштований'

        try:
            if service == 'instagram':
                ig_user_id = self.env['ir.config_parameter'].sudo().get_param(
                    'odoo_chatwoot_connector.ig_user_id', ''
                )
                if not ig_user_id:
                    return False, 'Instagram User ID не налаштований (odoo_chatwoot_connector.ig_user_id)'
                url = f'https://graph.facebook.com/v19.0/{ig_user_id}/messages'
                payload = {
                    'recipient': {'comment_id': comment_id},
                    'message': {'text': text},
                    'access_token': token,
                }
            else:
                url = f'https://graph.facebook.com/v19.0/{comment_id}/private_replies'
                payload = {'message': text, 'access_token': token}

            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                _logger.info('SendPulse Odo: private reply sent for comment %s (%s)', comment_id, service)
                return True, None
            err = self._parse_fb_error(resp)
            _logger.warning('SendPulse Odo: private reply failed for %s: %s', comment_id, err)
            return False, err
        except Exception as e:
            _logger.error('SendPulse Odo: private reply exception for %s: %s', comment_id, e)
            return False, str(e)

    def _get_fb_page_token(self):
        """Повертає Facebook Page Access Token з ir.config_parameter."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.fb_page_access_token', ''
        ) or ''

    @staticmethod
    def _parse_fb_error(resp):
        """Витягує людиночитане повідомлення про помилку з відповіді Graph API."""
        try:
            data = resp.json()
            err = data.get('error', {})
            msg = err.get('message', '') or ''
            code = err.get('code', '')
            subcode = err.get('error_subcode', '')
            parts = [p for p in [f'код {code}' if code else '', f'підкод {subcode}' if subcode else '', msg] if p]
            return ' — '.join(parts) or resp.text[:200]
        except Exception:
            return resp.text[:200] if resp.text else f'HTTP {resp.status_code}'

    def _notify_operator_comment(self, contact_name, comment_text, post_url,
                                  sent_public, sent_private, public_error, private_error):
        """Надсилає системну нотатку від OdooBot у Discuss-канал розмови."""
        if not self.channel_id:
            return

        lines = [f'💬 Новий коментар під постом [{self._get_service_label()}]', '']
        lines.append(f'👤 Клієнт: {contact_name}')
        if comment_text:
            lines.append(f'📝 Коментар: "{comment_text}"')
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
            lines.append('⏳ Очікуємо відповіді від клієнта — поки клієнт не відповів, писати йому не можна (правило Meta)')
        elif private_error:
            lines.append(f'❌ Приватне повідомлення не надіслано: {private_error}')
        else:
            lines.append('⏭️ Приватне повідомлення не надіслається (клієнт вже отримував раніше або вимкнено)')

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
            p = self.env['res.partner'].search(
                [('email', '=ilike', addr.strip())], limit=1
            )
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
        Обробляє outbound_message — повідомлення надіслані з SendPulse
        (зокрема з мобільного додатку менеджера).

        Дедуплікація: якщо цей текст вже є в Odoo як outgoing за останні 60 секунд
        (тобто надіслано з Odoo Discuss) — пропускаємо щоб не дублювати.
        """
        contact_id = contact.get('id', '')
        last_message = contact.get('last_message', '') or ''

        _logger.info(
            'SendPulse _process_outgoing_event: contact_id=%s, last_message=%r',
            contact_id, last_message[:80] if last_message else '',
        )

        if not last_message or not contact_id:
            return

        # ── Guard: contact.last_message у outbound_message завжди містить ОСТАННЄ
        # КЛІЄНТСЬКЕ повідомлення, а не текст оператора/бота. Якщо цей текст вже
        # збережений як incoming — це "луна" клієнта, ігноруємо.
        already_incoming = self.env['sendpulse.message'].search([
            ('sendpulse_contact_id', '=', contact_id),
            ('direction', '=', 'incoming'),
            ('text_message', '=', last_message),
        ], limit=1)
        _logger.info(
            'SendPulse _process_outgoing_event: already_incoming=%s for text=%r',
            bool(already_incoming), last_message[:40] if last_message else '',
        )
        if already_incoming:
            return

        # ── Дедуплікація: перевіряємо чи не ми самі щойно надіслали цей текст ──
        cutoff = fields.Datetime.now() - timedelta(seconds=60)
        already_saved = self.env['sendpulse.message'].search([
            ('sendpulse_contact_id', '=', contact_id),
            ('direction', '=', 'outgoing'),
            ('text_message', '=', last_message),
            ('date', '>=', cutoff),
        ], limit=1)

        if already_saved:
            # Повідомлення вже є — надіслано з Odoo Discuss, пропускаємо
            return

        # ── Знаходимо активну розмову ────────────────────────────────────────
        connect = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('service', '=', service),
            ('stage', '!=', 'close'),
        ], limit=1)

        if not connect:
            return

        now = fields.Datetime.now()

        # ── Зберігаємо повідомлення в sendpulse.message ──────────────────────
        self.env['sendpulse.message'].create({
            'name': now.strftime('%Y-%m-%d %H:%M'),
            'date': now,
            'connect_id': connect.id,
            'sendpulse_contact_id': contact_id,
            'direction': 'outgoing',
            'message_type': 'text',
            'text_message': last_message,
            'raw_json': str({'text': last_message, 'source': 'sendpulse_mobile'}),
        })

        # ── Постимо у discuss.channel щоб оператори в Odoo бачили ────────────
        if connect.channel_id:
            connect.channel_id.with_context(
                sendpulse_incoming=True
            ).message_post(
                body=Markup("<i>📱 SendPulse:</i> {}").format(escape(last_message)),
                author_id=self.env.ref('base.partner_root').id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        # ── Зберігаємо у вкладці Messaging картки партнера ───────────────────
        if connect.partner_id:
            self.env['partner.sendpulse.message'].create({
                'partner_id': connect.partner_id.id,
                'date': now,
                'text_message': f"<p>📱 {last_message}</p>",
                'service': service,
                'direction': 'outgoing',
            })

        # ── Оновлюємо preview розмови ─────────────────────────────────────────
        update_vals = {
            'last_message_preview': last_message[:100],
            'last_message_date': now,
        }
        # Якщо оператор відповів — знімаємо "Нове повідомлення"
        if connect.stage == 'new_message':
            update_vals['stage'] = 'in_progress'
        connect.write(update_vals)

    @api.model
    def _process_unsubscribe(self, contact_id, service):
        """Відмічає розмову як закриту при відписці клієнта."""
        connects = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('service', '=', service),
            ('stage', '!=', 'close'),
        ])
        for connect in connects:
            connect.write({'stage': 'close'})
            _logger.info(
                'SendPulse Odo: контакт %s відписався (%s), розмова закрита',
                contact_id, service,
            )

    def _download_media_as_attachment(self, media_url):
        """
        Download media file from SendPulse API (requires Bearer token) and
        save as ir.attachment so Odoo can display it inline in Discuss.
        Returns ir.attachment record or None on failure.
        """
        try:
            token = self._get_access_token()
            if not token:
                return None
            resp = requests.get(
                media_url,
                headers={'Authorization': f'Bearer {token}'},
                timeout=30,
            )
            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    resp = requests.get(
                        media_url,
                        headers={'Authorization': f'Bearer {token}'},
                        timeout=30,
                    )
            resp.raise_for_status()
            content_type = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
            ext_map = {
                'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif',
                'image/webp': 'webp', 'video/mp4': 'mp4',
                'audio/ogg': 'ogg', 'audio/mpeg': 'mp3', 'application/pdf': 'pdf',
            }
            ext = ext_map.get(content_type, 'bin')
            filename = f'sendpulse_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}.{ext}'
            att = self.env['ir.attachment'].create({
                'name': filename,
                'datas': base64.b64encode(resp.content).decode(),
                'mimetype': content_type,
            })
            att.generate_access_token()
            return att
        except Exception as e:
            _logger.warning('SendPulse Odo: не вдалося завантажити медіа %s: %s', media_url, e)
            return None

    # ════════════════════════════════════════════════════════════════════
    # SendPulse API — синхронізація профілю контакту (Priority 3)
    # ════════════════════════════════════════════════════════════════════

    # Ендпоінти GET-контакту по сервісу
    _CONTACT_GET_ENDPOINTS = {
        'telegram':  'https://api.sendpulse.com/telegram/contacts/get',
        'instagram': 'https://api.sendpulse.com/instagram/contacts/get',
        'facebook':  'https://api.sendpulse.com/facebook/contacts/get',
        'messenger': 'https://api.sendpulse.com/messenger/contacts/get',
        'viber':     'https://api.sendpulse.com/viber/contacts/get',
        'whatsapp':  'https://api.sendpulse.com/whatsapp/contacts/get',
        'tiktok':    'https://api.sendpulse.com/tiktok/contacts/get',
    }

    _SP_STATUS_MAP = {
        'active': 'active',
        'unsubscribed': 'unsubscribed',
        'deleted': 'deleted',
        'unconfirmed': 'unconfirmed',
    }

    def action_fetch_contact_info(self):
        """
        Отримує актуальні дані контакту з SendPulse API:
        avatar, мова, статус підписки, bot-змінні.
        Викликається вручну з форми розмови (кнопка "Оновити профіль").
        """
        self.ensure_one()
        if not self.sendpulse_contact_id:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'SendPulse', 'message': 'Немає contact_id', 'type': 'warning'}}

        token = self._get_access_token()
        if not token:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'SendPulse', 'message': 'Не вдалося отримати токен API', 'type': 'danger'}}

        endpoint = self._CONTACT_GET_ENDPOINTS.get(self.service or 'telegram',
                                                    self._CONTACT_GET_ENDPOINTS['telegram'])
        try:
            resp = requests.get(
                endpoint,
                params={'id': self.sendpulse_contact_id},
                headers={'Authorization': f'Bearer {token}'},
                timeout=10,
            )
            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    resp = requests.get(
                        endpoint,
                        params={'id': self.sendpulse_contact_id},
                        headers={'Authorization': f'Bearer {token}'},
                        timeout=10,
                    )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            _logger.warning('SendPulse Odo: не вдалося отримати профіль %s: %s', self.sendpulse_contact_id, e)
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'SendPulse', 'message': f'Помилка API: {e}', 'type': 'danger'}}

        vals = self._extract_contact_vals(data)
        if vals:
            self.write(vals)
            _logger.info('SendPulse Odo: профіль %s оновлено, поля: %s',
                         self.sendpulse_contact_id, list(vals.keys()))

        # Синхронізуємо аватар у картку партнера якщо він ідентифікований
        if self.partner_id and self.avatar_url:
            self._sync_avatar_to_partner()

        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'SendPulse', 'message': 'Профіль оновлено', 'type': 'success'}}

    def _sync_avatar_to_partner(self):
        """
        Завантажує фото з avatar_url і зберігає в картці Odoo-партнера (image_1920).
        Викликається після action_fetch_contact_info якщо партнер ідентифікований.
        Не перезаписує фото якщо URL не змінився (порівнюємо розмір).
        """
        self.ensure_one()
        if not self.partner_id or not self.avatar_url:
            return
        try:
            resp = requests.get(self.avatar_url, timeout=15)
            resp.raise_for_status()
            image_b64 = base64.b64encode(resp.content).decode()
            self.partner_id.write({'image_1920': image_b64})
            _logger.info('SendPulse Odo: аватар партнера %s оновлено', self.partner_id.name)
        except Exception as e:
            _logger.warning('SendPulse Odo: не вдалося завантажити аватар %s: %s', self.avatar_url, e)

    # GET /contacts/get: status — ціле число: 1=active, 0=unsubscribed, 2=deleted, 3=unconfirmed
    _SP_STATUS_INT_MAP = {1: 'active', 0: 'unsubscribed', 2: 'deleted', 3: 'unconfirmed'}

    def _extract_contact_vals(self, data):
        """
        Витягує поля з відповіді SendPulse GET /contacts/get.

        Реальна структура відповіді:
          {"success": true, "data": {
              "status": 1,
              "channel_data": {
                  "photo": "https://...",        (Telegram — може бути null)
                  "profile_pic": "https://...",  (Instagram)
                  "language_code": "uk",
                  "username": "...",
                  "name": "...",
              },
              "variables": {"user_email": "...", ...},
          }}
        """
        contact = data.get('data') if isinstance(data.get('data'), dict) else data
        channel_data = contact.get('channel_data') or {}

        vals = {}

        # Фото: Telegram/WA → channel_data.photo, Instagram → channel_data.profile_pic,
        # Messenger/FB → data.avatar.path
        avatar_obj = contact.get('avatar')
        avatar_path = avatar_obj.get('path') if isinstance(avatar_obj, dict) else None
        photo_url = (channel_data.get('photo') or
                     channel_data.get('profile_pic') or
                     avatar_path or
                     contact.get('photo'))
        if photo_url and isinstance(photo_url, str) and photo_url.startswith('http'):
            vals['avatar_url'] = photo_url

        # Мова — в channel_data
        lang = (channel_data.get('language_code') or
                channel_data.get('language') or
                contact.get('language_code') or
                contact.get('language'))
        if lang:
            vals['language_code'] = str(lang)

        # Статус — число або рядок
        raw_status = contact.get('status')
        if isinstance(raw_status, int):
            mapped_status = self._SP_STATUS_INT_MAP.get(raw_status)
        else:
            mapped_status = self._SP_STATUS_MAP.get((raw_status or '').lower())
        if mapped_status:
            vals['subscription_status'] = mapped_status

        # Bot-змінні
        variables = contact.get('variables') or {}
        if isinstance(variables, list):
            variables = {v['name']: v.get('value', '') for v in variables if v.get('name')}

        child_name = (variables.get('child_name') or '').strip()
        if child_name and not self.sp_child_name:
            vals['sp_child_name'] = child_name

        booking_email = (variables.get('booking_email') or '').strip()
        if booking_email and not self.sp_booking_email:
            vals['sp_booking_email'] = booking_email

        _logger.info('SendPulse Odo: extracted vals keys=%s', list(vals.keys()))
        return vals

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
            'telegram': 'Telegram', 'instagram': 'Instagram', 'facebook': 'Facebook',
            'messenger': 'Messenger', 'viber': 'Viber', 'whatsapp': 'WhatsApp',
            'tiktok': 'TikTok', 'livechat': 'LiveChat',
        }
        status_labels = {
            'active': 'Активний', 'unsubscribed': 'Відписаний',
            'deleted': 'Видалений', 'unconfirmed': 'Непідтверджений',
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
        }
        if connect.partner_id:
            p = connect.partner_id
            result['partner'] = {
                'id': p.id,
                'name': p.name,
                'email': p.email or '',
                'phone': p.phone or p.mobile or '',
            }
        return result

    def send_message_to_sendpulse(self, text, attachment_url=None):
        """
        Відправляє текстове повідомлення клієнту через SendPulse API.
        Викликається з mail_channel.py при відповіді оператора в Discuss.
        """
        self.ensure_one()
        if not self.sendpulse_contact_id:
            _logger.warning('SendPulse Odo: немає contact_id для відправки')
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
                    'type': 'RESPONSE', 'content_type': 'message', 'text': attachment_url,
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
                'SendPulse Odo: відправляємо в %s contact=%s payload=%s',
                endpoint, self.sendpulse_contact_id, payload,
            )
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            _logger.info(
                'SendPulse Odo: відповідь API status=%s body=%s',
                resp.status_code, resp.text.replace('\n', ' ').replace('\r', '')[:500],
            )

            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
                    _logger.info(
                        'SendPulse Odo: повтор після 401 status=%s body=%s',
                        resp.status_code, resp.text.replace('\n', ' ').replace('\r', '')[:500],
                    )

            # Карта назв каналів для повідомлень оператору
            _SERVICE_LABELS = {
                'telegram': 'Telegram', 'instagram': 'Instagram',
                'facebook': 'Facebook', 'messenger': 'Messenger',
                'viber': 'Viber', 'whatsapp': 'WhatsApp',
                'livechat': 'LiveChat', 'tiktok': 'TikTok',
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
                    'SendPulse Odo: 400 for %s contact=%s (%s): %s',
                    service, self.sendpulse_contact_id, self.name, err_code,
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
                    'SendPulse Odo: 422 for %s contact=%s (%s): %s',
                    service, self.sendpulse_contact_id, self.name, short_reason,
                )
                # Розбираємо тіло відповіді щоб дати точну підказку
                try:
                    err_data = resp.json()
                    err_code = err_data.get('error_code')
                    err_errors = err_data.get('errors', {})
                    err_text = ' '.join(
                        str(v) for vals in err_errors.values() for v in (vals if isinstance(vals, list) else [vals])
                    ).lower()
                except Exception:
                    err_code = None
                    err_text = ''

                if err_code == 403 or 'blocked by the user' in err_text or 'forbidden' in err_text:
                    policy_hint = (
                        f'Клієнт заблокував бота у {service_label}. '
                        'Написати через цей канал більше неможливо — зверніться через інший спосіб зв\'язку.'
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
            _logger.info('SendPulse Odo: повідомлення відправлено контакту %s', self.sendpulse_contact_id)
            return True
        except Exception as e:
            _logger.error('SendPulse Odo: помилка відправки: %s', e)
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
        'telegram':  'https://api.sendpulse.com/telegram/contacts',
        'instagram': 'https://api.sendpulse.com/instagram/contacts',
        'facebook':  'https://api.sendpulse.com/facebook/contacts',
        'viber':     'https://api.sendpulse.com/viber/contacts',
        'whatsapp':  'https://api.sendpulse.com/whatsapp/contacts',
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
                    _logger.warning('SendPulse cron_pull: помилка API %s bot=%s: %s', service, bot_id, e)
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
                        new_rec = self.create({
                            'sendpulse_contact_id': cid,
                            'name': name,
                            'service': service,
                            'bot_id': bot_id,
                        })
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
                total_created, total_updated,
            )
        else:
            _logger.debug('SendPulse cron_pull: всі контакти в Odoo, нічого не змінено')
